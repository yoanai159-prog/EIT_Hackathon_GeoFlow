"""Sentinel-2 -> NDWI -> water polygon -> data/satellite_observations.csv

Run:  pip install -r requirements-satellite.txt && python satellite_update.py
Needs internet (reads only a small window of the public Sentinel-2 L2A scenes).
The app itself only reads the files this script writes, so the demo works offline.
"""
import os
os.environ.pop("PROJ_LIB", None)
os.environ.pop("PROJ_DATA", None)

import csv
import json
from pathlib import Path

import numpy as np
import rasterio
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.features import shapes
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds
from shapely.geometry import shape
import geopandas as gpd
from skimage.filters import threshold_otsu

from core.satellite import area_pct_of_full

# ================= SETTINGS =================
RESERVOIR = "Ticha"
BBOX = [26.65, 42.98, 26.95, 43.12]          # [lon_min, lat_min, lon_max, lat_max] - check on a map
PERIODS = {
    "full":    ("2026-04-15", "2026-05-31"),  # full-pool reference period
    "current": ("2026-09-15", "2026-10-24"),  # period to assess
}
MAX_CLOUD = 30
# ============================================

DATA = Path(__file__).parent / "data"
cat = Client.open("https://earth-search.aws.element84.com/v1")  # public mirror of Copernicus Sentinel-2 L2A


def read_window(href, out_shape=None, ref_win=None):
    with rasterio.open(href) as src:
        if ref_win is None:
            b = transform_bounds("EPSG:4326", src.crs, *BBOX)
            ref_win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        arr = src.read(1, window=ref_win, out_shape=out_shape, resampling=Resampling.nearest)
        return arr.astype("float32"), src.window_transform(ref_win), src.crs, ref_win


def analyze(role, start, end):
    items = list(cat.search(collections=["sentinel-2-l2a"], bbox=BBOX, datetime=f"{start}/{end}",
                            query={"eo:cloud_cover": {"lt": MAX_CLOUD}}).items())
    if not items:
        raise SystemExit(f"[{role}] no scene between {start} and {end}: widen the period or raise MAX_CLOUD")
    item = min(items, key=lambda i: i.properties["eo:cloud_cover"])

    green, tr, crs, win = read_window(item.assets["green"].href)                 # B03
    nir, _, _, _ = read_window(item.assets["nir"].href, ref_win=win)             # B08
    scl, _, _, _ = read_window(item.assets["scl"].href, out_shape=green.shape)   # scene classification

    ndwi = (green - nir) / (green + nir + 1e-6)
    valid = ~np.isin(scl, [0, 1, 3, 8, 9, 10, 11])          # drop no-data, shadows, clouds, cirrus, snow
    water = (ndwi > threshold_otsu(ndwi[valid])) & valid

    polys = [shape(g) for g, v in shapes(water.astype("uint8"), mask=water, transform=tr) if v == 1]
    gdf = gpd.GeoDataFrame(geometry=polys, crs=crs)
    gdf["area_km2"] = gdf.area / 1e6                         # CRS is UTM, so metres
    lake = gdf.sort_values("area_km2", ascending=False).head(1).to_crs(4326)
    (DATA / f"satellite_water_{role}.geojson").write_text(lake.to_json())

    c = lake.geometry.iloc[0].centroid
    return {
        "reservoir": RESERVOIR, "role": role, "obs_date": str(item.datetime.date()), "scene": item.id,
        "cloud_cover_pct": round(item.properties["eo:cloud_cover"], 1),
        "water_area_km2": round(float(gdf.sort_values("area_km2", ascending=False).area_km2.iloc[0]), 3),
        "centroid_lon": round(c.x, 5), "centroid_lat": round(c.y, 5),
    }


rows = [analyze(role, s, e) for role, (s, e) in PERIODS.items()]
full = next(r for r in rows if r["role"] == "full")["water_area_km2"]
for r in rows:
    r["area_pct_of_full"] = round(area_pct_of_full(r["water_area_km2"], full), 1)
    print(r)

with open(DATA / "satellite_observations.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print("Wrote data/satellite_observations.csv and two GeoJSON files.")
