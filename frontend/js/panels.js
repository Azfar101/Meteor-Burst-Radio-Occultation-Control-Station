// Sidebar station list, right contextual panel (station detail / route
// plan), settings + import modals, data chip.

import { state, on, emit, stationById, timeISO, toast, escapeHtml } from "./state.js";
import { api } from "./api.js";
import {
  flyToStation, showCoverage, clearCoverage, coverageShownFor,
  drawRoute, clearRoute, startTransmit, stopTransmit, syncStations,
} from "./map.js";
import { AntennaView } from "./antenna3d.js";

const rp = () => document.getElementById("rightpanel");
let antennaView = null;     // singleton 3D viewer
let panelKind = null;       // "station" | "route" | null

// ════════════════════════ SIDEBAR ════════════════════════════════════

export function renderSidebar() {
  const q = (document.getElementById("sb-search").value || "").toLowerCase();
  const list = document.getElementById("sb-list");
  document.getElementById("sb-count").textContent = state.stations.length;

  list.innerHTML = "";
  for (const s of state.stations) {
    if (q && !(`${s.code} ${s.name} ${s.region}`.toLowerCase().includes(q))) continue;
    const t = state.telemetry[s.id];
    const status = t?.status || "online";
    const el = document.createElement("div");
    el.className = "sb-item" + (state.selectedId === s.id ? " selected" : "");
    el.innerHTML = `<span class="sb-dot ${status}"></span>
      <span class="code">${escapeHtml(s.code)}</span>
      <span class="nm">${escapeHtml(s.name)}</span>`;
    el.addEventListener("click", () => {
      selectStation(s.id);
      flyToStation(s);
    });
    list.appendChild(el);
  }
}

function refreshSidebarDots() {
  // cheap full re-render (list is small)
  renderSidebar();
}

// ════════════════════════ SELECTION ══════════════════════════════════

export function selectStation(id) {
  state.selectedId = id;
  emit("select");
  openStationPanel(id);
  renderSidebar();
}

export function deselect() {
  state.selectedId = null;
  emit("select");
  closePanel();
  renderSidebar();
}

// ════════════════════════ RIGHT PANEL: STATION ═══════════════════════

