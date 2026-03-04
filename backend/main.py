import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from .config import settings
from .database import init_db, get_rooms_for_building, get_cache_stats, building_has_cache
from .buildings import ALL_BUILDINGS, get_display_name
from .models import SearchRequest, SearchResponse, BuildingInfo, CacheStats, DiscoveryStatus
from .discovery import discover_building, discover_with_progress
from .scheduler import find_free_rooms

# Track in-flight discovery tasks to avoid duplicate crawls
_discovery_tasks: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
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
