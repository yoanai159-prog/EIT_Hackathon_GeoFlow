"""Real-data analysis for reservoir Ticha: seasonal norm, trends, balance forecast, backtests.

Pure functions on pandas data (no Streamlit). Units: volumes mln m3, flows m3/s, fill in %.
One day of inflow minus outflow at 1 m3/s is 0.0864 mln m3 (86 400 m3).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

CAPACITY_MM3 = 311.8
DEAD_MM3 = 40.0
MM3_PER_M3S_DAY = 0.0864

TREND_COLUMNS = ["avail_mm3", "fill_pct", "release_total_mm3", "drinking_shumen_vpreslav_mm3",
                 "drinking_targovishte_mm3", "irrigation_mm3", "min_flow_mm3"]


def load_monthly(path) -> pd.DataFrame:
    m = pd.read_csv(path)
    m["date"] = pd.to_datetime(dict(year=m.year, month=m.month, day=1))
    return m.sort_values("date").reset_index(drop=True)


def load_daily(path) -> pd.DataFrame:
    d = pd.read_csv(path, parse_dates=["date"]).sort_values("date")
    return d.drop_duplicates("date", keep="last").reset_index(drop=True)


# ---- seasonal norm -------------------------------------------------------------------------------

def seasonal_norm(monthly: pd.DataFrame, before_year: int, col: str = "fill_pct") -> pd.DataFrame:
    """Mean, 10th and 90th percentile of `col` for each calendar month, from the years before `before_year`."""
    h = monthly[monthly.year < before_year]
    g = h.groupby("month")[col]
    return pd.DataFrame({"norm": g.mean(), "p10": g.quantile(0.1), "p90": g.quantile(0.9), "n": g.count()})


def norm_at(norm: pd.Series, when: pd.Timestamp) -> float:
    """Seasonal norm for a date: linear between the mid-month values, wrapping over the year end."""
    pos = when.month - 1 + (when.day - 0.5) / when.days_in_month - 0.5   # 0 = mid-January
    lo = math.floor(pos)
    w = pos - lo
    a, b = norm.loc[(lo % 12) + 1], norm.loc[((lo + 1) % 12) + 1]
    return float(a * (1 - w) + b * w)


def weekly_observations(daily: pd.DataFrame, norm: pd.Series) -> pd.DataFrame:
    """Weekly fill and seasonal norm in the form `core.logic.reservoir_status` expects."""
    s = daily.set_index("date")["avail_mm3"]
    wk = s.resample("W").last().dropna()          # last known value of each week
    obs = pd.DataFrame({"obs_date": wk.index, "fill_pct": (wk.values / CAPACITY_MM3 * 100.0)})
    obs["season_norm_pct"] = [norm_at(norm, d) for d in obs.obs_date]
    return obs.reset_index(drop=True)


# ---- trend tests (no scipy needed) -----------------------------------------------------------------

def theil_sen(x, y) -> float:
    """Median of the slopes between all pairs of points (robust trend, units of y per unit of x)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    slopes = [(y[j] - y[i]) / (x[j] - x[i]) for i in range(len(x)) for j in range(i + 1, len(x)) if x[j] != x[i]]
    return float(np.median(slopes)) if slopes else float("nan")


def mann_kendall(y) -> tuple[float, float]:
    """Mann-Kendall test: returns (tau, two-sided p) with the normal approximation and a tie correction."""
    y = np.asarray(y, float)
    n = len(y)
    if n < 3:
        return float("nan"), float("nan")
    s = sum(np.sign(y[j] - y[i]) for i in range(n) for j in range(i + 1, n))
    _, counts = np.unique(y, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - sum(t * (t - 1) * (2 * t + 5) for t in counts)) / 18.0
    if var <= 0:
        return 0.0, 1.0
    z = (s - np.sign(s)) / math.sqrt(var)
    p = math.erfc(abs(z) / math.sqrt(2))
    return float(s / (n * (n - 1) / 2)), float(p)


