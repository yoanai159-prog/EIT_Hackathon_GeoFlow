"""DryRadar: drought and water-scarcity early-warning platform. Pilot: Shumen, reservoir Ticha.

Run:  streamlit run app.py
Real data: Ticha (MOEW schedules and bulletins), Sentinel-2 water extent, OSM vector layers.
Assumptions (marked on the pages): settlement dependence, backup sources, transfer links.
"""
from pathlib import Path

import streamlit as st

import page_about
import page_demo
import page_map
import page_scenarios
import page_story
import ticha_tab
import ui
from core.logic import Settings

DATA = Path(__file__).parent / "data"

ui.setup()

PAGES = ["About", "Map", "Reservoir", "Analytics", "Scenarios", "Demo scenario", "Settings", "Simulated demo"]
page = st.sidebar.radio("DryRadar", PAGES, label_visibility="collapsed")

if "critical" not in st.session_state:
    st.session_state.critical = 20
if "window" not in st.session_state:
    st.session_state.window = 4
settings = Settings(critical_fill_pct=float(st.session_state.critical), window_weeks=int(st.session_state.window))
st.sidebar.caption("Pilot: Shumen, reservoir Ticha")

if page == "About":
    page_about.render()
elif page == "Map":
    page_map.render(DATA, settings)
elif page == "Reservoir":
    ticha_tab.render(DATA, settings)
elif page == "Analytics":
    ticha_tab.render_analytics(DATA, settings)
elif page == "Scenarios":
    page_scenarios.render(DATA, settings)
elif page == "Demo scenario":
    page_story.render(DATA, settings)
elif page == "Settings":
    st.subheader("Settings")
    st.slider("Critical fill threshold (%)", 5, 40, key="critical")
    st.slider("Weeks used for the rate of decline", 2, 8, key="window")
    st.caption("The threshold also moves the risk scale on the Scenarios page and the traffic light of Ticha.")
elif page == "Simulated demo":
    page_demo.render(DATA, settings)
