"""
what to do: 
1. input lat lon
2. input target lat lon
3. find mbg points that are abouve horizon from both places (ts probably the hardest lmao)
4. calculate alt az and max freq for each point
5. sort by max freq
"""
import numpy as np
import pandas as pd
import sys


def latlon_to_cartesian(lat, lon, alt=0):
    R = 6371 + alt
    lat_rad = np.radians(lat)
    lon_rad = np.radians(lon)
    x = R * np.cos(lat_rad) * np.cos(lon_rad)
    y = R * np.cos(lat_rad) * np.sin(lon_rad)
    z = R * np.sin(lat_rad)
    return np.array([x, y, z])

def sinesphere(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in kilometers
    lat1_rad = np.radians(lat1)
    lon1_rad = np.radians(lon1)
    lat2_rad = np.radians(lat2)
    lon2_rad = np.radians(lon2)
    distance = np.arccos(np.sin(lat1_rad) * np.sin(lat2_rad) + np.cos(lat1_rad) * np.cos(lat2_rad) * np.cos(lon1_rad - lon2_rad))
    return np.degrees(distance)

def AZ(lat1, lon1, lat2, lon2, dist):
    lat1_rad = np.radians(lat1)
    lon1_rad = np.radians(lon1)
    lat2_rad = np.radians(lat2)
    lon2_rad = np.radians(lon2)
    dist_rad = np.radians(dist)
    dellon = lon2_rad - lon1_rad
    AZ_val = np.arctan2(np.sin(dellon) * np.cos(lat2_rad) / np.sin(dist_rad), (np.sin(lat2_rad) - np.sin(lat1_rad) * np.cos(dist_rad)) / (np.sin(dist_rad) * np.cos(lat1_rad)))
    return np.degrees(AZ_val) % 360


def MBG_angle(lat1, lon1, alt1, lat2, lon2, alt2, lat_mbg, lon_mbg, alt_mbg, plasma_freq):
    vec1 = latlon_to_cartesian(lat1, lon1, alt1)
    vec2 = latlon_to_cartesian(lat2, lon2, alt2)
    vec_mbg = latlon_to_cartesian(lat_mbg, lon_mbg, alt_mbg)
    
    vec1_mbg = vec_mbg - vec1
    vec2_mbg = vec_mbg - vec2
    
    angle = np.arccos(
        np.dot(vec1_mbg, vec2_mbg) /
        (np.linalg.norm(vec1_mbg) * np.linalg.norm(vec2_mbg))
    )

    # Calculate maximum frequency
    max_freq = plasma_freq / np.cos(angle / 2)
    return max_freq

def MBG_altaz(lat1, lon1, alt1, lat2, lon2, alt2, lat_mbg, lon_mbg, alt_mbg):
    vec1 = latlon_to_cartesian(lat1, lon1, alt1)
    vec2 = latlon_to_cartesian(lat2, lon2, alt2)
    vec_mbg = latlon_to_cartesian(lat_mbg, lon_mbg, alt_mbg)
    
    vec1_mbg = vec_mbg - vec1
    vec2_mbg = vec_mbg - vec2
    
    angle1 = np.arccos(
        np.dot(vec1_mbg, -vec1) /
        (np.linalg.norm(vec1_mbg) * np.linalg.norm(vec1))
    )
    
    angle2 = np.arccos(
        np.dot(vec2_mbg, -vec2) /
        (np.linalg.norm(vec2_mbg) * np.linalg.norm(vec2))
    )

    alt1 = np.degrees(angle1) - 90
    alt2 = np.degrees(angle2) - 90

    AZ1 = AZ(lat1, lon1, lat_mbg, lon_mbg, sinesphere(lat1, lon1, lat_mbg, lon_mbg))
    AZ2 = AZ(lat2, lon2, lat_mbg, lon_mbg, sinesphere(lat2, lon2, lat_mbg, lon_mbg))

    return alt1, alt2, AZ1, AZ2






#place A (sender)
lat_a = -8.69
lon_a = 115.23
alt_a = 0.02

#place B (receiver)
lat_b = -17.16
lon_b = 123.71
alt_b = 0.1 #km
print(f"Place A: lat={lat_a}, lon={lon_a}, alt={alt_a} km")
print(f"Place B: lat={lat_b}, lon={lon_b}, alt={alt_b} km")

#assume max alt of mbg points 120 km
R_earth = 6371 #km

R_A = np.arccos(R_earth / (R_earth + alt_a)) + np.arccos(R_earth / (R_earth + 120))
R_B = np.arccos(R_earth / (R_earth + alt_b)) + np.arccos(R_earth / (R_earth + 120))


dist_a_b = sinesphere(lat_a, lon_a, lat_b, lon_b)
if np.radians(dist_a_b) > R_A + R_B:
    print("No common MBG points above horizon for both places.")
    sys.exit()


# find all mbg points and sort them by max freq (kali)
df_mbg_points = pd.read_csv("profiles_with_fp_gt_5.2MHz.csv")
#print(df_mbg_points)

#distance from place A and B to each mbg point
df_mbg_points['Distance_A'] = df_mbg_points.apply(lambda row: sinesphere(lat_a, lon_a, row['Latitude'], row['Longitude']), axis=1)
df_mbg_points['Distance_B'] = df_mbg_points.apply(lambda row: sinesphere(lat_b, lon_b, row['Latitude'], row['Longitude']), axis=1)

#print(df_mbg_points[['Latitude', 'Longitude', 'Distance_A', 'Distance_B']])

#filter mbg points that are above horizon for both places
df_mbg_points['Above_Horizon_A'] = df_mbg_points['Distance_A'].apply(lambda d: np.radians(d) <= R_A)
df_mbg_points['Above_Horizon_B'] = df_mbg_points['Distance_B'].apply(lambda d: np.radians(d) <= R_B)
df_common_mbg = df_mbg_points[df_mbg_points['Above_Horizon_A'] & df_mbg_points['Above_Horizon_B']]

if df_common_mbg.empty:
    print("No common MBG points above horizon for both places.")
    sys.exit()

df_common_mbg['Max_Frequency'] = df_common_mbg.apply(lambda row: MBG_angle(lat_a, lon_a, alt_a, lat_b, lon_b, alt_b, row['Latitude'], row['Longitude'], row['Optimal Reflection Altitude (km)'], row['Plasma Frequency (MHz)']), axis=1)

df_common_mbg['Alt_A'], df_common_mbg['Alt_B'], df_common_mbg['AZ_A'], df_common_mbg['AZ_B'] = zip(*df_common_mbg.apply(lambda row: MBG_altaz(lat_a, lon_a, alt_a, lat_b, lon_b, alt_b, row['Latitude'], row['Longitude'], row['Optimal Reflection Altitude (km)']), axis=1))


#sort by max freq
df_common_mbg = df_common_mbg.sort_values(by='Max_Frequency', ascending=False)

print(df_common_mbg[['Time (UTC)','Latitude', 'Longitude','Optimal Reflection Altitude (km)','Plasma Frequency (MHz)', 'Max_Frequency','Distance_A', 'Distance_B', 'Alt_A', 'AZ_A', 'Alt_B', 'AZ_B']].sort_values(by='Max_Frequency', ascending=False))

