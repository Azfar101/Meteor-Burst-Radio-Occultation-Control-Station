import pandas as pd
import folium
import math

# Load data
df = pd.read_csv('profiles_with_fp_gt_5.2MHz.csv')

# Color mapping for Verdict
verdict_colors = {
}
default_color = '#3498db'

def get_color(verdict):
    for k, v in verdict_colors.items():
        if k.lower() in str(verdict).lower():
            return v
    return default_color

# Create map centered on mean lat/lon
center_lat = df['Latitude'].mean()
center_lon = df['Longitude'].mean()
m = folium.Map(location=[center_lat, center_lon], zoom_start=3, tiles='CartoDB positron')

# Degrees to meters conversion (approximate)
DEG_TO_M = 111_320  # meters per degree latitude

def add_donut(map_obj, lat, lon, inner_deg, outer_deg, color, tooltip_html):
    """Draw a donut by layering an outer circle with an inner white circle on top."""
    inner_m = inner_deg * DEG_TO_M
    outer_m = outer_deg * DEG_TO_M

    # Outer circle (filled)
    folium.Circle(
        location=[lat, lon],
        radius=outer_m,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.45,
        weight=1.5,
        opacity=0.9,
        tooltip=folium.Tooltip(tooltip_html, max_width=320),
    ).add_to(map_obj)

    # Inner circle (white cutout to create donut effect)
    folium.Circle(
        location=[lat, lon],
        radius=inner_m,
        color='white',
        fill=True,
        fill_color='white',
        fill_opacity=1.0,
        weight=1,
        opacity=0.0,
    ).add_to(map_obj)

    # Center dot for easier clicking
    folium.CircleMarker(
        location=[lat, lon],
        radius=4,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=1.0,
        weight=1,
        tooltip=folium.Tooltip(tooltip_html, max_width=320),
    ).add_to(map_obj)

for _, row in df.iterrows():
    color = get_color(row['Verdict'])

    # Build tooltip with all columns
    rows_html = ''.join(
        f'<tr><td style="padding:2px 8px 2px 0;color:#888;font-size:12px;">{col}</td>'
        f'<td style="padding:2px 0;font-size:12px;font-weight:500;">{row[col]}</td></tr>'
        for col in df.columns
    )
    tooltip_html = f"""
    <div style="font-family:Arial,sans-serif;min-width:220px;">
        <b style="font-size:13px;color:{color};">&#9679; {row['Verdict']}</b>
        <table style="border-collapse:collapse;margin-top:6px;">
            {rows_html}
        </table>
    </div>
    """

    add_donut(
        m,
        lat=row['Latitude'],
        lon=row['Longitude'],
        inner_deg=row['Inner radius (°)'],
        outer_deg=row['Outer radius (°)'],
        color=color,
        tooltip_html=tooltip_html,
    )

# Legend
legend_html = """
<div style="position:fixed;bottom:30px;left:30px;z-index:9999;background:white;
     padding:12px 16px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.2);
     font-family:Arial,sans-serif;font-size:13px;">
  <b style="display:block;margin-bottom:8px;">Verdict</b>
"""
for label, color in verdict_colors.items():
    legend_html += f'<div style="margin:3px 0;"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:{color};margin-right:6px;vertical-align:middle;"></span>{label}</div>'
legend_html += f'<div style="margin:3px 0;"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:{default_color};margin-right:6px;vertical-align:middle;"></span>Other</div>'
legend_html += "</div>"

m.get_root().html.add_child(folium.Element(legend_html))

# Title
title_html = """
<div style="position:fixed;top:15px;left:50%;transform:translateX(-50%);z-index:9999;
     background:white;padding:8px 20px;border-radius:8px;
     box-shadow:0 2px 8px rgba(0,0,0,0.2);font-family:Arial,sans-serif;">
  <b style="font-size:15px;">Suitable Plasma Frequency for MBC — Reflection Profiles (14 - 18 Apr 2026)</b>
</div>
"""
m.get_root().html.add_child(folium.Element(title_html))

output_path = 'donut_map.html'
m.save(output_path)
print(f"Map saved to {output_path}")
print(f"Plotted {len(df)} locations.")
