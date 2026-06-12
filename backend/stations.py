"""
Meteor-burst station registry + simulated telemetry.

Stations persist to backend/data/stations.json. Telemetry is generated
deterministically from (station id, wall time) with smooth pseudo-random
oscillations so the GCS feels live but is reproducible.
"""

import hashlib
import json
import math
import time
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
STATIONS_FILE = DATA_DIR / "stations.json"

# (code, name, region, lat, lon)
SEED_STATIONS = [
    ("MBS-SEA", "Seattle",       "North America", 47.61, -122.33),
    ("MBS-BLD", "Boulder",       "North America", 40.01, -105.27),
    ("MBS-DAL", "Dallas",        "North America", 32.78, -96.80),
    ("MBS-CHI", "Chicago",       "North America", 41.88, -87.63),
    ("MBS-NYC", "New York",      "North America", 40.71, -74.01),
    ("MBS-MEX", "Mexico City",   "North America", 19.43, -99.13),
    ("MBS-BSB", "Brasília",      "South America", -15.79, -47.88),
    ("MBS-SAO", "São Paulo",     "South America", -23.55, -46.63),
    ("MBS-BUE", "Buenos Aires",  "South America", -34.60, -58.38),
    ("MBS-SCL", "Santiago",      "South America", -33.45, -70.67),
    ("MBS-LON", "London",        "Europe", 51.51, -0.13),
    ("MBS-PAR", "Paris",         "Europe", 48.86, 2.35),
    ("MBS-MAD", "Madrid",        "Europe", 40.42, -3.70),
    ("MBS-BER", "Berlin",        "Europe", 52.52, 13.40),
    ("MBS-ROM", "Rome",          "Europe", 41.90, 12.50),
    ("MBS-WAW", "Warsaw",        "Europe", 52.23, 21.01),
    ("MBS-ATH", "Athens",        "Europe", 37.98, 23.73),
    ("MBS-MOW", "Moscow",        "Europe", 55.76, 37.62),
    ("MBS-ANK", "Ankara",        "Middle East", 39.93, 32.86),
    ("MBS-CAI", "Cairo",         "Middle East", 30.04, 31.24),
    ("MBS-RYD", "Riyadh",        "Middle East", 24.71, 46.68),
    ("MBS-DXB", "Dubai",         "Middle East", 25.20, 55.27),
    ("MBS-THR", "Tehran",        "Middle East", 35.69, 51.39),
    ("MBS-KHI", "Karachi",       "South Asia", 24.86, 67.00),
    ("MBS-DEL", "New Delhi",     "South Asia", 28.61, 77.21),
    ("MBS-BKK", "Bangkok",       "Southeast Asia", 13.76, 100.50),
    ("MBS-HAN", "Hanoi",         "Southeast Asia", 21.03, 105.85),
    ("MBS-HKG", "Hong Kong",     "East Asia", 22.32, 114.17),
    ("MBS-SHA", "Shanghai",      "East Asia", 31.23, 121.47),
    ("MBS-SEL", "Seoul",         "East Asia", 37.57, 126.98),
    ("MBS-TYO", "Tokyo",         "East Asia", 35.68, 139.69),
    ("MBS-SIN", "Singapore",     "Southeast Asia", 1.35, 103.82),
    ("MBS-JKT", "Jakarta",       "Southeast Asia", -6.21, 106.85),
    ("MBS-SUB", "Surabaya",      "Southeast Asia", -7.25, 112.75),
    ("MBS-KOE", "Kupang",        "Southeast Asia", -10.17, 123.58),
    ("MBS-DRW", "Darwin",        "Oceania", -12.46, 130.84),
    ("MBS-ASP", "Alice Springs", "Oceania", -23.70, 133.88),
    ("MBS-ADL", "Adelaide",      "Oceania", -34.93, 138.60),
    ("MBS-SYD", "Sydney",        "Oceania", -33.87, 151.21),
]


def _seed_list():
    out = []
    for code, name, region, lat, lon in SEED_STATIONS:
        out.append({
            "id": code.lower(),
            "code": code,
            "name": name,
            "region": region,
            "lat": lat,
            "lon": lon,
            "builtin": True,
            "antenna": {"type": "Yagi 5-el array", "gain_dbi": 12.0, "tx_power_w": 1000},
        })
    return out


