import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta, datetime, timezone

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from .config import settings, compute_current_term
from .database import (
    init_db, get_rooms_for_building, get_cache_stats, building_has_cache,
    get_active_term, set_active_term, wipe_for_new_term,
    get_semester_schedule, save_semester_schedule, get_schedule_last_fetched,
)
from .calendar_scraper import fetch_semester_starts
from .buildings import ALL_BUILDINGS, get_display_name
from .models import SearchRequest, SearchResponse, BuildingInfo, CacheStats, DiscoveryStatus
from .discovery import discover_building, discover_with_progress
from .scheduler import find_free_rooms

logger = logging.getLogger("freeroomfinder")

_SCHEDULE_REFRESH_DAYS = 7    # re-scrape BYU calendar once a week
_WATCHER_INTERVAL_SECS = 86400  # check for semester rollover once a day

# Track in-flight discovery tasks to avoid duplicate crawls
_discovery_tasks: dict[str, asyncio.Task] = {}


async def _refresh_semester_schedule() -> list[tuple[date, str]]:
    """Scrape BYU's academic calendar and persist results.  Returns the schedule."""
    scraped = await fetch_semester_starts(years_ahead=2)
    if scraped:
        await save_semester_schedule(scraped)
        logger.info(
            "calendar: refreshed semester schedule — %d semesters cached", len(scraped)
        )
    else:
        logger.warning("calendar: scrape returned no data; keeping existing schedule")
    return await get_semester_schedule()


async def _load_schedule() -> list[tuple[date, str]]:
    """Load semester schedule from DB, refreshing from BYU's site if stale."""
    last = await get_schedule_last_fetched()
    if last is None:
        # First run — always scrape immediately
        return await _refresh_semester_schedule()

    age_days = (datetime.now(timezone.utc) - last).days
    if age_days >= _SCHEDULE_REFRESH_DAYS:
        return await _refresh_semester_schedule()

    return await get_semester_schedule()


async def _check_and_wipe_if_needed(schedule: list[tuple[date, str]]) -> None:
    """Wipe room/schedule cache if a new semester boundary has been crossed."""
    today = date.today()
    for start_date, term_code in schedule:
        wipe_date = start_date - timedelta(days=1)
        if today >= wipe_date:
            active = await get_active_term()
            if active != term_code:
                logger.warning(
                    "Semester rollover: wiping cache for new term %s (was %s)",
                    term_code, active,
                )
                await wipe_for_new_term(term_code)
                settings.current_term = term_code
                logger.info("Cache wiped. Now serving term %s.", term_code)


async def _background_watcher() -> None:
    """Daily check: refresh stale calendar data and wipe on semester rollover."""
    while True:
        await asyncio.sleep(_WATCHER_INTERVAL_SECS)
        try:
            schedule = await _load_schedule()
            settings.current_term = compute_current_term(schedule)
            await _check_and_wipe_if_needed(schedule)
        except Exception:
            logger.exception("background_watcher: unexpected error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    # Load (and possibly refresh) the semester schedule from BYU's calendar
    schedule = await _load_schedule()

    # Sync the in-process term setting with the freshly loaded schedule
    settings.current_term = compute_current_term(schedule)
    logger.info("Serving term: %s", settings.current_term)

    # Seed term_meta on first run
    if await get_active_term() is None:
        await set_active_term(settings.current_term)

    # Wipe if we're already past a semester boundary
    await _check_and_wipe_if_needed(schedule)

    watcher = asyncio.create_task(_background_watcher())
    yield
    watcher.cancel()
    for task in _discovery_tasks.values():
        task.cancel()


app = FastAPI(title="FreeRoomFinder", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/", response_class=FileResponse)
async def serve_index():
    return FileResponse("frontend/index.html")


@app.get("/api/buildings")
async def list_buildings() -> list[BuildingInfo]:
    stats = await get_cache_stats()
    building_map = {s["building"]: s for s in stats["buildings"]}
    result = []
    for code in ALL_BUILDINGS:
        info = building_map.get(code, {})
        result.append(BuildingInfo(
            code=code,
            display_name=get_display_name(code),
            rooms_cached=info.get("rooms_found", 0),
            last_crawled=info.get("finished_at"),
        ))
    return result


@app.get("/api/rooms/{building}")
async def list_rooms(building: str) -> list[dict]:
    if building not in ALL_BUILDINGS:
        raise HTTPException(status_code=404, detail="Unknown building")
    return await get_rooms_for_building(building)


@app.post("/api/search")
async def search_free_rooms(req: SearchRequest) -> SearchResponse:
    for b in req.buildings:
        if b not in ALL_BUILDINGS:
            raise HTTPException(status_code=400, detail=f"Unknown building: {b}")

    free = await find_free_rooms(req, settings.current_term)

    total = 0
    for b in req.buildings:
        rooms = await get_rooms_for_building(b)
        total += len(rooms)

    return SearchResponse(
        rooms=free,
        searched_buildings=req.buildings,
        day=req.day,
        start_time=req.start_time,
        end_time=req.end_time,
        total_rooms_checked=total,
    )


@app.get("/api/discover/{building}")
async def discover_building_stream(building: str):
    """SSE stream of discovery progress for a building."""
    if building not in ALL_BUILDINGS:
        raise HTTPException(status_code=404, detail="Unknown building")

    async def event_generator():
        candidates_total = (settings.room_range_end - settings.room_range_start + 1) * 2
        async for attempted, total, found in discover_with_progress(building, settings.current_term):
            yield {
                "event": "progress",
                "data": json.dumps({
                    "attempted": attempted,
                    "total": total,
                    "found": found,
                    "status": "running",
                }),
            }
        yield {
            "event": "done",
            "data": json.dumps({"status": "done", "found": found if 'found' in dir() else 0}),
        }

    return EventSourceResponse(event_generator())


@app.get("/api/status")
async def cache_status() -> CacheStats:
    stats = await get_cache_stats()
    buildings_status = []
    for b in stats["buildings"]:
        buildings_status.append(DiscoveryStatus(
            building=b["building"],
            status=b["status"],
            rooms_found=b["rooms_found"],
            started_at=b.get("started_at"),
            finished_at=b.get("finished_at"),
        ))
    return CacheStats(
        total_buildings_crawled=stats["total_buildings_crawled"],
        total_rooms_cached=stats["total_rooms_cached"],
        buildings=buildings_status,
    )


def _trigger_discovery(building: str) -> None:
    """Start background discovery task if not already running."""
    existing = _discovery_tasks.get(building)
    if existing and not existing.done():
        return
    task = asyncio.create_task(discover_building(building, settings.current_term))
    _discovery_tasks[building] = task
