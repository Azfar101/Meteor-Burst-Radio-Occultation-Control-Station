// Application bootstrap: data loading, mode/tool wiring, link planning
// orchestration, telemetry polling.

import { state, on, emit, stationById, timeISO, toast } from "./state.js";
import { api } from "./api.js";
import {
  initMap, syncStations, renderProfiles, refreshIono, renderSondes,
  setSondesVisible, setBasemap, renderMbg, mapCenter,
  drawRoute, clearRoute, flyToStation, setMarkersDraggable, clearCoverage,
} from "./map.js";
import {
  renderSidebar, selectStation, deselect, closePanel,
  openRoutePanel, openSettingsModal, openImportModal, updateDataChip, openMbgPanel,
} from "./panels.js";
import { initTimebar } from "./timebar.js";

// ── data loaders ─────────────────────────────────────────────────────

async function loadStations() {
  state.stations = await api.stations();
  syncStations();
  renderSidebar();
}

async function loadTelemetry() {
  try {
    state.telemetry = await api.telemetry();
    emit("telemetry");
  } catch { /* server briefly unavailable — keep last values */ }
}

async function loadMbg() {
  try {
    state.mbg = await api.mbgPoints();
    renderMbg();
  } catch { /* keep last */ }
}

async function loadProfiles() {
  const r = await api.profiles();
  state.profiles = r.profiles;
  state.profileRange = r.time_min
    ? [new Date(r.time_min), new Date(r.time_max)]
    : null;
  renderProfiles();
  updateDataChip();
  emit("profiles");
  refreshIono(true);
}

async function loadSettings() {
  Object.assign(state.settings, await api.settings());
}

async function loadSondes() {
  try {
    const hadData = !!state.liveIono?.count;
    const r = await api.ionosondes();
    state.sondes = r.sondes;
    state.liveIono = { ok: r.ok, ssn: r.ssn, count: r.count };
    renderSondes();
    updateDataChip();
    // live data just arrived for the first time — repaint the heat grid
    if (!hadData && r.count > 0) refreshIono(true);
    else if (!hadData && !r.count && loadSondes._retries++ < 6) {
      setTimeout(loadSondes, 20000);  // retry while the backend cache warms
    }
  } catch { /* offline — model fallback keeps working */ }
}
loadSondes._retries = 0;

// ── theme ────────────────────────────────────────────────────────────

function applyTheme(theme, swapBasemap = true) {
  state.theme = theme;
  document.body.classList.toggle("light", theme === "light");
  const btn = document.getElementById("btn-theme");
  if (btn) btn.textContent = theme === "light" ? "☾" : "☀";
  localStorage.setItem("mbc-theme", theme);
  if (swapBasemap) setBasemap(theme);
}

// ── link planning orchestration ──────────────────────────────────────

async function computeRoute() {
  if (!state.linkA || !state.linkB) return;
  try {
    const r = await api.route(state.linkA, state.linkB, timeISO());
    state.route = r;
    state.transmitting = false;
    drawRoute(r);
    openRoutePanel(r, state.linkA, state.linkB);
    if (!r.feasible) toast("No feasible route — see analysis panel", "err");
  } catch (e) {
    toast(`Route failed: ${e.message}`, "err");
  }
}

function setLinkEnd(end, id) {
  if (end === "a") {
    state.linkA = id;
    if (state.linkB === id) state.linkB = null;
  } else {
    state.linkB = id;
    if (state.linkA === id) state.linkA = null;
  }
  emit("linksel");
  const s = stationById(id);
  if (state.linkA && state.linkB) {
    computeRoute();
  } else {
    toast(end === "a"
      ? `Source: ${s.code} — now pick a destination`
      : `Destination: ${s.code} — now pick a source`);
  }
}

function clearLink() {
  state.linkA = null;
  state.linkB = null;
  state.route = null;
  state.transmitting = false;
  emit("linksel");
  clearRoute();
  closePanel();
}

// ── mode + sim tools ─────────────────────────────────────────────────

function setMode(mode) {
  state.mode = mode;
  document.body.classList.toggle("sim-mode", mode === "sim");
  document.querySelectorAll(".modes button").forEach((b) =>
    b.classList.toggle("active", b.dataset.mode === mode));
  setTool(mode === "sim" ? state.tool : "select");
  // re-open the station panel so sim-only controls appear/disappear
  if (state.selectedId) selectStation(state.selectedId);
  if (mode === "ops") toast("Operations mode — live network monitoring");
  else toast("Simulation mode — place stations, plan links, transmit");
}

const TOOL_HINTS = {
  select: "Drag stations to move them",
  add: "Click anywhere on the map to place a station",
  link: "Click source station, then destination",
  mbg: "Click the map to drop a meteor-burst bounce point",
  delete: "Click a station or MBG point to remove it",
};

function setTool(tool) {
  state.tool = tool;
  document.body.classList.remove("tool-add", "tool-delete", "tool-link", "tool-mbg");
  if (state.mode === "sim" && tool !== "select") document.body.classList.add(`tool-${tool}`);
  document.querySelectorAll("#simbar button[data-tool]").forEach((b) =>
    b.classList.toggle("active", b.dataset.tool === tool));
  const hint = document.getElementById("sim-hint");
  if (hint) hint.textContent = state.mode === "sim" ? TOOL_HINTS[tool] : "";
  setMarkersDraggable(state.mode === "sim" && tool === "select");
}

