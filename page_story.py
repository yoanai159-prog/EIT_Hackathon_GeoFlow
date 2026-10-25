"""Demo scenario: a drought problem at Ticha, step by step, and what DryRadar proposes (HYPOTHETICAL, on real Ticha data).

The story: the reservoir falls week after week. DryRadar warns, asks for preparation, and when Ticha can no longer cover
the drinking-water demand it shows who gets water first and which alternative source covers the missing part.
Volumes, the donor reservoirs and the earlier restrictions are real; the decline, the settlements' dependence and the
transfer links are assumptions (see the Scenarios page and `data/pilot/*.csv`).
"""
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import map_view
import page_map
import pilot
import ticha_tab
import ui
from core import scenarios as sc
from core import ticha
from core.logic import Settings

CAP = ticha.CAPACITY_MM3
HORIZON = 52
STAGES = [("1", "Normal", "No action needed. Watch the bulletins."),
          ("2", "Early warning", "Warn the water utility and the municipality."),
          ("3", "Prepare", "Prepare the restriction plan and the alternative source."),
          ("4", "Act: shortage", "Ticha can no longer cover the demand. Reroute and restrict by priority.")]
LV = {"ok": "#1B7F4B", "warn": "#C99700", "high": "#D9660F", "crit": "#B3261E"}


def _first(path, pred):
    for wk, v in path.items():
        if pred(v):
            return int(wk)
    return None


def stage_weeks(path, sett, a):
    """First week of stages 2, 3, 4 along the path (None if never)."""
    warn = high = None
    for r in sett.itertuples():
        w = sc.week_reaching(path, a, r.dependence, r.backup_m3_day > 0)
        warn = w["warn"] if warn is None or (w["warn"] is not None and w["warn"] < warn) else warn
        high = w["high"] if high is None or (w["high"] is not None and w["high"] < high) else high
    v_crit = a.critical_fill_pct / 100 * CAP
    return {2: warn, 3: high, 4: _first(path, lambda v: v < v_crit)}


def current_stage(week, sw):
    s = 1
    for k in (2, 3, 4):
        if sw[k] is not None and week >= sw[k]:
            s = k
    return s


def flow_svg(plan: pd.DataFrame, levels: dict, reservoir: str, sources, fill: float) -> str:
    """Schematic: Ticha and the alternative sources on the left, the settlements on the right, flows in m3/day.
    `sources`: None, a name, or a list of names (drawn as nodes; flows come from plan.attrs["parts"])."""
    names = [] if not sources else ([sources] if isinstance(sources, str) else list(sources))
    parts = plan.attrs.get("parts", {})
    n = len(plan)
    H = max(110 + 96 * n, 110 + 100 * max(len(names), 1) + 40)
    mx = max(float(plan["demand (m3/day)"].max()), 1.0)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 {H}" width="100%" style="font-family:Segoe UI,Arial,sans-serif">']
    ty = 70
    sy = {nm: H - 70 - 92 * (len(names) - 1 - i) for i, nm in enumerate(names)}
    out.append(f'<rect x="10" y="{ty - 34}" width="190" height="68" rx="12" fill="#0B2A4A"/><text x="105" y="{ty - 6}" fill="#fff" font-size="16" '
               f'font-weight="700" text-anchor="middle">{reservoir}</text><text x="105" y="{ty + 16}" fill="#9fd8e4" font-size="13" text-anchor="middle">{fill:.1f} % full</text>')
    for nm, y in sy.items():
        out.append(f'<rect x="10" y="{y - 34}" width="190" height="68" rx="12" fill="#F59E0B"/><text x="105" y="{y - 6}" fill="#0B2A4A" font-size="14" '
                   f'font-weight="700" text-anchor="middle">{nm}</text><text x="105" y="{y + 16}" fill="#0B2A4A" font-size="12" text-anchor="middle">alternative source</text>')
    for i in range(n):
        y = 60 + 96 * i + 30
        row = plan.iloc[i]
        name, demand, fr, un = row["settlement"], row["demand (m3/day)"], row["from reservoir (m3/day)"], row["unmet (m3/day)"]
        col = LV.get(levels.get(name, "ok"), "#1B7F4B")
        out.append(f'<rect x="620" y="{y - 34}" width="230" height="68" rx="12" fill="#fff" stroke="{col}" stroke-width="3"/>'
                   f'<text x="735" y="{y - 8}" font-size="15" font-weight="700" fill="#0B2A4A" text-anchor="middle">P{row["priority"]} {name}</text>'
                   f'<text x="735" y="{y + 12}" font-size="12" fill="#5b6f82" text-anchor="middle">demand {demand:,.0f} m3/day</text>')
        if fr > 1:
            w = 3 + 22 * fr / mx
            out.append(f'<path d="M200 {ty} C 400 {ty}, 420 {y}, 620 {y - 8}" stroke="#0E8FA8" stroke-width="{w:.1f}" fill="none" opacity=".85"/>'
                       f'<text x="410" y="{(ty + y) / 2 - 8:.0f}" font-size="12" fill="#0A6C80" text-anchor="middle">{fr:,.0f} m3/day</text>')
        for nm, q in parts.get(name, []):
            if q > 1 and nm in sy:
                w = 3 + 22 * q / mx
                out.append(f'<path d="M200 {sy[nm]} C 400 {sy[nm]}, 420 {y}, 620 {y + 8}" stroke="#F59E0B" stroke-width="{w:.1f}" fill="none" opacity=".9"/>'
                           f'<text x="410" y="{(sy[nm] + y) / 2 + 16:.0f}" font-size="12" fill="#8a5a00" text-anchor="middle">{q:,.0f} m3/day</text>')
        if un > 1:
            out.append(f'<text x="735" y="{y + 52}" font-size="12" font-weight="700" fill="#B3261E" text-anchor="middle">unmet {un:,.0f} m3/day: restrictions</text>')
    out.append("</svg>")
    return "".join(out)


