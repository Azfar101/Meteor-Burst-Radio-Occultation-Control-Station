// Sidebar station list, right contextual panel (station detail / route
// plan), settings + import modals, data chip.

import { state, on, emit, stationById, timeISO, toast, escapeHtml } from "./state.js";
import { api } from "./api.js";
import {
  flyToStation, showCoverage, clearCoverage, coverageShownFor,
  drawRoute, clearRoute, startTransmit, stopTransmit,
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
      ${sim
        ? `<input class="rp-name-input" data-k="name" value="${escapeHtml(s.name)}">`
        : `<div style="font-weight:700;font-size:14px;margin-bottom:4px">${escapeHtml(s.name)}</div>`}
      <div class="rp-sub">${escapeHtml(s.region)} · <span class="mono">${s.lat.toFixed(3)}°, ${s.lon.toFixed(3)}°</span>
        · ${escapeHtml(s.antenna?.type || "Yagi array")}</div>

      <div class="viewer3d" data-k="v3d">
        <span class="v3d-tag">ANTENNA · LIVE ATTITUDE</span>
        <div class="v3d-point">
          <span data-k="az">AZ —</span><span data-k="el">EL —</span><span data-k="target">PARKED</span>
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
        ${sim ? `<button class="btn danger" data-act="del">✕ Remove station</button>` : ""}
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
          ? `Reach ${Math.round(c.min_km)}–${Math.round(c.max_km)} km · fp ${c.fp_mhz} MHz (${c.source})`
          : `E-layer too weak at ${c.f_op_mhz} MHz here — meteor-burst mode only (max ${Math.round(c.max_km)} km)`,
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
    </div>
    <div class="hc-grid">
      <div><span class="k">Distance</span><span class="v">${Math.round(h.distance_km)} km</span></div>
      <div><span class="k">Elevation</span><span class="v">${h.elevation_deg.toFixed(1)}°</span></div>
      <div><span class="k">Azimuth (tx)</span><span class="v">${h.azimuth_ab.toFixed(1)}°</span></div>
      <div><span class="k">Azimuth (rx)</span><span class="v">${h.azimuth_ba.toFixed(1)}°</span></div>
      <div><span class="k">Refl. height</span><span class="v">${r.h_km} km</span></div>
      <div><span class="k">Plasma freq</span><span class="v">${r.fp_mhz} MHz</span></div>
      <div><span class="k">MUF (sec law)</span><span class="v">${h.muf_mhz} MHz</span></div>
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
      <label class="lbl">Operating frequency — <span class="range-val" id="set-freq-val">${s.freq_mhz} MHz</span></label>
      <input type="range" id="set-freq" min="15" max="60" step="0.5" value="${s.freq_mhz}">
      <div class="hint">Meteor-burst systems typically run 30–50 MHz. The secant law
        fp·sec(θ) ≥ f decides whether the E-layer supports each hop.</div>
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
    <div class="actions">
      <button class="btn danger" id="set-reset">Reset network</button>
      <button class="btn" id="set-cancel">Cancel</button>
      <button class="btn primary" id="set-save">Save</button>
    </div>`);

  m.querySelector("#set-freq").addEventListener("input", (e) => {
    m.querySelector("#set-freq-val").textContent = `${e.target.value} MHz`;
  });
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
        freq_mhz: +m.querySelector("#set-freq").value,
        max_hops: +m.querySelector("#set-hops").value,
        data_rate_kbps: +m.querySelector("#set-rate").value,
        ssn: +m.querySelector("#set-ssn").value,
        auto_ssn: m.querySelector("#set-autossn").checked,
        allow_meteor_mode: m.querySelector("#set-mb").checked,
      });
      Object.assign(state.settings, saved);
      emit("settings");
      closeModal();
      toast("Settings applied", "ok");
    } catch (e) { toast(e.message, "err"); }
  });
}

export function openImportModal() {
  const lastFolder = localStorage.getItem("mbc-folder") || "asd";
  const m = modal(`
    <h2>IMPORT COSMIC-2 IONPRF DATA</h2>
    <div class="tabs">
      <button class="active" data-tab="folder">Folder on this PC</button>
      <button data-tab="upload">Upload files</button>
    </div>
    <div data-pane="folder">
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
    <div id="imp-result"></div>
    <div class="actions" style="margin-top:8px">
      <button class="btn danger" id="imp-clear">Clear loaded data</button>
      <button class="btn" id="imp-close">Close</button>
    </div>`);

  const panes = { folder: m.querySelector("[data-pane=folder]"), upload: m.querySelector("[data-pane=upload]") };
  m.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
    m.querySelectorAll(".tabs button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    for (const k of Object.keys(panes)) panes[k].style.display = k === b.dataset.tab ? "" : "none";
  }));

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