export function openStationPanel(id) {
  const s = stationById(id);
  if (!s) return;
  destroyAntenna();
  panelKind = "station";

  const sim = state.mode === "sim";
  rp().innerHTML = `
    <div class="rp-head">
      <span class="code">${escapeHtml(s.code)}</span>
      <span class="pill online" data-k="status">—</span>
      <button class="x" data-act="close">✕</button>
    </div>
    <div class="rp-body">
      <input class="rp-name-input" data-k="name" value="${escapeHtml(s.name)}">
      <div class="rp-sub">${escapeHtml(s.region)} · ${escapeHtml(s.antenna?.type || "Yagi array")}</div>
      <div class="rp-sub" title="The station tunes within this band; each hop picks the best supported frequency">
        Operating band · <span class="mono">${state.settings.freq_min_mhz}–${state.settings.freq_max_mhz} MHz</span></div>
      <div class="row two">
        <div><label class="lbl">Latitude</label><input data-k="lat-in" type="number" step="0.01" value="${s.lat}"></div>
        <div><label class="lbl">Longitude</label><input data-k="lon-in" type="number" step="0.01" value="${s.lon}"></div>
      </div>

      <div class="viewer3d" data-k="v3d">
        <span class="v3d-tag">ANTENNA · LIVE ATTITUDE</span>
        <div class="v3d-point">
          <span data-k="az">AZ —</span><span data-k="el">EL —</span><span data-k="target">PARKED</span><span data-k="freq"></span>
        </div>
      </div>

      <div class="tel-grid">
        ${telTile("TX Power", "tx", "W")}
        ${telTile("PA Temp", "temp", "°C")}
        ${telTile("SWR", "swr", "")}
        ${telTile("SNR", "snr", "dB")}
        ${telTile("Noise floor", "noise", "dBm")}
        ${telTile("Battery", "batt", "V")}
        ${telTile("TX Queue", "queue", "pkts")}
        ${telTile("Meteor bursts", "bursts", "/hr")}
      </div>

      <div class="rp-actions">
        <button class="btn" data-act="coverage">◎ Coverage</button>
        <button class="btn" data-act="src">⇡ Set source</button>
        <button class="btn" data-act="dst">⇣ Set destination</button>
        <button class="btn danger" data-act="del">✕ Remove station</button>
      </div>
    </div>`;
  rp().classList.add("open");

  // 3D viewer
  const holder = rp().querySelector("[data-k=v3d]");
  antennaView = new AntennaView(holder);

  // actions
  rp().querySelector("[data-act=close]").addEventListener("click", deselect);
  rp().querySelector("[data-act=coverage]").addEventListener("click", async (e) => {
    if (coverageShownFor() === id) {
      clearCoverage();
      e.target.textContent = "◎ Coverage";
    } else {
      const c = await showCoverage(id);
      if (c) {
        e.target.textContent = "◎ Hide coverage";
        toast(c.iono_supported
          ? `Reach ${Math.round(c.min_km)}–${Math.round(c.max_km)} km · fp ${c.fp_mhz} MHz · max usable ${c.muf_max_mhz} MHz (${c.source})`
          : `Max usable ${c.muf_max_mhz} MHz < ${c.f_min_mhz} MHz min op freq here — meteor-burst only (max ${Math.round(c.max_km)} km)`,
          c.iono_supported ? "ok" : "");
      }
    }
  });
  rp().querySelector("[data-act=src]").addEventListener("click", () => emit("linkpick", { id, end: "a" }));
  rp().querySelector("[data-act=dst]").addEventListener("click", () => emit("linkpick", { id, end: "b" }));
  rp().querySelector("[data-act=del]")?.addEventListener("click", () => emit("station:delete", { id }));
  rp().querySelector("[data-k=name]")?.addEventListener("change", async (e) => {
    try {
      await api.updateStation(id, { name: e.target.value });
      const st = stationById(id);
      if (st) st.name = e.target.value;
      renderSidebar();
      toast("Station renamed", "ok");
    } catch (err) { toast(err.message, "err"); }
  });

  const savePos = async () => {
    const lat = +rp().querySelector("[data-k=lat-in]").value;
    const lon = +rp().querySelector("[data-k=lon-in]").value;
    if (Number.isNaN(lat) || Number.isNaN(lon)) return;
    try {
      await api.updateStation(id, { lat, lon });
      const st = stationById(id);
      if (st) { st.lat = lat; st.lon = lon; }
      syncStations();                       // move the marker
      emit("stations:moved", { id });       // re-render sidebar + recompute route
      toast("Station moved", "ok");
    } catch (err) { toast(err.message, "err"); }
  };
  rp().querySelector("[data-k=lat-in]")?.addEventListener("change", savePos);
  rp().querySelector("[data-k=lon-in]")?.addEventListener("change", savePos);

  updateStationPanel();
}

function telTile(label, key, unit) {
  return `<div class="tel" data-tile="${key}">
    <div class="k">${label}</div>
    <div class="v"><span data-k="${key}">—</span> <small>${unit}</small></div>
  </div>`;
}

export function updateStationPanel() {
  if (panelKind !== "station" || !state.selectedId) return;
  const t = state.telemetry[state.selectedId];
  if (!t) return;
  const set = (k, v) => { const el = rp().querySelector(`[data-k="${k}"]`); if (el) el.textContent = v; };

  const pill = rp().querySelector("[data-k=status]");
  if (pill) { pill.className = `pill ${t.status}`; pill.textContent = t.status; }

  set("tx", t.tx_power_w);
  set("temp", t.pa_temp_c);
  set("swr", t.swr);
  set("snr", t.snr_db);
  set("noise", t.noise_floor_dbm);
  set("batt", t.battery_v);
  set("queue", t.queue_pkts);
  set("bursts", t.bursts_per_hr);

  rp().querySelector("[data-tile=temp]")?.classList.toggle("warn", t.pa_temp_c > 52);
  rp().querySelector("[data-tile=swr]")?.classList.toggle("warn", t.swr > 1.6);

  const pt = t.pointing;
  set("az", `AZ ${pt.az.toFixed(1)}°`);
  set("el", `EL ${pt.el.toFixed(1)}°`);
  set("target", pt.target ? `→ ${pt.target}` : "PARKED");
  set("freq", pt.frequency_mhz ? ` · ${pt.frequency_mhz.toFixed(2)} MHz` : "");

  if (antennaView) {
    antennaView.setPointing(pt.az, pt.el);
    antennaView.setStatus(t.status);
  }
}

// ════════════════════════ RIGHT PANEL: ROUTE ═════════════════════════

