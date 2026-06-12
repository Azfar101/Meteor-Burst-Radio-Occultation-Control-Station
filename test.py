import netCDF4 as nc
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import csv
import datetime
from meteor_spike_classifier import MeteorSpikeClassifier
# Open the file

folder_path = Path('asd')
output_folder = Path('csv')
output_folder.mkdir(parents=True, exist_ok=True)
plasma_freqs = []
time = []
all_plasma_freqs = []
count_52 = 0
total_files = 0
all_location_52 = []
no_nan = 0
for file in folder_path.glob('*.0001_nc'):
    print("--------------------------------------------------------------")
    print(f"Processing file: {file.name}")
    total_files += 1
    ds = nc.Dataset(str(file), 'r')

    # --- Location of the profile ---
    lat = ds.variables['GEO_lat'][:]   # Geographic latitude (degrees)
    lon = ds.variables['GEO_lon'][:]   # Geographic longitude (degrees)
    msl_alt = ds.variables['MSL_alt'][:]  # Altitude above mean sea level (km)


    # --- Electron density profile ---
    ed = ds.variables['ELEC_dens'][:]  # Electron density (electrons/m³)
    ed[ed < 0] = np.nan  # Replace negative values with NaN
    #ed[ed > 1e12] = np.nan  # Replace unphysically high values with NaN
    ed_idk = []


    #print(f"Profile Location:")
    #print(f"  Latitude : {lat[0]:.4f}°")
    #print(f"  Longitude: {lon[0]:.4f}°")
    #print(f"  Altitude range: {msl_alt.min():.1f} – {msl_alt.max():.1f} km")
    #print(f"  Peak electron density: {ed.max():.2e} e/m³")


    # Find index of minimum altitude (perigee)
    perigee_idx = np.argmin(msl_alt)

    perigee_lat = lat[perigee_idx]
    perigee_lon = lon[perigee_idx]
    perigee_alt = msl_alt[perigee_idx]
    dt = datetime.datetime(getattr(ds, 'year', 0), getattr(ds, 'month', 0), getattr(ds, 'day', 0), getattr(ds, 'hour', 0), getattr(ds, 'minute', 0), int(getattr(ds, 'second', 0)))
    
    #print(f"Perigee (representative location):")
    #print(f"  Lat: {perigee_lat:.4f}°, Lon: {perigee_lon:.4f}°, Alt: {perigee_alt:.1f} km")

    # List all variables
    #for var in ds.variables:
        #v = ds.variables[var]
        #print(f"{var:30s} shape={v.shape}  units={getattr(v, 'units', 'N/A')}")

    # Global attributes (metadata)
    #print("\n--- Global Attributes ---")
    #for attr in ds.ncattrs():
        #print(f"{attr}: {getattr(ds, attr)}")
    csv_path = output_folder / f"{file.stem}.csv"
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Altitude (km)', 'Electron Density (e/cm³)'])
        for alt, dens in zip(msl_alt, ed):
            writer.writerow([alt, dens])


    alt  = msl_alt[:]  # Altitude (km)
    Ne   = ed[:]     # Electron density (electrons/m³)
    



    # Find the E-region peak gradient (meteor ablation zone)
    mask = (alt >= 80) & (alt <= 120)
    if np.sum(mask) < 2 or np.all(np.isnan(Ne[mask])):
        print("No valid altitude range for gradient calculation. Skipping this profile.")
        continue
    else:
        dNe_dh = np.gradient(Ne[mask], alt[mask])
        h_peak = alt[mask][np.argmax(np.abs(dNe_dh))]

        print(Ne[mask][np.argmax(np.abs(dNe_dh))])
        # Plasma frequency at h_peak
        fp_hz = 8.98 * np.sqrt(Ne[mask][np.argmax(np.abs(dNe_dh))] * 1e6)
        fp_MHz = fp_hz / 1e6
        if np.isnan(fp_MHz):
            print("Plasma frequency calculation resulted in NaN. Skipping this profile.")
            continue
        print(fp_hz)
        no_nan += 1
        print(f"Optimal reflection altitude: {h_peak:.1f} km")
        print(f"Plasma frequency there: {fp_MHz:.2f} MHz")
        if fp_MHz > np.sqrt(1-(6378/(6378+h_peak))**2)*30:
            count_52 += 1
            classifier = MeteorSpikeClassifier()
            # Create classifier and classify
            verdict, details = classifier.classify(alt, Ne)
            max_theta = np.rad2deg(np.arccos(6378/(6378+h_peak)))
            sin_theta_crit = np.sqrt(1-fp_MHz**2/30**2)
            xx = np.pi - np.arcsin(sin_theta_crit*(6378+h_peak)/6378)
            min_theta = 180 - np.rad2deg(xx + np.arcsin(sin_theta_crit))
            all_location_52.append((dt, perigee_lat, perigee_lon, h_peak, fp_MHz, max_theta, min_theta, verdict, details['reality_score'],details['confidence']))
            if verdict == "ACCEPT":
                aewkfbjruwernaads=1
                fig, axes = plt.subplots(figsize=(8, 5))
                axes.plot(Ne,alt, label='Electron Density Profile')
                axes.set_xlabel("Electron Density (e/cm³)")
                axes.set_ylabel("Altitude (km)")
                axes.set_title(f"Profile with Suspected Meteor Trail Spike - {file.stem}")
                axes.grid(True)

        plasma_freqs.append(fp_MHz)

    # Extract time from global attributes
    print(dt)
    time.append(dt)
    all_plasma_freqs.append((dt, fp_MHz))

    ds.close()

