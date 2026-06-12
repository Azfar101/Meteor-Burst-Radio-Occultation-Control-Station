"""
MBC Ground Control System — FastAPI backend.

Serves the API under /api and the no-build web frontend from /frontend.
Start with:  python run.py   (repo root)
"""

import datetime
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cosmic2_loader, geometry as geo, linkplan, livedata
from .ionosphere import Ionosphere
from .stations import StationStore

app = FastAPI(title="MBC Ground Control System", version="1.1")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
UPLOAD_DIR = Path(__file__).resolve().parent / "data" / "uploads"

iono = Ionosphere()
iono.live_fn = livedata.get_live
store = StationStore()
settings = {
    "freq_mhz": 30.0,
    "data_rate_kbps": 9.6,
    "max_hops": 6,
    "allow_meteor_mode": True,
    "ssn": 70,
    "auto_ssn": True,   # drive the foE model with the live effective SSN
}


def _eff_settings():
    """Settings with the SSN resolved (live effective SSN when enabled)."""
    eff = dict(settings)
    if settings.get("auto_ssn"):
        live = iono.live_ssn()
        if live is not None:
            eff["ssn"] = live
    return eff


# warm the live-ionosphere cache so the first map render doesn't block
threading.Thread(target=livedata.get_live, daemon=True).start()


def _parse_t(t: Optional[str]) -> datetime.datetime:
    if not t:
        return datetime.datetime.utcnow()
    return datetime.datetime.fromisoformat(t.replace("Z", "+00:00")).replace(tzinfo=None)


def _profile_json(p):
    out = dict(p)
    out["time"] = p["time"].isoformat() + "Z"
    for k in ("nmf2", "hmf2", "fof2_mhz"):
        v = out.get(k)
        if v is None or v != v:  # NaN
            out[k] = None
    return out


# ── settings ─────────────────────────────────────────────────────────────────

class SettingsIn(BaseModel):
    freq_mhz: Optional[float] = None
    data_rate_kbps: Optional[float] = None
    max_hops: Optional[int] = None
    allow_meteor_mode: Optional[bool] = None
    ssn: Optional[float] = None
    auto_ssn: Optional[bool] = None


@app.get("/api/settings")
def get_settings():
    return settings


@app.patch("/api/settings")
def patch_settings(body: SettingsIn):
    for k, v in body.model_dump(exclude_none=True).items():
        settings[k] = v
    settings["freq_mhz"] = max(15.0, min(60.0, float(settings["freq_mhz"])))
    settings["max_hops"] = max(1, min(10, int(settings["max_hops"])))
    return settings


# ── stations ─────────────────────────────────────────────────────────────────

class StationIn(BaseModel):
    name: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    region: Optional[str] = None


@app.get("/api/stations")
def list_stations():
    return store.all()


@app.post("/api/stations")
def add_station(body: StationIn):
    if body.lat is None or body.lon is None:
        raise HTTPException(400, "lat and lon are required")
    return store.add(body.name, body.lat, body.lon, body.region or "Custom")


@app.patch("/api/stations/{sid}")
def update_station(sid: str, body: StationIn):
    st = store.update(sid, body.model_dump())
    if not st:
        raise HTTPException(404, "station not found")
    return st


@app.delete("/api/stations/{sid}")
def delete_station(sid: str):
    if not store.delete(sid):
        raise HTTPException(404, "station not found")
    return {"ok": True}


@app.post("/api/stations/reset")
def reset_stations():
    store.reset()
    return store.all()


@app.get("/api/telemetry")
def telemetry():
    return store.telemetry()


@app.get("/api/stations/{sid}/coverage")
def coverage(sid: str, t: Optional[str] = None):
    """Estimated reachable ground-range annulus around a station."""
    st = store.get(sid)
    if not st:
        raise HTTPException(404, "station not found")
    tt = _parse_t(t)
    eff = _eff_settings()
    iq = iono.query(st["lat"], st["lon"], tt, eff["ssn"])
    fp, h = iq["fp_mhz"], iq["h_km"]
    f_op = settings["freq_mhz"]
    d_max = geo.max_hop_range_km(h)
    d_min = geo.min_hop_range_km(fp, f_op, h)
    iono_ok = d_min is not None
    return {
        "station": sid,
        "fp_mhz": fp, "h_km": h, "source": iq["source"],
        "f_op_mhz": f_op,
        "iono_supported": iono_ok,
        "min_km": round(d_min, 1) if iono_ok else None,
        "max_km": round(d_max, 1),
        "outer_ring": geo.ring_coords(st["lat"], st["lon"], d_max),
        "inner_ring": geo.ring_coords(st["lat"], st["lon"], d_min)
        if iono_ok and d_min > 1 else None,
    }


