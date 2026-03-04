from pydantic import BaseModel, Field
from typing import Optional

VALID_DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"}


class BuildingInfo(BaseModel):
    code: str
    display_name: str
    rooms_cached: int
    last_crawled: Optional[str] = None


class RoomInfo(BaseModel):
    building: str
    room_number: str
    description: Optional[str] = None
    capacity: Optional[int] = None
    discovered_at: str


class SearchRequest(BaseModel):
    buildings: list[str] = Field(..., min_length=1)
    day: str
    start_time: str  # "HH:MM" 24-hr
    end_time: str    # "HH:MM" 24-hr


class FreeWindow(BaseModel):
    start_time: str       # "HH:MM" 24-hr
    end_time: str         # "HH:MM" 24-hr
    duration_minutes: int


class FreeRoom(BaseModel):
    building: str
    room_number: str
    description: Optional[str] = None
    capacity: Optional[int] = None
    is_fully_free: bool
    free_windows: list[FreeWindow]
    longest_free_minutes: int


class SearchResponse(BaseModel):
    rooms: list[FreeRoom]
    searched_buildings: list[str]
    day: str
    start_time: str
    end_time: str
    total_rooms_checked: int


class DiscoveryStatus(BaseModel):
    building: str
    status: str  # 'running' | 'done' | 'error' | 'not_started'
    rooms_found: int
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class CacheStats(BaseModel):
    total_buildings_crawled: int
    total_rooms_cached: int
    buildings: list[DiscoveryStatus]
