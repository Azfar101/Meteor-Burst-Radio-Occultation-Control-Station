"""
Ionosphere state model.

Three tiers of E-region plasma frequency (fp), blended by Gaussian
inverse-distance/time weighting:

1. COSMIC-2 profiles imported by the user (E-region peak-gradient fp,
   exactly as in the project's research code) — highest priority.
2. Live GIRO ionosonde soundings (foE / sporadic-E foEs at hmE) from the
   open prop.kc2g.com API — the real-data default before any COSMIC-2
   import. Weighted by the sounding confidence score.
3. Solar-zenith-angle foE model
   (foE = 0.9 * ((180 + 1.44*R12) * cos(chi))^0.25 MHz, night floor),
   driven by the live effective SSN when available.

query() reports which tier dominated ("cosmic2" / "ionosonde" /
"blended" / "model").
"""

import datetime
import math

import numpy as np

# interpolation kernel scales
DIST_SCALE_KM = 1200.0     # spatial e-folding distance
TIME_SCALE_H = 2.5         # temporal e-folding window
SEARCH_TIME_H = 8.0        # hard cutoff: ignore data further than this in time
MODEL_WEIGHT = 0.35        # pseudo-weight of the model (controls blending)
SONDE_WEIGHT = 0.6         # ionosonde weight relative to COSMIC-2
MODEL_H_KM = 102.0         # assumed reflection height for the model


def _to_dt(t):
    if isinstance(t, datetime.datetime):
        return t
    return datetime.datetime.fromisoformat(str(t).replace("Z", "+00:00")).replace(tzinfo=None)


def solar_cos_chi(lat_deg, lon_deg, t):
    """Cosine of solar zenith angle (vectorised over lat/lon arrays)."""
    doy = t.timetuple().tm_yday
    decl = math.radians(-23.44) * math.cos(2.0 * math.pi * (doy + 10) / 365.0)
    hours = t.hour + t.minute / 60.0 + t.second / 3600.0
    lst = hours + np.asarray(lon_deg, dtype=float) / 15.0  # local solar time
    H = np.radians(15.0 * (lst - 12.0))                     # hour angle
    lat = np.radians(np.asarray(lat_deg, dtype=float))
    return np.sin(lat) * math.sin(decl) + np.cos(lat) * math.cos(decl) * np.cos(H)


def model_foe_mhz(lat_deg, lon_deg, t, ssn=70.0):
    """Daytime Chapman-layer foE with a nighttime floor (MHz)."""
    cos_chi = np.clip(solar_cos_chi(lat_deg, lon_deg, t), 0.0, 1.0)
    foe = 0.9 * ((180.0 + 1.44 * ssn) * cos_chi) ** 0.25
    return np.maximum(foe, 0.45)


