// ── State ───────────────────────────────────────────────
let buildings = [];
let selectedDay = null;
let activeDiscovery = {}; // building -> EventSource

// ── Init ────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", init);

async function init() {
  initTheme();
  populateTimeDropdowns();
  attachEventListeners();
  await loadBuildings();
}

// ── Dark mode ────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem("theme") || "light";
  applyTheme(saved);
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("btn-theme");
  if (btn) btn.innerHTML = theme === "dark" ? "&#9728; Light" : "&#9790; Dark";
  localStorage.setItem("theme", theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  applyTheme(current === "dark" ? "light" : "dark");
}

// ── Buildings ────────────────────────────────────────────
async function loadBuildings() {
  try {
    const res = await fetch("/api/buildings");
    buildings = await res.json();
    renderBuildingList(buildings);
  } catch (e) {
    document.getElementById("building-list").innerHTML =
      '<div class="error-msg">Failed to load buildings.</div>';
  }
}

function renderBuildingList(list) {
  const container = document.getElementById("building-list");
  container.innerHTML = "";
  list.forEach((b) => {
    const label = document.createElement("label");
    label.className = "building-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = b.code;

    const nameSpan = document.createElement("span");
    nameSpan.className = "b-name";
    nameSpan.textContent = `${b.code} – ${b.display_name}`;

    const badge = document.createElement("span");
    badge.className = b.rooms_cached > 0 ? "b-badge cached" : "b-badge";
    badge.textContent = b.rooms_cached > 0
      ? `${b.rooms_cached} rooms`
      : b.last_crawled ? "0 rooms" : "not cached";
    badge.id = `badge-${b.code}`;

    label.appendChild(checkbox);
    label.appendChild(nameSpan);
    label.appendChild(badge);
    container.appendChild(label);
  });
}

function getSelectedBuildings() {
  return Array.from(
    document.querySelectorAll("#building-list input[type=checkbox]:checked")
  ).map((cb) => cb.value);
}

function selectAllBuildings() {
  document.querySelectorAll("#building-list input[type=checkbox]").forEach(
    (cb) => (cb.checked = true)
  );
}

function clearBuildings() {
  document.querySelectorAll("#building-list input[type=checkbox]").forEach(
    (cb) => (cb.checked = false)
  );
}

function filterBuildingList(query) {
  const q = query.trim().toLowerCase();
  document.querySelectorAll("#building-list .building-item").forEach((item) => {
    const text = item.querySelector(".b-name").textContent.toLowerCase();
    item.style.display = !q || text.includes(q) ? "" : "none";
  });
}

// ── Day selector ──────────────────────────────────────────
function attachEventListeners() {
  document.getElementById("btn-select-all").addEventListener("click", selectAllBuildings);
  document.getElementById("btn-clear").addEventListener("click", clearBuildings);
  document.getElementById("btn-search").addEventListener("click", handleSearch);
  document.getElementById("btn-theme").addEventListener("click", toggleTheme);
  document.getElementById("building-search").addEventListener("input", (e) => {
    filterBuildingList(e.target.value);
  });

  document.querySelectorAll(".day-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".day-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      selectedDay = btn.dataset.day;
    });
  });
}

function getSelectedDay() {
  return selectedDay;
}

// ── Time dropdowns ────────────────────────────────────────
function populateTimeDropdowns() {
  const startSel = document.getElementById("start-time");
  const endSel = document.getElementById("end-time");
  const slots = [];

  for (let h = 7; h <= 22; h++) {
    for (let m = 0; m < 60; m += 30) {
      if (h === 22 && m > 0) break;
      slots.push({ h, m });
    }
  }

  slots.forEach(({ h, m }) => {
    const value = formatTimeValue(h, m);
    const label = formatTimeLabel(h, m);
    startSel.add(new Option(label, value));
    endSel.add(new Option(label, value));
  });

  // Default: 8:00 AM – 10:00 AM
  startSel.value = "08:00";
  endSel.value = "10:00";
}

function formatTimeLabel(h, m) {
  const ampm = h < 12 ? "AM" : "PM";
  const hDisplay = h % 12 === 0 ? 12 : h % 12;
  const mDisplay = m === 0 ? "00" : m;
  return `${hDisplay}:${mDisplay} ${ampm}`;
}

