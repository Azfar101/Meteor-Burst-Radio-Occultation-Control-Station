"""
COSMIC-2 ionPrf ingestion.

Faithful port of the project's research pipeline (test.py /
cosmic2_plasma_map.py): for each profile, find the E-region
peak-gradient altitude in 80-120 km, compute the plasma frequency
there, and run the MeteorSpikeClassifier over the meteor zone.
"""

import datetime
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

# the classifier lives at the repo root
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from meteor_spike_classifier import MeteorSpikeClassifier  # noqa: E402

ALT_MIN_KM = 80.0
ALT_MAX_KM = 120.0

_classifier = MeteorSpikeClassifier()


def process_file(path):
    """
    Process one ionPrf NetCDF file.
    Returns (profile_dict, None) on success or (None, reason) on skip.
    """
    import netCDF4 as nc

    path = Path(path)
    ds = nc.Dataset(str(path), "r")
    try:
        lat = np.asarray(ds.variables["GEO_lat"][:], dtype=float)
        lon = np.asarray(ds.variables["GEO_lon"][:], dtype=float)
        alt = np.asarray(ds.variables["MSL_alt"][:], dtype=float)
        ed = np.asarray(ds.variables["ELEC_dens"][:], dtype=float)
        ed = np.where(ed < 0, np.nan, ed)

        perigee_idx = int(np.argmin(alt))

        mask = (alt >= ALT_MIN_KM) & (alt <= ALT_MAX_KM)
        if np.sum(mask) < 2 or np.all(np.isnan(ed[mask])):
            return None, "no valid E-region data"

        dne_dh = np.gradient(ed[mask], alt[mask])
        peak_idx = int(np.nanargmax(np.abs(dne_dh)))
        h_peak = float(alt[mask][peak_idx])
        ne_peak = float(ed[mask][peak_idx])

        fp_mhz = 8.98 * np.sqrt(ne_peak * 1e6) / 1e6
        if np.isnan(fp_mhz):
            return None, "NaN plasma frequency"

        verdict, details = _classifier.classify(alt, ed)

        dt = datetime.datetime(
            int(getattr(ds, "year", 2000)),
            int(getattr(ds, "month", 1)),
            int(getattr(ds, "day", 1)),
            int(getattr(ds, "hour", 0)),
            int(getattr(ds, "minute", 0)),
            int(getattr(ds, "second", 0)),
        )

        return {
            "file": path.name,
            "time": dt,
            "lat": float(lat[perigee_idx]),
            "lon": float(lon[perigee_idx]),
            "fp_mhz": round(float(fp_mhz), 4),
            "ne_peak": ne_peak,
            "h_peak_km": round(h_peak, 2),
            "nmf2": float(getattr(ds, "edmax", np.nan)),
            "hmf2": float(getattr(ds, "edmaxalt", np.nan)),
            "fof2_mhz": float(getattr(ds, "critfreq", np.nan)),
            "sat_id": str(getattr(ds, "occulting_sat_id", "?")),
            "occ_type": "setting" if getattr(ds, "setting", -1) == 1 else "rising",
            "verdict": verdict,
            "reality_score": details.get("reality_score"),
            "confidence": details.get("confidence"),
            "flags": details.get("flags", []),
        }, None
    finally:
        ds.close()


def scan_folder(folder):
    """Process every ionPrf file in a folder. Returns (profiles, skipped)."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")

    files = sorted(set(
        list(folder.glob("*_nc")) + list(folder.glob("*.nc")) + list(folder.glob("ionPrf*"))
    ))
    profiles, skipped = [], []
    for f in files:
        if not f.is_file():
            continue
        try:
            prof, reason = process_file(f)
        except Exception as e:  # malformed / non-ionPrf file
            prof, reason = None, str(e)
        if prof:
            profiles.append(prof)
        else:
            skipped.append({"file": f.name, "reason": reason})
    return profiles, skipped
