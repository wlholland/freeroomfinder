import re
import httpx
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from typing import Optional
from .config import settings

_INVALID_ROOM_MARKERS = [
    "Select a Valid room using the room/building navigation.",
    "is an invalid room/building.",
    "There is no schedule for this room",
]

# Regex for "8:00a - 9:15a" or "1:00p - 2:15p"
_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2})\s*(a|p)m?\s*[-\u2013]\s*(\d{1,2}):(\d{2})\s*(a|p)m?",
    re.IGNORECASE,
)


@dataclass
class TimeSlot:
    course: str
    section: str
    sec_type: str
    days_raw: str       # raw BYU string e.g. "TTh"
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


async def fetch_room_schedule(
    client: httpx.AsyncClient,
    building: str,
    room: str,
    year_term: str,
) -> RoomSchedule:
    payload = {
        "year_term": year_term,
        "building": building,
        "room": room,
        "tab_option": "Schedule",
    }
    response = await client.post(
        settings.byu_url,
        data=payload,
        timeout=settings.request_timeout,
    )
    response.raise_for_status()
    return parse_room_page(building, room, response.text)


def parse_room_page(building: str, room: str, html: str) -> RoomSchedule:
    soup = BeautifulSoup(html, "lxml")

    # Check for invalid room
    body_text = soup.get_text()
    if any(m in body_text for m in _INVALID_ROOM_MARKERS):
        return RoomSchedule(building=building, room_number=room, is_valid=False)

    # Extract room metadata — labels are <th> tags, values are adjacent <td> tags
    description: Optional[str] = None
    capacity: Optional[int] = None
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            texts = [c.get_text(strip=True) for c in cells]
            for i, text in enumerate(texts):
                if text == "Description:" and i + 1 < len(texts) and description is None:
                    description = texts[i + 1] or None
                elif text == "Capacity:" and i + 1 < len(texts) and capacity is None:
                    val = texts[i + 1]
                    capacity = int(val) if val and val.isdigit() else None

    slots: list[TimeSlot] = []
    seen_slots: set[tuple] = set()

    for table in soup.find_all("table"):
        # Skip outer container tables that nest other tables inside them
        if table.find("table"):
            continue
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        # Academic schedule table — BYU uses no-space header names in HTML
        if "Course" in headers and "ClassPeriod" in headers:
            col = {name: idx for idx, name in enumerate(headers)}
            for tr in table.find_all("tr")[1:]:
                cells = tr.find_all("td")
                if len(cells) < len(headers):
                    continue
                period_text = cells[col["ClassPeriod"]].get_text(strip=True)
                days_text = cells[col["Days"]].get_text(strip=True)
                if not period_text or not days_text:
                    continue
                start_24, end_24 = parse_class_period(period_text)
                if start_24 is None:
                    continue
                key = (cells[col["Course"]].get_text(strip=True), days_text, start_24)
                if key in seen_slots:
                    continue
                seen_slots.add(key)
                slots.append(TimeSlot(
                    course=cells[col["Course"]].get_text(strip=True),
                    section=cells[col["Sec"]].get_text(strip=True) if "Sec" in col else "",
                    sec_type=cells[col["SecType"]].get_text(strip=True) if "SecType" in col else "",
                    days_raw=days_text,
                    start_time=start_24,
                    end_time=end_24,
                    begin_date=cells[col["BeginDate"]].get_text(strip=True) if "BeginDate" in col else "",
                    end_date=cells[col["EndDate"]].get_text(strip=True) if "EndDate" in col else "",
                    instructor=cells[col["Instructor"]].get_text(strip=True) if "Instructor" in col else "",
                ))

        # Non-Academic Events table
        if "TimeUsed" in headers and "DaysUsed" in headers:
            col = {name: idx for idx, name in enumerate(headers)}
            for tr in table.find_all("tr")[1:]:
                cells = tr.find_all("td")
                if len(cells) < len(headers):
                    continue
                time_text = cells[col["TimeUsed"]].get_text(strip=True)
                days_text = cells[col["DaysUsed"]].get_text(strip=True)
                if not time_text or not days_text:
                    continue
                start_24, end_24 = parse_class_period(time_text)
                if start_24 is None:
                    continue
                slots.append(TimeSlot(
                    course="[Event]",
                    section="",
                    sec_type="",
                    days_raw=days_text,
                    start_time=start_24,
                    end_time=end_24,
                    begin_date=cells[col.get("StartDate", 0)].get_text(strip=True) if "StartDate" in col else "",
                    end_date=cells[col.get("EndDate", 0)].get_text(strip=True) if "EndDate" in col else "",
                    instructor="",
                ))

    return RoomSchedule(
        building=building,
        room_number=room,
        is_valid=True,
        description=description,
        capacity=capacity,
        slots=slots,
    )


def parse_class_period(period: str) -> tuple[Optional[str], Optional[str]]:
    """
    "8:00a - 9:15a"  ->  ("08:00", "09:15")
    "1:00p - 2:15p"  ->  ("13:00", "14:15")
    Returns (None, None) on parse failure.
    """
    m = _TIME_RE.search(period)
    if not m:
        return None, None
    sh, sm, sa, eh, em, ea = m.groups()
    return _to_24(int(sh), int(sm), sa), _to_24(int(eh), int(em), ea)


def _to_24(hour: int, minute: int, ampm: str) -> str:
    ampm = ampm.lower()
    if ampm == "a":
        h = 0 if hour == 12 else hour
    else:
        h = hour if hour == 12 else hour + 12
    return f"{h:02d}:{minute:02d}"
