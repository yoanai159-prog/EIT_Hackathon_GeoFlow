"""About page (first page): what DryRadar is and what is where. Laid out as a landing page of cards, not a wide table."""
from pathlib import Path

import streamlit as st

import ui

ROOT = Path(__file__).parent

MODULES = [
    ("Map", "Shumen map with pale layers, names of objects, click for attributes, base-map switch, Sentinel-2 water extent of Ticha, "
            "radar of the dependent settlements, traffic light and 14-day forecast.", "OSM, AGKK cadastre, Copernicus Sentinel-2, MOEW"),
    ("Reservoir", "Module 1, early warning. Verified satellite view of Ticha checked against the bulletin of the same day, then the "
                  "traffic light, volume, fill and a 14-day forecast (demo algorithm).", "Sentinel-2, MOEW bulletins and schedules"),
    ("Analytics", "Seasonal norm, trends 2014 to 2026, what was restricted in earlier dry periods, planned release by use.", "MOEW schedules"),
    ("Scenarios", "Module 2, decisions. Optimistic, baseline, pessimistic and stress-test paths; priority by settlement; rerouting to other "
                  "sources; expected restrictions on other uses; radar. Assumptions are editable.", "MOEW (real); dependence and links (assumptions)"),
    ("Demo scenario", "A hypothetical drought at Ticha told step by step: warning, preparation, shortage, and which alternative source covers which settlement.", "MOEW (real); the decline and the links are assumptions"),
    ("Settings", "Critical fill threshold and the window for the rate of decline.", ""),
    ("Simulated demo", "The generic chain on invented reservoirs and settlements, and leak detection from night flow.", "SIMULATED"),
]


def render():
    logo = ROOT / "assets" / "dryradar_logo.png"
    if logo.exists():
        st.image(str(logo), width=340)
    st.markdown("## Early warning for drought and water scarcity")
    st.markdown(
        "DryRadar warns when a reservoir may not cover the settlements that depend on it, and shows what can be decided. "
        "**Pilot territory:** province Shumen. **Pilot reservoir:** Ticha, which supplies Shumen, Veliki Preslav and Targovishte with "
        "drinking water and is also used for irrigation, for power from the small HPP Ticha and to regulate the flow of the river "
        "Golyama Kamchiya.")

    st.markdown("### Where to find what")
    for i in range(0, len(MODULES), 2):
        cols = st.columns(2, gap="medium")
        for col, (name, text, data) in zip(cols, MODULES[i:i + 2]):
            with col:
                extra = f'<div class="dr-muted">Data: {data}</div>' if data else ""
                ui.card(name, f"<div style='font-size:14px;margin-bottom:6px'>{text}</div>{extra}")

    st.markdown("### Real data, assumptions and demo")
    c1, c2, c3 = st.columns(3, gap="medium")
    with c1:
        ui.card("Real", "Ticha volumes, inflows and outflows (MOEW bulletins, 10 August to 23 October 2026) and schedules 2014 to 2026; "
                        "Sentinel-2 water extent (6 May and 5 October 2026); OSM layers; cadastral parcels.")
    with c2:
        ui.card("Assumptions", "To confirm with the water utilities and the basin directorate: dependence of each settlement on Ticha, backup "
                               "sources, the two transfer links, Targovishte position and population, the risk scale.")
    with c3:
        ui.card("Demo", "The forecast algorithms cannot foresee inflow. The Simulated demo page, including leak detection, uses invented data. "
                        "The rest of the cadastre is not drawn (too large); it is summarised in <code>data/pilot/cadastre_summary.csv</code>.")
    st.caption("Units: mln m3 = million cubic metres; m3/s = cubic metres per second; m3/day = cubic metres per day; pp = percentage points. "
               "Coordinates: UTM zone 35N (EPSG:32635). Every chart names its axes, units and source.")
