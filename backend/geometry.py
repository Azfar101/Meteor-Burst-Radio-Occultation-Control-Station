"""
Spherical-Earth geodesy and meteor-burst reflection geometry.

All distances in km, angles in degrees unless suffixed otherwise.
The reflection model follows the project's research code (test.py):
a signal launched from a ground station reflects at the E-region
peak-gradient altitude h; the secant law f_max = fp * sec(theta)
(theta = incidence angle from local vertical at the layer) decides
whether an operating frequency can be supported.
"""

import math

R_E = 6371.0  # mean Earth radius, km


# ── Basic geodesy ────────────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R_E * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlmb = math.radians(lon2 - lon1)
    y = math.sin(dlmb) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlmb)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def midpoint(lat1, lon1, lat2, lon2):
    return intermediate_point(lat1, lon1, lat2, lon2, 0.5)


def intermediate_point(lat1, lon1, lat2, lon2, f):
    """Point at fraction f along the great circle from 1 to 2."""
    p1, l1 = math.radians(lat1), math.radians(lon1)
    p2, l2 = math.radians(lat2), math.radians(lon2)
    d = haversine_km(lat1, lon1, lat2, lon2) / R_E
    if d < 1e-9:
        return lat1, lon1
    a = math.sin((1 - f) * d) / math.sin(d)
    b = math.sin(f * d) / math.sin(d)
    x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
    y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
    z = a * math.sin(p1) + b * math.sin(p2)
    lat = math.atan2(z, math.sqrt(x * x + y * y))
    lon = math.atan2(y, x)
    return math.degrees(lat), math.degrees(lon)


def great_circle_coords(lat1, lon1, lat2, lon2, n=64):
    """[lon, lat] list along the great circle (GeoJSON order)."""
    pts = []
    prev_lon = None
    for i in range(n + 1):
        la, lo = intermediate_point(lat1, lon1, lat2, lon2, i / n)
        # unwrap across the antimeridian so the line doesn't streak across the map
        if prev_lon is not None:
            while lo - prev_lon > 180:
                lo -= 360
            while lo - prev_lon < -180:
                lo += 360
        prev_lon = lo
        pts.append([round(lo, 4), round(la, 4)])
    return pts


