// MapLibre map: basemap, ionosphere overlay, station markers, coverage
// rings, COSMIC-2 profile layer, route arcs and packet animation.

import { state, on, emit, timeISO, toast, escapeHtml } from "./state.js";
import { api } from "./api.js";
import { fpColorExpression } from "./colormap.js";

export let map = null;

const EMPTY = { type: "FeatureCollection", features: [] };
const R_E = 6371.0;

const markers = {};        // station id -> { marker, el }
let coveredId = null;      // station id with coverage ring shown
let packetEl = null;
let packetMarker = null;
let animState = null;      // { hops:[{coords, cum, total}], hopIdx, t0 }
let pulsePhase = 0;
let rafId = null;

// ── init ─────────────────────────────────────────────────────────────

function cartoSource(theme) {
  const flavor = theme === "light" ? "light_all" : "dark_all";
  return {
    type: "raster",
    tiles: ["a", "b", "c", "d"].map(
      (s) => `https://${s}.basemaps.cartocdn.com/${flavor}/{z}/{x}/{y}@2x.png`),
    tileSize: 256,
    attribution: "© OpenStreetMap contributors © CARTO",
  };
}

export function setBasemap(theme) {
  if (!map || !map.getSource("carto")) return;
  if (map.getLayer("base")) map.removeLayer("base");
  map.removeSource("carto");
  map.addSource("carto", cartoSource(theme));
  // re-insert beneath all overlay layers
  const before = map.getLayer("iono-fill") ? "iono-fill" : undefined;
  map.addLayer({ id: "base", type: "raster", source: "carto" }, before);
}

export function initMap(theme = "dark") {
  return new Promise((resolve) => {
    map = new maplibregl.Map({
      container: "map",
      style: {
        version: 8,
        sources: { carto: cartoSource(theme) },
        layers: [{ id: "base", type: "raster", source: "carto" }],
      },
      center: [60, 18],
      zoom: 2.1,
      minZoom: 1.2,
      maxZoom: 12,
      attributionControl: { compact: true },
    });

    map.dragRotate.disable();
    map.touchZoomRotate.disableRotation();

    window.__map = map;  // debugging hook

    map.on("load", () => {
      addLayers();
      wireMapEvents();
      startRaf();
      resolve();
    });
  });
}

