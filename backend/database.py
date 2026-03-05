import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from .config import settings

DB = settings.db_path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS term_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Scraped from BYU's academic calendar; refreshed weekly
CREATE TABLE IF NOT EXISTS semester_schedule (
    term_code  TEXT PRIMARY KEY,
    start_date TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    building      TEXT    NOT NULL,
    room_number   TEXT    NOT NULL,
    description   TEXT,
    capacity      INTEGER,
    discovered_at TEXT    NOT NULL,
    UNIQUE(building, room_number)
);

CREATE TABLE IF NOT EXISTS schedules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    building    TEXT NOT NULL,
    room_number TEXT NOT NULL,
    year_term   TEXT NOT NULL,
    course      TEXT,
    section     TEXT,
    sec_type    TEXT,
    days        TEXT NOT NULL,
    start_time  TEXT NOT NULL,
    end_time    TEXT NOT NULL,
    begin_date  TEXT,
    end_date    TEXT,
    instructor  TEXT,
    fetched_at  TEXT NOT NULL,
    UNIQUE(building, room_number, year_term, course, section, days, start_time)
);

CREATE TABLE IF NOT EXISTS discovery_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    building     TEXT NOT NULL,
    year_term    TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    rooms_found  INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'running'
);

CREATE INDEX IF NOT EXISTS idx_schedules_building_room
    ON schedules(building, room_number);

CREATE INDEX IF NOT EXISTS idx_schedules_days_times
    ON schedules(days, start_time, end_time);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()


async def upsert_room(
    building: str,
    room_number: str,
    description: Optional[str],
    capacity: Optional[int],
    discovered_at: str,
) -> None:
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            """
            INSERT INTO rooms (building, room_number, description, capacity, discovered_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(building, room_number) DO UPDATE SET
                description = excluded.description,
                capacity = excluded.capacity,
                discovered_at = excluded.discovered_at
            """,
            (building, room_number, description, capacity, discovered_at),
        )
        await db.commit()


async def get_rooms_for_building(building: str) -> list[dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT building, room_number, description, capacity, discovered_at "
            "FROM rooms WHERE building = ? ORDER BY room_number",
            (building,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def bulk_upsert_schedules(
    building: str,
    room_number: str,
    year_term: str,
    slots: list,  # list of TimeSlot dataclasses
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB) as db:
        for slot in slots:
            await db.execute(
                """
                INSERT INTO schedules
                    (building, room_number, year_term, course, section, sec_type,
                     days, start_time, end_time, begin_date, end_date, instructor, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(building, room_number, year_term, course, section, days, start_time)
                DO UPDATE SET
                    end_time = excluded.end_time,
                    fetched_at = excluded.fetched_at
                """,
                (
                    building, room_number, year_term,
                    slot.course, slot.section, slot.sec_type,
                    slot.days_raw, slot.start_time, slot.end_time,
                    slot.begin_date, slot.end_date, slot.instructor,
                    now,
                ),
            )
        await db.commit()


async def get_schedules_for_rooms(
    building_room_pairs: list[tuple[str, str]],
    year_term: str,
) -> list[dict]:
    if not building_room_pairs:
        return []
    placeholders = ",".join("(?,?)" for _ in building_room_pairs)
    params: list = []
    for b, r in building_room_pairs:
        params.extend([b, r])
    params.append(year_term)
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT building, room_number, days, start_time, end_time
            FROM schedules
            WHERE (building, room_number) IN ({placeholders})
              AND year_term = ?
            """,
            params,
        ) as cursor:
            rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def building_has_cache(building: str) -> bool:
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT 1 FROM rooms WHERE building = ? LIMIT 1", (building,)
        ) as cursor:
            return await cursor.fetchone() is not None


async def log_discovery_start(building: str, year_term: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "INSERT INTO discovery_log (building, year_term, started_at, status) VALUES (?, ?, ?, 'running')",
            (building, year_term, now),
        )
        await db.commit()
        return cursor.lastrowid


async def log_discovery_finish(log_id: int, rooms_found: int, status: str = "done") -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE discovery_log SET finished_at = ?, rooms_found = ?, status = ? WHERE id = ?",
            (now, rooms_found, status, log_id),
        )
        await db.commit()


async def get_discovery_log(building: str) -> Optional[dict]:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM discovery_log WHERE building = ? ORDER BY id DESC LIMIT 1",
            (building,),
        ) as cursor:
            row = await cursor.fetchone()
    return dict(row) if row else None


async def get_semester_schedule() -> list[tuple["date", str]]:
    """Return all cached (start_date, term_code) pairs ordered by start date."""
    from datetime import date as _date
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT start_date, term_code FROM semester_schedule ORDER BY start_date"
        ) as cursor:
            rows = await cursor.fetchall()
    return [(_date.fromisoformat(r[0]), r[1]) for r in rows]


async def save_semester_schedule(entries: list[tuple["date", str]]) -> None:
    """Persist scraped semester start dates, replacing any existing data."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB) as db:
        for start_date, term_code in entries:
            await db.execute(
                """
                INSERT INTO semester_schedule (term_code, start_date, fetched_at)
                VALUES (?, ?, ?)
                ON CONFLICT(term_code) DO UPDATE SET
                    start_date = excluded.start_date,
                    fetched_at = excluded.fetched_at
                """,
                (term_code, start_date.isoformat(), now),
            )
        await db.commit()


async def get_schedule_last_fetched() -> "datetime | None":
    """Return the most recent fetched_at timestamp across all semester_schedule rows."""
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT MAX(fetched_at) FROM semester_schedule"
        ) as cursor:
            row = await cursor.fetchone()
    if row and row[0]:
        return datetime.fromisoformat(row[0])
    return None


async def get_active_term() -> str | None:
    """Return the term code that was used to populate the current DB cache."""
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT value FROM term_meta WHERE key = 'active_term'"
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None


async def set_active_term(term: str) -> None:
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO term_meta (key, value) VALUES ('active_term', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (term,),
        )
        await db.commit()


async def wipe_for_new_term(new_term: str) -> None:
    """Drop all cached schedule data and record the new active term.

    Called automatically when the semester rolls over so users always search
    the current semester's schedule.
    """
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM schedules")
        await db.execute("DELETE FROM rooms")
        await db.execute("DELETE FROM discovery_log")
        await db.execute(
            "INSERT INTO term_meta (key, value) VALUES ('active_term', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (new_term,),
        )
        await db.commit()


async def get_cache_stats() -> dict:
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            "SELECT COUNT(DISTINCT building) as cnt FROM rooms"
        ) as cursor:
            row = await cursor.fetchone()
            total_buildings = row["cnt"] if row else 0

        async with db.execute("SELECT COUNT(*) as cnt FROM rooms") as cursor:
            row = await cursor.fetchone()
            total_rooms = row["cnt"] if row else 0

        async with db.execute(
            """
            SELECT dl.building, dl.status, dl.rooms_found, dl.started_at, dl.finished_at
            FROM discovery_log dl
            INNER JOIN (
                SELECT building, MAX(id) as max_id FROM discovery_log GROUP BY building
            ) latest ON dl.id = latest.max_id
            """
        ) as cursor:
            log_rows = await cursor.fetchall()

    buildings = [
        {
            "building": r["building"],
            "status": r["status"],
            "rooms_found": r["rooms_found"],
            "started_at": r["started_at"],
            "finished_at": r["finished_at"],
        }
        for r in log_rows
    ]

    return {
        "total_buildings_crawled": total_buildings,
        "total_rooms_cached": total_rooms,
        "buildings": buildings,
    }
