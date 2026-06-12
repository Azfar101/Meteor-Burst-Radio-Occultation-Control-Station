"""
Meteor-burst link planning.

A hop A->B reflects at the great-circle midpoint, at the E-region
peak-gradient height h taken from the ionosphere model. Two modes:

- "ionospheric": fp * sec(theta) >= f_min -> the background E-layer /
  sporadic-E supports a continuous oblique reflection at some frequency
  within the station's tunable range (the criterion used in the
  project's research code). The station operates at the highest such
  frequency, capped by f_max.
- "meteor-burst": geometry is within range but the background layer is
  too weak for continuous support; communication rides on transient
  meteor trails with an estimated duty cycle.

Routing runs Dijkstra over the station graph; edge cost prefers
ionospheric-supported, mid-range, healthy hops.
"""

import datetime
import heapq
import math

from . import geometry as geo

MIN_HOP_KM = 80.0        # below this a ground-wave / LOS link is assumed instead
BURST_AVG_S = 0.45       # mean usable burst duration, s
BACKED_MATCH_KM = 350.0  # reflection-to-measured-patch match radius for the soft boost


def _local_hour(lon, t):
    return (t.hour + t.minute / 60.0 + lon / 15.0) % 24.0


def duty_cycle_pct(d_km, margin, f_op_mhz, lon_mid, t):
    """
    Estimated meteor-burst duty cycle (% of time a usable trail exists).
    Heuristic model: diurnal meteor rate (peak ~06:00 local), frequency
    scaling (~f^-2), hop-geometry factor (mid-range hops see the most
    usable common volume), and background-ionization support.
    """
    lh = _local_hour(lon_mid, t)
    diurnal = 0.65 + 0.45 * math.cos(2 * math.pi * (lh - 6.0) / 24.0)
    freq = min(3.0, max(0.2, (40.0 / f_op_mhz) ** 2))
    rng = 0.3 + 0.7 * math.exp(-(((d_km - 1000.0) / 900.0) ** 2))
    support = min(1.5, max(0.2, margin)) / 1.5
    pct = 5.0 * diurnal * freq * rng * support
    return max(0.05, min(35.0, pct))


def _bounce_hop(a, b, bounce_pts, f_min, f_max, settings):
    """
    Best A -> patch -> B reflection over the visible footprints. Returns a hop
    dict (same schema as compute_hop) or None if no patch is usable in common
    view (caller then falls back to the midpoint model).
    """
    best = None
    for p in bounce_pts:
        g = geo.bounce_geometry(a["lat"], a["lon"], 0.0, b["lat"], b["lon"], 0.0,
                                p["lat"], p["lon"], p["h_km"])
        if not g or g["el_a"] < 0.0 or g["el_b"] < 0.0:
            continue                                   # below horizon from a station
        muf = p["fp_mhz"] * g["half_sec"]
        if muf < f_min:
            continue                                   # patch can't support the band
        if best is None or muf > best[0]:
            best = (muf, p, g)
    if best is None:
        return None

    muf, p, g = best
    d_a = geo.haversine_km(a["lat"], a["lon"], p["lat"], p["lon"])
    d_b = geo.haversine_km(b["lat"], b["lon"], p["lat"], p["lon"])
    el_a, el_b = max(0.0, g["el_a"]), max(0.0, g["el_b"])
    f_used = min(f_max, muf)                            # muf >= f_min ⇒ continuous support
    margin = muf / f_used
    rate = float(settings.get("data_rate_kbps", 9.6))
    q = round(min(100.0, 60.0 + 8.0 * min(margin, 2.0)), 0)
    path = (geo.great_circle_coords(a["lat"], a["lon"], p["lat"], p["lon"], 32)
            + geo.great_circle_coords(p["lat"], p["lon"], b["lat"], b["lon"], 32))
    return {
        "from": a["id"], "to": b["id"], "from_code": a["code"], "to_code": b["code"],
        "distance_km": round(d_a + d_b, 1),
        "azimuth_ab": round(geo.initial_bearing_deg(a["lat"], a["lon"], p["lat"], p["lon"]), 1),
        "azimuth_ba": round(geo.initial_bearing_deg(b["lat"], b["lon"], p["lat"], p["lon"]), 1),
        "elevation_deg": round(min(el_a, el_b), 2),
        "el_a": round(el_a, 2), "el_b": round(el_b, 2),
        "reflection": {
            "lat": round(p["lat"], 3), "lon": round(p["lon"], 3),
            "h_km": round(p["h_km"], 1), "fp_mhz": round(p["fp_mhz"], 3),
            "source": p.get("source", "bounce"), "blend": 1.0,
            "cosmic2_backed": True, "bounce": True,
            "scatter_deg": round(g["scatter_deg"], 1),
        },
        "sec_theta": round(g["half_sec"], 3),
        "muf_mhz": round(muf, 2),
        "f_used_mhz": round(f_used, 2), "f_min_mhz": round(f_min, 1), "f_max_mhz": round(f_max, 1),
        "margin": round(margin, 3),
        "margin_db": round(20.0 * math.log10(max(margin, 1e-3)), 1),
        "mode": "ionospheric",
        "feasible": True,
        "duty_cycle_pct": 100.0,
        "throughput_kbps": round(rate, 2),
        "bursts_per_hr": None,
        "mean_wait_s": 0.0,
        "quality": q,
        "reasons": [
            f"Bounces off a {p.get('source', 'measured')} footprint at "
            f"({p['lat']:.1f}, {p['lon']:.1f}), h {p['h_km']:.0f} km, fp {p['fp_mhz']:.1f} MHz — "
            f"scatter {g['scatter_deg']:.0f}°, MUF {muf:.1f} MHz, operating at {f_used:.1f} MHz."],
        "path": path,
    }