function addLayers() {
  map.addSource("iono", { type: "geojson", data: EMPTY });
  map.addLayer({
    id: "iono-fill", type: "fill", source: "iono",
    paint: {
      "fill-color": fpColorExpression("fp"),
      "fill-opacity": ["+", 0.16, ["*", 0.34, ["get", "blend"]]],
      "fill-antialias": false,
    },
  });

  map.addSource("coverage", { type: "geojson", data: EMPTY });
  map.addLayer({
    id: "coverage-fill", type: "fill", source: "coverage",
    filter: ["==", ["get", "kind"], "annulus"],
    paint: { "fill-color": "#22d3ee", "fill-opacity": 0.09 },
  });
  map.addLayer({
    id: "coverage-line", type: "line", source: "coverage",
    filter: ["==", ["get", "kind"], "edge"],
    paint: {
      "line-color": "#22d3ee", "line-width": 1.4,
      "line-dasharray": [3, 2], "line-opacity": 0.75,
    },
  });

  map.addSource("profile-donut", { type: "geojson", data: EMPTY });
  map.addLayer({
    id: "profile-donut-fill", type: "fill", source: "profile-donut",
    filter: ["==", ["get", "kind"], "annulus"],
    paint: { "fill-color": "#fbbf24", "fill-opacity": 0.13 },
  });
  map.addLayer({
    id: "profile-donut-line", type: "line", source: "profile-donut",
    filter: ["==", ["get", "kind"], "edge"],
    paint: { "line-color": "#fbbf24", "line-width": 1.1, "line-dasharray": [2, 2], "line-opacity": 0.8 },
  });

  // live GIRO ionosondes (E-region: max(foE, foEs))
  map.addSource("sondes", { type: "geojson", data: EMPTY });
  map.addLayer({
    id: "sondes-circle", type: "circle", source: "sondes",
    paint: {
      "circle-radius": 4,
      "circle-color": fpColorExpression("fp"),
      "circle-stroke-width": 1.4,
      "circle-stroke-color": "#22d3ee",
      "circle-opacity": 0.9,
    },
  });

  map.addSource("profiles", { type: "geojson", data: EMPTY });
  map.addLayer({
    id: "profiles-circle", type: "circle", source: "profiles",
    paint: {
      "circle-radius": ["case", ["==", ["get", "verdict"], "ACCEPT"], 5.5, 4],
      "circle-color": fpColorExpression("fp"),
      "circle-stroke-width": ["case", ["==", ["get", "verdict"], "ACCEPT"], 1.8, 1],
      "circle-stroke-color": ["case", ["==", ["get", "verdict"], "ACCEPT"], "#ffffff", "rgba(255,255,255,.55)"],
      "circle-opacity": 0.92,
    },
  });

  map.addSource("route", { type: "geojson", data: EMPTY });
  map.addLayer({
    id: "route-direct", type: "line", source: "route",
    filter: ["==", ["get", "kind"], "direct-fail"],
    paint: { "line-color": "#f87171", "line-width": 1.8, "line-dasharray": [2, 2.5], "line-opacity": 0.85 },
  });
  map.addLayer({
    id: "route-glow", type: "line", source: "route",
    filter: ["==", ["get", "kind"], "hop"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#22d3ee", "line-width": 9, "line-blur": 7, "line-opacity": 0.55 },
  });
  map.addLayer({
    id: "route-core", type: "line", source: "route",
    filter: ["==", ["get", "kind"], "hop"],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: {
      "line-color": ["case", ["==", ["get", "mode"], "ionospheric"], "#67e8f9", "#a5f3fc"],
      "line-width": 2.2, "line-opacity": 0.95,
    },
  });
  map.addLayer({
    id: "route-nodes", type: "circle", source: "route",
    filter: ["==", ["get", "kind"], "node"],
    paint: {
      "circle-radius": 6,
      "circle-color": "#fbbf24",
      "circle-opacity": 0.9,
      "circle-stroke-width": 6,
      "circle-stroke-color": "#fbbf24",
      "circle-stroke-opacity": 0.18,
    },
  });
}

function wireMapEvents() {
  map.on("click", (e) => {
    if (state.mode === "sim" && state.tool === "add") {
      emit("map:add", { lat: e.lngLat.lat, lon: ((e.lngLat.lng + 540) % 360) - 180 });
    }
  });

  map.on("click", "profiles-circle", (e) => {
    if (state.mode === "sim" && state.tool === "add") return;
    const f = e.features[0];
    showProfilePopup(f, e.lngLat);
    e.preventDefault?.();
  });
  map.on("mouseenter", "profiles-circle", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "profiles-circle", () => { map.getCanvas().style.cursor = ""; });

  map.on("click", "sondes-circle", (e) => {
    if (state.mode === "sim" && state.tool === "add") return;
    showSondePopup(e.features[0], e.lngLat);
  });
  map.on("mouseenter", "sondes-circle", () => { map.getCanvas().style.cursor = "pointer"; });
  map.on("mouseleave", "sondes-circle", () => { map.getCanvas().style.cursor = ""; });
}

// ── ionosphere overlay ───────────────────────────────────────────────

let ionoTimer = null;
let ionoBusy = false;

export function refreshIono(immediate = false) {
  clearTimeout(ionoTimer);
  ionoTimer = setTimeout(async () => {
    if (!map || !map.getSource("iono")) return;
    if (!state.ionoVisible) {
      map.getSource("iono").setData(EMPTY);
      return;
    }
    if (ionoBusy) { refreshIono(); return; }
    ionoBusy = true;
    try {
      const grid = await api.ionoGrid(timeISO(), 4);
      map.getSource("iono").setData(gridToGeoJSON(grid));
    } catch (e) {
      console.error("iono grid", e);
    } finally {
      ionoBusy = false;
    }
  }, immediate ? 0 : 280);
}

function gridToGeoJSON(g) {
  const feats = [];
  const { res, lat0, lon0, nlat, nlon, fp, blend } = g;
  for (let i = 0; i < nlat; i++) {
    const la = lat0 + i * res;
    for (let j = 0; j < nlon; j++) {
      const lo = lon0 + j * res;
      feats.push({
        type: "Feature",
        properties: { fp: fp[i * nlon + j], blend: blend[i * nlon + j] },
        geometry: {
          type: "Polygon",
          coordinates: [[
            [lo, la], [lo + res, la], [lo + res, la + res], [lo, la + res], [lo, la],
          ]],
        },
      });
    }
  }
  return { type: "FeatureCollection", features: feats };
}

// ── COSMIC-2 profiles layer ──────────────────────────────────────────

export function renderProfiles() {
  if (!map || !map.getSource("profiles")) return;
  const feats = state.profiles.map((p) => ({
    type: "Feature",
    properties: {
      fp: p.fp_mhz, h: p.h_peak_km, verdict: p.verdict, score: p.reality_score,
      conf: p.confidence, time: p.time, file: p.file, sat: p.sat_id, occ: p.occ_type,
    },
    geometry: { type: "Point", coordinates: [p.lon, p.lat] },
  }));
  map.getSource("profiles").setData({ type: "FeatureCollection", features: feats });
}

function showProfilePopup(f, lngLat) {
  const p = f.properties;
  const ok = p.verdict === "ACCEPT";
  const html = `
    <div class="pp-title">COSMIC-2 E${escapeHtml(p.sat)} · ${escapeHtml(p.occ)}
      <span class="pill ${ok ? "online" : "offline"}">${escapeHtml(p.verdict)}</span></div>
    <div class="pp-row"><span class="k">Time</span><span class="v">${escapeHtml((p.time || "").replace("T", " ").slice(0, 16))}Z</span></div>
    <div class="pp-row"><span class="k">Plasma freq (E-region)</span><span class="v">${(+p.fp).toFixed(2)} MHz</span></div>
    <div class="pp-row"><span class="k">Reflection altitude</span><span class="v">${(+p.h).toFixed(1)} km</span></div>
    <div class="pp-row"><span class="k">Meteor-spike score</span><span class="v">${p.score ?? "—"}/10 (${Math.round((p.conf ?? 0) * 100)}%)</span></div>
    <div class="pp-row"><span class="k">File</span><span class="v" style="font-size:9px">${escapeHtml(p.file)}</span></div>
    <div class="hint" style="font-size:10px;color:#7d8fa8;margin-top:6px">
      Dashed rings: ground band where a station could use this reflection point
      at ${state.settings.freq_mhz} MHz.</div>`;
  const popup = new maplibregl.Popup({ className: "gcs-popup", maxWidth: "300px" })
    .setLngLat(lngLat).setHTML(html).addTo(map);

  drawProfileDonut(lngLat.lat, lngLat.lng, +p.fp, +p.h);
  popup.on("close", () => map.getSource("profile-donut")?.setData(EMPTY));
}

function drawProfileDonut(lat, lon, fp, h) {
  // distances from the reflection point to a usable station = half hop length
  const f = state.settings.freq_mhz;
  const dMax = maxHopKm(h) / 2;
  const dMin = minHopKm(fp, f, h);
  const feats = [];
  const outer = ringCoords(lat, lon, dMax);
  feats.push({ type: "Feature", properties: { kind: "edge" }, geometry: { type: "LineString", coordinates: outer } });
  if (dMin !== null) {
    const inner = dMin > 2 ? ringCoords(lat, lon, dMin / 2) : null;
    feats.push({
      type: "Feature", properties: { kind: "annulus" },
      geometry: { type: "Polygon", coordinates: inner ? [outer, inner] : [outer] },
    });
    if (inner) feats.push({ type: "Feature", properties: { kind: "edge" }, geometry: { type: "LineString", coordinates: inner } });
  }
  map.getSource("profile-donut").setData({ type: "FeatureCollection", features: feats });
}

// ── live ionosonde layer ─────────────────────────────────────────────

export function renderSondes() {
  if (!map || !map.getSource("sondes")) return;
  const feats = (state.sondes || []).map((s) => ({
    type: "Feature",
    properties: {
      fp: s.fp_mhz, foe: s.foe, foes: s.foes, fof2: s.fof2, mufd: s.mufd,
      h: s.h_km, cs: s.cs, age: s.age_h, name: s.name, code: s.code,
    },
    geometry: { type: "Point", coordinates: [s.lon, s.lat] },
  }));
  map.getSource("sondes").setData({ type: "FeatureCollection", features: feats });
}

export function setSondesVisible(v) {
  if (map?.getLayer("sondes-circle")) {
    map.setLayoutProperty("sondes-circle", "visibility", v ? "visible" : "none");
  }
}

function showSondePopup(f, lngLat) {
  const p = f.properties;
  const html = `
    <div class="pp-title">IONOSONDE ${escapeHtml(p.code)}
      <span class="src-tag src-ionosonde">GIRO LIVE</span></div>
    <div class="pp-row"><span class="k">${escapeHtml(p.name)}</span><span class="v"></span></div>
    <div class="pp-row"><span class="k">E-region fp (max foE, foEs)</span><span class="v">${(+p.fp).toFixed(2)} MHz</span></div>
    <div class="pp-row"><span class="k">foE / foEs</span><span class="v">${p.foe ?? "—"} / ${p.foes ?? "—"} MHz</span></div>
    <div class="pp-row"><span class="k">foF2</span><span class="v">${p.fof2 ?? "—"} MHz</span></div>
    <div class="pp-row"><span class="k">MUF(3000)F2</span><span class="v">${p.mufd ?? "—"} MHz</span></div>
    <div class="pp-row"><span class="k">E-layer height</span><span class="v">${(+p.h).toFixed(0)} km</span></div>
    <div class="pp-row"><span class="k">Confidence</span><span class="v">${Math.round(+p.cs)}%</span></div>
    <div class="pp-row"><span class="k">Sounding age</span><span class="v">${(+p.age).toFixed(1)} h</span></div>`;
  new maplibregl.Popup({ className: "gcs-popup", maxWidth: "300px" })
    .setLngLat(lngLat).setHTML(html).addTo(map);
}

// ── station markers ──────────────────────────────────────────────────

export function syncStations() {
  const ids = new Set(state.stations.map((s) => s.id));
  for (const id of Object.keys(markers)) {
    if (!ids.has(id)) { markers[id].marker.remove(); delete markers[id]; }
  }
  for (const s of state.stations) {
    if (markers[s.id]) {
      markers[s.id].marker.setLngLat([s.lon, s.lat]);
      markers[s.id].el.querySelector(".lbl").textContent = s.code;
    } else {
      createMarker(s);
    }
  }
  updateMarkerClasses();
  setMarkersDraggable(state.mode === "sim" && state.tool === "select");
}

function createMarker(s) {
  const el = document.createElement("div");
  el.className = "stn online";
  el.innerHTML = `<div class="ring"></div><div class="core"></div><div class="lbl">${escapeHtml(s.code)}</div>`;

  el.addEventListener("click", (e) => {
    e.stopPropagation();
    emit("station:click", { id: s.id });
  });
  el.addEventListener("mouseenter", () => showTooltip(s.id));
  el.addEventListener("mousemove", moveTooltip);
  el.addEventListener("mouseleave", hideTooltip);

  const marker = new maplibregl.Marker({ element: el, anchor: "center" })
    .setLngLat([s.lon, s.lat]).addTo(map);

  marker.on("dragend", async () => {
    const ll = marker.getLngLat();
    const lon = ((ll.lng + 540) % 360) - 180;
    try {
      await api.updateStation(s.id, { lat: ll.lat, lon });
      const st = state.stations.find((x) => x.id === s.id);
      if (st) { st.lat = +ll.lat.toFixed(4); st.lon = +lon.toFixed(4); }
      emit("stations:moved", { id: s.id });
    } catch (err) { toast(`Move failed: ${err.message}`, "err"); }
  });

  markers[s.id] = { marker, el };
}

const OWN_MARKER_CLASSES = ["online", "degraded", "offline", "selected", "link-a", "link-b"];

export function updateMarkerClasses() {
  for (const s of state.stations) {
    const m = markers[s.id];
    if (!m) continue;
    const status = state.telemetry[s.id]?.status || "online";
    // NEVER assign el.className wholesale — MapLibre's own classes
    // (maplibregl-marker, which carries position:absolute) must survive.
    m.el.classList.remove(...OWN_MARKER_CLASSES);
    m.el.classList.add(status);
    if (state.selectedId === s.id) m.el.classList.add("selected");
    if (state.linkA === s.id) m.el.classList.add("link-a");
    if (state.linkB === s.id) m.el.classList.add("link-b");
  }
}

export function setMarkersDraggable(v) {
  for (const id of Object.keys(markers)) markers[id].marker.setDraggable(v);
}

export function flyToStation(s, zoom = 4.4) {
  map.flyTo({ center: [s.lon, s.lat], zoom: Math.max(map.getZoom(), zoom), speed: 1.6 });
}

// ── tooltip ──────────────────────────────────────────────────────────

const ttEl = () => document.getElementById("tooltip");
let ttStationId = null;

function showTooltip(id) {
  ttStationId = id;
  renderTooltip();
  ttEl().style.display = "block";
}

export function renderTooltip() {
  if (!ttStationId) return;
  const s = state.stations.find((x) => x.id === ttStationId);
  const t = state.telemetry[ttStationId];
  if (!s) return;
  const status = t?.status || "online";
  const pt = t?.pointing;
  ttEl().innerHTML = `
    <div class="tt-head"><span class="tt-code">${escapeHtml(s.code)}</span>
      <span class="pill ${status}">${status}</span></div>
    <div class="tt-row"><span class="k">${escapeHtml(s.name)}</span><span class="v"></span></div>
    <div class="tt-row"><span class="k">Antenna az / el</span>
      <span class="v">${pt ? `${pt.az.toFixed(0)}° / ${pt.el.toFixed(0)}°` : "—"}</span></div>
    <div class="tt-row"><span class="k">Target</span><span class="v">${pt?.target ? escapeHtml(pt.target) : "parked"}</span></div>
    <div class="tt-row"><span class="k">SNR</span><span class="v">${t ? t.snr_db + " dB" : "—"}</span></div>
    <div class="tt-row"><span class="k">Bursts/hr</span><span class="v">${t ? t.bursts_per_hr : "—"}</span></div>`;
}

function moveTooltip(e) {
  const el = ttEl();
  const w = el.offsetWidth, h = el.offsetHeight;
  let x = e.clientX + 16, y = e.clientY + 14;
  if (x + w > innerWidth - 8) x = e.clientX - w - 14;
  if (y + h > innerHeight - 8) y = e.clientY - h - 12;
  el.style.left = x + "px";
  el.style.top = y + "px";
}

function hideTooltip() {
  ttStationId = null;
  ttEl().style.display = "none";
}

// ── coverage rings ───────────────────────────────────────────────────

export async function showCoverage(id) {
  try {
    const c = await api.coverage(id, timeISO());
    coveredId = id;
    const feats = [];
    const outer = c.outer_ring;
    const inner = c.inner_ring;
    feats.push({ type: "Feature", properties: { kind: "edge" }, geometry: { type: "LineString", coordinates: outer } });
    if (c.iono_supported) {
      feats.push({
        type: "Feature", properties: { kind: "annulus" },
        geometry: { type: "Polygon", coordinates: inner ? [outer, inner] : [outer] },
      });
      if (inner) feats.push({ type: "Feature", properties: { kind: "edge" }, geometry: { type: "LineString", coordinates: inner } });
    }
    map.getSource("coverage").setData({ type: "FeatureCollection", features: feats });
    return c;
  } catch (e) {
    toast(`Coverage failed: ${e.message}`, "err");
    return null;
  }
}

export function clearCoverage() {
  coveredId = null;
  map.getSource("coverage")?.setData(EMPTY);
}

export function refreshCoverage() {
  if (coveredId) showCoverage(coveredId);
}

export function coverageShownFor() { return coveredId; }

// ── route drawing + packet animation ────────────────────────────────

export function drawRoute(route) {
  const feats = [];
  if (route?.feasible) {
    for (const h of route.hops) {
      feats.push({
        type: "Feature", properties: { kind: "hop", mode: h.mode },
        geometry: { type: "LineString", coordinates: h.path },
      });
      feats.push({
        type: "Feature", properties: { kind: "node", fp: h.reflection.fp_mhz },
        geometry: { type: "Point", coordinates: [h.reflection.lon, h.reflection.lat] },
      });
    }
  } else if (route?.direct) {
    feats.push({
      type: "Feature", properties: { kind: "direct-fail" },
      geometry: { type: "LineString", coordinates: route.direct.path },
    });
  }
  map.getSource("route").setData({ type: "FeatureCollection", features: feats });
}

export function clearRoute() {
  stopTransmit();
  map.getSource("route")?.setData(EMPTY);
}

export function startTransmit(route) {
  stopTransmit();
  if (!route?.feasible) return;
  const hops = route.hops.map((h) => {
    const coords = h.path;
    const cum = [0];
    for (let i = 1; i < coords.length; i++) {
      cum.push(cum[i - 1] + flatDist(coords[i - 1], coords[i]));
    }
    return { coords, cum, total: cum[cum.length - 1] || 1 };
  });
  const wrap = document.createElement("div");
  wrap.className = "packet";
  packetEl = document.createElement("div");
  packetEl.className = "packet-inner";
  wrap.appendChild(packetEl);
  packetMarker = new maplibregl.Marker({ element: wrap, anchor: "center" })
    .setLngLat(hops[0].coords[0]).addTo(map);
  animState = { hops, hopIdx: 0, t0: performance.now() };
}

export function stopTransmit() {
  animState = null;
  if (packetMarker) { packetMarker.remove(); packetMarker = null; packetEl = null; }
}

function flatDist(a, b) {
  const dx = (a[0] - b[0]) * Math.cos(((a[1] + b[1]) / 2) * Math.PI / 180);
  const dy = a[1] - b[1];
  return Math.sqrt(dx * dx + dy * dy);
}

function startRaf() {
  const step = (now) => {
    rafId = requestAnimationFrame(step);
    // pulse the reflection nodes
    pulsePhase += 0.045;
    if (map.getLayer("route-nodes")) {
      const r = 5 + Math.sin(pulsePhase) * 1.8;
      map.setPaintProperty("route-nodes", "circle-radius", r);
      map.setPaintProperty("route-nodes", "circle-stroke-width", 9 + Math.sin(pulsePhase) * 4);
    }
    // packet motion
    if (animState && packetMarker) {
      const hop = animState.hops[animState.hopIdx];
      const durMs = Math.min(3400, Math.max(1100, hop.total * 110));
      let t = (now - animState.t0) / durMs;
      if (t >= 1) {
        animState.hopIdx = (animState.hopIdx + 1) % animState.hops.length;
        animState.t0 = now;
        t = 0;
      }
      const target = t * hop.total;
      let i = 1;
      while (i < hop.cum.length - 1 && hop.cum[i] < target) i++;
      const seg = hop.cum[i] - hop.cum[i - 1] || 1e-9;
      const f = (target - hop.cum[i - 1]) / seg;
      const a = hop.coords[i - 1], b = hop.coords[i];
      packetMarker.setLngLat([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]);
      // arc altitude illusion: scale packet by hop progress
      const s = 1 + 0.55 * Math.sin(Math.PI * Math.min(1, Math.max(0, t)));
      if (packetEl) packetEl.style.transform = `scale(${s.toFixed(3)})`;
    }
  };
  rafId = requestAnimationFrame(step);
}

// ── client-side geodesy (mirrors backend/geometry.py) ───────────────

function maxHopKm(h) { return 2 * R_E * Math.acos(R_E / (R_E + h)); }

function minHopKm(fp, f, h) {
  if (fp <= 0) return null;
  if (fp >= f) return 0;
  const sinT = Math.sqrt(1 - (fp / f) ** 2);
  const s = sinT * (R_E + h) / R_E;
  if (s > 1) return null;
  const angS = Math.PI - Math.asin(s);
  const gamma = Math.PI - angS - Math.asin(sinT);
  return 2 * gamma * R_E;
}

function destPoint(lat, lon, brgDeg, distKm) {
  const p1 = lat * Math.PI / 180, l1 = lon * Math.PI / 180, brg = brgDeg * Math.PI / 180;
  const d = distKm / R_E;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(brg));
  const l2 = l1 + Math.atan2(Math.sin(brg) * Math.sin(d) * Math.cos(p1),
    Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [((l2 * 180 / Math.PI + 540) % 360) - 180, p2 * 180 / Math.PI];
}

function ringCoords(lat, lon, radiusKm, n = 72) {
  const pts = [];
  let prev = null;
  for (let i = 0; i <= n; i++) {
    let [lo, la] = destPoint(lat, lon, (i % n) * 360 / n, radiusKm);
    if (prev !== null) {
      while (lo - prev > 180) lo -= 360;
      while (lo - prev < -180) lo += 360;
    }
    prev = lo;
    pts.push([+lo.toFixed(4), +la.toFixed(4)]);
  }
  return pts;
}

// ── reactive wiring ──────────────────────────────────────────────────

on("telemetry", () => { updateMarkerClasses(); renderTooltip(); });
on("time", () => { refreshIono(); refreshCoverage(); });
on("iono", () => refreshIono(true));
on("settings", () => { refreshIono(true); refreshCoverage(); });
on("select", updateMarkerClasses);
on("linksel", updateMarkerClasses);