def annual_trends(monthly: pd.DataFrame, last_year: int, first_year: int = 2014) -> pd.DataFrame:
    """Per parameter: Theil-Sen slope per year and Mann-Kendall p, on the yearly means of the available months.

    Years with fewer than 9 months are left out, because missing winter or summer months bias a yearly mean.
    """
    m = monthly[(monthly.year >= first_year) & (monthly.year <= last_year)]
    cnt = m.groupby("year").size()
    m = m[m.year.isin(cnt[cnt >= 9].index)]
    rows = []
    for c in TREND_COLUMNS:
        a = m.groupby("year")[c].mean().dropna()
        tau, p = mann_kendall(a.values)
        rows.append({"parameter": c, "years": len(a), "slope_per_year": theil_sen(a.index, a.values),
                     "kendall_tau": tau, "p_value": p})
    return pd.DataFrame(rows)


# ---- water-balance forecast -----------------------------------------------------------------------

def daily_net(daily: pd.DataFrame) -> pd.Series:
    """Net change of the volume per day (mln m3/day) from the bulletin inflow and outflow (m3/s)."""
    return (daily.set_index("date")["inflow_m3s"] - daily.set_index("date")["outflow_m3s"]) * MM3_PER_M3S_DAY


def balance_forecast(daily: pd.DataFrame, horizon_days: int = 28, window_days: int = 7,
                     history_days: int = 28) -> pd.DataFrame:
    """Volume forecast from the last known day.

    central: the mean net change of the last `window_days` days continues.
    lower / upper: the fastest and slowest `window_days`-day mean net change seen in the last `history_days` days.
    """
    net = daily_net(daily).dropna()
    last_date, v0 = net.index[-1], float(daily.set_index("date")["avail_mm3"].loc[net.index[-1]])
    roll = net.rolling(f"{window_days}D").mean()
    recent = roll[roll.index >= last_date - pd.Timedelta(days=history_days)]
    rate = float(net[net.index > last_date - pd.Timedelta(days=window_days)].mean())
    lo_rate, hi_rate = float(recent.min()), float(recent.max())      # lo = fastest fall
    rows = [{"date": last_date + pd.Timedelta(days=h), "days_ahead": h,
             "central": max(v0 + rate * h, DEAD_MM3), "lower": max(v0 + lo_rate * h, DEAD_MM3),
             "upper": min(v0 + hi_rate * h, CAPACITY_MM3)} for h in range(horizon_days + 1)]
    return pd.DataFrame(rows)


def backtest_balance(daily: pd.DataFrame, horizons=(7, 14, 28), window_days: int = 7) -> pd.DataFrame:
    """Test the balance forecast against what the bulletins later showed.

    For every day with a bulletin, forecast `h` days ahead from the mean net change of the last `window_days`
    days, and compare with the volume of the bulletin `h` days later (when one exists). Also scores the
    baseline "volume stays the same".
    """
    d = daily.set_index("date")
    net = daily_net(daily)
    out = []
    for h in horizons:
        for o in d.index:
            t = o + pd.Timedelta(days=h)
            if t not in d.index:
                continue
            rate = net[(net.index > o - pd.Timedelta(days=window_days)) & (net.index <= o)].mean()
            out.append({"horizon_days": h, "balance": d.avail_mm3[o] + rate * h - d.avail_mm3[t],
                        "persistence": d.avail_mm3[o] - d.avail_mm3[t]})
    e = pd.DataFrame(out)
    rows = []
    for h, g in e.groupby("horizon_days"):
        rows.append({"horizon_days": h, "n": len(g),
                     "balance_MAE_mm3": g.balance.abs().mean(), "balance_bias_mm3": g.balance.mean(),
                     "persistence_MAE_mm3": g.persistence.abs().mean()})
    return pd.DataFrame(rows)


# ---- long-range scenarios from past years ---------------------------------------------------------

