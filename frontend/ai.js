// "Link your AI" page: theme toggle, server-URL fill-in, setup tabs, copy buttons.

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  document.getElementById("btn-theme").addEventListener("click", toggleTheme);
  fillBaseUrl();
  initTabs();
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", () =>
      copyText(document.getElementById(btn.dataset.copy).textContent, btn)
    );
  });
  document.querySelectorAll("[data-copy-text]").forEach((btn) => {
    btn.addEventListener("click", () => copyText(btn.dataset.copyText, btn));
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

// ── Setup tabs ────────────────────────────────────────────
function initTabs() {
  const tabs = [...document.querySelectorAll('.ai-tabs [role="tab"]')];

  function select(tab) {
    tabs.forEach((t) => {
      const on = t === tab;
      t.setAttribute("aria-selected", on);
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    });
  }

  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => select(tab));
    tab.addEventListener("keydown", (e) => {
      const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (!step) return;
      const next = tabs[(i + step + tabs.length) % tabs.length];
      select(next);
      next.focus();
    });
  });
}

// ── Copy to clipboard ─────────────────────────────────────
async function copyText(text, btn) {
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
  // Example rows show their label in a child span; copy buttons use their own text
  const label = btn.querySelector(".example-copy") || btn;
  const original = label.textContent;
  label.textContent = "Copied!";
  btn.classList.add("copied");
  setTimeout(() => {
    label.textContent = original;
    btn.classList.remove("copied");
  }, 1500);
}