# ── ionosphere / profiles ────────────────────────────────────────────────────

@app.get("/api/profiles")
def profiles():
    tr = iono.time_range()
    return {
        "count": len(iono.profiles),
        "time_min": tr[0].isoformat() + "Z" if tr else None,
        "time_max": tr[1].isoformat() + "Z" if tr else None,
        "profiles": [_profile_json(p) for p in iono.profiles],
    }


@app.delete("/api/profiles")
def clear_profiles():
    iono.clear()
    return {"count": 0}


class ImportIn(BaseModel):
    folder: str


@app.post("/api/import/folder")
def import_folder(body: ImportIn):
    try:
        profs, skipped = cosmic2_loader.scan_folder(body.folder)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    added = iono.add_profiles(profs)
    tr = iono.time_range()
    return {
        "imported": added,
        "duplicates": len(profs) - added,
        "skipped": skipped[:50],
        "n_skipped": len(skipped),
        "total": len(iono.profiles),
        "time_min": tr[0].isoformat() + "Z" if tr else None,
        "time_max": tr[1].isoformat() + "Z" if tr else None,
    }


@app.post("/api/import/upload")
async def import_upload(files: list[UploadFile] = File(...)):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    profs, skipped = [], []
    for uf in files:
        dest = UPLOAD_DIR / Path(uf.filename or "upload_nc").name
        dest.write_bytes(await uf.read())
        try:
            p, reason = cosmic2_loader.process_file(dest)
        except Exception as e:
            p, reason = None, str(e)
        if p:
            profs.append(p)
        else:
            skipped.append({"file": dest.name, "reason": reason})
    added = iono.add_profiles(profs)
    tr = iono.time_range()
    return {
        "imported": added,
        "duplicates": len(profs) - added,
        "skipped": skipped[:50],
        "n_skipped": len(skipped),
        "total": len(iono.profiles),
        "time_min": tr[0].isoformat() + "Z" if tr else None,
        "time_max": tr[1].isoformat() + "Z" if tr else None,
    }


@app.get("/api/ionosphere/grid")
def iono_grid(t: Optional[str] = None, res: float = 4.0):
    res = max(2.0, min(10.0, res))
    return iono.grid(_parse_t(t), res, _eff_settings()["ssn"])


@app.get("/api/ionosphere/point")
def iono_point(lat: float, lon: float, t: Optional[str] = None):
    return iono.query(lat, lon, _parse_t(t), _eff_settings()["ssn"])


@app.get("/api/ionosondes")
def ionosondes():
    """Live GIRO ionosonde soundings (via the open prop.kc2g.com API)."""
    live = livedata.get_live()
    return {
        "ok": live["ok"],
        "ssn": round(live["ssn"], 1) if live["ssn"] is not None else None,
        "count": len(live["sondes"]),
        "error": live["error"],
        "sondes": [{k: v for k, v in s.items() if k != "ts"} for s in live["sondes"]],
    }


# ── link planning ────────────────────────────────────────────────────────────

class LinkIn(BaseModel):
    from_id: str
    to_id: str
    t: Optional[str] = None


def _endpoints(body: LinkIn):
    a, b = store.get(body.from_id), store.get(body.to_id)
    if not a or not b:
        raise HTTPException(404, "station not found")
    if a["id"] == b["id"]:
        raise HTTPException(400, "source and destination are the same station")
    return a, b


@app.post("/api/link")
def link(body: LinkIn):
    a, b = _endpoints(body)
    return linkplan.compute_hop(a, b, iono, _parse_t(body.t), _eff_settings())


@app.post("/api/route")
def route(body: LinkIn):
    a, b = _endpoints(body)
    tel = store.telemetry()
    return linkplan.compute_route(a, b, store.all(), tel, iono, _parse_t(body.t), _eff_settings())


@app.post("/api/transmit")
def transmit(body: LinkIn):
    """Compute the route and slew every involved antenna toward its next hop."""
    a, b = _endpoints(body)
    tel = store.telemetry()
    result = linkplan.compute_route(a, b, store.all(), tel, iono, _parse_t(body.t), _eff_settings())
    if result.get("feasible"):
        for h in result["hops"]:
            store.set_pointing(h["from"], h["azimuth_ab"], h["elevation_deg"], h["to_code"])
            store.set_pointing(h["to"], h["azimuth_ba"], h["elevation_deg"], h["from_code"])
    return result


# ── frontend ─────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")
