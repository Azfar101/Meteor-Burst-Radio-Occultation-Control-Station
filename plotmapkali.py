import csv
import matplotlib.pyplot as plt


with open("profiles_with_fp_gt_5.2MHz.csv", 'r') as f:
    reader = csv.reader(f)
    header = next(reader)  # Skip header row
    data = list(reader)

plasma_freqs = [float(row[4]) for row in data]
print(plasma_freqs)
latitudes = [float(row[1]) for row in data]
longitudes = [float(row[2]) for row in data]
altitudes = [float(row[3]) for row in data]

fig, ax = plt.subplots(figsize=(8, 5))
scatter = ax.scatter(longitudes, latitudes, c=plasma_freqs, cmap='viridis', s=100, edgecolors='k')
ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")
ax.set_title("Locations of Profiles with Plasma Frequency > 5.2 MHz")
plt.show()