export function openRoutePanel(route, aId, bId) {
  destroyAntenna();
  panelKind = "route";
  const a = stationById(aId), b = stationById(bId);
  if (!a || !b) return;

  let body;
  if (!route.feasible) {
    body = `
      <div class="notebox">${route.notes.map(escapeHtml).join("<br>")}</div>
      ${directBlock(route.direct)}`;
  } else {
    const chainCodes = route.station_ids
      .map((id) => stationById(id)?.code || "?").join(" → ");
    body = `
      <div class="route-summary">
        ${statBox("Hops", route.n_hops)}
        ${statBox("Distance", `${Math.round(route.total_distance_km)} km`)}
        ${statBox("Throughput", `${route.bottleneck_kbps} kbps`)}
        ${statBox("Quality", `${route.quality}/100`)}
      </div>
      <div class="notebox info" style="font-size:11px">${escapeHtml(chainCodes)}</div>
      ${route.direct && !route.direct.feasible && route.n_hops > 1
        ? `<div class="hint" style="margin-bottom:10px">Direct link not possible
           (${escapeHtml(route.direct.reasons[0] || "")}) — routed through the relay constellation.</div>`
        : ""}
      <div class="sect-title">Hop plan</div>
      ${route.hops.map((h, i) => hopCard(h, i)).join("")}
      <button class="btn-transmit" data-act="tx">▶ &nbsp;TRANSMIT</button>`;
  }

  rp().innerHTML = `
    <div class="rp-head">
      <span class="code">${escapeHtml(a.code)} → ${escapeHtml(b.code)}</span>
      <span class="pill ${route.feasible ? "mode-iono" : "mode-bad"}">
        ${route.feasible ? "ROUTE OK" : "NO ROUTE"}</span>
      <button class="x" data-act="close">✕</button>
    </div>
    <div class="rp-body">${body}</div>`;
  rp().classList.add("open");

  rp().querySelector("[data-act=close]").addEventListener("click", () => emit("route:clear"));
  const txBtn = rp().querySelector("[data-act=tx]");
  if (txBtn) {
    txBtn.addEventListener("click", async () => {
      if (state.transmitting) {
        state.transmitting = false;
        stopTransmit();
        txBtn.classList.remove("stop");
        txBtn.innerHTML = "▶ &nbsp;TRANSMIT";
        return;
      }
      try {
        const r = await api.transmit(aId, bId, timeISO());
        if (!r.feasible) { toast("Route became infeasible", "err"); return; }
        state.route = r;
        drawRoute(r);
        startTransmit(r);
        state.transmitting = true;
        txBtn.classList.add("stop");
        txBtn.innerHTML = "■ &nbsp;STOP TRANSMISSION";
        toast(`Transmitting ${a.code} → ${b.code} · antennas slewing`, "ok");
      } catch (e) { toast(e.message, "err"); }
    });
  }
}

function statBox(k, v) {
  return `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`;
}

function modePill(mode) {
  if (mode === "ionospheric") return `<span class="pill mode-iono">IONO</span>`;
  if (mode === "meteor-burst") return `<span class="pill mode-mb">METEOR</span>`;
  if (mode === "line-of-sight") return `<span class="pill mode-mb">LOS</span>`;
  return `<span class="pill mode-bad">${escapeHtml(mode)}</span>`;
}

function hopCard(h, i) {
  const r = h.reflection;
  return `<div class="hopcard">
    <div class="hc-head">
      <span class="hc-num">${i + 1}</span>
      <span class="hc-route">${escapeHtml(h.from_code)} → ${escapeHtml(h.to_code)}</span>
      ${modePill(h.mode)}
      <span class="src-tag src-${r.source}" title="ionosphere data source">${r.source.toUpperCase()}</span>
      ${r.cosmic2_backed ? `<span class="src-tag backed-tag" title="Reflection backed by a measured COSMIC-2 patch${r.backed ? ` · ${r.backed.dist_km} km away` : ""}">◉ BACKED</span>` : ""}
    </div>
    <div class="hc-grid">
      <div><span class="k">Distance</span><span class="v">${Math.round(h.distance_km)} km</span></div>
      <div><span class="k">Elevation</span><span class="v">${h.elevation_deg.toFixed(1)}°</span></div>
      <div><span class="k">Azimuth (tx)</span><span class="v">${h.azimuth_ab.toFixed(1)}°</span></div>
      <div><span class="k">Azimuth (rx)</span><span class="v">${h.azimuth_ba.toFixed(1)}°</span></div>
      <div><span class="k">Refl. height</span><span class="v">${r.h_km} km</span></div>
      <div><span class="k">Plasma freq</span><span class="v">${r.fp_mhz} MHz</span></div>
      <div><span class="k">MUF (sec law)</span><span class="v">${h.muf_mhz} MHz</span></div>
      <div><span class="k">Op frequency</span><span class="v" title="Adaptively chosen within the ${h.f_min_mhz}–${h.f_max_mhz} MHz station range">${h.f_used_mhz} MHz</span></div>
      <div><span class="k">Margin</span><span class="v">${h.margin_db} dB</span></div>
      <div><span class="k">Duty cycle</span><span class="v">${h.duty_cycle_pct}%</span></div>
      <div><span class="k">Throughput</span><span class="v">${h.throughput_kbps} kbps</span></div>
    </div>
  </div>`;
}

