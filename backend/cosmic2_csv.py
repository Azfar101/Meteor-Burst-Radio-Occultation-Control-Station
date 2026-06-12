"""
CSV round-trip for processed COSMIC-2 profiles.

Exports the in-memory profile table (the dicts produced by
``cosmic2_loader.process_file`` / ``cosmic2_fetch``) to a single CSV — one
row per profile — and parses such a CSV back into the same dict shape so a
session can be reloaded without the original NetCDF files.

The two "radius" columns mirror the original research script (test.py): the
ground band, measured from the reflection point, within which a station can
use that ionization patch at the current operating frequency. They are
derived from ``fp``/``h``/``f_op`` and are written for reference only — they
are recomputed (not read) on import.
"""

import csv
import datetime
import io

from . import geometry as geo

# Persisted fields (round-trip) followed by derived-for-reference radii.
_CORE = [
    "file", "time", "lat", "lon", "fp_mhz", "ne_peak", "h_peak_km",
    "nmf2", "hmf2", "fof2_mhz", "sat_id", "occ_type",
    "verdict", "reality_score", "confidence", "flags",
]
_DERIVED = ["outer_radius_km", "inner_radius_km"]
COLUMNS = _CORE + _DERIVED

_FLOAT = {"lat", "lon", "fp_mhz", "ne_peak", "h_peak_km",
          "nmf2", "hmf2", "fof2_mhz", "reality_score", "confidence"}


def _radii_km(fp_mhz, h_km, f_op):
    """Outer/inner ground radius (half-hop) of the reflection footprint."""
    try:
        outer = geo.max_hop_range_km(float(h_km)) / 2.0
    except (TypeError, ValueError):
        return None, None
    inner_hop = geo.min_hop_range_km(float(fp_mhz), float(f_op), float(h_km))
    inner = inner_hop / 2.0 if inner_hop else None
    return outer, inner


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v != v:  # NaN
        return ""
    return v


def profiles_to_csv(profiles, f_op=30.0):
    """Serialize a list of profile dicts to CSV text."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    for p in profiles:
        t = p.get("time")
        t_iso = t.isoformat() if isinstance(t, datetime.datetime) else (t or "")
        flags = p.get("flags") or []
        flags_s = ";".join(str(x) for x in flags) if isinstance(flags, (list, tuple)) else str(flags)
        outer, inner = _radii_km(p.get("fp_mhz"), p.get("h_peak_km"), f_op)
        w.writerow([
            _fmt(p.get("file")), t_iso,
            _fmt(p.get("lat")), _fmt(p.get("lon")), _fmt(p.get("fp_mhz")),
            _fmt(p.get("ne_peak")), _fmt(p.get("h_peak_km")),
            _fmt(p.get("nmf2")), _fmt(p.get("hmf2")), _fmt(p.get("fof2_mhz")),
            _fmt(p.get("sat_id")), _fmt(p.get("occ_type")),
            _fmt(p.get("verdict")), _fmt(p.get("reality_score")), _fmt(p.get("confidence")),
            flags_s,
            round(outer, 2) if outer is not None else "",
            round(inner, 2) if inner is not None else "",
        ])
    return buf.getvalue()


def _to_float(s):
    if s is None or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_time(s):
    if not s:
        raise ValueError("missing time")
    return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)


def csv_to_profiles(text):
    """
    Parse CSV text back into profile dicts. Returns (profiles, errors) where
    errors is a list of {row, reason}. Derived radius columns are ignored.
    """
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return [], [{"row": 0, "reason": "empty file"}]
    required = {"file", "time", "lat", "lon", "fp_mhz", "h_peak_km"}
    missing = required - set(h.strip() for h in reader.fieldnames)
    if missing:
        return [], [{"row": 0, "reason": f"missing required columns: {', '.join(sorted(missing))}"}]

    profiles, errors = [], []
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        row = {(k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        try:
            lat, lon = _to_float(row.get("lat")), _to_float(row.get("lon"))
            fp = _to_float(row.get("fp_mhz"))
            h = _to_float(row.get("h_peak_km"))
            if None in (lat, lon, fp, h):
                raise ValueError("non-numeric lat/lon/fp_mhz/h_peak_km")
            flags = [f for f in (row.get("flags") or "").split(";") if f]
            profiles.append({
                "file": row.get("file") or f"csv_row_{i}",
                "time": _parse_time(row.get("time")),
                "lat": lat, "lon": lon, "fp_mhz": fp,
                "ne_peak": _to_float(row.get("ne_peak")),
                "h_peak_km": h,
                "nmf2": _to_float(row.get("nmf2")),
                "hmf2": _to_float(row.get("hmf2")),
                "fof2_mhz": _to_float(row.get("fof2_mhz")),
                "sat_id": row.get("sat_id") or "?",
                "occ_type": row.get("occ_type") or "?",
                "verdict": row.get("verdict") or "UNKNOWN",
                "reality_score": _to_float(row.get("reality_score")),
                "confidence": _to_float(row.get("confidence")),
                "flags": flags,
            })
        except Exception as e:  # noqa: BLE001 — record bad rows, keep going
            errors.append({"row": i, "reason": str(e)})
    return profiles, errors
