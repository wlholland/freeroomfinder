import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator
from .config import settings
from .scraper import (
    create_client,
    fetch_sections,
    get_session_id,
    search_course_ids,
    slots_for_building,
)
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


_WEEKDAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"}


def day_matches(raw_days: str, target_day: str) -> bool:
    if raw_days.strip().lower() == "daily":
        return target_day in _WEEKDAYS
    return target_day in parse_day_codes(raw_days)


async def discover_with_progress(
    building: str,
    year_term: str,
) -> AsyncGenerator[tuple[int, int, int], None]:
    """
    Course-driven discovery for a building via BYU's public class-search API.

    1. Search all courses with ≥1 section in *building*.
    2. Fetch each course's sections concurrently and keep only the meeting
       times physically in *building*.
    3. Write each distinct room + its schedule slots to the DB.

    Yields (attempted, total, found) after each course completes, where
    *total* is the number of courses to inspect and *found* is the number of
    distinct rooms discovered so far.
    """
    log_id = await log_discovery_start(building, year_term)
    attempted = 0
    found = 0
    seen_rooms: set[str] = set()
    sem = asyncio.Semaphore(settings.discovery_semaphore)

    async with create_client() as client:
        try:
            session_id = await get_session_id(client)
        except Exception:
            await log_discovery_finish(log_id, 0, status="error")
            return
        course_ids = await search_course_ids(client, session_id, building, year_term)
        total = len(course_ids)
        if total == 0:
            await log_discovery_finish(log_id, 0)
            return

        async def probe(course_id: str):
            async with sem:
                await asyncio.sleep(settings.crawl_delay)
                try:
                    sections = await fetch_sections(
                        client, session_id, course_id, year_term
                    )
                    return course_id, slots_for_building(sections, building)
                except Exception:
                    return course_id, None

        tasks = [asyncio.create_task(probe(cid)) for cid in course_ids]
        for coro in asyncio.as_completed(tasks):
            _, grouped = await coro
            attempted += 1
            if grouped:
                now = datetime.now(timezone.utc).isoformat()
                for (bld, room), slots in grouped.items():
                    # The public API exposes no room capacity/description, so
                    # those stay NULL (frontend renders "—" for them).
                    await upsert_room(bld, room, None, None, now)
                    await bulk_upsert_schedules(bld, room, year_term, slots)
                    if room not in seen_rooms:
                        seen_rooms.add(room)
                        found += 1
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
