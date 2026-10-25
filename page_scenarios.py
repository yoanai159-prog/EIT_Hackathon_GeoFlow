"""Scenarios page (module 2): what to decide if Ticha has a problem. Rules are explicit; assumptions are editable."""
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

import map_view
import page_map
import pilot
import ticha_tab
import ui
from core import scenarios as sc
from core import ticha
from core.logic import Settings

CAP = ticha.CAPACITY_MM3


def render(data_dir: Path, settings: Settings):
    S = ticha_tab.state(data_dir, settings)
    monthly, daily = S["monthly"], S["daily"]
    now = S["now"]
    fill_now = float(S["status"]["fill_pct"])
    st.subheader("Scenarios and decisions")
    st.info("DEMONSTRATION: the volumes come from real bulletins and schedules. How much each settlement depends on Ticha, "
            "the backup sources and the transfer links are ASSUMPTIONS to confirm with the water utilities and the basin directorate.")

    a = sc.Assumptions(critical_fill_pct=settings.critical_fill_pct)
    c1, c2, c3 = st.columns([1.3, 1.5, 1.2])
    scenario = c1.selectbox("Scenario", ["Baseline", "Optimistic", "Pessimistic", "Stress test (fastest decline on record)"])
    weeks = c2.slider("Weeks ahead", 0, 26, 14)
    whatif = c3.checkbox("Set the start fill by hand")
    start_fill = fill_now
    if whatif:
        start_fill = st.slider("Start fill (%)", 5.0, 100.0, float(round(fill_now, 1)), 0.5)
    v0 = start_fill / 100 * CAP

    paths = ticha.scenario_paths(monthly, v0, pd.Timestamp(now.date), weeks=26)
    rate = ticha.fastest_decline_pp_week(monthly)
    paths["stress test"] = np.maximum(sc.DEAD_MM3, v0 - rate / 100 * CAP * paths["week"])
    key = {"Baseline": "baseline", "Optimistic": "optimistic", "Pessimistic": "pessimistic"}.get(scenario, "stress test")
    path = paths.set_index("week")[key]
    vol = float(path.loc[weeks])
    fill = vol / CAP * 100
    chart = paths.set_index("date")[["optimistic", "baseline", "pessimistic", "stress test"]] / CAP * 100
    chart["50 % (risk starts)"] = a.risk_starts_fill_pct
    chart[f"{a.critical_fill_pct:.0f} % (critical)"] = a.critical_fill_pct
    ui.chart("line", chart, "date (week)", "fill of the reservoir (% of total capacity)",
             "MOEW schedules 2014 to 2026 and bulletins (volumes); scenarios: DryRadar demo method.",
             "Four scenario lines start from the current fill; the two flat lines are the thresholds.")
    st.caption("Optimistic, baseline and pessimistic are the 90th, 50th and 10th percentile of the changes in earlier years over the same "
               f"months. Stress test: a fall of {rate:.2f} pp per week, the fastest 3-month decline in 2014 to 2026. "
               "The method cannot foresee inflow (spring 2026 added about 100 mln m3).")

    m = st.columns(3)
    m[0].metric(f"Fill after {weeks} weeks", f"{fill:.1f} %", f"{fill - start_fill:+.1f} pp")
    m[1].metric("Volume", f"{vol:.1f} mln m3")
    cov = sc.drinking_coverage(vol, a)
    m[2].metric("Drinking water deliverable", f"{cov:.0%}")

    sett, src = pilot.load_assumptions(data_dir)
    left, right = st.columns(2)
    with left:
        st.markdown("**Settlements (edit the assumptions)**")
        sett = st.data_editor(sett[["name", "population", "dependence", "backup_m3_day", "critical_facility", "supply_group", "lat", "lon"]],
                              hide_index=True, use_container_width=True, key="sett_edit",
                              disabled=["name", "supply_group", "lat", "lon"])
    with right:
        st.markdown("**Transfer links (HYPOTHETICAL)**")
        try:
            bulletin = pd.read_csv(data_dir / "pilot" / "bulletin_latest.csv")
            src = pilot.donors(bulletin, src)
        except Exception:
            src["donor_fill_pct"] = float("nan")
        src = st.data_editor(src[["name", "capacity_m3_day", "active", "donor_fill_pct", "min_donor_fill_pct", "serves", "donor_reservoir"]],
                             hide_index=True, use_container_width=True, key="src_edit",
                             disabled=["name", "donor_fill_pct", "serves", "donor_reservoir"])
    sett = pilot.with_demand(sett.assign(critical_facility=sett.critical_facility.astype(bool)), monthly)
    ok = src.donor_fill_pct.fillna(0) >= src.min_donor_fill_pct
    src = src.assign(active=src.active.astype(bool) & ok)

    plan = sc.plan_supply(vol, sett, src, a)
    st.markdown(f"**Decision table at {fill:.1f} % fill** (priority: critical facilities first, then larger population)")
    show = plan.copy()
    for c in show.columns:
        if c.endswith("(m3/day)"):
            show[c] = show[c].round(0)
    st.dataframe(show, hide_index=True, use_container_width=True)

    st.markdown("**Risk by settlement and first week it is reached**")
    rr = []
    for r in sett.itertuples():
        rk = sc.settlement_risk(fill, r.dependence, r.backup_m3_day > 0, a)
        wr = sc.week_reaching(path, a, r.dependence, r.backup_m3_day > 0)
        rr.append({"settlement": r.name, "risk now": f"{rk['level_name']} ({rk['risk']:.0%})", "first week Attention": wr["warn"],
                   "first week High": wr["high"], "first week Critical": wr["crit"], "action": rk["action"]})
    st.dataframe(pd.DataFrame(rr), hide_index=True, use_container_width=True)

    st.markdown("**Other uses of the reservoir: precedent**")
    lad = ticha.restriction_ladder(monthly)
    band = "under 50 %" if fill < 50 else "50 to 65 %" if fill < 65 else "65 to 80 %" if fill < 80 else "80 % and more"
    row = lad[lad["fill band"] == band].iloc[0]
    st.write(f"At a fill in the band **{band}**, earlier years kept: irrigation at {row['irrigation, share of normal']:.0%} of normal, "
             f"minimum flow to the river Golyama Kamchiya at {row['minimum flow, share of normal']:.0%}, drinking water at "
             f"{row['drinking water, share of normal']:.0%}. The small HPP Ticha uses only water already released, so it follows the other uses.")

    st.markdown("**Radar**")
    layers, _ = page_map.shumen_layers(str(data_dir / "vectors"), ("Shumen_Muni", "Reservoirs_OSM", "Rivers_OSM", "Settlements_OSM"))
    radar = pilot.radar_config(sett, plan, fill, a, scenario, visible=True, center=pilot.reservoir_center(data_dir))
    map_view.render(list(layers), height=560, base="pale", fit_bounds=page_map.fit_of(layers), radar=radar)
    st.caption("Marker shape = risk level (circle low, diamond attention, triangle high, square critical). Line width = dependence on Ticha; "
               "dotted = backup source.")