class StationStore:
    def __init__(self):
        self.pointing = {}  # id -> {az, el, target_code} (runtime only)
        self._load()

    def _load(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if STATIONS_FILE.exists():
            try:
                self.stations = json.loads(STATIONS_FILE.read_text(encoding="utf-8"))
                return
            except Exception:
                pass
        self.stations = _seed_list()
        self._save()

    def _save(self):
        STATIONS_FILE.write_text(
            json.dumps(self.stations, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── CRUD ────────────────────────────────────────────────────────────
    def all(self):
        return self.stations

    def get(self, sid):
        for s in self.stations:
            if s["id"] == sid:
                return s
        return None

    def add(self, name, lat, lon, region="Custom"):
        n = sum(1 for s in self.stations if not s.get("builtin")) + 1
        code = f"MBS-X{n:02d}"
        st = {
            "id": uuid.uuid4().hex[:10],
            "code": code,
            "name": name or f"Station {code}",
            "region": region,
            "lat": round(float(lat), 4),
            "lon": round(float(lon), 4),
            "builtin": False,
            "antenna": {"type": "Yagi 5-el array", "gain_dbi": 12.0, "tx_power_w": 1000},
        }
        self.stations.append(st)
        self._save()
        return st

    def update(self, sid, fields):
        st = self.get(sid)
        if not st:
            return None
        for k in ("name", "lat", "lon", "region"):
            if k in fields and fields[k] is not None:
                st[k] = round(float(fields[k]), 4) if k in ("lat", "lon") else fields[k]
        self._save()
        return st

    def delete(self, sid):
        before = len(self.stations)
        self.stations = [s for s in self.stations if s["id"] != sid]
        self.pointing.pop(sid, None)
        if len(self.stations) != before:
            self._save()
            return True
        return False

    def reset(self):
        self.stations = _seed_list()
        self.pointing = {}
        self._save()

    # ── pointing (set when a link/route is computed) ────────────────────
    def set_pointing(self, sid, az, el, target_code, frequency_mhz=None):
        self.pointing[sid] = {
            "az": round(az, 1), "el": round(el, 1),
            "target": target_code, "since": time.time(),
            "frequency_mhz": round(frequency_mhz, 2) if frequency_mhz is not None else None,
        }

    # ── simulated telemetry ─────────────────────────────────────────────
    @staticmethod
    def _h(sid, salt=""):
        """Stable 0..1 hash per station."""
        d = hashlib.md5((sid + salt).encode()).digest()
        return int.from_bytes(d[:4], "big") / 0xFFFFFFFF

    def telemetry(self, now=None):
        now = now or time.time()
        out = {}
        for s in self.stations:
            sid = s["id"]
            h1, h2, h3 = self._h(sid), self._h(sid, "b"), self._h(sid, "c")
            ph = h1 * 6.283
            wob = math.sin(now / 47.0 + ph) * 0.5 + math.sin(now / 13.0 + ph * 2) * 0.3 \
                + math.sin(now / 211.0 + ph * 3) * 0.2  # smooth -1..1-ish

            # status: a couple of seed stations cycle through degraded/offline
            # states slowly so the network looks alive
            cycle = math.sin(now / 1800.0 + h2 * 6.283)
            if s.get("builtin") and h3 > 0.93 and cycle > 0.2:
                status = "offline"
            elif s.get("builtin") and h3 > 0.82 and cycle > 0.0:
                status = "degraded"
            else:
                status = "online"

            deg = 1.0 if status == "online" else (0.55 if status == "degraded" else 0.0)
            pt = self.pointing.get(sid)
            if pt:
                pt_out = {
                    "az": pt["az"], "el": pt["el"],
                    "target": pt["target"], "since": pt["since"],
                    "frequency_mhz": pt.get("frequency_mhz"),
                }
            else:
                pt_out = {
                    "az": round(h1 * 360, 1), "el": 12.0,
                    "target": None, "frequency_mhz": None,
                }

            out[sid] = {
                "status": status,
                "uptime_h": round(200 + h2 * 4000 + (now % 86400) / 3600.0, 1),
                "tx_power_w": 0 if status == "offline" else round(950 + wob * 40 * deg, 0),
                "swr": round(1.12 + abs(wob) * 0.25 + (0.6 if status == "degraded" else 0), 2),
                "pa_temp_c": round(38 + h1 * 8 + wob * 4 + (14 if status == "degraded" else 0), 1),
                "noise_floor_dbm": round(-118 + wob * 3 + h2 * 4, 1),
                "snr_db": 0 if status == "offline" else round(14 + wob * 5 * deg, 1),
                "battery_v": round(27.2 + wob * 0.5, 2),
                "solar_w": round(max(0, 220 * math.sin(now / 86400.0 * 6.283 + s["lon"] / 57.3)), 0),
                "queue_pkts": 0 if status == "offline" else int(abs(wob) * 14 + h3 * 5),
                "bursts_per_hr": 0 if status == "offline" else int(40 + wob * 18 + h1 * 25),
                "last_burst_s": int(2 + abs(wob) * 40),
                "pointing": pt_out,
            }
        return out
