# FreeRoomFinder – BYU

Find unoccupied classrooms at BYU for any day and time window. Great for grabbing a quiet study space or an open room for a group meeting.

**Live at:** [freeroomfinder-production.up.railway.app](https://freeroomfinder-production.up.railway.app)

> "Free" means **no class is scheduled there** in BYU's public class schedule. It is inferred from class meeting times, not a reservation system — rooms may still be locked or in use for non-class events.

---

## What it does

1. You pick one or more **buildings**, a **day of the week**, and a **time range** (or use the "Right Now" quick-select)
2. The app looks up every class meeting in those buildings for the current semester and returns each room with free time during that window
3. Rooms are sorted: fully free ones first, then partially free ones (by longest free gap), with their available sub-windows shown
4. Clicking a room number opens BYU's public class search, where its schedule can be looked up (BYU no longer has a per-room schedule page to link to)

Availability is based on the **weekday's recurring class schedule** for the term — it does not know about specific dates, holidays, finals, or one-off events.

The same data is also available as a [read-only JSON API](#public-api-v1-read-only-json) and a [remote MCP server](#remote-mcp-server-claude-custom-connector) for Claude.

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML / CSS / JS (no framework) |
| Backend | Python 3.12 · FastAPI · Uvicorn · sse-starlette |
| Database | SQLite via aiosqlite (persisted on a Railway volume) |
| Data source | BYU's public class-search JSON API (httpx) |
| Calendar scraping | BeautifulSoup4 · lxml (academiccalendar.byu.edu) |
| MCP | Official `mcp` Python SDK (Streamable HTTP) |
| Hosting | [Railway](https://railway.app) |

---

## Project structure

```
freeroomfinder/
├── frontend/
│   ├── index.html          # Single-page UI
│   ├── app.js              # All frontend logic (search, SSE crawl progress, filters)
│   └── style.css           # Styles (dark mode, responsive)
├── backend/
│   ├── main.py             # FastAPI app, web-UI routes, startup + semester watcher
│   ├── config.py           # Settings, term-code computation
│   ├── calendar_scraper.py # Scrapes academiccalendar.byu.edu for semester start dates
│   ├── scraper.py          # Client for BYU's class-search API (commtech.byu.edu)
│   ├── discovery.py        # Crawls a building's courses concurrently → rooms + schedules
│   ├── scheduler.py        # Free-window computation used by the web UI
│   ├── availability.py     # Shared core for the public API + MCP tools
│   ├── api_v1.py           # Public read-only REST API (/api/v1/...)
│   ├── mcp_server.py       # Remote MCP server mounted at /mcp
│   ├── database.py         # SQLite schema + all DB queries
│   ├── buildings.py        # Master list of BYU building codes + display names
│   └── models.py           # Pydantic request/response models
├── tests/
│   └── test_availability.py
├── MCP_SETUP.md            # Shareable guide for connecting Claude to the MCP server
├── requirements.txt
├── Procfile
└── railway.toml
```

---

## Running locally

**Prerequisites:** Python 3.12+

```powershell
# 1. Create and activate a virtual environment (first time only)
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install dependencies (first time only)
pip install -r requirements.txt

# 3. Start the dev server
.venv\Scripts\uvicorn backend.main:app --reload --port 8080
```

Open [http://localhost:8080](http://localhost:8080).

`--reload` watches for Python file changes and restarts automatically. Frontend changes (HTML/CSS/JS) take effect on browser refresh.

> **Note:** Port 8000 may be blocked on some Windows machines. Use `--port 8080` or any other free port.

Run the tests (no network; they use a temporary SQLite DB):

```powershell
.venv\Scripts\python -m pytest
```

---

## How the data is collected

BYU doesn't publish room occupancy directly, so the app builds it from the public class search at `https://commtech.byu.edu/noauth/classSchedule` (no login):

1. `GET index.php` → extract the page's `_session_id` token
2. `POST ajax/getClasses.php` with `{yearterm, building}` → every course with a section meeting in that building
3. `POST ajax/getSections.php` for each course (up to `DISCOVERY_SEMAPHORE` at a time, `CRAWL_DELAY` apart) → section meeting times, which are filtered to the building and grouped by room

Each room and its class meetings (days, start/end time, course, section, instructor) are stored in SQLite. The API exposes no capacity, room description, or amenity data, so those fields are empty.

> The original scraper used `y.byu.edu/class_schedule/cgi/classRoom.cgi`, which BYU decommissioned around August 2026 (it now returns 404).

## How the cache works

- **First search of a building (web UI):** triggers a crawl of that building, streamed to the browser over SSE (`/api/discover/{building}`) as a progress bar (courses inspected / total, rooms found). Usually takes a few seconds. The UI also has a "cache all" action that crawls every building.
- **Subsequent searches:** instant — served from SQLite.
- **Cache is shared:** if one user crawls a building, everyone benefits immediately.
- **Cache lifetime:** data is kept until the next semester rollover (see below); it is not periodically re-crawled.
- **Only the web UI crawls.** The public API and MCP tools read whatever is already cached and never start a crawl, so a building nobody has searched on the website returns no rooms there.

The `cached` / `not cached` badge next to each building name shows its status at a glance.

## How free time is computed

For each room, the class meetings on the chosen weekday are clipped to your window, overlapping ones are merged, and the gaps that remain are returned as free windows (`backend/scheduler.py::compute_free_windows`). A room with no gaps is omitted. The web UI offers Monday–Saturday only; the API and MCP return no rooms for Sunday dates.

---

## Automatic semester management

No manual maintenance is required between semesters.

### Term detection

On startup, the app scrapes [academiccalendar.byu.edu](https://academiccalendar.byu.edu) for the start date of every semester (current year + 2 years ahead) and stores it in the DB. It re-scrapes when the stored copy is more than 7 days old. The current BYU term code (`YYYYT`) is computed from today's date against that schedule.

If BYU's calendar site is unreachable and nothing is stored, the app falls back to an algorithmic estimate based on approximate semester windows.

### Automatic cache wipe

A background task checks once a day (and once at startup). Starting the day before a new semester begins, the app treats that semester as active and clears all cached room and schedule data, so searches use the incoming semester's schedule. The wipe only happens when the effective term actually changes, so ordinary restarts keep the cache. Buildings must be re-crawled (by searching them) after a wipe.

Setting `YEAR_TERM` disables the automatic wipe.

### Term code format

BYU uses `YYYYT` where `T` is:

| Suffix | Semester | Approx. dates |
|---|---|---|
| `1` | Winter | Jan – Apr |
| `3` | Spring | Apr – Jun |
| `4` | Summer | Jun – Aug |
| `5` | Fall | Sep – Dec |

Example: `20261` = Winter 2026.

---

## HTTP routes

| Route | Used by | Purpose |
|---|---|---|
| `GET /` | browser | Serves the single-page UI |
| `GET /api/buildings` | web UI | All buildings with cached room counts |
| `GET /api/rooms/{building}` | web UI | Cached rooms for a building |
| `POST /api/search` | web UI | Free rooms for `{buildings, day, start_time, end_time}` |
| `GET /api/discover/{building}` | web UI | SSE stream that crawls a building |
| `GET /api/status` | Railway healthcheck | Cache stats per building |
| `/api/v1/...` | public | Read-only JSON API (below) |
| `/mcp` | Claude | Remote MCP server (below) |

---

## Environment variables (Railway)

| Variable | Required | Description |
|---|---|---|
| `PORT` | Auto-set by Railway | Port the server listens on |
| `DB_PATH` | Yes in production | Path to SQLite file on the mounted volume (e.g. `/data/freeroomfinder.db`). Defaults to `data/freeroomfinder.db` |
| `YEAR_TERM` | No | Override the auto-detected term code (local testing only; also disables the automatic wipe) |
| `DISCOVERY_SEMAPHORE` | No | Max concurrent course requests during a crawl (default: `15`) |
| `CRAWL_DELAY` | No | Seconds each request waits before firing during a crawl (default: `0.5`) |

> `YEAR_TERM` does not need to be set in production. The app detects the current term automatically.

---

## Deployment (Railway)

The app is configured for Railway via `railway.toml` (Nixpacks build, `uvicorn backend.main:app`, healthcheck on `/api/status`). It uses:
- A **GitHub-connected service** for the app code (auto-deploys on push to `main`)
- A **volume** mounted at the `DB_PATH` location for SQLite persistence

To deploy changes:
```bash
git add .
git commit -m "your message"
git push
```

Railway picks up the push and redeploys automatically.

---

## Public API v1 (read-only JSON)

One shared core (`backend/availability.py::find_open_rooms`) powers both the
REST API and the MCP tools, so they always agree. Human docs page:
`GET /api/v1/docs`.

```bash
curl "http://localhost:8080/api/v1/rooms/available?start=15:00&duration=120&building=HBLL"
curl "http://localhost:8080/api/v1/rooms/available?date=2026-09-23&start=09:00&duration=60"
curl "http://localhost:8080/api/v1/buildings"
curl "http://localhost:8080/api/v1/rooms/HBLL:2214"   # id = BUILDING:room, URL-encoded
```

- Params: `date` YYYY-MM-DD (default today, America/Denver) → mapped to its
  weekday; `start` HH:MM required; `duration` 15–960 min; `group_size` advisory
  only (capacity data doesn't exist, never excludes); `building` code (omit to
  search all *cached* buildings); `amenities` comma-separated — always matches
  nothing (no amenity data).
- Only buildings already crawled via the web UI return rooms;
  `/api/v1/buildings` reports `has_cached_rooms` for each.
- Every response includes `as_of` + `timezone: America/Denver`; times ISO 8601.
- Bad params → `400 {"detail": "..."}`. Rate limit 120 req/min/IP (429).
  Server-side response cache ~5 min. CORS open for GET.
- Honest nulls: `capacity` usually null, `amenities` always `[]`,
  `booking_url` = generic BYU class-search page, `requires_login: false`.
  Rooms are walk-in spaces inferred from class times, not bookable reservations.

## Remote MCP server (Claude custom connector)

- URL after deploy: `https://<your-railway-domain>/mcp` (Streamable HTTP,
  official `mcp` Python SDK — works with v2 `MCPServer` or v1 `FastMCP`;
  no auth — read-only public data).
- Tools (all read-only, all backed by `availability.py`): `find_open_rooms`,
  `get_room_details`, `list_buildings`, `get_booking_link`. Verify locally:
  `npx @modelcontextprotocol/inspector` → transport Streamable HTTP →
  URL `http://localhost:8080/mcp`.
- Claude setup: Settings → Connectors → Add custom connector → paste the
  `/mcp` URL. A shareable walkthrough is in [MCP_SETUP.md](MCP_SETUP.md).
- Example prompts: "Find a room for 4 people in the library tomorrow at 3pm
  for 2 hours" · "What's open in the HBLL this Saturday morning?" ·
  "Get details and today's availability for HBLL:2214."

## Upstream respect / BYU terms note

Source is BYU's public `noauth` class search (no login, no credentials ever
collected/proxied/stored). We cache DB-side for the whole semester + 5-min API
cache, limit crawl concurrency (15, 0.5s delay), rate-limit callers, and send a
normal browser UA. BYU's IT appropriate-use policy has no explicit scraping
license — `noauth` implies public, but if OIT objects, throttle further or
remove the building. No commercial use; site use is incidental/personal.
