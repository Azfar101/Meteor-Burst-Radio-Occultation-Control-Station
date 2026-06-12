"""
Meteor-burst link planning.

A hop A->B reflects at the great-circle midpoint, at the E-region
peak-gradient height h taken from the ionosphere model. Two modes:

- "ionospheric": fp * sec(theta) >= f_op -> the background E-layer /
  sporadic-E supports a continuous oblique reflection (the criterion
  used in the project's research code).
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


def compute_hop(a, b, iono, t, settings):
    """Full physics for one hop between station dicts a and b."""
    if isinstance(t, str):
        t = datetime.datetime.fromisoformat(t.replace("Z", "+00:00")).replace(tzinfo=None)

    f_op = float(settings["freq_mhz"])
    d = geo.haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
    mlat, mlon = geo.midpoint(a["lat"], a["lon"], b["lat"], b["lon"])
    iq = iono.query(mlat, mlon, t, settings.get("ssn", 70))
    fp, h = iq["fp_mhz"], iq["h_km"]

    d_max = geo.max_hop_range_km(h)
    reasons = []
    feasible = True

    if d < MIN_HOP_KM:
        mode = "line-of-sight"
        el = 0.0
        sec = 1.0
        muf = fp
        margin = 99.0
        duty = 100.0
        reasons.append(f"Stations only {d:.0f} km apart — direct ground/LOS link assumed.")
    elif d > d_max:
        feasible = False
        mode = "unreachable"
        el = 0.0
        sec = geo.sec_theta(d_max * 0.999, h)
        muf = fp * sec
        margin = muf / f_op
        duty = 0.0
        reasons.append(
            f"Hop length {d:.0f} km exceeds the horizon-limited maximum "
            f"{d_max:.0f} km for a {h:.0f} km reflection height.")
    else:
        el = geo.elevation_angle_deg(d, h)
        sec = geo.sec_theta(d, h)
        muf = fp * sec
        margin = muf / f_op
        if margin >= 1.0:
            mode = "ionospheric"
            duty = 100.0
            reasons.append(
                f"E-layer supports continuous reflection: MUF {muf:.1f} MHz ≥ "
                f"{f_op:.0f} MHz operating frequency.")
        else:
            mode = "meteor-burst"
            duty = duty_cycle_pct(d, margin, f_op, mlon, t)
            reasons.append(
                f"Background MUF {muf:.1f} MHz < {f_op:.0f} MHz — link rides on "
                f"transient meteor trails (est. duty cycle {duty:.1f}%).")
            if not settings.get("allow_meteor_mode", True):
                feasible = False
                reasons.append("Meteor-burst mode disabled in settings.")

    rate = float(settings.get("data_rate_kbps", 9.6))
    throughput = round(rate * duty / 100.0, 2)
    bursts_hr = int(duty / 100.0 * 3600.0 / BURST_AVG_S) if mode == "meteor-burst" else None
    wait_s = round(3600.0 / bursts_hr, 1) if bursts_hr else 0.0

    q = 0.0
    if feasible:
        q_margin = min(margin, 1.6) / 1.6
        q_range = 1.0 - min(1.0, abs(d - 900.0) / 1600.0) if d >= MIN_HOP_KM else 1.0
        q_duty = duty / 100.0
        q = round(100.0 * (0.45 * q_margin + 0.25 * q_range + 0.30 * q_duty), 0)

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
        },
        "sec_theta": round(sec, 3),
        "muf_mhz": round(muf, 2),
        "f_op_mhz": f_op,
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


def compute_route(src, dst, stations, telemetry, iono, t, settings):
    """
    Dijkstra over the station graph. Offline stations are excluded;
    degraded ones are penalised. Returns route dict (may be infeasible).
    """
    if isinstance(t, str):
        t = datetime.datetime.fromisoformat(t.replace("Z", "+00:00")).replace(tzinfo=None)

    direct = compute_hop(src, dst, iono, t, settings)

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
            hop_cache[key] = compute_hop(idx[a_id], idx[b_id], iono, t, settings)
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