function formatTimeValue(h, m) {
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

// ── Search ────────────────────────────────────────────────
async function handleSearch() {
  clearResults();
  clearError();

  const selectedBuildings = getSelectedBuildings();
  const day = getSelectedDay();
  const startTime = document.getElementById("start-time").value;
  const endTime = document.getElementById("end-time").value;

  if (selectedBuildings.length === 0) {
    showError("Please select at least one building.");
    return;
  }
  if (!day) {
    showError("Please select a day.");
    return;
  }
  if (startTime >= endTime) {
    showError("End time must be after start time.");
    return;
  }

  const btn = document.getElementById("btn-search");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Searching…';

  try {
    // Discover any uncached buildings first, then search
    const uncached = buildings
      .filter((b) => selectedBuildings.includes(b.code) && b.last_crawled === null)
      .map((b) => b.code);

    if (uncached.length > 0) {
      showProgressArea(uncached);
      btn.innerHTML = '<span class="spinner"></span> Discovering rooms…';
      await discoverBuildings(uncached);
      await loadBuildings(); // refresh cached counts
    }

    btn.innerHTML = '<span class="spinner"></span> Searching…';

    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        buildings: selectedBuildings,
        day,
        start_time: startTime,
        end_time: endTime,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      showError(err.detail || "Search failed.");
      return;
    }

    const data = await res.json();
    renderResults(data);
    await loadBuildings();
  } catch (e) {
    showError("Network error. Is the server running?");
  } finally {
    btn.disabled = false;
    btn.textContent = "Find Free Rooms";
  }
}

function renderResults(data) {
  const placeholder = document.getElementById("results-placeholder");
  const table = document.getElementById("results-table");
  const tbody = document.getElementById("results-body");
  const countBadge = document.getElementById("results-count");

  tbody.innerHTML = "";

  if (!data.rooms || data.rooms.length === 0) {
    placeholder.textContent = `No rooms with any free time found on ${data.day} from ${fmtTime(data.start_time)} to ${fmtTime(data.end_time)}. Try different buildings or a wider time window.`;
    placeholder.style.display = "";
    table.style.display = "none";
    countBadge.style.display = "none";
    return;
  }

  placeholder.style.display = "none";
  table.style.display = "";

  const fullyFree = data.rooms.filter((r) => r.is_fully_free);
  const partial   = data.rooms.filter((r) => !r.is_fully_free);
  countBadge.textContent = `${fullyFree.length} fully free · ${partial.length} partial`;
  countBadge.style.display = "";

  let lastWasFull = true;

  data.rooms.forEach((room, i) => {
    // Insert a divider between fully-free and partial sections
    if (lastWasFull && !room.is_fully_free && i > 0) {
      const divRow = document.createElement("tr");
      divRow.className = "section-divider";
      divRow.innerHTML = `<td colspan="5">Partially free — room has classes during part of this window</td>`;
      tbody.appendChild(divRow);
    }
    lastWasFull = room.is_fully_free;

    const tr = document.createElement("tr");
    if (!room.is_fully_free) tr.classList.add("partial-row");

    const roomLink = `<a class="room-link" href="#" onclick="openBYURoom('${room.building}','${room.room_number}'); return false;">${room.room_number}</a>`;
    const availHtml = renderAvailability(room);

    tr.innerHTML = `
      <td><strong>${room.building}</strong></td>
      <td>${roomLink}</td>
      <td>${room.description || "—"}</td>
      <td>${room.capacity != null ? `<span class="cap-badge">${room.capacity}</span>` : "—"}</td>
      <td>${availHtml}</td>
    `;
    tbody.appendChild(tr);
  });
}

function renderAvailability(room) {
  return room.free_windows.map((w) => {
    const dur = fmtDuration(w.duration_minutes);
    const tag = room.is_fully_free
      ? `<span class="avail-full">${fmtTime(w.start_time)} – ${fmtTime(w.end_time)} · ${dur}</span>`
      : `<span class="avail-part">${fmtTime(w.start_time)} – ${fmtTime(w.end_time)} · ${dur}</span>`;
    return tag;
  }).join("<br>");
}

