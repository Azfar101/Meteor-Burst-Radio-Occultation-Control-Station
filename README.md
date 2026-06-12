# MBC Ground Control System

A browser-based Ground Control System (GCS) for a **meteor burst communication
(MBC) network**, driven by **ion density from GNSS radio occultation**
(COSMIC-2 ionPrf). It turns the research pipeline in this repo (E-region
peak-gradient plasma frequency + meteor-spike classification) into an
interactive mission-control application: a live world map of stations,
3D antenna visualization, ionosphere overlays, and a full link/route
simulator that computes how each antenna must be pointed.

![mode](https://img.shields.io/badge/frontend-no--build%20ES%20modules-22d3ee)
![backend](https://img.shields.io/badge/backend-FastAPI-009688)

---

## Quick start

```bash
pip install fastapi uvicorn numpy netCDF4 python-multipart
python run.py
```

The browser opens at **http://127.0.0.1:8600**. Internet access is needed for
map tiles and the CDN libraries (MapLibre GL, Three.js, fonts).

---

## Features

### Operations mode
- **World map** (dark CARTO basemap) with the full station network.
  Hover a station for a quick condition card; click it for the full panel.
- **Station panel** — live simulated telemetry (TX power, PA temperature,
  SWR, SNR, noise floor, battery, queue, meteor bursts/hr) and a **3D view
  of the antenna** (stacked 5-element Yagi on a rotator) showing its actual
  azimuth/elevation attitude in real time. Drag to orbit the 3D view.
- **Ionosphere overlay** — E-region plasma frequency everywhere on Earth,
  blended from three tiers (highest priority first):
  1. **COSMIC-2** profiles imported by you, interpolated in space/time
     (Gaussian inverse-distance weighting, ±8 h window);
  2. **Live GIRO ionosondes** — real-time foE / sporadic-E (foEs) soundings
     fetched automatically from the open `prop.kc2g.com` API (no key needed);
     this is the default real-data source before any COSMIC-2 import.
     Ionosondes appear as cyan-ringed dots — click one for its full sounding;
  3. **foE model** — solar-zenith-angle Chapman model
     `foE = 0.9·((180+1.44·R12)·cos χ)^0.25 MHz` with a night floor, driven
     by the **live effective sunspot number** (also from KC2G) and falling
     back to the manual SSN setting when offline.
  Brighter cells = observed data dominates; each hop card reports
  COSMIC2 / IONOSONDE / BLENDED / MODEL.
- **Light & dark themes** — toggle with the ☀/☾ button in the top bar
  (basemap swaps too; the choice is remembered).
- **Coverage rings** — for any station, the ground annulus reachable via
  E-layer reflection at the current operating frequency (secant law),
  or the horizon-limited maximum for meteor-burst-only conditions.
- **Time bar** — scrub/play through the loaded COSMIC-2 time window (or
  ±12 h around now); the ionosphere, coverage and routes recompute live.

### Simulation mode
- **Place / drag / rename / remove stations** anywhere on the map.
- **Link tool** — click a source and a destination station. The planner:
  1. computes the great-circle hop and its midpoint reflection point;
  2. queries the ionosphere there for fp and reflection height h;
  3. applies the secant law `MUF = fp·sec θ` for the hop geometry;
  4. classifies the hop: **IONO** (continuous E-layer support),
     **METEOR** (meteor-burst with estimated duty cycle), or unreachable;
  5. if the direct hop fails, runs **Dijkstra over the constellation**
     (offline stations excluded, degraded penalised) to find a multi-hop
     relay route within the configured hop limit.
- Each hop card reports distance, **antenna azimuth/elevation for both
  ends**, reflection height, plasma frequency + data source, MUF, margin
  (dB), duty cycle, and throughput.
- **TRANSMIT** animates the packet along the route and slews every
  involved antenna (watch the 3D view and the az/el in hover cards).

### COSMIC-2 data import
`⬆ Import data` →
- **Folder on this PC** — point at a folder of `*_nc` ionPrf files
  (e.g. your `asd/` folder downloaded from
  https://data.cosmic.ucar.edu/gnss-ro/cosmic2/provisional/spaceWeather/level2/).
- **Upload files** — drag-and-drop individual files.

Every profile goes through the original research pipeline: E-region
(80–120 km) peak-gradient plasma frequency + `MeteorSpikeClassifier`
verdict. Profiles appear on the map as colored dots (white-ringed =
ACCEPT); clicking one shows its details and the **donut rings** — the
ground band where a station could use that reflection point.

`test_data/` contains three **synthetic** ionPrf files for demoing the
import flow without real data.

### Settings (⚙)
Operating frequency (15–60 MHz; the research default 30 MHz gives the
familiar 5.2 MHz grazing threshold), max relay hops, burst data rate,
sunspot number for the foE model, meteor-burst mode on/off, and a
network reset.

---

## Architecture

```
run.py                  one-command launcher (uvicorn + browser)
backend/
  app.py                FastAPI app: REST API + serves the frontend
  geometry.py           spherical geodesy + reflection geometry (secant law,
                        elevation/incidence angles, donut min/max ranges)
  ionosphere.py         three-tier blend: COSMIC-2 + live ionosondes + foE model
  livedata.py           open KC2G/GIRO API client (ionosondes, effective SSN)
  cosmic2_loader.py     ionPrf NetCDF ingestion (port of test.py pipeline)
  linkplan.py           hop physics, duty-cycle model, Dijkstra routing
  stations.py           station registry (persisted to backend/data/) +
                        deterministic live telemetry simulation
frontend/               no-build ES-module app (no Node.js required)
  js/map.js             MapLibre map, overlays, markers, route animation
  js/antenna3d.js       Three.js Yagi antenna viewer
  js/panels.js          station/route panels, settings, import dialogs
  js/timebar.js         time scrubber
  meteor_spike_classifier.py   original classifier (used by the backend)
```

API docs (auto-generated): http://127.0.0.1:8600/docs

## Legacy research scripts

The original analysis scripts still work standalone:
`test.py` (batch profile analysis → CSV), `cosmic2_plasma_map.py`
(Plotly time-slider map), `plot_donuts.py` (Folium donut map),
`plotmapkali.py` (scatter plot).
