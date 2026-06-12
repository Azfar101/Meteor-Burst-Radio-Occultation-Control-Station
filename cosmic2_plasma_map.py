"""
COSMIC-2 ionPrf — Interactive Plasma Frequency Map
===================================================
Reads all *.0001_nc files from a folder, extracts the E-region plasma
frequency at the peak gradient altitude (80–120 km), and plots each
profile's perigee location on an interactive world map.

Features
--------
- World map coloured by plasma frequency (el/cm³ → MHz)
- Time slider (step through each observation chronologically)
- Hover tooltip: lat, lon, altitude, plasma freq, time, filename
- Animated "Play" button to auto-advance through time
- Saved as a standalone HTML — no server needed

Usage
-----
    python cosmic2_plasma_map.py                    # reads from ./asd/
    python cosmic2_plasma_map.py --folder my_data   # custom folder
    python cosmic2_plasma_map.py --folder asd --output map.html
"""

import argparse
import datetime
import warnings
from pathlib import Path

import netCDF4 as nc
import numpy as np
import plotly.graph_objects as go

warnings.filterwarnings("ignore")

# ── CLI ──────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="COSMIC-2 plasma frequency map")
parser.add_argument("--folder", default="asd",
                    help="Folder containing *.0001_nc files (default: asd)")
parser.add_argument("--output", default="cosmic2_plasma_map.html",
                    help="Output HTML file (default: cosmic2_plasma_map.html)")
parser.add_argument("--alt_min", type=float, default=80.0,
                    help="Lower altitude limit for E-region search in km (default: 80)")
parser.add_argument("--alt_max", type=float, default=120.0,
                    help="Upper altitude limit for E-region search in km (default: 120)")
args = parser.parse_args()

folder_path = Path(args.folder)
output_file = Path(args.output)

# ── Read all files ────────────────────────────────────────────────────────────

records = []  # list of dicts

files = sorted(folder_path.glob("*.0001_nc"))
if not files:
    raise FileNotFoundError(f"No *.0001_nc files found in '{folder_path}'")

print(f"Found {len(files)} file(s) in '{folder_path}'. Processing…\n")

for file in files:
    try:
        ds = nc.Dataset(str(file), "r")

        lat    = ds.variables["GEO_lat"][:]
        lon    = ds.variables["GEO_lon"][:]
        alt    = ds.variables["MSL_alt"][:]
        ed     = ds.variables["ELEC_dens"][:]

        ed = np.where(ed < 0, np.nan, ed)

        # Perigee = minimum altitude point (representative location)
        perigee_idx = int(np.argmin(alt))
        perigee_lat = float(lat[perigee_idx])
        perigee_lon = float(lon[perigee_idx])
        perigee_alt = float(alt[perigee_idx])

        # E-region plasma frequency (80–120 km)
        mask = (alt >= args.alt_min) & (alt <= args.alt_max)
        if np.sum(mask) < 2 or np.all(np.isnan(ed[mask])):
            print(f"  SKIP {file.name}: no valid E-region data")
            ds.close()
            continue

        dNe_dh   = np.gradient(ed[mask], alt[mask])
        peak_idx = int(np.argmax(np.abs(dNe_dh)))
        h_peak   = float(alt[mask][peak_idx])
        Ne_peak  = float(ed[mask][peak_idx])

        fp_hz  = 8.98 * np.sqrt(Ne_peak * 1e6)
        fp_MHz = fp_hz / 1e6

        if np.isnan(fp_MHz):
            print(f"  SKIP {file.name}: NaN plasma frequency")
            ds.close()
            continue

        # NmF2 peak info (from global attributes if available)
        nmF2     = float(getattr(ds, "edmax",    np.nan))
        hmF2     = float(getattr(ds, "edmaxalt", np.nan))
        critfreq = float(getattr(ds, "critfreq", np.nan))
        sat_id   = getattr(ds, "occulting_sat_id", "?")
        setting  = getattr(ds, "setting", -1)

        dt = datetime.datetime(
            int(getattr(ds, "year",   2000)),
            int(getattr(ds, "month",  1)),
            int(getattr(ds, "day",    1)),
            int(getattr(ds, "hour",   0)),
            int(getattr(ds, "minute", 0)),
            int(getattr(ds, "second", 0)),
        )

        records.append({
            "file":        file.name,
            "time":        dt,
            "time_str":    dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "lat":         perigee_lat,
            "lon":         perigee_lon,
            "perigee_alt": perigee_alt,
            "h_peak":      h_peak,
            "fp_MHz":      fp_MHz,
            "Ne_peak":     Ne_peak,
            "nmF2":        nmF2,
            "hmF2":        hmF2,
            "critfreq":    critfreq,
            "sat_id":      sat_id,
            "occ_type":    "Setting" if setting == 1 else "Rising",
        })

        print(f"  OK  {file.name}  |  "
              f"lat={perigee_lat:+.2f}° lon={perigee_lon:+.2f}°  |  "
              f"fp={fp_MHz:.3f} MHz  |  {dt.strftime('%Y-%m-%d %H:%M')}")

        ds.close()

    except Exception as e:
        print(f"  ERROR {file.name}: {e}")

if not records:
    raise ValueError("No valid profiles were extracted. Check your data folder.")

records.sort(key=lambda r: r["time"])
print(f"\n✓ {len(records)} valid profiles loaded.\n")

# ── Build Plotly figure with time slider ─────────────────────────────────────

