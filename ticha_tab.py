"""Reservoir Ticha with REAL MOEW data: status, 2-week forecast, trends and the history of restrictions."""
from pathlib import Path

import pandas as pd
import streamlit as st

import satellite_tab
import ui
from core import ticha
from core.logic import Settings, reservoir_status

LIGHT = {"green": "🟢 Green", "yellow": "🟡 Yellow", "orange": "🟠 Orange", "red": "🔴 Red"}
LABELS = {
    "avail_mm3": "Available volume (mln m3)", "fill_pct": "Fill (%)", "release_total_mm3": "Planned release, total (mln m3/month)",
    "drinking_shumen_vpreslav_mm3": "Drinking water, Shumen and V. Preslav (mln m3/month)",
    "drinking_targovishte_mm3": "Drinking water, Targovishte (mln m3/month)",
    "irrigation_mm3": "Irrigation (mln m3/month)", "min_flow_mm3": "Minimum flow downstream (mln m3/month)",
}


@st.cache_data
def _load(path: str):
    p = Path(path)
    return ticha.load_monthly(p / "ticha_monthly.csv"), ticha.load_daily(p / "ticha_daily.csv")


def state(data_dir: Path, settings: Settings) -> dict:
    """Everything the pages need about Ticha: data, seasonal norm, current status with the traffic light."""
    monthly, daily = _load(str(data_dir / "ticha"))
    test_year = int(monthly.year.max())
    norm = ticha.seasonal_norm(monthly, before_year=test_year)
    obs = ticha.weekly_observations(daily, norm["norm"])
    status = reservoir_status(obs, ticha.CAPACITY_MM3 * 1e6, settings)
    return {"monthly": monthly, "daily": daily, "norm": norm, "obs": obs, "status": status, "test_year": test_year,
            "now": daily.iloc[-1]}


def status_metrics(S: dict, settings: Settings):
    st_, now = S["status"], S["now"]
    c = st.columns(5)
    c[0].metric("Traffic light", LIGHT[st_["alert_level"]])
    c[1].metric(f"Volume, {now.date:%d.%m.%Y}", f"{now.avail_mm3:.1f} mln m3")
    c[2].metric("Fill", f"{st_['fill_pct']:.1f} %", f"{st_['deviation_pp']:+.1f} pp vs norm")
    c[3].metric("Inflow / outflow", f"{now.inflow_m3s:.2f} / {now.outflow_m3s:.2f} m3/s")
    w = st_["weeks_to_threshold"]
    c[4].metric(f"To {settings.critical_fill_pct:.0f} % fill", "not falling" if w is None else f"~{w:.0f} weeks",
                None if w is None else f"range {st_['weeks_min']:.0f} to {st_['weeks_max']:.0f}", delta_color="off")


def forecast_frame(S: dict, horizon: int = 14, history_days: int = 45) -> pd.DataFrame:
    fc = ticha.balance_forecast(S["daily"], horizon_days=horizon)
    hist = S["daily"].set_index("date")["avail_mm3"].rename("observed")
    hist = hist[hist.index >= hist.index.max() - pd.Timedelta(days=history_days)]
    return pd.concat([hist, fc.set_index("date")[["central", "lower", "upper"]]], axis=1)


SRC_MOEW = "Ministry of Environment and Water (MOEW), daily reservoir bulletins and monthly water-use schedules"