print("\nSummary of plasma frequencies at optimal reflection altitudes:")

for i, freq in enumerate(plasma_freqs):
    print(f"  File {i+1}: {freq:.2f} MHz")


with open("profiles_with_fp_gt_5.2MHz.csv", 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['Time (UTC)', 'Latitude', 'Longitude', 'Optimal Reflection Altitude (km)', 'Plasma Frequency (MHz)', 'Outer radius (°)', 'Inner radius (°)', 'Verdict', 'Reality Score', 'Confidence'])
    for loc in all_location_52:
        writer.writerow(loc)



print(f"\nNumber of profiles with sufficient plasma frequency (calculated using height): {len(plasma_freqs)} out of {total_files}")
print(f"\nNumber of profiles with valid plasma frequency calculations: {no_nan} out of {total_files}")
print(f"\nNumber of profiles with sufficient plasma frequency (calculated using height also): {count_52} out of {total_files}")

all_plasma_freqs.sort(key=lambda item: item[0])

fig, ax = plt.subplots(figsize=(8, 5))
ax.plot([item[0] for item in all_plasma_freqs], [item[1] for item in all_plasma_freqs], 'o-')
ax.set_xlabel("Time (UTC)")
ax.set_ylabel("Plasma Frequency at Optimal Reflection Altitude (MHz)")
ax.set_title("Plasma Frequency at Optimal Reflection Altitude Over Time")
ax.grid(True)

fig, ax = plt.subplots(figsize=(8, 5))
ax.plot([item[0] for item in all_plasma_freqs if item[1] > 5.2], [item[1] for item in all_plasma_freqs if item[1] > 5.2], 'o-')
ax.set_xlabel("Time (UTC)")
ax.set_ylabel("Plasma Frequency at Optimal Reflection Altitude (MHz) > 5.2 MHz")
ax.set_title("Plasma Frequency at Optimal Reflection Altitude Over Time")
ax.grid(True)


plt.show()


"""fig, axes = plt.subplots(1, 2, figsize=(10, 6))

# Electron density profile
axes[0].plot(ed, msl_alt)
axes[0].set_xlabel("Electron Density (e/m³)")
axes[0].set_ylabel("Altitude (km)")
axes[0].set_title("Electron Density Profile")
axes[0].grid(True)

# Lat/Lon track of the occultation
axes[1].plot(lon, lat, 'b.-')
axes[1].plot(perigee_lon, perigee_lat, 'r*', markersize=12, label='Perigee')
axes[1].set_xlabel("Longitude (°)")
axes[1].set_ylabel("Latitude (°)")
axes[1].set_title("Occultation Ray Path Location")
axes[1].legend()
axes[1].grid(True)

plt.tight_layout()
plt.savefig("cosmic2_profile.png", dpi=150)
plt.show()"""