function directBlock(d) {
  if (!d) return "";
  return `<div class="sect-title">Direct link analysis</div>
    <div class="hopcard">
      <div class="hc-head"><span class="hc-route">${escapeHtml(d.from_code)} → ${escapeHtml(d.to_code)}</span>${modePill(d.mode)}</div>
      <div class="hc-grid">
        <div><span class="k">Distance</span><span class="v">${Math.round(d.distance_km)} km</span></div>
        <div><span class="k">MUF</span><span class="v">${d.muf_mhz} MHz</span></div>
      </div>
      <div class="hint" style="margin-top:7px">${d.reasons.map(escapeHtml).join("<br>")}</div>
    </div>`;
}

// ════════════════════════ RIGHT PANEL: MBG POINT ═════════════════════

export function openMbgPanel(id) {
  const m = state.mbg.find((x) => x.id === id);
  if (!m) return;
  destroyAntenna();
  panelKind = "mbg";
  rp().innerHTML = `
    <div class="rp-head">
      <span class="code">◆ <span data-k="title">${escapeHtml(m.name)}</span></span>
      <span class="pill mode-mb">MBG POINT</span>
      <button class="x" data-act="close">✕</button>
    </div>
    <div class="rp-body">
      <div class="rp-sub">Custom meteor-burst bounce point — usable as a reflection point
        when “bounce off footprints” is on.</div>
      <div class="row"><label class="lbl">Name</label><input id="mbg-name" type="text" value="${escapeHtml(m.name)}"></div>
      <div class="row two">
        <div><label class="lbl">Latitude</label><input id="mbg-lat" type="number" step="0.01" value="${m.lat}"></div>
        <div><label class="lbl">Longitude</label><input id="mbg-lon" type="number" step="0.01" value="${m.lon}"></div>
      </div>
      <div class="row two">
        <div><label class="lbl">Height (km)</label><input id="mbg-h" type="number" step="1" value="${m.h_km}"></div>
        <div><label class="lbl">Plasma freq (MHz)</label><input id="mbg-fp" type="number" step="0.1" value="${m.fp_mhz}"></div>
      </div>
      <div class="hint" id="mbg-info"></div>
      <div class="rp-actions">
        <button class="btn primary" data-act="save">Save changes</button>
        <button class="btn danger" data-act="del">✕ Delete point</button>
      </div>
    </div>`;
  rp().classList.add("open");

  const q = (sel) => rp().querySelector(sel);
  const refreshInfo = () => {
    const fp = +q("#mbg-fp").value, h = +q("#mbg-h").value;
    const muf = fp / Math.sqrt(1 - (6371 / (6371 + h)) ** 2);
    q("#mbg-info").innerHTML = `Max usable operating frequency ≈ <b>${muf.toFixed(1)} MHz</b>
      (at grazing geometry). Min op freq to stay usable: ≤ that value.`;
  };
  refreshInfo();
  q("#mbg-fp").addEventListener("input", refreshInfo);
  q("#mbg-h").addEventListener("input", refreshInfo);

  q("[data-act=close]").addEventListener("click", closePanel);
  q("[data-act=save]").addEventListener("click", async () => {
    try {
      await api.updateMbg(id, {
        name: q("#mbg-name").value,
        lat: +q("#mbg-lat").value, lon: +q("#mbg-lon").value,
        h_km: +q("#mbg-h").value, fp_mhz: +q("#mbg-fp").value,
      });
      emit("mbg:reload");
      toast("MBG point updated", "ok");
    } catch (e) { toast(e.message, "err"); }
  });
  q("[data-act=del]").addEventListener("click", async () => {
    try {
      await api.deleteMbg(id);
      emit("mbg:reload");
      closePanel();
      toast("MBG point removed", "ok");
    } catch (e) { toast(e.message, "err"); }
  });
}