def render(data_dir: Path, settings: Settings):
    """Page 'Reservoir': verified satellite view first, then the status and the (demo) forecast."""
    S = state(data_dir, settings)
    daily, monthly = S["daily"], S["monthly"]
    st.subheader("Reservoir Ticha")
    st.caption("Part 1 is the verified satellite view (Sentinel-2, checked against the bulletin of the same day). "
               "Part 2 is the status and a demonstration forecast from the MOEW data (10 August to 23 October 2026). "
               "Details and known problems of the data: `data/ticha/README.md`.")
    st.markdown("### 1. Satellite view (verified data)")
    satellite_tab.render(data_dir, daily, monthly)
    st.divider()
    st.markdown("### 2. Status and trend of the volume")
    status_metrics(S, settings)
    st.caption(f"Volume in mln m3 (million cubic metres); fill in % of the total capacity {ticha.CAPACITY_MM3} mln m3; flows in m3/s; "
               f"pp = percentage points. Source: {SRC_MOEW}.")

    st.markdown("**Trend and forecast of the available volume\\***")
    horizon = st.slider("Days ahead", 7, 28, 14)
    fc = ticha.balance_forecast(daily, horizon_days=horizon)
    frame = forecast_frame(S, horizon).rename(columns={"observed": "observed (bulletin)", "central": "forecast, central",
                                                       "lower": "forecast, lower bound", "upper": "forecast, upper bound"})
    ui.chart("line", frame, "date (day)", "available volume (mln m3)", SRC_MOEW + "; forecast: DryRadar demo algorithm.",
             "Solid line: volume reported in the bulletins; the other three lines continue from the last bulletin day (central value and range).")
    last = fc.iloc[-1]
    st.write(f"In **{horizon} days** the volume is expected near **{last.central:.1f} mln m3** "
             f"(range {last.lower:.1f} to {last.upper:.1f} mln m3, i.e. {last.central / ticha.CAPACITY_MM3 * 100:.1f} % fill). "
             "Rule: the inflow and outflow of the last 7 days continue (change of volume = (inflow - outflow) x 0.0864 mln m3 per day for each m3/s).")
    st.warning("\\* DEMO: the forecast algorithm is a demonstration. It is a simple water balance, tested only on the 2026 bulletins, and it cannot "
               "foresee future inflow (rain, snowmelt) or changes in releases.")
    bt = ticha.backtest_balance(daily)
    show = bt.rename(columns={"horizon_days": "days ahead", "n": "tests (number)", "balance_MAE_mm3": "balance: mean error (mln m3)",
                              "balance_bias_mm3": "balance: bias (mln m3)", "persistence_MAE_mm3": "'no change': mean error (mln m3)"})
    st.dataframe(show.round(2), hide_index=True, use_container_width=True)
    st.caption("Test: each day was forecast from the days before it and compared with what the bulletin later showed. "
               f"Errors in mln m3. Source of the observations: {SRC_MOEW}.")


def render_analytics(data_dir: Path, settings: Settings):
    """Page 'Analytics': norm, trends, history of restrictions, test of a long-range forecast."""
    S = state(data_dir, settings)
    monthly, norm, test_year = S["monthly"], S["norm"], S["test_year"]
    st.subheader("Analytics: Ticha 2014 to 2026")
    st.markdown("**Fill by month with the seasonal norm and the 10th to 90th percentile range (%)**")
    series = pd.DataFrame({"fill": monthly.set_index("date").fill_pct})
    for col, name in (("norm", "norm (mean)"), ("p10", "10th percentile"), ("p90", "90th percentile")):
        series[name] = [norm.loc[d.month, col] for d in series.index]
    ui.chart("line", series.rename(columns={"fill": "fill (observed, schedule)"}), "month", "fill of the reservoir (% of total capacity)", SRC_MOEW + ".")
    st.caption("The norm uses the years before the latest one. Dry years: 2020 and 2024 to 2025. 2026 started in the dry range and rose "
               "above the norm after a wet spring.")

    st.markdown("**Trend of yearly means, 2014 to the last full year**")
    tr = ticha.annual_trends(monthly, last_year=test_year - 1)
    tr["parameter"] = tr["parameter"].map(LABELS)
    tr = tr.rename(columns={"slope_per_year": "Theil-Sen slope per year", "kendall_tau": "Kendall tau", "p_value": "p-value (Mann-Kendall)"})
    st.caption("Table: Theil-Sen slope in the unit of the parameter per year (mln m3 or % per year); Kendall tau is unitless (-1 to 1); p-value is unitless (0 to 1). Source: MOEW schedules 2014 to 2026.")
    st.dataframe(tr.round(3), hide_index=True, use_container_width=True)
    st.caption("Years with fewer than 9 schedule months are left out of the means. 11 or 12 yearly points are few: read p-values as a guide.")

    st.markdown("**What was restricted when the reservoir was lower (precedent)**")
    st.dataframe(ticha.restriction_ladder(monthly).round(2), hide_index=True, use_container_width=True)
    st.caption("Median share of the normal allocation, by fill of the reservoir in the schedule month. In the dry years irrigation and the "
               "minimum flow downstream were cut to about a third, while drinking water was kept (even raised). This is the ladder the "
               "Scenarios page uses as precedent.")

    with st.expander("Planned release by use, 2026 (mln m3 per month)"):
        r = monthly[monthly.year == test_year].set_index("month")[["drinking_shumen_vpreslav_mm3", "drinking_targovishte_mm3",
                                                                    "irrigation_mm3", "min_flow_mm3"]]
        ui.chart("bar", r.rename(columns=LABELS), "month of 2026 (1 = January)", "planned release (mln m3 per month)", SRC_MOEW + ".",
                 "Bars: planned release for each use in the monthly schedule.")