fp_vals = np.array([r["fp_MHz"] for r in records])
fp_min, fp_max = fp_vals.min(), fp_vals.max()

# Unique time steps for the slider
time_steps = sorted({r["time_str"] for r in records})

def make_trace(subset, visible=True):
    """Scatter geo trace for a list of records."""
    return go.Scattergeo(
        lat=[r["lat"]         for r in subset],
        lon=[r["lon"]         for r in subset],
        mode="markers",
        visible=visible,
        marker=dict(
            size=10,
            color=[r["fp_MHz"] for r in subset],
            colorscale="Plasma",
            cmin=fp_min,
            cmax=fp_max,
            colorbar=dict(
                title=dict(text="Plasma Freq (MHz)", side="right"),
                thickness=16,
                len=0.75,
            ),
            line=dict(width=0.8, color="white"),
            opacity=0.9,
        ),
        customdata=[
            [r["lat"], r["lon"], r["perigee_alt"],
             r["fp_MHz"], r["h_peak"], r["Ne_peak"],
             r["nmF2"], r["hmF2"], r["critfreq"],
             r["sat_id"], r["occ_type"], r["time_str"], r["file"]]
            for r in subset
        ],
        hovertemplate=(
            "<b>COSMIC-2 E%{customdata[9]}</b> — %{customdata[10]}<br>"
            "<b>Time:</b> %{customdata[11]}<br>"
            "<b>Perigee:</b> %{customdata[0]:.3f}°N, %{customdata[1]:.3f}°E  "
            "@ %{customdata[2]:.1f} km<br>"
            "<hr>"
            "<b>E-region plasma freq:</b> %{customdata[3]:.3f} MHz<br>"
            "<b>  at altitude:</b> %{customdata[4]:.1f} km<br>"
            "<b>  Ne there:</b> %{customdata[5]:.2e} el/cm³<br>"
            "<hr>"
            "<b>NmF2:</b> %{customdata[6]:.0f} el/cm³  "
            "@ hmF2=%{customdata[7]:.1f} km<br>"
            "<b>foF2:</b> %{customdata[8]:.3f} MHz<br>"
            "<b>File:</b> %{customdata[12]}<extra></extra>"
        ),
        name="",
    )

# One frame per unique time step
frames = []
slider_steps = []

for ts in time_steps:
    subset = [r for r in records if r["time_str"] == ts]
    frames.append(go.Frame(data=[make_trace(subset)], name=ts))
    slider_steps.append(dict(
        args=[[ts], {"frame": {"duration": 400, "redraw": True},
                     "mode": "immediate",
                     "transition": {"duration": 200}}],
        label=ts[:16],   # "YYYY-MM-DD HH:MM"
        method="animate",
    ))

# Initial trace = first time step
first_subset = [r for r in records if r["time_str"] == time_steps[0]]

fig = go.Figure(
    data=[make_trace(first_subset)],
    frames=frames,
    layout=go.Layout(
        title=dict(
            text="COSMIC-2 E-Region Plasma Frequency — Perigee Locations",
            font=dict(size=17, color="white"),
            x=0.5,
        ),
        paper_bgcolor="#0d1b2a",
        plot_bgcolor="#0d1b2a",
        geo=dict(
            projection_type="natural earth",
            showland=True,
            landcolor="#1a3a52",
            showocean=True,
            oceancolor="#0a1628",
            showcountries=True,
            countrycolor="#2a4a6a",
            showcoastlines=True,
            coastlinecolor="#3a6a8a",
            showframe=False,
            bgcolor="#0d1b2a",
            lataxis=dict(showgrid=True, gridcolor="#1e3a5f"),
            lonaxis=dict(showgrid=True, gridcolor="#1e3a5f"),
        ),
        updatemenus=[dict(
            type="buttons",
            showactive=False,
            y=0.02,
            x=0.5,
            xanchor="center",
            yanchor="bottom",
            bgcolor="#1e3a5f",
            font=dict(color="white"),
            buttons=[
                dict(label="▶  Play",
                     method="animate",
                     args=[None, {"frame": {"duration": 600, "redraw": True},
                                  "fromcurrent": True,
                                  "transition": {"duration": 300}}]),
                dict(label="⏸  Pause",
                     method="animate",
                     args=[[None], {"frame": {"duration": 0, "redraw": False},
                                    "mode": "immediate",
                                    "transition": {"duration": 0}}]),
            ],
        )],
        sliders=[dict(
            active=0,
            steps=slider_steps,
            currentvalue=dict(
                prefix="Time: ",
                font=dict(size=13, color="white"),
                visible=True,
                xanchor="center",
            ),
            pad=dict(t=55, b=10),
            bgcolor="#1e3a5f",
            bordercolor="#334155",
            font=dict(color="white", size=9),
            tickcolor="white",
            len=0.85,
            x=0.075,
        )],
        margin=dict(l=0, r=0, t=50, b=120),
        height=680,
        font=dict(color="white"),
        hoverlabel=dict(
            bgcolor="#1e3a5f",
            bordercolor="#3a6a8a",
            font=dict(color="white", size=12),
        ),
    ),
)

# ── Save ─────────────────────────────────────────────────────────────────────

fig.write_html(
    str(output_file),
    include_plotlyjs="cdn",
    full_html=True,
    config={"scrollZoom": True, "displayModeBar": True,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"]},
)

print(f"✓ Map saved → {output_file.resolve()}")
print("  Open it in any browser — no server required.")