// ════════════════════════ PANEL LIFECYCLE ════════════════════════════

export function closePanel() {
  destroyAntenna();
  panelKind = null;
  rp().classList.remove("open");
}

function destroyAntenna() {
  if (antennaView) { antennaView.dispose(); antennaView = null; }
}

// ════════════════════════ MODALS ═════════════════════════════════════

function modal(html) {
  const root = document.getElementById("modal-root");
  root.innerHTML = `<div class="modal-overlay"><div class="modal">${html}</div></div>`;
  root.querySelector(".modal-overlay").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) root.innerHTML = "";
  });
  return root.querySelector(".modal");
}

export function closeModal() {
  document.getElementById("modal-root").innerHTML = "";
}

export function openSettingsModal() {
  const s = state.settings;
  const m = modal(`
    <h2>SYSTEM SETTINGS</h2>
    <div class="row">
      <label class="lbl">Operating frequency range — <span class="range-val" id="set-freq-val">${s.freq_min_mhz}–${s.freq_max_mhz} MHz</span></label>
      <div class="dual-range">
        <input type="range" id="set-freq-min" min="15" max="60" step="1" value="${s.freq_min_mhz}">
        <input type="range" id="set-freq-max" min="15" max="60" step="1" value="${s.freq_max_mhz}">
      </div>
      <div class="hint">Each hop adaptively tunes to the best frequency in this band.
        The minimum (also the live “Min op freq” slider) widens reach and decides which
        patches are usable; the secant law fp·sec(θ) ≥ f decides E-layer support.</div>
    </div>
    <div class="row">
      <label class="lbl">Max relay hops</label>
      <input type="number" id="set-hops" min="1" max="10" value="${s.max_hops}">
    </div>
    <div class="row">
      <label class="lbl">Burst data rate (kbps)</label>
      <input type="number" id="set-rate" min="0.3" max="256" step="0.1" value="${s.data_rate_kbps}">
    </div>
    <div class="row">
      <label class="check"><input type="checkbox" id="set-autossn" ${s.auto_ssn ? "checked" : ""}>
        Use live effective SSN from GIRO/KC2G
        ${state.liveIono?.ssn != null ? `(currently <b>&nbsp;${Math.round(state.liveIono.ssn)}</b>)` : "(unavailable)"}</label>
    </div>
    <div class="row">
      <label class="lbl">Manual sunspot number fallback — <span class="range-val" id="set-ssn-val">${s.ssn}</span></label>
      <input type="range" id="set-ssn" min="0" max="200" step="5" value="${s.ssn}">
      <div class="hint">Drives the foE day/night model where neither COSMIC-2 nor live
        ionosonde data covers. Used only when live SSN is off or unreachable.</div>
    </div>
    <div class="row">
      <label class="check"><input type="checkbox" id="set-mb" ${s.allow_meteor_mode ? "checked" : ""}>
        Allow meteor-burst mode (links without continuous E-layer support)</label>
    </div>
    <div class="row">
      <label class="check"><input type="checkbox" id="set-bounce" ${s.use_footprints_bounce ? "checked" : ""}>
        Bounce links off visible footprints (use real/placed meteor-burst points as
        reflection points instead of the great-circle midpoint)</label>
    </div>
    <div class="actions">
      <button class="btn danger" id="set-reset">Reset network</button>
      <button class="btn" id="set-cancel">Cancel</button>
      <button class="btn primary" id="set-save">Save</button>
    </div>`);

  const fMin = m.querySelector("#set-freq-min");
  const fMax = m.querySelector("#set-freq-max");
  const fVal = m.querySelector("#set-freq-val");
  const syncFreq = (driver) => {
    let lo = +fMin.value, hi = +fMax.value;
    if (lo > hi) { if (driver === "min") hi = lo, fMax.value = String(hi); else lo = hi, fMin.value = String(lo); }
    fVal.textContent = `${lo}–${hi} MHz`;
  };
  fMin.addEventListener("input", () => syncFreq("min"));
  fMax.addEventListener("input", () => syncFreq("max"));
  m.querySelector("#set-ssn").addEventListener("input", (e) => {
    m.querySelector("#set-ssn-val").textContent = e.target.value;
  });
  m.querySelector("#set-cancel").addEventListener("click", closeModal);
  m.querySelector("#set-reset").addEventListener("click", async () => {
    try {
      await api.resetStations();
      emit("stations:reload");
      closeModal();
      toast("Network reset to default constellation", "ok");
    } catch (e) { toast(e.message, "err"); }
  });
  m.querySelector("#set-save").addEventListener("click", async () => {
    try {
      const saved = await api.saveSettings({
        freq_min_mhz: +fMin.value,
        freq_max_mhz: +fMax.value,
        max_hops: +m.querySelector("#set-hops").value,
        data_rate_kbps: +m.querySelector("#set-rate").value,
        ssn: +m.querySelector("#set-ssn").value,
        auto_ssn: m.querySelector("#set-autossn").checked,
        allow_meteor_mode: m.querySelector("#set-mb").checked,
        use_footprints_bounce: m.querySelector("#set-bounce").checked,
      });
      Object.assign(state.settings, saved);
      emit("settings");
      closeModal();
      toast("Settings applied", "ok");
    } catch (e) { toast(e.message, "err"); }
  });
}

