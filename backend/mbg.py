"""
Custom meteor-burst reflection points ("MBG points").

User-placed bounce points for the simulation: each is a fixed ionization
patch at (lat, lon, height) with a plasma frequency, usable as a reflection
point for links exactly like a measured COSMIC-2 footprint. Persisted to
backend/data/mbg_points.json.
"""

import json
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
MBG_FILE = DATA_DIR / "mbg_points.json"

DEFAULT_H_KM = 100.0
DEFAULT_FP_MHZ = 6.0


class MBGStore:
    def __init__(self):
        self._load()

    def _load(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if MBG_FILE.exists():
            try:
                self.points = json.loads(MBG_FILE.read_text(encoding="utf-8"))
                return
            except Exception:
                pass
        self.points = []
        self._save()

    def _save(self):
        MBG_FILE.write_text(
            json.dumps(self.points, indent=2, ensure_ascii=False), encoding="utf-8")

    def all(self):
        return self.points

    def get(self, mid):
        for m in self.points:
            if m["id"] == mid:
                return m
        return None

    def add(self, lat, lon, h_km=None, fp_mhz=None, name=None):
        n = len(self.points) + 1
        m = {
            "id": uuid.uuid4().hex[:10],
            "name": name or f"MBG-{n:02d}",
            "lat": round(float(lat), 4),
            "lon": round(float(lon), 4),
            "h_km": round(float(h_km if h_km is not None else DEFAULT_H_KM), 2),
            "fp_mhz": round(float(fp_mhz if fp_mhz is not None else DEFAULT_FP_MHZ), 4),
        }
        self.points.append(m)
        self._save()
        return m

    def update(self, mid, fields):
        m = self.get(mid)
        if not m:
            return None
        for k in ("name", "lat", "lon", "h_km", "fp_mhz"):
            if fields.get(k) is not None:
                m[k] = fields[k] if k == "name" else round(float(fields[k]), 4)
        self._save()
        return m

    def delete(self, mid):
        before = len(self.points)
        self.points = [m for m in self.points if m["id"] != mid]
        if len(self.points) != before:
            self._save()
            return True
        return False

    def reset(self):
        self.points = []
        self._save()
