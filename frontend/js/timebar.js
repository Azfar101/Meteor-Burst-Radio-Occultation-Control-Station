// Bottom time bar: scrub through the loaded COSMIC-2 window (or ±12 h
// around now), play/pause animation, LIVE mode, ionosphere toggle.

import { state, on, emit, fmtTime } from "./state.js";
import { api } from "./api.js";
import { opFreqGradientCss } from "./colormap.js";

let t0 = null;   // Date range covered by the slider
let t1 = null;
let playTimer = null;

const slider = () => document.getElementById("tb-slider");
const label = () => document.getElementById("tb-label");
const playBtn = () => document.getElementById("tb-play");
const liveBtn = () => document.getElementById("tb-live");

export function initTimebar() {
  computeRange();

  slider().addEventListener("input", () => {
    state.time = posToTime(+slider().value);
    updateLabel();
    emit("time");
  });

  playBtn().addEventListener("click", togglePlay);

  liveBtn().addEventListener("click", () => {
    stopPlay();
    state.time = null;
    computeRange();
    updateLabel();
    emit("time");
  });

  document.getElementById("tb-iono").addEventListener("change", (e) => {
    state.ionoVisible = e.target.checked;
    emit("iono");
  });

  initThresholdControls();

  on("profiles", () => { computeRange(); updateLabel(); });
  updateLabel();
}

// ── minimum operating frequency + footprint toggle ───────────────────
// The slider sets the station's lowest operating frequency, which doubles as
// the "usable patch" threshold: a patch shows iff its max usable frequency
// (fp·sec at grazing) clears this value.

let saveThreshTimer = null;

function initThresholdControls() {
  // restore persisted values
  const savedT = parseFloat(localStorage.getItem("mbc-opfreq-min"));
  if (!Number.isNaN(savedT)) state.settings.freq_min_mhz = savedT;
  state.footprintsVisible = localStorage.getItem("mbc-footprints") === "1";

  const grad = document.getElementById("legend-grad-op");
  if (grad) grad.style.background = opFreqGradientCss();

  const slider = document.getElementById("tb-opfreq");
  const valEl = document.getElementById("tb-opfreq-val");
  const fp = document.getElementById("tb-footprints");
  slider.value = String(state.settings.freq_min_mhz);
  valEl.textContent = `${Math.round(state.settings.freq_min_mhz)} MHz`;
  fp.checked = state.footprintsVisible;

  slider.addEventListener("input", () => {
    let v = +slider.value;
    if (v > state.settings.freq_max_mhz) v = state.settings.freq_max_mhz;  // keep min ≤ max
    state.settings.freq_min_mhz = v;
    slider.value = String(v);
    valEl.textContent = `${Math.round(v)} MHz`;
    localStorage.setItem("mbc-opfreq-min", String(v));
    emit("fpthreshold");                       // cheap: map filter + footprints
    clearTimeout(saveThreshTimer);             // debounce backend save + route recompute
    saveThreshTimer = setTimeout(async () => {
      try {
        const saved = await api.saveSettings({ freq_min_mhz: v });
        Object.assign(state.settings, saved);
        emit("settings");
      } catch { /* offline — display filter still applied locally */ }
    }, 500);
  });

  fp.addEventListener("change", () => {
    state.footprintsVisible = fp.checked;
    localStorage.setItem("mbc-footprints", fp.checked ? "1" : "0");
    const legend = document.getElementById("legend-op");
    if (legend) legend.style.display = fp.checked ? "" : "none";
    emit("footprints:toggle");
  });

  // apply restored values to the map (listeners are already wired)
  emit("fpthreshold");
  if (state.footprintsVisible) {
    document.getElementById("legend-op").style.display = "";
    emit("footprints:toggle");
  }

  // keep the slider in sync when the Settings modal changes the range
  on("settings", syncOpFreqSlider);
}

function syncOpFreqSlider() {
  const slider = document.getElementById("tb-opfreq");
  const valEl = document.getElementById("tb-opfreq-val");
  if (!slider) return;
  slider.value = String(state.settings.freq_min_mhz);
  valEl.textContent = `${Math.round(state.settings.freq_min_mhz)} MHz`;
}

function computeRange() {
  if (state.profileRange) {
    const pad = 2 * 3600 * 1000;
    t0 = new Date(state.profileRange[0].getTime() - pad);
    t1 = new Date(state.profileRange[1].getTime() + pad);
  } else {
    const now = Date.now();
    t0 = new Date(now - 12 * 3600 * 1000);
    t1 = new Date(now + 12 * 3600 * 1000);
  }
  slider().value = String(timeToPos(state.time || new Date()));
}

function posToTime(pos) {
  return new Date(t0.getTime() + (pos / 1000) * (t1.getTime() - t0.getTime()));
}

function timeToPos(d) {
  const f = (d.getTime() - t0.getTime()) / (t1.getTime() - t0.getTime());
  return Math.round(Math.min(1, Math.max(0, f)) * 1000);
}

function updateLabel() {
  const live = state.time === null;
  label().textContent = fmtTime(state.time || new Date()) + (live ? " · LIVE" : "");
  liveBtn().classList.toggle("active", live);
}

function togglePlay() {
  if (playTimer) { stopPlay(); return; }
  playBtn().classList.add("playing");
  playBtn().textContent = "❚❚";
  if (state.time === null) state.time = posToTime(+slider().value);
  playTimer = setInterval(() => {
    let pos = +slider().value + 2;
    if (pos > 1000) pos = 0;
    slider().value = String(pos);
    state.time = posToTime(pos);
    updateLabel();
    emit("time");
  }, 140);
}

function stopPlay() {
  clearInterval(playTimer);
  playTimer = null;
  playBtn().classList.remove("playing");
  playBtn().textContent = "▶";
}

// keep the LIVE clock ticking in the label
setInterval(() => { if (state.time === null) updateLabel(); }, 20000);