// ──────────── AUTO-FETCH CONTROLLER (UCAR archive) ────────────
// A single background poller, kept at module scope so progress keeps
// streaming into the map even if the import modal is closed mid-fetch.
let fetchTimer = null;
let lastFetchProfiles = null;

function startFetchPoll() {
  if (fetchTimer) return;
  fetchTimer = setInterval(pollFetch, 1200);
}
function stopFetchPoll() {
  if (fetchTimer) { clearInterval(fetchTimer); fetchTimer = null; }
}

async function pollFetch() {
  let s;
  try { s = await api.fetchStatus(); }
  catch { return; }              // server hiccup — try again next tick
  renderFetchProgress(s);
  // stream freshly-landed profiles onto the map as each day completes
  if (s.total_profiles != null && s.total_profiles !== lastFetchProfiles) {
    lastFetchProfiles = s.total_profiles;
    emit("profiles:reload");
  }
  if (!s.running) {
    stopFetchPoll();
    setFetchBusy(false);
    if (s.phase === "done") {
      toast(`Auto-fetch complete · ${s.imported} new profile(s)`, "ok");
    } else if (s.phase === "cancelled") {
      toast("Auto-fetch cancelled", "");
    } else if (s.phase === "error") {
      toast(`Auto-fetch failed: ${s.error || "unknown error"}`, "err");
    }
    emit("profiles:reload");
  }
}

function setFetchBusy(busy) {
  const go = document.getElementById("fetch-go");
  const cancel = document.getElementById("fetch-cancel");
  if (go) { go.disabled = busy; go.style.display = busy ? "none" : ""; }
  if (cancel) cancel.style.display = busy ? "" : "none";
}

function renderFetchProgress(s) {
  const box = document.getElementById("fetch-progress");
  if (!box) return;             // modal closed — nothing to draw
  if (!s || s.phase === "idle" || !s.total_days) { box.innerHTML = ""; return; }
  const pct = Math.max(0, Math.min(100, s.pct || 0));
  const cls = s.phase === "error" ? "err" : s.phase === "cancelled" ? "warn" : "";
  const dayDots = (s.days || []).map((d) => {
    const title = `${d.date} (DOY ${d.doy}) — ${d.status}`
      + (d.imported ? `, ${d.imported} profiles` : "")
      + (d.error ? `: ${d.error}` : "");
    return `<span class="fday ${d.status}" title="${escapeHtml(title)}"></span>`;
  }).join("");
  box.innerHTML = `
    <div class="fetch-status ${cls}">
      <div class="fetch-msg">${escapeHtml(s.message || "")}</div>
      <div class="fetch-bar"><span style="width:${pct}%"></span></div>
      <div class="fetch-days">${dayDots}</div>
      <div class="fetch-tally">
        Imported <b>${s.imported}</b>${s.duplicates ? ` · ${s.duplicates} dup` : ""}${s.skipped_total ? ` · ${s.skipped_total} skipped` : ""}
        ${s.total_profiles != null ? ` · loaded total <b>${s.total_profiles}</b>` : ""}
        ${s.time_min ? `<br>Coverage: <span class="mono">${s.time_min.slice(0, 16)}Z → ${s.time_max.slice(0, 16)}Z</span>` : ""}
      </div>
    </div>`;
}