// ── event wiring ─────────────────────────────────────────────────────

function wireEvents() {
  document.querySelectorAll(".modes button").forEach((b) =>
    b.addEventListener("click", () => setMode(b.dataset.mode)));

  document.querySelectorAll("#simbar button[data-tool]").forEach((b) =>
    b.addEventListener("click", () => setTool(b.dataset.tool)));

  document.getElementById("btn-settings").addEventListener("click", openSettingsModal);
  document.getElementById("btn-import").addEventListener("click", openImportModal);
  document.getElementById("btn-about").addEventListener("click", () => {
    document.getElementById("about-overlay").style.display = "grid";
  });
  document.getElementById("about-close").addEventListener("click", () => {
    document.getElementById("about-overlay").style.display = "none";
  });
  document.getElementById("about-overlay").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) e.currentTarget.style.display = "none";
  });
  document.getElementById("sb-add").addEventListener("click", async () => {
    try {
      const c = mapCenter();
      const s = await api.addStation({ name: "New Station", lat: c.lat, lon: c.lon });
      await loadStations();
      selectStation(s.id);
      flyToStation(s);
      toast(`Station ${s.code} added — edit its name/position in the panel`, "ok");
    } catch (e) { toast(e.message, "err"); }
  });
  document.getElementById("btn-theme").addEventListener("click", () =>
    applyTheme(state.theme === "light" ? "dark" : "light"));

  on("sondes:toggle", () => setSondesVisible(state.sondesVisible));

  document.getElementById("sb-toggle").addEventListener("click", () => {
    const sb = document.getElementById("sidebar");
    sb.classList.toggle("hidden");
    document.body.classList.toggle("sidebar-hidden", sb.classList.contains("hidden"));
  });

  on("station:click", async ({ id }) => {
    if (state.mode === "sim" && state.tool === "delete") {
      try {
        await api.deleteStation(id);
        if (state.selectedId === id) deselect();
        if (state.linkA === id || state.linkB === id) clearLink();
        await loadStations();
        toast("Station removed", "ok");
      } catch (e) { toast(e.message, "err"); }
      return;
    }
    if (state.mode === "sim" && state.tool === "link") {
      if (!state.linkA) setLinkEnd("a", id);
      else if (id !== state.linkA && (!state.linkB || state.linkB !== id)) setLinkEnd("b", id);
      else setLinkEnd("a", id);
      return;
    }
    selectStation(id);
  });

  on("map:add", async ({ lat, lon }) => {
    try {
      const s = await api.addStation({ name: "Field Relay", lat, lon });
      await loadStations();
      toast(`Station ${s.code} placed — drag with Select tool to adjust`, "ok");
    } catch (e) { toast(e.message, "err"); }
  });

  on("mbg:add", async ({ lat, lon }) => {
    try {
      const m = await api.addMbg({ lat, lon });
      await loadMbg();
      openMbgPanel(m.id);
      toast(`Bounce point ${m.name} placed — set its height & plasma freq`, "ok");
    } catch (e) { toast(e.message, "err"); }
  });
  on("mbg:click", ({ id }) => openMbgPanel(id));
  on("mbg:delete", async ({ id }) => {
    try { await api.deleteMbg(id); await loadMbg(); toast("MBG point removed", "ok"); }
    catch (e) { toast(e.message, "err"); }
  });
  on("mbg:reload", loadMbg);

  on("station:delete", async ({ id }) => {
    try {
      await api.deleteStation(id);
      deselect();
      if (state.linkA === id || state.linkB === id) clearLink();
      await loadStations();
      toast("Station removed", "ok");
    } catch (e) { toast(e.message, "err"); }
  });

  on("linkpick", ({ id, end }) => setLinkEnd(end, id));
  on("route:clear", clearLink);

  on("stations:reload", async () => { clearLink(); clearCoverage(); deselect(); await loadStations(); });
  on("stations:moved", () => {
    renderSidebar();
    if (state.linkA && state.linkB) computeRoute();
  });
  on("profiles:reload", loadProfiles);

  // recompute the active route when sim time or settings change
  let recompute;
  const queueRecompute = () => {
    clearTimeout(recompute);
    recompute = setTimeout(() => {
      if (state.linkA && state.linkB && !state.transmitting) computeRoute();
    }, 600);
  };
  on("time", queueRecompute);
  on("settings", queueRecompute);

  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const about = document.getElementById("about-overlay");
      if (about.style.display !== "none") { about.style.display = "none"; return; }
      document.getElementById("modal-root").innerHTML = "";
      if (state.route) clearLink();
      else deselect();
    }
  });
}

// ── boot ─────────────────────────────────────────────────────────────

async function boot() {
  try {
    const theme = localStorage.getItem("mbc-theme") || "dark";
    applyTheme(theme, false);          // basemap gets the theme via initMap
    await loadSettings();
    await initMap(theme);
    await loadStations();
    await loadTelemetry();
    await loadProfiles();
    await loadMbg();
    initTimebar();
    wireEvents();
    setMode("ops");
    loadSondes();                       // live GIRO data (non-blocking)

    setInterval(loadTelemetry, 3000);
    setInterval(loadSondes, 5 * 60 * 1000);
    toast("MBC Ground Control online", "ok");
  } catch (e) {
    console.error(e);
    toast(`Startup failed: ${e.message}`, "err");
  }
}

boot();