def compute_hop(a, b, iono, t, settings, bounce_pts=None):
    """Full physics for one hop between station dicts a and b."""
    if isinstance(t, str):
        t = datetime.datetime.fromisoformat(t.replace("Z", "+00:00")).replace(tzinfo=None)

    f_min = float(settings.get("freq_min_mhz", 25.0))
    f_max = float(settings.get("freq_max_mhz", 45.0))
    if f_max < f_min:
        f_min, f_max = f_max, f_min

    # Footprint-bounce mode: reflect off the best real patch visible from both
    # ends. Falls through to the midpoint model when no patch is in common view.
    if bounce_pts:
        bhop = _bounce_hop(a, b, bounce_pts, f_min, f_max, settings)
        if bhop is not None:
            return bhop

    d = geo.haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
    mlat, mlon = geo.midpoint(a["lat"], a["lon"], b["lat"], b["lon"])
    iq = iono.query(mlat, mlon, t, settings.get("ssn", 70))
    fp, h = iq["fp_mhz"], iq["h_km"]

    d_max = geo.max_hop_range_km(h)
    reasons = []
    feasible = True

    # The station tunes within [f_min, f_max]: it operates at the highest frequency
    # the ionosphere still supports (capped by f_max); if even f_min exceeds the MUF
    # the hop drops to transient meteor-burst mode at f_min.
    if d < MIN_HOP_KM:
        mode = "line-of-sight"
        el = 0.0
        sec = 1.0
        muf = fp
        f_used = f_min
        margin = 99.0
        duty = 100.0
        reasons.append(f"Stations only {d:.0f} km apart — direct ground/LOS link assumed.")
    elif d > d_max:
        feasible = False
        mode = "unreachable"
        el = 0.0
        sec = geo.sec_theta(d_max * 0.999, h)
        muf = fp * sec
        f_used = f_min
        margin = muf / f_used
        duty = 0.0
        reasons.append(
            f"Hop length {d:.0f} km exceeds the horizon-limited maximum "
            f"{d_max:.0f} km for a {h:.0f} km reflection height.")
    else:
        el = geo.elevation_angle_deg(d, h)
        sec = geo.sec_theta(d, h)
        muf = fp * sec
        if muf >= f_min:
            mode = "ionospheric"
            f_used = min(f_max, muf)           # ride as high as the E-layer allows
            margin = muf / f_used
            duty = 100.0
            reasons.append(
                f"E-layer supports continuous reflection: MUF {muf:.1f} MHz ≥ "
                f"{f_min:.0f} MHz min operating frequency — operating at {f_used:.1f} MHz.")
        else:
            mode = "meteor-burst"
            f_used = f_min                     # lowest frequency = easiest support
            margin = muf / f_used
            duty = duty_cycle_pct(d, margin, f_used, mlon, t)
            reasons.append(
                f"Background MUF {muf:.1f} MHz < {f_min:.0f} MHz min operating frequency — "
                f"link rides on transient meteor trails at {f_used:.1f} MHz "
                f"(est. duty cycle {duty:.1f}%).")
            if not settings.get("allow_meteor_mode", True):
                feasible = False
                reasons.append("Meteor-burst mode disabled in settings.")

    rate = float(settings.get("data_rate_kbps", 9.6))
    throughput = round(rate * duty / 100.0, 2)
    bursts_hr = int(duty / 100.0 * 3600.0 / BURST_AVG_S) if mode == "meteor-burst" else None
    wait_s = round(3600.0 / bursts_hr, 1) if bursts_hr else 0.0

    # soft boost: does a real measured usable patch sit where this hop reflects?
    backed = None
    if feasible and mode not in ("line-of-sight", "unreachable"):
        backed = iono.nearest_usable(mlat, mlon, t, f_min, BACKED_MATCH_KM)
        if backed:
            reasons.append(
                f"Reflection backed by a measured COSMIC-2 patch "
                f"({backed['fp_mhz']} MHz, {backed['dist_km']} km away).")

    q = 0.0
    if feasible:
        q_margin = min(margin, 1.6) / 1.6
        q_range = 1.0 - min(1.0, abs(d - 900.0) / 1600.0) if d >= MIN_HOP_KM else 1.0
        q_duty = duty / 100.0
        q = round(100.0 * (0.45 * q_margin + 0.25 * q_range + 0.30 * q_duty), 0)
        if backed:
            q = min(100.0, q + 8.0)

    el = max(el, 0.0)
    return {
        "from": a["id"], "to": b["id"],
        "from_code": a["code"], "to_code": b["code"],
        "distance_km": round(d, 1),
        "azimuth_ab": round(geo.initial_bearing_deg(a["lat"], a["lon"], b["lat"], b["lon"]), 1),
        "azimuth_ba": round(geo.initial_bearing_deg(b["lat"], b["lon"], a["lat"], a["lon"]), 1),
        "elevation_deg": round(el, 2),
        "reflection": {
            "lat": round(mlat, 3), "lon": round(mlon, 3),
            "h_km": round(h, 1), "fp_mhz": round(fp, 3),
            "source": iq["source"], "blend": iq["blend"],
            "cosmic2_backed": backed is not None,
            "backed": backed,
        },
        "sec_theta": round(sec, 3),
        "muf_mhz": round(muf, 2),
        "f_used_mhz": round(f_used, 2),
        "f_min_mhz": round(f_min, 1),
        "f_max_mhz": round(f_max, 1),
        "margin": round(margin, 3),
        "margin_db": round(20.0 * math.log10(max(margin, 1e-3)), 1),
        "mode": mode,
        "feasible": feasible,
        "duty_cycle_pct": round(duty, 2),
        "throughput_kbps": throughput,
        "bursts_per_hr": bursts_hr,
        "mean_wait_s": wait_s,
        "quality": q,
        "reasons": reasons,
        "path": geo.great_circle_coords(a["lat"], a["lon"], b["lat"], b["lon"], 48),
    }