def render(data_dir: Path, settings: Settings):
    S = ticha_tab.state(data_dir, settings)
    monthly, now = S["monthly"], S["now"]
    fill_now = float(S["status"]["fill_pct"])
    a = sc.Assumptions(critical_fill_pct=settings.critical_fill_pct)
    rate_rec = ticha.fastest_decline_pp_week(monthly)

    st.subheader("Demo scenario: a drought problem at Ticha")
    st.error("HYPOTHETICAL SCENARIO. It does not forecast what will happen. It shows how DryRadar would warn and what it would propose if "
             "Ticha fell as described below. Real: Ticha volumes, the donor reservoirs in the bulletin, the earlier restrictions. "
             "Assumptions: the decline, how much each settlement depends on Ticha, the transfer links.")

    c1, c2, c3 = st.columns([1.5, 1.2, 1.3])
    start_name = c1.selectbox("Story", ["After a dry winter: Ticha starts at 40 % (hypothetical)", "From today's real state"])
    start_fill = 40.0 if start_name.startswith("After") else fill_now
    rate = c2.slider("Fall of the fill (pp per week)", 0.5, 3.0, float(round(rate_rec, 2)), 0.05)
    c2.caption(f"Default {rate_rec:.2f} pp per week = the fastest 3-month decline in 2014 to 2026 (MOEW schedules).")
    try:
        bulletin = pd.read_csv(data_dir / "pilot" / "bulletin_latest.csv")
    except Exception:
        bulletin = None
    sett, src = pilot.load_assumptions(data_dir)
    sett = pilot.with_demand(sett, monthly)
    src = pilot.donors(bulletin, src) if bulletin is not None else src.assign(donor_fill_pct=float("nan"), donor_usable_mm3=float("nan"))
    both = "Both links together"
    options = ["None (see what happens without it)"] + list(src.name) + [both]
    pick = c3.selectbox("Alternative water source", options, index=len(options) - 1)

    weeks = list(range(HORIZON + 1))
    dead_pct = sc.DEAD_MM3 / CAP * 100
    path = pd.Series([max(sc.DEAD_MM3, (start_fill - rate * w) / 100 * CAP) for w in weeks], index=weeks)
    sw = stage_weeks(path, sett, a)

    if "story_week" not in st.session_state:
        st.session_state.story_week = 0
    st.markdown("**Move through the story**")
    bcols = st.columns(len(STAGES) + 1)
    bcols[0].caption("Jump to the start of a stage:")
    for k, col in zip((1, 2, 3, 4), bcols[1:]):
        target = 0 if k == 1 else sw[k]
        if col.button(f"{k}. {STAGES[k - 1][1]}", disabled=target is None, key=f"jump{k}"):
            st.session_state.story_week = int(target)
    week = st.slider("Weeks from the start of the story", 0, HORIZON, key="story_week")

    vol = float(path.loc[week])
    fill = vol / CAP * 100
    date = pd.Timestamp(now.date) + pd.Timedelta(weeks=week)
    stage = current_stage(week, sw)
    cov = sc.drinking_coverage(vol, a)

    chosen = []
    active = src.assign(active=False)
    if pick == both:
        chosen = list(src.name)
    elif pick != options[0]:
        chosen = [pick]
    active.loc[active.name.isin(chosen), "active"] = True
    plan_with = sc.plan_supply(vol, sett, active.assign(serves="all"), a)
    plan_without = sc.plan_supply(vol, sett, active.assign(active=False), a)

    # ---- banner and metrics
    col = {1: "#1B7F4B", 2: "#C99700", 3: "#D9660F", 4: "#B3261E"}[stage]
    st.markdown(f'<div class="dr-card" style="border-left:8px solid {col}"><h4>Stage {stage} of 4: {STAGES[stage - 1][1]}</h4>'
                f'<div>{STAGES[stage - 1][2]}</div></div>', unsafe_allow_html=True)
    m = st.columns(4)
    m[0].metric("Date in the story", f"{date:%d.%m.%Y}", f"week {week}", delta_color="off")
    m[1].metric("Ticha volume", f"{vol:.1f} mln m3")
    m[2].metric("Fill", f"{fill:.1f} %", f"{fill - start_fill:+.1f} pp", delta_color="off")
    m[3].metric("Drinking water Ticha can deliver", f"{cov:.0%}")

    # ---- chart
    frame = pd.DataFrame({"fill so far": [path[w] / CAP * 100 if w <= week else None for w in weeks],
                          "fill ahead": [path[w] / CAP * 100 if w >= week else None for w in weeks],
                          f"{a.risk_starts_fill_pct:.0f} % (risk starts)": a.risk_starts_fill_pct,
                          f"{a.critical_fill_pct:.0f} % (critical)": a.critical_fill_pct,
                          f"{dead_pct:.1f} % (dead volume)": dead_pct}, index=pd.Index(weeks, name="week"))
    ui.chart("line", frame, "weeks from the start of the story", "fill of Ticha (% of total capacity 311.8 mln m3)",
             "DryRadar hypothetical scenario on MOEW capacity data.", "Line: assumed fall of the fill; flat lines: thresholds.")

    # ---- the decision
    st.markdown(f"### What DryRadar proposes at week {week} ({date:%d.%m.%Y})")
    levels = {r.name: sc.settlement_risk(fill, r.dependence, r.backup_m3_day > 0, a)["level"] for r in sett.itertuples()}
    left, right = st.columns([1.6, 1])
    with left:
        components.html(flow_svg(plan_with, levels, "Ticha", chosen, fill), height=max(110 + 96 * len(plan_with), 110 + 100 * max(len(chosen), 1) + 40) + 20)
        st.caption("Schematic, not to scale. Line width = water per day (m3/day). Teal: from Ticha. Amber: from the alternative source. "
                   "Frame colour = risk level of the settlement (green low, yellow attention, orange high, red critical). P1, P2, P3 = priority.")
    with right:
        need = float(plan_without["demand (m3/day)"].mul(sett.set_index("name").loc[plan_without.settlement, "dependence"].values).sum())
        unm0, unm1 = float(plan_without["unmet (m3/day)"].sum()), float(plan_with["unmet (m3/day)"].sum())
        if cov >= 1.0:
            st.success("Ticha still covers the drinking-water demand of all three settlements. Keep watching; prepare the alternative source.")
        else:
            st.markdown(f"- Ticha can deliver **{cov:.0%}** of the drinking water that the three settlements take from it ({need:,.0f} m3/day).\n"
                        f"- **Without an alternative source** {unm0:,.0f} m3/day ({unm0 / need:.0%}) is unmet: restrictions.\n"
                        + (f"- **With {pick}** the unmet water falls to **{unm1:,.0f} m3/day** ({unm1 / need:.0%})." if chosen else
                           "- Pick an alternative source above to see how much of it can be covered."))
        if chosen:
            cap = float(src[src.name.isin(chosen)].capacity_m3_day.sum())
            st.info(f"{', '.join(chosen)}: capacity {cap:,.0f} m3/day (HYPOTHETICAL). These are local reservoirs near Shumen (OSM). They are not in the "
                    "MOEW bulletin, so their volume is unknown: ViK must confirm that they can supply this water for weeks and that a link exists.")
    show = plan_with.copy()
    for c in show.columns:
        if c.endswith("(m3/day)"):
            show[c] = show[c].round(0)
    st.dataframe(show, hide_index=True, use_container_width=True)
    st.caption("Priority: critical facilities first, then larger population. Units: m3/day (cubic metres per day). "
               "Demand = share of the schedule allocation of the month (MOEW). Dependence and links: assumptions.")

    lad = ticha.restriction_ladder(monthly)
    band = "under 50 %" if fill < 50 else "50 to 65 %" if fill < 65 else "65 to 80 %" if fill < 80 else "80 % and more"
    row = lad[lad["fill band"] == band].iloc[0]
    st.markdown(f"**Other uses of Ticha (precedent, fill {band}):** irrigation about {row['irrigation, share of normal']:.0%} of normal, minimum flow to the "
                f"river Golyama Kamchiya about {row['minimum flow, share of normal']:.0%}, drinking water {row['drinking water, share of normal']:.0%}. "
                "The small HPP Ticha uses only water that is released anyway. Source: MOEW schedules 2014 to 2026.")

    with st.expander("Map: radar of the dependent settlements"):
        layers, _ = page_map.shumen_layers(str(data_dir / "vectors"), ("Shumen_Muni", "Reservoirs_OSM", "Rivers_OSM", "Settlements_OSM"))
        radar = pilot.radar_config(sett, plan_with, fill, a, f"Story, week {week}", visible=True, center=pilot.reservoir_center(data_dir))
        map_view.render(list(layers), height=520, base="pale", fit_bounds=page_map.fit_of(layers), radar=radar)

    with st.expander("What the water utility and the basin directorate must confirm before this is real"):
        st.markdown("- The real dependence of each settlement on Ticha and its own sources.\n- Whether a physical link to the alternative source exists, "
                    "its capacity and the water quality after mixing.\n- The donor reservoir's own needs (it must not fall into shortage).\n"
                    "- The legal priority of uses in a shortage and who may declare restrictions.")
