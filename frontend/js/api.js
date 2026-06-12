// Thin API client for the FastAPI backend.

async function req(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    if (body instanceof FormData) {
      opts.body = body;
    } else {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
  }
  const r = await fetch(url, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch { /* keep statusText */ }
    throw new Error(detail);
  }
  return r.json();
}

export const api = {
  settings: () => req("GET", "/api/settings"),
  saveSettings: (s) => req("PATCH", "/api/settings", s),

  stations: () => req("GET", "/api/stations"),
  addStation: (b) => req("POST", "/api/stations", b),
  updateStation: (id, b) => req("PATCH", `/api/stations/${id}`, b),
  deleteStation: (id) => req("DELETE", `/api/stations/${id}`),
  resetStations: () => req("POST", "/api/stations/reset"),

  mbgPoints: () => req("GET", "/api/mbg"),
  addMbg: (b) => req("POST", "/api/mbg", b),
  updateMbg: (id, b) => req("PATCH", `/api/mbg/${id}`, b),
  deleteMbg: (id) => req("DELETE", `/api/mbg/${id}`),
  telemetry: () => req("GET", "/api/telemetry"),
  coverage: (id, t) => req("GET", `/api/stations/${id}/coverage?t=${encodeURIComponent(t)}`),

  profiles: () => req("GET", "/api/profiles"),
  clearProfiles: () => req("DELETE", "/api/profiles"),
  importFolder: (folder) => req("POST", "/api/import/folder", { folder }),
  importUpload: (formData) => req("POST", "/api/import/upload", formData),

  fetchStart: (start, end) => req("POST", "/api/fetch", { start, end }),
  fetchStatus: () => req("GET", "/api/fetch"),
  fetchCancel: () => req("POST", "/api/fetch/cancel"),

  exportCsvUrl: "/api/export/csv",
  importCsv: (formData) => req("POST", "/api/import/csv", formData),

  ionoGrid: (t, res = 4) =>
    req("GET", `/api/ionosphere/grid?t=${encodeURIComponent(t)}&res=${res}`),
  ionosondes: () => req("GET", "/api/ionosondes"),

  link: (a, b, t) => req("POST", "/api/link", { from_id: a, to_id: b, t }),
  route: (a, b, t) => req("POST", "/api/route", { from_id: a, to_id: b, t }),
  transmit: (a, b, t) => req("POST", "/api/transmit", { from_id: a, to_id: b, t }),
};
