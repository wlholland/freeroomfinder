"""Scrapes BYU's public academic calendar to discover semester start dates.

BYU's academic calendar (https://academiccalendar.byu.edu/) is server-rendered.
"Start of Classes" events embed their date in the URL slug:
  .../start-of-classes/start-of-classes-2026-01-05
  .../start-of-classes/start-of-classes-1st-day-2026-04-27

We extract those dates and map each month to a BYU term code suffix:
  January        → 1  (Winter)
  April / May    → 3  (Spring)
  June           → 4  (Summer)
  August / Sept  → 5  (Fall)

Results are cached in the DB and refreshed weekly so the app never needs
manual updates — not even once a year.
"""

import re
import logging
from datetime import date

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("freeroomfinder")

_CALENDAR_BASE = "https://academiccalendar.byu.edu/"

# Maps the *month* of a semester's first day → BYU year_term suffix
# (BYU skips 2; Spring=3, Summer=4)
_MONTH_TO_SUFFIX: dict[int, str] = {
    1: "1",   # Winter
    4: "3",   # Spring  (occasionally starts late April)
    5: "3",   # Spring  (usually early May)
    6: "4",   # Summer
    8: "5",   # Fall    (URL dates sometimes land in Aug even if class starts Sep)
    9: "5",   # Fall
}

# Matches the trailing YYYY-MM-DD in a BYU calendar event URL
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[^/]*)$")


def _extract_starts(html: str, year: int) -> list[tuple[date, str]]:
    """Parse all 'start-of-classes' links from a calendar page."""
    soup = BeautifulSoup(html, "lxml")
    seen_suffixes: set[str] = set()
    results: list[tuple[date, str]] = []

    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if "start-of-classes" not in href:
            continue
        m = _DATE_RE.search(href)
        if not m:
            continue
        try:
            d = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        # Only keep events whose year matches (some pages list adjacent years)
        if d.year != year:
            continue
        suffix = _MONTH_TO_SUFFIX.get(d.month)
        if not suffix or suffix in seen_suffixes:
            continue
        seen_suffixes.add(suffix)
        results.append((d, f"{year}{suffix}"))

    return sorted(results)


async def _fetch_year_page(client: httpx.AsyncClient, year: int) -> str | None:
    """Try several URL patterns to get BYU's calendar page for *year*."""
    candidates = [
        f"{_CALENDAR_BASE}?year={year}",
        f"{_CALENDAR_BASE}{year}",
        _CALENDAR_BASE,
    ]
    for url in candidates:
        try:
            r = await client.get(url, timeout=12.0)
            if r.status_code == 200 and "start-of-classes" in r.text:
                return r.text
        except Exception:
            continue
    return None


async def fetch_semester_starts(years_ahead: int = 2) -> list[tuple[date, str]]:
    """Return a sorted list of (semester_start_date, term_code) tuples scraped
    from BYU's academic calendar for the current year plus *years_ahead* future
    years.

    Returns an empty list (never raises) if the site is unreachable — the caller
    should fall back to the algorithmic estimate in that case.
    """
    today = date.today()
    all_results: list[tuple[date, str]] = []

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for year in range(today.year, today.year + years_ahead + 1):
                html = await _fetch_year_page(client, year)
                if html:
                    found = _extract_starts(html, year)
                    logger.info(
                        "calendar_scraper: found %d semester starts for %d: %s",
                        len(found), year,
                        [f"{t} ({d})" for d, t in found],
                    )
                    all_results.extend(found)
                else:
                    logger.warning(
                        "calendar_scraper: could not fetch BYU calendar for year %d", year
                    )
    except Exception as e:
        logger.warning("calendar_scraper: unexpected error: %s", e)

    return sorted(all_results)