def compute_route(src, dst, stations, telemetry, iono, t, settings, bounce_pts=None):
    """
    Dijkstra over the station graph. Offline stations are excluded;
    degraded ones are penalised. Returns route dict (may be infeasible).
    """
    if isinstance(t, str):
        t = datetime.datetime.fromisoformat(t.replace("Z", "+00:00")).replace(tzinfo=None)

    direct = compute_hop(src, dst, iono, t, settings, bounce_pts)

    usable = [s for s in stations
              if telemetry.get(s["id"], {}).get("status") != "offline"
              or s["id"] in (src["id"], dst["id"])]
    idx = {s["id"]: s for s in usable}
    if src["id"] not in idx or dst["id"] not in idx:
        return {"feasible": False, "direct": direct, "hops": [],
                "notes": ["Source or destination station is offline."]}

    max_hops = int(settings.get("max_hops", 6))
    hop_cache = {}

    def hop(a_id, b_id):
        key = (a_id, b_id)
        if key not in hop_cache:
            hop_cache[key] = compute_hop(idx[a_id], idx[b_id], iono, t, settings, bounce_pts)
        return hop_cache[key]

    def edge_cost(h, b_id):
        if not h["feasible"]:
            return None
        c = 0.6 + h["distance_km"] / 2400.0           # per-hop base + distance
        c += (1.0 - min(h["quality"], 100) / 100.0) * 1.2
        if h["mode"] == "meteor-burst":
            c += 0.8 * (1.0 - h["duty_cycle_pct"] / 35.0)
        if telemetry.get(b_id, {}).get("status") == "degraded":
            c += 0.7
        if h["reflection"].get("cosmic2_backed"):
            c -= 0.25  # prefer measurement-backed reflections (tie-breaker only)
        return c

    # Dijkstra with hop-count cap
    start, goal = src["id"], dst["id"]
    best = {(start, 0): 0.0}
    prev = {}
    pq = [(0.0, start, 0)]
    found = None
    while pq:
        cost, node, nh = heapq.heappop(pq)
        if node == goal:
            found = (node, nh)
            break
        if cost > best.get((node, nh), 1e18) or nh >= max_hops:
            continue
        for nb in usable:
            if nb["id"] == node:
                continue
            h = hop(node, nb["id"])
            ec = edge_cost(h, nb["id"])
            if ec is None:
                continue
            nc = cost + ec
            key = (nb["id"], nh + 1)
            if nc < best.get(key, 1e18):
                best[key] = nc
                prev[key] = (node, nh)
                heapq.heappush(pq, (nc, nb["id"], nh + 1))

    if not found:
        return {
            "feasible": False, "direct": direct, "hops": [],
            "notes": [f"No relay path found within {max_hops} hops. "
                      "Try raising max hops, lowering the operating frequency, "
                      "or adding intermediate stations."],
        }

    # reconstruct
    chain = []
    key = found
    while key in prev:
        chain.append(key[0])
        key = prev[key]
    chain.append(start)
    chain.reverse()

    hops = [hop(chain[i], chain[i + 1]) for i in range(len(chain) - 1)]
    bottleneck = min(h["throughput_kbps"] for h in hops)
    total_wait = sum(h["mean_wait_s"] for h in hops)
    return {
        "feasible": True,
        "direct": direct,
        "station_ids": chain,
        "hops": hops,
        "total_distance_km": round(sum(h["distance_km"] for h in hops), 1),
        "n_hops": len(hops),
        "bottleneck_kbps": bottleneck,
        "est_total_wait_s": round(total_wait, 1),
        "quality": round(sum(h["quality"] for h in hops) / len(hops), 0),
        "notes": [],
    }
