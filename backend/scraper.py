"""BYU class-schedule client.

Data source: BYU's public class-search backend at
``https://commtech.byu.edu/noauth/classSchedule`` (no auth required).

.. note::
    The original scraper targeted
    ``https://y.byu.edu/class_schedule/cgi/classRoom.cgi``.
    BYU decommissioned that CGI around August 2026 — every request (GET or
    POST, with or without a browser User-Agent) now returns HTTP 404, so room
    discovery found 0 rooms and every search came back empty. This module
    replaces it with the commtech JSON API, which uses the same ``YYYYT``
    term codes (e.g. ``20265`` = Fall 2026):

    - ``GET  index.php``                     → page embeds a ``_session_id`` token
    - ``POST ajax/getClasses.php``           → courses using a building
      (``searchObject {yearterm, building}`` + ``sessionId``)
    - ``POST ajax/getSections.php``          → sections + meeting times
      (``courseId`` + ``sessionId`` + ``yearterm``). Each meeting time carries
      ``building``, ``room``, ``begin_time``/``end_time`` (``"0930"`` style)
      and per-weekday flags (``mon``/``tue``/``wed``/``thu``/``fri``/``sat``,
      where Thursday is ``"R"``).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .config import settings

logger = logging.getLogger("freeroomfinder")

_SESSION_ID_RE = re.compile(r'_session_id\s*=\s*"([^"]+)"')

# Browser UA: the API sits behind BYU's bot-mitigation (Dynatrace Ruxit);
# the default "python-httpx/..." UA is treated with suspicion.
_CLIENT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    )
}


@dataclass
class TimeSlot:
    course: str
    section: str
    sec_type: str
    days_raw: str       # e.g. "MWF" / "TTh" (compatible with discovery.day_matches)
    start_time: str     # "HH:MM" 24-hr
    end_time: str       # "HH:MM" 24-hr
    begin_date: str
    end_date: str
    instructor: str


@dataclass
class RoomSchedule:
    building: str
    room_number: str
    is_valid: bool
    description: Optional[str] = None
    capacity: Optional[int] = None
    slots: list[TimeSlot] = field(default_factory=list)


def _api_url(path: str) -> str:
    return f"{settings.byu_url.rstrip('/')}/{path.lstrip('/')}"


async def get_session_id(client: httpx.AsyncClient) -> str:
    """Fetch the class-search homepage and extract its session token."""
    resp = await client.get(_api_url("index.php"), timeout=settings.request_timeout)
    resp.raise_for_status()
    m = _SESSION_ID_RE.search(resp.text)
    if not m:
        raise RuntimeError("could not find _session_id on BYU class-search page")
    return m.group(1)


async def search_course_ids(
    client: httpx.AsyncClient,
    session_id: str,
    building: str,
    year_term: str,
) -> list[str]:
    """Return course IDs (``"<curriculum>-<title>"``) with ≥1 section in *building*.

    Returns an empty list when the building has no scheduled classes (or when
    BYU returns an error payload instead of JSON).
    """
    try:
        resp = await client.post(
            _api_url("ajax/getClasses.php"),
            data={
                "searchObject[yearterm]": year_term,
                "searchObject[building]": building,
                "sessionId": session_id,
            },
            timeout=settings.request_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("search_course_ids(%s): request failed: %s", building, e)
        return []
    if isinstance(data, dict):
        return list(data.keys())
    if isinstance(data, list):
        # Empty result set comes back as [].
        return [c for c in data if isinstance(c, str)]
    logger.warning("search_course_ids(%s): unexpected payload %r", building, type(data))
    return []


async def fetch_sections(
    client: httpx.AsyncClient,
    session_id: str,
    course_id: str,
    year_term: str,
) -> list[dict]:
    """Return the raw section dicts for *course_id* (empty list on failure)."""
    try:
        resp = await client.post(
            _api_url("ajax/getSections.php"),
            data={
                "courseId": course_id,
                "sessionId": session_id,
                "yearterm": year_term,
            },
            timeout=settings.request_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug("fetch_sections(%s): request failed: %s", course_id, e)
        return []
    if isinstance(data, dict):
        sections = data.get("sections", [])
        return sections if isinstance(sections, list) else []
    return []


def format_api_time(hhmm: Optional[str]) -> Optional[str]:
    """``"0930"`` → ``"09:30"``. Returns None for null/TBA/malformed values."""
    if not hhmm:
        return None
    digits = "".join(ch for ch in str(hhmm) if ch.isdigit())
    if len(digits) < 3 or len(digits) > 4:
        return None
    digits = digits.zfill(4)
    hour, minute = int(digits[:2]), int(digits[2:])
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


# Weekday flags in API order → tokens understood by discovery.day_matches.
# NOTE: the API marks Thursday with "R" (not "Th").
_DAY_FLAGS: list[tuple[str, str]] = [
    ("mon", "M"),
    ("tue", "T"),
    ("wed", "W"),
    ("thu", "Th"),
    ("fri", "F"),
    ("sat", "S"),
]


def days_raw_from_flags(meeting: dict) -> str:
    """``{"mon": "M", "wed": "W", ...}`` → ``"MW"`` (``""`` if no days)."""
    return "".join(token for flag, token in _DAY_FLAGS if meeting.get(flag))


def _instructor_name(section: dict) -> str:
    instructors = section.get("instructors") or []
    primary = next(
        (i for i in instructors if i.get("attribute_type") == "PRIMARY"),
        instructors[0] if instructors else None,
    )
    if not primary:
        return ""
    first = (primary.get("preferred_first_name") or "").strip()
    last = (primary.get("preferred_surname") or "").strip()
    full = f"{first} {last}".strip()
    return full or (primary.get("sort_name") or "")


def _course_label(section: dict) -> str:
    dept = (section.get("dept_name") or "").strip()
    cat = (section.get("catalog_number") or "").strip()
    suffix = (section.get("catalog_suffix") or "").strip()
    return f"{dept} {cat}{suffix}".strip()


def slots_for_building(
    sections: list[dict], building: str
) -> dict[tuple[str, str], list[TimeSlot]]:
    """Group a course's meeting times by ``(building, room)`` for *building*.

    Only classroom meetings in the requested building are kept — the sections
    endpoint returns *all* sections of each course (including other buildings,
    TBA/online entries, and time-less entries), so filtering here is required.
    """
    grouped: dict[tuple[str, str], list[TimeSlot]] = {}
    for section in sections:
        for meeting in section.get("times") or []:
            if meeting.get("building") != building:
                continue
            room = (meeting.get("room") or "").strip()
            if not room or room.upper() == "TBA":
                continue
            start = format_api_time(meeting.get("begin_time"))
            end = format_api_time(meeting.get("end_time"))
            if start is None or end is None:
                continue
            days_raw = days_raw_from_flags(meeting)
            if not days_raw:
                continue
            slot = TimeSlot(
                course=_course_label(section),
                section=str(section.get("section_number") or ""),
                sec_type=str(section.get("section_type") or ""),
                days_raw=days_raw,
                start_time=start,
                end_time=end,
                begin_date=str(section.get("start_date") or ""),
                end_date=str(section.get("end_date") or ""),
                instructor=_instructor_name(section),
            )
            grouped.setdefault((building, room), []).append(slot)
    return grouped


def create_client() -> httpx.AsyncClient:
    """Shared client factory (browser UA so BYU serves the API calls)."""
    return httpx.AsyncClient(headers=_CLIENT_HEADERS)
