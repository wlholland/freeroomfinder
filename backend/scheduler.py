from .database import get_schedules_for_rooms, get_rooms_for_building
from .discovery import day_matches
from .models import FreeRoom, FreeWindow, SearchRequest


def _mins(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _from_mins(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def compute_free_windows(
    booked: list[tuple[str, str]],
    window_start: str,
    window_end: str,
) -> list[FreeWindow]:
    """
    Given booked (start, end) intervals on a day, return the free sub-intervals
    within [window_start, window_end].

    Works in integer minutes to avoid string comparison edge cases.
    """
    ws = _mins(window_start)
    we = _mins(window_end)

    # Clip each booked interval to the window; discard if no overlap
    clipped: list[list[int]] = []
    for s, e in booked:
        cs = max(_mins(s), ws)
        ce = min(_mins(e), we)
        if cs < ce:
            clipped.append([cs, ce])

    if not clipped:
        dur = we - ws
        return [FreeWindow(start_time=window_start, end_time=window_end, duration_minutes=dur)]

    # Sort then merge overlapping/adjacent booked intervals
    clipped.sort()
    merged: list[list[int]] = [clipped[0]]
    for s, e in clipped[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    # Gaps between booked intervals (and between window edges and first/last slots)
    free: list[FreeWindow] = []
    cursor = ws
    for s, e in merged:
        if cursor < s:
            free.append(FreeWindow(
                start_time=_from_mins(cursor),
                end_time=_from_mins(s),
                duration_minutes=s - cursor,
            ))
        cursor = max(cursor, e)
    if cursor < we:
        free.append(FreeWindow(
            start_time=_from_mins(cursor),
            end_time=_from_mins(we),
            duration_minutes=we - cursor,
        ))

    return free


async def find_free_rooms(req: SearchRequest, year_term: str) -> list[FreeRoom]:
    """
    For each building, find all rooms that have ANY free time within the requested
    window. Returns both fully-free and partially-free rooms.

    Sort order: fully free first, then by longest free window descending.
    """
    results: list[FreeRoom] = []

    for building in req.buildings:
        rooms = await get_rooms_for_building(building)
        if not rooms:
            continue

        pairs = [(r["building"], r["room_number"]) for r in rooms]
        schedules = await get_schedules_for_rooms(pairs, year_term)

        # Group booked intervals by (building, room_number) for the target day
        booked_by_room: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for sched in schedules:
            if day_matches(sched["days"], req.day):
                key = (sched["building"], sched["room_number"])
                booked_by_room.setdefault(key, []).append(
                    (sched["start_time"], sched["end_time"])
                )

        for room in rooms:
            key = (room["building"], room["room_number"])
            booked = booked_by_room.get(key, [])
            windows = compute_free_windows(booked, req.start_time, req.end_time)

            if not windows:
                continue  # room is fully booked within the window

            longest = max(w.duration_minutes for w in windows)
            total_window = _mins(req.end_time) - _mins(req.start_time)
            is_fully_free = (
                len(windows) == 1
                and windows[0].start_time == req.start_time
                and windows[0].end_time == req.end_time
            )

            results.append(FreeRoom(
                building=room["building"],
                room_number=room["room_number"],
                description=room.get("description"),
                capacity=room.get("capacity"),
                is_fully_free=is_fully_free,
                free_windows=windows,
                longest_free_minutes=longest,
            ))

    # Fully free first, then by longest free window desc, then room number asc
    return sorted(
        results,
        key=lambda r: (not r.is_fully_free, -r.longest_free_minutes, r.building, r.room_number),
    )
