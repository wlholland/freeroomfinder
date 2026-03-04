import asyncio
import httpx
from datetime import datetime, timezone
from typing import AsyncGenerator
from .config import settings
from .scraper import fetch_room_schedule
from .database import (
    upsert_room,
    bulk_upsert_schedules,
    log_discovery_start,
    log_discovery_finish,
)

# Map of single/double char tokens to full day name.
# Order matters for the parsing loop: try two-char first at each position.
_DAY_MAP: dict[str, str] = {
    "Th": "Thursday",
    "M":  "Monday",
    "T":  "Tuesday",
    "W":  "Wednesday",
    "F":  "Friday",
    "S":  "Saturday",
}

_TWO_CHAR = {"Th"}
_ONE_CHAR = {"M", "T", "W", "F", "S"}


def parse_day_codes(raw: str) -> list[str]:
    """
    Parse BYU day strings left-to-right with longest-match-first.

    "TTh"  -> ["Tuesday", "Thursday"]
    "MWF"  -> ["Monday", "Wednesday", "Friday"]
    "Th"   -> ["Thursday"]
    "S"    -> ["Saturday"]

    Algorithm: at each position, try two-char token first ("Th"),
    then one-char. "TT" is not a valid two-char token, so at i=0 of "TTh"
    we match "T" (Tuesday), then at i=1 we match "Th" (Thursday).
    """
    days: list[str] = []
    i = 0
    while i < len(raw):
        two = raw[i:i + 2]
        one = raw[i:i + 1]
        if two in _TWO_CHAR:
            days.append(_DAY_MAP[two])
            i += 2
        elif one in _ONE_CHAR:
            days.append(_DAY_MAP[one])
            i += 1
        else:
            i += 1  # skip unexpected characters
    return days


def day_matches(raw_days: str, target_day: str) -> bool:
    return target_day in parse_day_codes(raw_days)


def _room_candidates(start: int, end: int) -> list[str]:
    """
    Generate deduplicated room number strings to try.
    Includes both bare integers ("1") and zero-padded ("001").
    """
    seen: set[str] = set()
    result: list[str] = []
    for n in range(start, end + 1):
        for fmt in (str(n), f"{n:03d}"):
            if fmt not in seen:
                seen.add(fmt)
                result.append(fmt)
    return result


async def discover_with_progress(
    building: str,
    year_term: str,
) -> AsyncGenerator[tuple[int, int, int], None]:
    """
    Async generator that probes all room candidates for a building.
    Yields (attempted, total, found) after each probe completes.
    Writes valid rooms and their schedules to the DB.
    """
    log_id = await log_discovery_start(building, year_term)
    candidates = _room_candidates(settings.room_range_start, settings.room_range_end)
    total = len(candidates)
    found = 0
    attempted = 0
    sem = asyncio.Semaphore(settings.discovery_semaphore)

    async def probe(client: httpx.AsyncClient, room: str):
        async with sem:
            await asyncio.sleep(settings.crawl_delay)
            try:
                return await fetch_room_schedule(client, building, room, year_term)
            except Exception:
                return None

    async with httpx.AsyncClient() as client:
        tasks = [asyncio.create_task(probe(client, r)) for r in candidates]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            attempted += 1
            if result and result.is_valid:
                found += 1
                now = datetime.now(timezone.utc).isoformat()
                await upsert_room(
                    building,
                    result.room_number,
                    result.description,
                    result.capacity,
                    now,
                )
                await bulk_upsert_schedules(
                    building,
                    result.room_number,
                    year_term,
                    result.slots,
                )
            yield attempted, total, found

    await log_discovery_finish(log_id, found)


async def discover_building(building: str, year_term: str) -> int:
    """
    Run full discovery for a building without streaming progress.
    Returns number of rooms found.
    """
    found = 0
    async for _, _, found in discover_with_progress(building, year_term):
        pass
    return found
