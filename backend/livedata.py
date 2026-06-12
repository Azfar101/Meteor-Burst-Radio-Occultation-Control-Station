"""
Live ionosphere data from open, key-less APIs (prop.kc2g.com, which
republishes GIRO/DIDBase ionosonde soundings and an effective sunspot
number derived from them).

- stations.json -> real-time ionosonde characteristics. We use the
  E-region values (foE, sporadic-E foEs, E-layer height hmE), which is
  the layer that matters for meteor-burst reflection.
- essn.json     -> live effective SSN driving the foE model fallback.

Everything is cached and degrades gracefully: if the network is down the
last good data is kept, and the static SSN setting takes over.
"""

import datetime
import json
import threading
import time
import urllib.request

STATIONS_URL = "https://prop.kc2g.com/api/stations.json"
ESSN_URL = "https://prop.kc2g.com/api/essn.json"

CACHE_TTL_S = 900          # refresh every 15 min
RETRY_AFTER_S = 120        # wait after a failed fetch before retrying
MAX_SONDE_AGE_H = 6.0      # drop soundings older than this
TIMEOUT_S = 8

_lock = threading.Lock()
_cache = {
    "sondes": [],
    "ssn": None,
    "fetched": 0.0,       # last successful fetch (epoch)
    "attempted": 0.0,     # last attempt (epoch)
    "ok": False,
    "error": None,
}


def _fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "MBC-GCS/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))


def _parse_sondes(raw, now_utc):
    out = []
    for rec in raw:
        try:
            st = rec.get("station") or {}
            lat = float(st.get("latitude"))
            lon = float(st.get("longitude"))
            if lon > 180:
                lon -= 360
            t = datetime.datetime.fromisoformat(str(rec.get("time")))
            age_h = (now_utc - t).total_seconds() / 3600.0
            if age_h > MAX_SONDE_AGE_H or age_h < -1:
                continue
            foe = rec.get("foe") or 0.0
            foes = rec.get("foes") or 0.0
            fp = max(float(foe), float(foes))
            if fp <= 0:
                continue
            cs = rec.get("cs")
            cs = float(cs) if cs is not None and cs >= 0 else 50.0
            out.append({
                "code": st.get("code", "?"),
                "name": st.get("name", "?"),
                "lat": lat,
                "lon": lon,
                "fp_mhz": round(fp, 3),                 # E-region: max(foE, foEs)
                "foe": round(float(foe), 2) if foe else None,
                "foes": round(float(foes), 2) if foes else None,
                "fof2": rec.get("fof2"),
                "mufd": rec.get("mufd"),
                "h_km": float(rec.get("hme") or 105.0),
                "cs": cs,
                "time": t.isoformat() + "Z",
                "ts": t.timestamp(),
                "age_h": round(age_h, 2),
            })
        except (TypeError, ValueError):
            continue
    return out


def get_live(force=False):
    """Cached live data snapshot. Never raises."""
    now = time.time()
    with _lock:
        fresh = (now - _cache["fetched"]) < CACHE_TTL_S
        recently_failed = (now - _cache["attempted"]) < RETRY_AFTER_S
        if not force and (fresh or recently_failed):
            return dict(_cache)
        _cache["attempted"] = now

    sondes, ssn, err = None, None, None
    try:
        raw = _fetch_json(STATIONS_URL)
        sondes = _parse_sondes(raw, datetime.datetime.utcnow())
    except Exception as e:
        err = f"stations: {e}"
    try:
        essn = _fetch_json(ESSN_URL)
        series = essn.get("24h") or []
        if series:
            ssn = float(series[-1]["ssn"])
    except Exception as e:
        err = (err + " | " if err else "") + f"essn: {e}"

    with _lock:
        if sondes is not None:
            _cache["sondes"] = sondes
        if ssn is not None:
            _cache["ssn"] = ssn
        if sondes is not None or ssn is not None:
            _cache["fetched"] = time.time()
            _cache["ok"] = True
        if sondes is None and ssn is None:
            _cache["ok"] = bool(_cache["sondes"])  # stale data may remain usable
        _cache["error"] = err
        return dict(_cache)