def analog_ensemble(monthly: pd.DataFrame, start_year: int, start_month: int, horizon_months: int,
                    first_year: int = 2014, v0: float | None = None) -> pd.DataFrame:
    """Scenarios for the volume: add to the last known value the change seen in each earlier year over the same months.

    Missing months are filled by linear interpolation. Returns one column per earlier year (the scenario),
    rows = months ahead. It shows the range of past years, not a prediction of the coming one.
    """
    s = monthly.set_index(monthly.year * 12 + monthly.month - 1)["avail_mm3"]
    full = s.reindex(range(int(s.index.min()), int(s.index.max()) + 1)).interpolate()
    t0 = start_year * 12 + start_month - 1
    v0 = float(s.loc[t0]) if v0 is None else float(v0)
    cols = {}
    for y in range(first_year, start_year):
        ty = y * 12 + start_month - 1
        if ty in full.index and ty + horizon_months in full.index and ty in s.index:
            cols[y] = [min(max(v0 + full[ty + h] - full[ty], DEAD_MM3), CAPACITY_MM3) for h in range(1, horizon_months + 1)]
    out = pd.DataFrame(cols)
    out.index = range(1, horizon_months + 1)
    out.index.name = "months_ahead"
    return out


def scenario_paths(monthly: pd.DataFrame, v0: float, start: pd.Timestamp, weeks: int = 26) -> pd.DataFrame:
    """Optimistic, baseline and pessimistic volume paths (weekly, mln m3) from the same-month changes of earlier years.

    For each earlier year the change of the volume from the start month onward is added to `v0`; at every month the
    90th, 50th and 10th percentile over the earlier years give the optimistic, baseline and pessimistic path. The start
    month of `start` is used as the common starting point, with changes taken from the first day of the month.
    """
    months = int(math.ceil(weeks / 4.345)) + 1
    ens = analog_ensemble(monthly, start.year, start.month, months, v0=v0)
    t = np.array([0.0] + list(ens.index), dtype=float)                       # months ahead, 0 = start
    q = {"optimistic": 0.9, "baseline": 0.5, "pessimistic": 0.1}
    w = np.arange(0, weeks + 1)
    out = {"week": w, "date": [start + pd.Timedelta(weeks=int(x)) for x in w]}
    for name, qq in q.items():
        y = np.array([v0] + list(ens.quantile(qq, axis=1).values), dtype=float)
        out[name] = np.interp(w / 4.345, t, y)
    return pd.DataFrame(out)


def restriction_ladder(monthly: pd.DataFrame) -> pd.DataFrame:
    """What happened to each use when the reservoir was fuller or emptier: median share of the normal allocation.

    "Normal" = the median of the same calendar month in the months when the reservoir was at least 80% full (for the
    minimum flow: 1.58 mln m3, the usual value). Months with hydropower water are left out (the minimum flow is not listed
    there). A small sample: use it as precedent, not as a law.
    """
    m = monthly.copy()
    m["drinking"] = m.drinking_shumen_vpreslav_mm3 + m.drinking_targovishte_mm3
    full = m[m.fill_pct >= 80]
    ref_irr = full.groupby("month").irrigation_mm3.median()
    ref_drink = float(full.drinking.median())
    bands = [("under 50 %", 0, 50), ("50 to 65 %", 50, 65), ("65 to 80 %", 65, 80), ("80 % and more", 80, 101)]
    rows = []
    for name, lo, hi in bands:
        b = m[(m.fill_pct >= lo) & (m.fill_pct < hi)]
        irr = b[b.month.map(ref_irr).fillna(0) > 0.5]
        irr_ratio = (irr.irrigation_mm3 / irr.month.map(ref_irr)).median() if len(irr) else float("nan")
        mf = b[b.energy_mm3 == 0]
        rows.append({"fill band": name, "months": len(b), "irrigation, share of normal": irr_ratio,
                     "minimum flow, share of normal": (mf.min_flow_mm3 / 1.58).median() if len(mf) else float("nan"),
                     "drinking water, share of normal": (b.drinking / ref_drink).median() if len(b) else float("nan")})
    return pd.DataFrame(rows)


def fastest_decline_pp_week(monthly: pd.DataFrame, months: int = 3) -> float:
    """Largest fall of the fill over `months` consecutive schedule months, in pp per week (a stress-test rate)."""
    m = monthly.set_index(monthly.year * 12 + monthly.month - 1).fill_pct
    best = 0.0
    for t in m.index:
        if t + months in m.index and all((t + k) in m.index for k in range(months + 1)):
            best = max(best, (m[t] - m[t + months]) / (months * 4.345))
    return best
