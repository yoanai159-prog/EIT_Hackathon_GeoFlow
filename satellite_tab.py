"""Satellite section: real Sentinel-2 water surface of Ticha, checked against the MOEW bulletin of the same day."""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

import map_view
from core.satellite import MESSAGES, consistency

PREVIOUS_STYLE = {"type": "single", "style": {"fill": "#F59E0B", "fill_opacity": 0.0, "stroke": "#F59E0B", "weight": 2.5, "dash": "7,5"}}
CURRENT_STYLE = {"type": "single", "style": {"fill": "#0E8FA8", "fill_opacity": 0.45, "stroke": "#0A6C80", "weight": 2}}


def water_layers(data_dir: Path, obs: pd.DataFrame, visible: bool = True) -> list[dict]:
    """The two Sentinel-2 water polygons as map layers: the earlier extent (dashed) and the current one (filled)."""
    layers = []
    for role, style, label in (("full", PREVIOUS_STYLE, "Previous water extent"), ("current", CURRENT_STYLE, "Current water extent")):
        gj = json.loads((data_dir / f"satellite_water_{role}.geojson").read_text())
        row = obs.loc[role]
        for f in gj["features"]:
            f["properties"] = {"extent": label, "date": str(row.obs_date), "sentinel_2_scene": str(row.scene),
                               "cloud_cover_pct": float(row.cloud_cover_pct), "water_area_km2": float(row.water_area_km2),
                               "area_pct_of_reference": float(row.area_pct_of_full)}
        layers.append(map_view.make_layer(f"{label} ({row.obs_date}, Sentinel-2)", gj, style, visible=visible,
                                          popup_title="extent"))
    return layers


def render(data_dir: Path, daily: pd.DataFrame | None = None, monthly: pd.DataFrame | None = None):
    st.subheader("Satellite check: Sentinel-2 and the bulletin")
    csv_path = data_dir / "satellite_observations.csv"
    if not csv_path.exists():
        st.info("No satellite data yet. Run `python satellite_update.py` once (needs internet) and reload.")
        return
    obs = pd.read_csv(csv_path).set_index("role")
    full, cur = obs.loc["full"], obs.loc["current"]

    c1, c2, c3 = st.columns(3)
    c1.metric(f"Earlier water area ({full.obs_date})", f"{full.water_area_km2:.2f} km²")
    c2.metric(f"Current water area ({cur.obs_date})", f"{cur.water_area_km2:.2f} km²", f"{cur.water_area_km2 - full.water_area_km2:+.2f} km²")
    c3.metric("Current area as share of the earlier one", f"{cur.area_pct_of_full:.0f}%")

    map_view.render(water_layers(data_dir, obs), center=(float(cur.centroid_lat), float(cur.centroid_lon)), zoom=11,
                    height=470, base="osm")
    st.caption("Dashed amber: water surface on the earlier date. Teal: water surface now. Click a polygon for its attributes. "
               "Source: Sentinel-2 L2A, NDWI. Coordinates in UTM 35N.")

    # ---- the bulletin of the same day, so that the two sections tell one story
    bulletin_fill, bulletin_vol, bulletin_day = 78.0, None, None
    if daily is not None and len(daily):
        d = daily[daily.date <= pd.Timestamp(cur.obs_date)]
        if len(d):
            row = d.iloc[-1]
            bulletin_fill, bulletin_vol, bulletin_day = float(row.avail_mm3) / 311.8 * 100.0, float(row.avail_mm3), row.date
    ref_fill = 100.0
    if monthly is not None:
        mm = monthly[(monthly.year == pd.Timestamp(full.obs_date).year) & (monthly.month == pd.Timestamp(full.obs_date).month)]
        if len(mm):
            ref_fill = float(mm.fill_pct.iloc[0])

    st.markdown("**Cross-check against the MOEW bulletin of the same day**")
    a, b = st.columns(2)
    reported = a.number_input("Fill reported in the bulletin (%)", 0.0, 100.0, round(bulletin_fill, 1), 0.1)
    ref = b.number_input("Fill on the earlier satellite date (%)", 1.0, 100.0, round(ref_fill, 1), 0.1)
    tol = st.slider("Tolerance (percentage points of area)", 3, 30, 10)
    res = consistency(reported, float(cur.area_pct_of_full), float(tol), ref_fill_pct=ref)
    (st.success if res["status"] == "consistent" else st.warning)(MESSAGES[res["status"]])
    src = (f"the bulletin of {bulletin_day:%d.%m.%Y}: {bulletin_vol:.1f} mln m3" if bulletin_day is not None else "the value entered")
    st.write(f"Bulletin fill {reported:.1f}% ({src}) with an earlier-date fill of {ref:.1f}% implies a water area of about "
             f"**{res['expected_area_pct']:.0f}%** of the earlier area. The satellite measures **{cur.area_pct_of_full:.0f}%** "
             f"(gap {res['gap_pp']:+.1f} pp).")
    st.caption("Area is not volume: the conversion assumes volume ~ area^1.5 (illustrative); a real pilot uses the "
               "level-area-volume curve. The earlier scene is not a full pool: the May schedule gives the fill used as a default "
               "(about the volume at the start of the month). Clouds, shadows and ice can make the area too small.")