function fmtDuration(mins) {
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m === 0 ? `${h} hr` : `${h} hr ${m} min`;
}

function openBYURoom(building, room) {
  // BYU's site uses a POST form, so we open the page and let the user navigate
  const url = `https://y.byu.edu/class_schedule/cgi/classRoom.cgi`;
  // Open a helper that uses a form POST via a new tab
  const win = window.open("", "_blank");
  win.document.write(`
    <html><body>
    <form id="f" method="POST" action="${url}">
      <input name="year_term" value="20261">
      <input name="building" value="${building}">
      <input name="room" value="${room}">
      <input name="tab_option" value="Schedule">
    </form>
    <script>document.getElementById('f').submit();<\/script>
    </body></html>
  `);
  win.document.close();
}

// ── Discovery Progress (SSE) ──────────────────────────────

/**
 * Run discovery for all listed buildings concurrently.
 * Returns a Promise that resolves when ALL buildings finish.
 */
function discoverBuildings(buildingCodes) {
  return Promise.all(buildingCodes.map((code) => discoverOneBuilding(code)));
}

/**
 * Run discovery for a single building via SSE.
 * Returns a Promise that resolves when the "done" event is received.
 */
function discoverOneBuilding(building) {
  return new Promise((resolve) => {
    if (activeDiscovery[building]) {
      // Already running — reuse existing promise would be complex; just resolve immediately
      // The progress bar update will still happen via the existing EventSource
      resolve();
      return;
    }
    const es = new EventSource(`/api/discover/${building}`);
    activeDiscovery[building] = es;

    es.addEventListener("progress", (e) => {
      const d = JSON.parse(e.data);
      updateProgressBar(building, d.attempted, d.total, d.found);
    });

    es.addEventListener("done", (e) => {
      const bar = document.getElementById(`prog-bar-${building}`);
      const txt = document.getElementById(`prog-text-${building}`);
      if (bar) bar.style.width = "100%";
      if (txt) {
        const d = JSON.parse(e.data);
        txt.textContent = `Done – ${d.found} rooms cached`;
      }
      es.close();
      delete activeDiscovery[building];
      resolve();
    });

    es.onerror = () => {
      es.close();
      delete activeDiscovery[building];
      resolve(); // resolve anyway so Promise.all doesn't hang
    };
  });
}

function showProgressArea(buildingCodes) {
  const area = document.getElementById("progress-area");
  area.innerHTML = "";
  buildingCodes.forEach((code) => {
    const wrap = document.createElement("div");
    wrap.className = "progress-wrap";
    wrap.id = `progress-${code}`;
    wrap.innerHTML = `
      <div class="progress-label">
        <span>${code} – discovering rooms…</span>
        <span id="prog-text-${code}">0%</span>
      </div>
      <div class="progress-bar-track">
        <div class="progress-bar-fill" id="prog-bar-${code}" style="width:0%"></div>
      </div>
    `;
    area.appendChild(wrap);
  });
}

function updateProgressBar(building, attempted, total, found) {
  const pct = total > 0 ? Math.round((attempted / total) * 100) : 0;
  const bar = document.getElementById(`prog-bar-${building}`);
  const txt = document.getElementById(`prog-text-${building}`);
  if (bar) bar.style.width = `${pct}%`;
  if (txt) txt.textContent = `${pct}% (${found} cached)`;
}

// ── Utilities ─────────────────────────────────────────────
function fmtTime(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  const ampm = h < 12 ? "AM" : "PM";
  const hd = h % 12 === 0 ? 12 : h % 12;
  return `${hd}:${String(m).padStart(2, "0")} ${ampm}`;
}

function showError(msg) {
  document.getElementById("error-area").innerHTML =
    `<div class="error-msg">${msg}</div>`;
}

function clearError() {
  document.getElementById("error-area").innerHTML = "";
}

function clearResults() {
  document.getElementById("results-placeholder").textContent =
    "Select buildings and a time window, then click Find Free Rooms.";
  document.getElementById("results-placeholder").style.display = "";
  document.getElementById("results-table").style.display = "none";
  document.getElementById("results-count").style.display = "none";
  document.getElementById("progress-area").innerHTML = "";
  document.getElementById("results-body").innerHTML = "";
}
