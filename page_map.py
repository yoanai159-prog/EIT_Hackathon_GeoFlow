"""Map page: Shumen vector layers (pale), Ticha water extents from Sentinel-2, radar overlay, Ticha card."""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

import map_view
import pilot
import satellite_tab
import ticha_tab
from core import scenarios as sc
from core import ticha
from core.logic import Settings
from ui import ALERT_HEX, badge, card, rows

TITLES = {"Landuse_OSM": "Land use (OSM)", "Shumen_Muni": "Municipalities, Shumen province",
          "Reservoirs_OSM": "Reservoirs and water bodies (OSM)", "Rivers_OSM": "Rivers (OSM)",
          "Settlements_OSM": "Settlements (OSM)",
          "Cadastre_urban": "Cadastre: urbanised parcels, town of Shumen (AGKK)"}
ORDER = ["Landuse_OSM", "Shumen_Muni", "Cadastre_urban", "Reservoirs_OSM", "Rivers_OSM", "Settlements_OSM"]
LABELS = {"Settlements_OSM": ("name", 10), "Reservoirs_OSM": ("name", 11), "Rivers_OSM": ("name", 12), "Shumen_Muni": ("NAME_2", 8)}
FADE = (0.55, 0.75)


@st.cache_data(show_spinner="Loading Shumen layers")
def shumen_layers(vec_dir: str, only: tuple, visible_landuse: bool = False):
    layers, msgs = map_view.load_vector_dir(Path(vec_dir), fade=FADE, visible={"Landuse_OSM": visible_landuse, **{k: True for k in ORDER if k != "Landuse_OSM"}},
                                            order=ORDER, titles=TITLES, only=list(only), labels=LABELS)
    return layers, msgs


def fit_of(layers):
    for l in layers:
        if l["title"] == TITLES["Shumen_Muni"]:
            return l["bounds"]
    return None


def current_plan(data_dir: Path, S: dict, settings: Settings):
    """Plan of supply and radar config at the current fill (used by the map and the Ticha card)."""
    a = sc.Assumptions(critical_fill_pct=settings.critical_fill_pct)
    sett, src = pilot.load_assumptions(data_dir)
    sett = pilot.with_demand(sett, S["monthly"])
    fill = float(S["status"]["fill_pct"])
    plan = sc.plan_supply(fill / 100 * ticha.CAPACITY_MM3, sett, src, a)
    return a, sett, plan, fill


def render(data_dir: Path, settings: Settings):
    S = ticha_tab.state(data_dir, settings)
    a, sett, plan, fill = current_plan(data_dir, S, settings)
    layers, msgs = shumen_layers(str(data_dir / "vectors"), tuple(ORDER))
    layers = list(layers)
    sat_csv = data_dir / "satellite_observations.csv"
    if sat_csv.exists():
        obs = pd.read_csv(sat_csv).set_index("role")
        layers += satellite_tab.water_layers(data_dir, obs, visible=True)
    nodes_risk = [sc.settlement_risk(fill, r.dependence, r.backup_m3_day > 0, a)["risk"] for r in sett.itertuples()]
    radar = pilot.radar_config(sett, plan, fill, a, "Current state", visible=max(nodes_risk) >= 0.15,
                               center=pilot.reservoir_center(data_dir))

    left, right = st.columns([3, 1.15])
    with left:
        st.subheader("Shumen pilot")
        for m in msgs:
            st.warning(m)
        map_view.render(layers, height=660, base="osm", fit_bounds=fit_of(layers), radar=radar)
        st.caption("Layers are pale on purpose; switch layers and the base map (OSM, pale OSM, none) in the control at the top right. "
                   "Each layer shows its legend only while it is on. Click an object for its attributes. Coordinates: UTM 35N (EPSG:32635).")
    with right:
        status = S["status"]
        color = ALERT_HEX[status["alert_level"]]
        card("Reservoir Ticha", f'{badge(status["alert_level"].upper(), color)}' + rows([
            ("Volume", f'{S["now"].avail_mm3:.1f} mln m3'), ("Fill", f"{fill:.1f} %"),
            ("vs seasonal norm", f'{status["deviation_pp"]:+.1f} pp'), ("Date", f'{S["now"].date:%d.%m.%Y}')]))
        fc = ticha.balance_forecast(S["daily"], horizon_days=14).iloc[-1]
        card("Forecast, 14 days", rows([("Central", f"{fc.central:.1f} mln m3"), ("Range", f"{fc.lower:.1f} to {fc.upper:.1f}"),
                                         ("Fill (central)", f"{fc.central / ticha.CAPACITY_MM3 * 100:.1f} %")]))
        sett_rows = ""
        for r in sett.itertuples():
            rk = sc.settlement_risk(fill, r.dependence, r.backup_m3_day > 0, a)
            sett_rows += (f'<div class="dr-row"><span><span class="dr-dot" style="background:{ALERT_HEX_BY_LEVEL[rk["level"]]}"></span>'
                          f'{r.name}</span><b>{rk["level_name"]}</b></div>')
        card("Settlements supplied by Ticha", sett_rows + '<div class="dr-muted">Dependence is a demonstration assumption. '
             "See the Scenarios page.</div>")
        st.caption("Uses of the water: drinking supply, irrigation, the small HPP Ticha, and the flow of the river Golyama Kamchiya.")


ALERT_HEX_BY_LEVEL = {"ok": "#1B7F4B", "warn": "#C99700", "high": "#D9660F", "crit": "#B3261E"}