class Ionosphere:
    def __init__(self):
        self.profiles = []          # COSMIC-2 profile dicts (see cosmic2_loader)
        self.live_fn = None         # injected: callable -> livedata snapshot
        self._pool = None           # numpy cache of pooled observation points
        self._pool_live_ts = None   # live-fetch timestamp the pool was built with

    # ── profile management ──────────────────────────────────────────────
    def set_profiles(self, profiles):
        self.profiles = sorted(profiles, key=lambda p: p["time"])
        self._pool = None

    def add_profiles(self, profiles):
        existing = {p["file"] for p in self.profiles}
        added = [p for p in profiles if p["file"] not in existing]
        self.set_profiles(self.profiles + added)
        return len(added)

    def clear(self):
        self.set_profiles([])

    def time_range(self):
        if not self.profiles:
            return None
        return self.profiles[0]["time"], self.profiles[-1]["time"]

    # ── observation pool (COSMIC-2 + live ionosondes) ───────────────────
    def _live(self):
        if self.live_fn is None:
            return {"sondes": [], "ssn": None, "fetched": 0.0, "ok": False}
        return self.live_fn()

    def _pool_arrays(self):
        live = self._live()
        if self._pool is None or self._pool_live_ts != live["fetched"]:
            lat, lon, fp, h, ts, wm, c2 = [], [], [], [], [], [], []
            for p in self.profiles:
                lat.append(p["lat"]); lon.append(p["lon"])
                fp.append(p["fp_mhz"]); h.append(p["h_peak_km"])
                ts.append(p["time"].timestamp()); wm.append(1.0); c2.append(1.0)
            for s in live["sondes"]:
                lat.append(s["lat"]); lon.append(s["lon"])
                fp.append(s["fp_mhz"]); h.append(s["h_km"])
                ts.append(s["ts"])
                wm.append(SONDE_WEIGHT * max(0.1, min(1.0, s["cs"] / 100.0)))
                c2.append(0.0)
            self._pool = {
                "lat": np.array(lat), "lon": np.array(lon),
                "fp": np.array(fp), "h": np.array(h),
                "ts": np.array(ts), "wm": np.array(wm), "c2": np.array(c2),
            }
            self._pool_live_ts = live["fetched"]
        return self._pool

    def live_ssn(self):
        return self._live().get("ssn")

    # ── queries ─────────────────────────────────────────────────────────
    def query_many(self, lats, lons, t, ssn=70.0):
        """
        Returns (fp MHz, h km, blend 0..1, c2_frac 0..1) at each (lat, lon)
        for time t. blend = how much observed data (vs model) contributed;
        c2_frac = COSMIC-2 share of the observed weight.
        """
        t = _to_dt(t)
        lats = np.asarray(lats, dtype=float)
        lons = np.asarray(lons, dtype=float)

        fp_model = model_foe_mhz(lats, lons, t, ssn)
        h_model = np.full(lats.shape, MODEL_H_KM)

        pool = self._pool_arrays()
        if pool["fp"].size == 0:
            z = np.zeros(lats.shape)
            return fp_model, h_model, z, z

        dt_h = np.abs(pool["ts"] - t.timestamp()) / 3600.0
        sel = dt_h <= SEARCH_TIME_H
        if not np.any(sel):
            z = np.zeros(lats.shape)
            return fp_model, h_model, z, z

        plat = np.radians(pool["lat"][sel])[None, :]
        plon = np.radians(pool["lon"][sel])[None, :]
        pfp = pool["fp"][sel][None, :]
        ph = pool["h"][sel][None, :]
        pc2 = pool["c2"][sel][None, :]
        wt = (np.exp(-((dt_h[sel] / TIME_SCALE_H) ** 2)) * pool["wm"][sel])[None, :]

        qlat = np.radians(lats)[:, None]
        qlon = np.radians(lons)[:, None]

        # haversine distance matrix (queries x pool points)
        a = (np.sin((plat - qlat) / 2) ** 2
             + np.cos(qlat) * np.cos(plat) * np.sin((plon - qlon) / 2) ** 2)
        d_km = 2.0 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

        w = np.exp(-((d_km / DIST_SCALE_KM) ** 2)) * wt
        wsum = w.sum(axis=1)
        wsum_c2 = (w * pc2).sum(axis=1)
        safe = np.maximum(wsum, 1e-12)
        fp_obs = (w * pfp).sum(axis=1) / safe
        h_obs = (w * ph).sum(axis=1) / safe

        blend = wsum / (wsum + MODEL_WEIGHT)
        fp = blend * fp_obs + (1 - blend) * fp_model
        h = blend * h_obs + (1 - blend) * h_model
        c2_frac = wsum_c2 / safe
        return fp, h, blend, c2_frac

    @staticmethod
    def _source_label(blend, c2_frac):
        if blend <= 0.12:
            return "model"
        if blend < 0.5:
            return "blended"
        return "cosmic2" if c2_frac >= 0.5 else "ionosonde"

    def query(self, lat, lon, t, ssn=70.0):
        """Single-point query -> dict."""
        fp, h, blend, c2f = self.query_many([lat], [lon], t, ssn)
        b = float(blend[0])
        return {
            "fp_mhz": round(float(fp[0]), 3),
            "h_km": round(float(h[0]), 1),
            "blend": round(b, 3),
            "source": self._source_label(b, float(c2f[0])),
        }

    def nearest_usable(self, lat, lon, t, freq_min=0.0, max_km=350.0):
        """
        Nearest *measured* COSMIC-2 patch to (lat, lon) at time t whose max usable
        operating frequency (fp * sec at grazing) clears ``freq_min`` and that lies
        within ``max_km``. Returns {fp_mhz, h_km, muf_max_mhz, dist_km, time} or
        None — used to give hops a soft routing boost when their reflection point
        sits on real measured ionization usable at the operating frequency.
        """
        t = _to_dt(t)
        pool = self._pool_arrays()
        if pool["fp"].size == 0:
            return None
        is_c2 = pool["c2"] >= 1.0
        dt_h = np.abs(pool["ts"] - t.timestamp()) / 3600.0
        # max usable operating frequency of each patch at grazing geometry
        sec_max = 1.0 / np.sqrt(1.0 - (6371.0 / (6371.0 + pool["h"])) ** 2)
        muf_max = pool["fp"] * sec_max
        sel = is_c2 & (dt_h <= SEARCH_TIME_H) & (muf_max >= freq_min)
        if not np.any(sel):
            return None

        plat = np.radians(pool["lat"][sel])
        plon = np.radians(pool["lon"][sel])
        qlat = math.radians(lat)
        qlon = math.radians(lon)
        a = (np.sin((plat - qlat) / 2) ** 2
             + math.cos(qlat) * np.cos(plat) * np.sin((plon - qlon) / 2) ** 2)
        d_km = 2.0 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))

        k = int(np.argmin(d_km))
        if d_km[k] > max_km:
            return None
        return {
            "fp_mhz": round(float(pool["fp"][sel][k]), 3),
            "h_km": round(float(pool["h"][sel][k]), 1),
            "muf_max_mhz": round(float(muf_max[sel][k]), 1),
            "dist_km": round(float(d_km[k]), 1),
            # mirror the naive .timestamp() used when the pool was built
            "time": datetime.datetime.fromtimestamp(float(pool["ts"][sel][k])).isoformat() + "Z",
        }

    def usable_patches(self, freq_min=0.0):
        """
        Loaded COSMIC-2 patches whose max usable frequency (fp * sec at grazing)
        clears ``freq_min`` — i.e. the footprints visible on the map. Returned as
        bounce-point dicts for the link planner (time-independent, matching the
        on-screen footprints).
        """
        out = []
        for p in self.profiles:
            h = p["h_peak_km"]
            sec_max = 1.0 / math.sqrt(1.0 - (6371.0 / (6371.0 + h)) ** 2)
            if p["fp_mhz"] * sec_max >= freq_min:
                out.append({"lat": p["lat"], "lon": p["lon"],
                            "h_km": h, "fp_mhz": p["fp_mhz"], "source": "cosmic2"})
        return out

    def grid(self, t, res_deg=4.0, ssn=70.0):
        """Regular lat/lon grid of fp for the map overlay."""
        t = _to_dt(t)
        lat_edges = np.arange(-80.0, 80.0 + 1e-9, res_deg)
        lon_edges = np.arange(-180.0, 180.0 + 1e-9, res_deg)
        lat_c = (lat_edges[:-1] + lat_edges[1:]) / 2.0
        lon_c = (lon_edges[:-1] + lon_edges[1:]) / 2.0
        glon, glat = np.meshgrid(lon_c, lat_c)
        flat_lat = glat.ravel()
        flat_lon = glon.ravel()

        # chunk to bound the distance-matrix memory
        fp_parts, blend_parts = [], []
        for i in range(0, flat_lat.size, 2048):
            fp, _h, blend, _c2 = self.query_many(flat_lat[i:i + 2048], flat_lon[i:i + 2048], t, ssn)
            fp_parts.append(fp)
            blend_parts.append(blend)
        fp = np.concatenate(fp_parts)
        blend = np.concatenate(blend_parts)

        return {
            "res": res_deg,
            "lat0": float(lat_edges[0]),
            "lon0": float(lon_edges[0]),
            "nlat": lat_c.size,
            "nlon": lon_c.size,
            "fp": [round(float(v), 2) for v in fp],
            "blend": [round(float(v), 2) for v in blend],
            "time": t.isoformat(),
            "n_profiles": len(self.profiles),
            "n_sondes": len(self._live()["sondes"]),
        }
