import os
from dataclasses import dataclass, field
from datetime import date, timedelta


# ── Algorithmic term estimator ───────────────────────────────────────────────
# Used only when the DB-cached scrape of BYU's academic calendar is unavailable
# (e.g. first ever startup before scraping finishes, or BYU's site is down).
#
# BYU semester approximate start windows (based on historic calendar):
#   Winter  ~ Jan  5        Fall   ~ Sep  2
#   Spring  ~ Apr 27        Summer ~ Jun 22
#
# The real start dates are fetched automatically from academiccalendar.byu.edu
# and stored in the `semester_schedule` DB table. This function is a last resort.

_APPROX: list[tuple[int, int, str]] = [
    # (month, day, term_suffix) — in ascending calendar order
    (1,  1, "1"),   # Winter  (generous: treat Jan 1 as the floor)
    (4, 27, "3"),   # Spring
    (6, 22, "4"),   # Summer
    (9,  2, "5"),   # Fall
]


def algorithmic_term(today: date | None = None) -> str:
    """Best-guess BYU term code for *today* using fixed approximate start dates."""
    if today is None:
        today = date.today()
    year = today.year
    suffix = "1"
    for month, day, term_suffix in _APPROX:
        if (today.month, today.day) >= (month, day):
            suffix = term_suffix
    return f"{year}{suffix}"


def compute_current_term(
    schedule: list[tuple[date, str]] | None = None,
    today: date | None = None,
) -> str:
    """Return the active BYU term code.

    Priority order:
      1. YEAR_TERM env var override (useful for local testing)
      2. Scraped schedule from DB (most accurate)
      3. Algorithmic approximation (fallback)
    """
    override = os.getenv("YEAR_TERM")
    if override:
        return override

    if today is None:
        today = date.today()

    if schedule:
        active = schedule[0][1]
        for start_date, term_code in schedule:
            if today >= start_date:
                active = term_code
        return active

    return algorithmic_term(today)


def next_wipe_info(
    schedule: list[tuple[date, str]] | None = None,
    today: date | None = None,
) -> tuple[date, str] | None:
    """Return (wipe_date, incoming_term) for the next upcoming semester, or None."""
    if today is None:
        today = date.today()
    if not schedule:
        return None
    for start_date, term_code in schedule:
        wipe_date = start_date - timedelta(days=1)
        if today <= wipe_date:
            return wipe_date, term_code
    return None


# ── App settings ─────────────────────────────────────────────────────────────
@dataclass
class Settings:
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "data/freeroomfinder.db"))
    # Populated at startup once the DB schedule is loaded; starts as a best guess
    current_term: str = field(default_factory=lambda: compute_current_term())
    discovery_semaphore: int = field(default_factory=lambda: int(os.getenv("DISCOVERY_SEMAPHORE", "15")))
    crawl_delay: float = field(default_factory=lambda: float(os.getenv("CRAWL_DELAY", "0.5")))
    room_range_start: int = 1
    room_range_end: int = 499
    byu_url: str = "https://y.byu.edu/class_schedule/cgi/classRoom.cgi"
    request_timeout: float = 15.0


settings = Settings()