function wireFetchPane(m) {
  const go = m.querySelector("#fetch-go");
  const cancel = m.querySelector("#fetch-cancel");

  go.addEventListener("click", async () => {
    const start = m.querySelector("#fetch-start").value;
    const end = m.querySelector("#fetch-end").value;
    if (!start || !end) { toast("Pick a start and end date", "err"); return; }
    setFetchBusy(true);
    try {
      const s = await api.fetchStart(start, end);
      lastFetchProfiles = s.total_profiles;
      renderFetchProgress(s);
      startFetchPoll();
    } catch (e) {
      setFetchBusy(false);
      toast(e.message, "err");
    }
  });

  cancel.addEventListener("click", async () => {
    cancel.disabled = true;
    try { await api.fetchCancel(); } catch (e) { toast(e.message, "err"); }
    cancel.disabled = false;
  });

  // If a fetch is already in flight (e.g. modal was reopened), resume the view.
  api.fetchStatus().then((s) => {
    if (s && s.running) {
      lastFetchProfiles = s.total_profiles;
      setFetchBusy(true);
      renderFetchProgress(s);
      startFetchPoll();
    } else if (s && s.phase !== "idle") {
      renderFetchProgress(s);     // show the last result
    }
  }).catch(() => {});
}

// Default the auto-fetch range to the last few complete UTC days.
function defaultFetchRange() {
  const today = new Date();
  const iso = (d) => d.toISOString().slice(0, 10);
  const end = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - 1));
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - 2);
  return { start: iso(start), end: iso(end), max: iso(today) };
}