def destination_point(lat, lon, bearing_deg, dist_km):
    p1 = math.radians(lat)
    l1 = math.radians(lon)
    brg = math.radians(bearing_deg)
    d = dist_km / R_E
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(brg))
    l2 = l1 + math.atan2(math.sin(brg) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    lon2 = (math.degrees(l2) + 540.0) % 360.0 - 180.0
    return math.degrees(p2), lon2


# ── Reflection geometry ──────────────────────────────────────────────────────

def elevation_angle_deg(d_km, h_km):
    """Antenna elevation for a hop of ground distance d via a layer at height h."""
    delta = (d_km / 2.0) / R_E  # half central angle
    num = math.cos(delta) - R_E / (R_E + h_km)
    den = math.sin(delta)
    if den < 1e-12:
        return 90.0
    return math.degrees(math.atan2(num, den))


def incidence_angle_deg(d_km, h_km):
    """Incidence angle from local vertical at the reflection layer."""
    el = math.radians(elevation_angle_deg(d_km, h_km))
    sin_th = (R_E * math.cos(el)) / (R_E + h_km)
    return math.degrees(math.asin(min(1.0, sin_th)))


def sec_theta(d_km, h_km):
    th = math.radians(incidence_angle_deg(d_km, h_km))
    c = math.cos(th)
    return 1.0 / max(c, 1e-6)


def max_hop_range_km(h_km):
    """Horizon-limited maximum hop length (both ends at 0° elevation)."""
    return 2.0 * R_E * math.acos(R_E / (R_E + h_km))


def min_hop_range_km(fp_mhz, f_op_mhz, h_km):
    """
    Minimum hop length for which the secant law closes at f_op
    (fp * sec(theta) >= f_op). 0 if even vertical reflection works.
    Returns None if no geometry works (fp too low even at grazing).
    Mirrors the min_theta computation in the original test.py.
    """
    if fp_mhz <= 0:
        return None
    if fp_mhz >= f_op_mhz:
        return 0.0
    sin_th_crit = math.sqrt(1.0 - (fp_mhz / f_op_mhz) ** 2)
    s = sin_th_crit * (R_E + h_km) / R_E
    if s > 1.0:
        return None  # not achievable even at the horizon
    # triangle: Earth centre C, station S, reflection point T (law of sines)
    angle_at_S = math.pi - math.asin(s)            # obtuse branch (ray goes up)
    gamma = math.pi - angle_at_S - math.asin(sin_th_crit)  # half-hop central angle
    return 2.0 * gamma * R_E


def muf_mhz(fp_mhz, d_km, h_km):
    """Maximum usable frequency for this hop geometry."""
    return fp_mhz * sec_theta(d_km, h_km)


def sec_max(h_km):
    """Secant of the incidence angle at grazing (0° elevation) — the largest
    obliquity geometry, where the secant law gives the highest usable frequency."""
    return 1.0 / math.sqrt(1.0 - (R_E / (R_E + h_km)) ** 2)


def muf_max_mhz(fp_mhz, h_km):
    """
    Highest operating frequency a reflection patch can ever support, reached at
    the grazing (maximum-range) geometry: fp * sec(theta_grazing). A patch is
    "usable" for an operating frequency f iff muf_max >= f — algebraically the
    same test as the original research code (test.py).
    """
    return fp_mhz * sec_max(h_km)


# ── 3-D bounce geometry (reflection off a specific patch, per input_latlon.py) ──

def latlon_to_ecef(lat, lon, alt_km=0.0):
    R = R_E + alt_km
    la, lo = math.radians(lat), math.radians(lon)
    return (R * math.cos(la) * math.cos(lo),
            R * math.cos(la) * math.sin(lo),
            R * math.sin(la))


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    return math.sqrt(_dot(a, a))


def bounce_geometry(lat_a, lon_a, alt_a, lat_b, lon_b, alt_b, lat_p, lon_p, h_p):
    """
    Geometry of a signal A -> patch P -> B, with P a real reflection point at
    height h_p (not the great-circle midpoint). Mirrors input_latlon.py:

      scatter angle at P (between the two rays), the secant-law factor
      1/cos(scatter/2), and the elevation of P above each station's horizon.

    Returns a dict, or None if degenerate. el_a / el_b < 0 means P is below
    that station's horizon (not usable).
    """
    A = latlon_to_ecef(lat_a, lon_a, alt_a)
    B = latlon_to_ecef(lat_b, lon_b, alt_b)
    P = latlon_to_ecef(lat_p, lon_p, h_p)
    vA = (P[0] - A[0], P[1] - A[1], P[2] - A[2])
    vB = (P[0] - B[0], P[1] - B[1], P[2] - B[2])
    nA, nB = _norm(vA), _norm(vB)
    if nA < 1e-9 or nB < 1e-9:
        return None
    cos_scatter = max(-1.0, min(1.0, _dot(vA, vB) / (nA * nB)))
    scatter = math.acos(cos_scatter)
    # elevation = angle of the ray above the local horizon at each station
    naA, naB = _norm(A), _norm(B)
    el_a = math.degrees(math.acos(max(-1.0, min(1.0, _dot(vA, (-A[0], -A[1], -A[2])) / (nA * naA))))) - 90.0
    el_b = math.degrees(math.acos(max(-1.0, min(1.0, _dot(vB, (-B[0], -B[1], -B[2])) / (nB * naB))))) - 90.0
    return {
        "scatter_deg": math.degrees(scatter),
        "half_sec": 1.0 / max(math.cos(scatter / 2.0), 1e-6),
        "el_a": el_a,
        "el_b": el_b,
    }


def ring_coords(lat, lon, radius_km, n=72):
    """Closed geodesic circle as [lon, lat] list, antimeridian-unwrapped."""
    pts = []
    prev_lon = None
    for i in range(n + 1):
        la, lo = destination_point(lat, lon, (i % n) * 360.0 / n, radius_km)
        if prev_lon is not None:
            while lo - prev_lon > 180:
                lo -= 360
            while lo - prev_lon < -180:
                lo += 360
        prev_lon = lo
        pts.append([round(lo, 4), round(la, 4)])
    return pts
