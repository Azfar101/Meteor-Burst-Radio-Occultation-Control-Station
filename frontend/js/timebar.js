// Bottom time bar: scrub through the loaded COSMIC-2 window (or ±12 h
// around now), play/pause animation, LIVE mode, ionosphere toggle.

import { state, on, emit, fmtTime } from "./state.js";

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

  document.getElementById("tb-sondes").addEventListener("change", (e) => {
    state.sondesVisible = e.target.checked;
    emit("sondes:toggle");
  });

  on("profiles", () => { computeRange(); updateLabel(); });
  updateLabel();
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
