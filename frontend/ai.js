// "Use with AI" page: theme toggle, server-URL fill-in, copy buttons.

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  document.getElementById("btn-theme").addEventListener("click", toggleTheme);
  fillBaseUrl();
  document.querySelectorAll(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", () => copyFrom(btn));
  });
});

// ── Dark mode (same storage key as the main page) ────────
function initTheme() {
  let saved = "light";
  try { saved = localStorage.getItem("theme") || "light"; } catch {}
  applyTheme(saved);
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  const btn = document.getElementById("btn-theme");
  if (btn) btn.innerHTML = theme === "dark" ? "&#9728; Light" : "&#9790; Dark";
  try { localStorage.setItem("theme", theme); } catch {}
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme");
  applyTheme(current === "dark" ? "light" : "dark");
}

// ── URLs follow whichever host serves the page (prod or localhost) ──
function fillBaseUrl() {
  const base = window.location.origin;
  document.querySelectorAll("[data-fill]").forEach((el) => {
    el.textContent = el.textContent.replaceAll("__BASE__", base);
  });
}

// ── Copy to clipboard ─────────────────────────────────────
async function copyFrom(btn) {
  const text = document.getElementById(btn.dataset.copy).textContent;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Fallback for browsers/contexts without the async clipboard API
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  const label = btn.textContent;
  btn.textContent = "Copied!";
  btn.classList.add("copied");
  setTimeout(() => {
    btn.textContent = label;
    btn.classList.remove("copied");
  }, 1500);
}