export function openImportModal() {
  const lastFolder = localStorage.getItem("mbc-folder") || "asd";
  const fr = defaultFetchRange();
  const m = modal(`
    <h2>COSMIC-2 IONPRF DATA</h2>
    <div class="tabs">
      <button class="active" data-tab="fetch">Auto-fetch (UCAR)</button>
      <button data-tab="folder">Folder on this PC</button>
      <button data-tab="upload">Upload files</button>
      <button data-tab="csv">CSV</button>
    </div>
    <div data-pane="fetch">
      <div class="row">
        <label class="lbl">Date range (UTC) — auto-download from the UCAR archive</label>
        <div class="date-range">
          <input type="date" id="fetch-start" value="${fr.start}" max="${fr.max}">
          <span class="date-sep">→</span>
          <input type="date" id="fetch-end" value="${fr.end}" max="${fr.max}">
        </div>
        <div class="hint">Pulls one ionPrf archive per day from
          <span class="mono">data.cosmic.ucar.edu</span>, extracts it, and runs the same
          E-region + meteor-spike pipeline. Up to <b>31</b> days per fetch; recent days may
          not be published yet. Archives are cached locally after the first download.</div>
      </div>
      <div class="actions" style="justify-content:flex-start">
        <button class="btn primary" id="fetch-go">⬇ Fetch &amp; process</button>
        <button class="btn danger" id="fetch-cancel" style="display:none">■ Cancel</button>
      </div>
      <div id="fetch-progress"></div>
    </div>
    <div data-pane="folder" style="display:none">
      <div class="row">
        <label class="lbl">Folder path containing *_nc files</label>
        <input type="text" id="imp-folder" value="${escapeHtml(lastFolder)}" spellcheck="false">
        <div class="hint">e.g. <span class="mono">D:\\CEO_MBG-master\\CEO_MBG-master\\asd</span> — every
          ionPrf profile is processed with the E-region peak-gradient + meteor-spike classifier pipeline.</div>
      </div>
      <div class="actions"><button class="btn primary" id="imp-go">Import folder</button></div>
    </div>
    <div data-pane="upload" style="display:none">
      <div class="dropzone" id="imp-drop">Drop ionPrf files here or click to browse</div>
      <input type="file" id="imp-files" multiple style="display:none">
    </div>
    <div data-pane="csv" style="display:none">
      <div class="row">
        <label class="lbl">Save / restore the processed profile table</label>
        <div class="hint">Exports every loaded profile (location, plasma freq, reflection
          height, burst radius, verdict, scores) to one CSV — re-importable here with no
          NetCDF files needed. Raw electron-density arrays are not included.</div>
      </div>
      <div class="actions" style="justify-content:flex-start">
        <button class="btn primary" id="csv-export">⬇ Export CSV</button>
        <button class="btn" id="csv-import-btn">⬆ Import CSV</button>
        <input type="file" id="csv-file" accept=".csv,text/csv" style="display:none">
      </div>
    </div>
    <div id="imp-result"></div>
    <div class="actions" style="margin-top:8px">
      <button class="btn danger" id="imp-clear">Clear loaded data</button>
      <button class="btn" id="imp-close">Close</button>
    </div>`);

  const panes = {
    fetch: m.querySelector("[data-pane=fetch]"),
    folder: m.querySelector("[data-pane=folder]"),
    upload: m.querySelector("[data-pane=upload]"),
    csv: m.querySelector("[data-pane=csv]"),
  };
  m.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
    m.querySelectorAll(".tabs button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    for (const k of Object.keys(panes)) panes[k].style.display = k === b.dataset.tab ? "" : "none";
  }));

  // ── auto-fetch from the UCAR archive ──
  wireFetchPane(m);

  const showResult = (r) => {
    m.querySelector("#imp-result").innerHTML = `<div class="import-result">
      ✓ Imported <b>${r.imported}</b> profile(s)
      ${r.duplicates ? ` · ${r.duplicates} duplicate(s) ignored` : ""}
      ${r.n_skipped ? ` · ${r.n_skipped} skipped (no valid E-region data)` : ""}<br>
      Loaded total: <b>${r.total}</b>
      ${r.time_min ? `<br>Coverage: <span class="mono">${r.time_min.slice(0, 16)}Z → ${r.time_max.slice(0, 16)}Z</span>` : ""}
    </div>`;
    emit("profiles:reload");
  };
  const showErr = (e) => {
    m.querySelector("#imp-result").innerHTML =
      `<div class="import-result err">✗ ${escapeHtml(e.message)}</div>`;
  };

  m.querySelector("#imp-go").addEventListener("click", async (e) => {
    const folder = m.querySelector("#imp-folder").value.trim();
    if (!folder) return;
    localStorage.setItem("mbc-folder", folder);
    e.target.disabled = true;
    e.target.textContent = "Processing…";
    try { showResult(await api.importFolder(folder)); }
    catch (err) { showErr(err); }
    e.target.disabled = false;
    e.target.textContent = "Import folder";
  });

  const drop = m.querySelector("#imp-drop");
  const fileInput = m.querySelector("#imp-files");
  drop.addEventListener("click", () => fileInput.click());
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  const doUpload = async (files) => {
    if (!files.length) return;
    drop.textContent = `Processing ${files.length} file(s)…`;
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    try { showResult(await api.importUpload(fd)); }
    catch (err) { showErr(err); }
    drop.textContent = "Drop ionPrf files here or click to browse";
  };
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    doUpload([...e.dataTransfer.files]);
  });
  fileInput.addEventListener("change", () => doUpload([...fileInput.files]));

  // ── CSV export / import ──
  m.querySelector("#csv-export").addEventListener("click", () => {
    if (!state.profiles.length) { toast("No profiles loaded to export", "err"); return; }
    const a = document.createElement("a");
    a.href = api.exportCsvUrl;
    a.download = "cosmic2_profiles.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast(`Exporting ${state.profiles.length} profile(s) to CSV`, "ok");
  });
  const csvFile = m.querySelector("#csv-file");
  m.querySelector("#csv-import-btn").addEventListener("click", () => csvFile.click());
  csvFile.addEventListener("change", async () => {
    if (!csvFile.files.length) return;
    const fd = new FormData();
    for (const f of csvFile.files) fd.append("files", f);
    try { showResult(await api.importCsv(fd)); }
    catch (err) { showErr(err); }
    csvFile.value = "";
  });

  m.querySelector("#imp-clear").addEventListener("click", async () => {
    await api.clearProfiles();
    emit("profiles:reload");
    m.querySelector("#imp-result").innerHTML =
      `<div class="import-result">All loaded profiles cleared.</div>`;
  });
  m.querySelector("#imp-close").addEventListener("click", closeModal);
}

// ════════════════════════ DATA CHIP ══════════════════════════════════

export function updateDataChip() {
  const chip = document.getElementById("data-chip");
  const txt = document.getElementById("data-chip-text");
  const n = state.profiles.length;
  const live = state.liveIono;
  const liveTxt = live?.count
    ? `GIRO live · ${live.count} sondes${live.ssn != null ? ` · SSN ${Math.round(live.ssn)}` : ""}`
    : null;
  if (n > 0) {
    chip.classList.add("has-data");
    txt.textContent = `${n} COSMIC-2 profiles${liveTxt ? " + GIRO live" : ""}`;
  } else if (liveTxt) {
    chip.classList.add("has-data");
    txt.textContent = liveTxt;
  } else {
    chip.classList.remove("has-data");
    txt.textContent = "Offline · foE model only";
  }
}

// ── reactive wiring ──────────────────────────────────────────────────

on("telemetry", () => { updateStationPanel(); refreshSidebarDots(); });
document.getElementById("sb-search").addEventListener("input", renderSidebar);
