// Global app state + tiny event bus.

export const state = {
  mode: "ops",            // "ops" | "sim"
  tool: "select",         // sim tool: select | add | link | delete
  stations: [],
  telemetry: {},
  profiles: [],
  profileRange: null,     // [Date, Date] | null
  settings: { freq_min_mhz: 25, freq_max_mhz: 45, data_rate_kbps: 9.6, max_hops: 6, allow_meteor_mode: true, ssn: 70, use_footprints_bounce: true },
  footprintsVisible: false,  // persistent reflection-footprint rings
  mbg: [],                   // custom MBG bounce points
  time: null,             // Date | null (null = live)
  selectedId: null,
  linkA: null,            // station id
  linkB: null,
  route: null,            // last route result
  transmitting: false,
  ionoVisible: true,
  sondesVisible: true,
  sondes: [],             // live GIRO ionosonde soundings
  liveIono: null,         // { ok, ssn, count } from /api/ionosondes
  theme: "dark",
};

const listeners = {};

export function on(event, cb) {
  (listeners[event] = listeners[event] || []).push(cb);
}

export function emit(event, data) {
  (listeners[event] || []).forEach((cb) => {
    try { cb(data); } catch (e) { console.error(`[bus:${event}]`, e); }
  });
}

// ── helpers ──────────────────────────────────────────────────────────

export function stationById(id) {
  return state.stations.find((s) => s.id === id) || null;
}

export function currentTime() {
  return state.time || new Date();
}

export function timeISO() {
  return currentTime().toISOString();
}

export function fmtTime(d) {
  if (!d) return "—";
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ` +
         `${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`;
}

export function fmtKm(v) {
  return v >= 1000 ? `${(v / 1000).toFixed(2)} Mm`.replace(" Mm", " ×10³ km") : `${Math.round(v)} km`;
}

export function toast(msg, kind = "") {
  const root = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  root.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .4s"; }, 3400);
  setTimeout(() => el.remove(), 3900);
}

export function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
