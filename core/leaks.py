"""Early leak detection from the inflow meter of a supply zone (minimum night flow).

Idea: between 02:00 and 04:00 almost nobody uses water, so the inflow to a zone is mostly leakage
plus a small, stable legitimate demand. A leak shows up as a persistent rise of this minimum night
flow (MNF) above the zone's own recent baseline.

Rules (all thresholds are illustrative defaults, to be tuned per zone with the operator):
- MNF of a day = median of the hourly inflow between night_start_h and night_end_h.
- Baseline = median of the last `baseline_days` (28) days that were NOT flagged. Days that look like a leak are
  kept out of the baseline, so a slow leak cannot hide by dragging the baseline up.
- A day is "above" when the excess over the baseline is at least z_threshold robust standard deviations
  AND at least min_excess_rel of the baseline.
- Status: normal (no day above), watch (1 to confirm_days-1 days in a row), suspected_leak (confirm_days or more).
- Leak estimate = median excess of the last days above baseline; lost volume per day = estimate x 24 h.

Limits: needs an inflow meter per zone with hourly data; night irrigation, tank refilling or a real change
in demand also raise the MNF; leakage depends on pressure, so the estimate is approximate.
Units: flow in m3/h, volume in m3.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LeakSettings:
    night_start_h: int = 2
    night_end_h: int = 4              # inclusive: hours 2, 3 and 4
    baseline_days: int = 28
    min_baseline_days: int = 7        # learning period before any alert
    z_threshold: float = 3.0
    min_excess_rel: float = 0.15      # at least 15% above the baseline
    confirm_days: int = 3             # days in a row before "suspected leak"


def daily_mnf(flow: pd.DataFrame, s: LeakSettings) -> pd.Series:
    """Minimum night flow per day (m3/h). flow needs the columns ts and inflow_m3_h for ONE zone."""
    f = flow.copy()
    f["ts"] = pd.to_datetime(f["ts"])
    days = f["ts"].dt.normalize()
    night = f[f["ts"].dt.hour.between(s.night_start_h, s.night_end_h)]
    g = night.groupby(night["ts"].dt.normalize())["inflow_m3_h"]
    mnf = g.median().where(g.count() >= 2)  # a night with fewer than 2 readings is treated as missing
    return mnf.reindex(pd.date_range(days.min(), days.max(), freq="D"))


def detect(mnf: pd.Series, s: LeakSettings) -> pd.DataFrame:
    """Walk through the days in order and flag those that are persistently above the baseline."""
    clean: list[float] = []
    run = 0
    rows = []
    for day, v in mnf.items():
        base = scale = excess = z = np.nan
        above = False
        if pd.notna(v):
            hist = clean[-s.baseline_days:]
            if len(hist) < s.min_baseline_days:
                clean.append(float(v))  # learning period
            else:
                base = float(np.median(hist))
                mad = float(np.median(np.abs(np.array(hist) - base)))
                scale = max(1.4826 * mad, 0.05 * base)  # floor so a very quiet history does not give huge z
                excess = float(v) - base
                z = excess / scale
                above = bool(z >= s.z_threshold and excess >= s.min_excess_rel * base)
                run = run + 1 if above else 0
                if not above:
                    clean.append(float(v))
        rows.append({"date": day, "mnf": v, "baseline": base, "scale": scale,
                     "excess": excess, "z": z, "above": above, "run": run})
    return pd.DataFrame(rows).set_index("date")


def summarize(det: pd.DataFrame, s: LeakSettings) -> dict:
    """Current status of the zone and an estimate of the leak."""
    if det["baseline"].notna().sum() == 0:
        return {"status": "insufficient_data", "run_days": 0, "baseline_m3h": None, "leak_m3h": 0.0,
                "lost_m3_day": 0.0, "since": None}
    run = int(det["run"].iloc[-1])
    status = "suspected_leak" if run >= s.confirm_days else "watch" if run >= 1 else "normal"
    out = {"status": status, "run_days": run, "baseline_m3h": float(det["baseline"].dropna().iloc[-1]),
           "leak_m3h": 0.0, "lost_m3_day": 0.0, "since": None}
    if run >= 1:
        ab = det[det["above"]]
        out["leak_m3h"] = float(ab.tail(min(run, 7))["excess"].median())
        out["lost_m3_day"] = out["leak_m3h"] * 24.0
        out["since"] = ab.index[-run].date()
    return out


def analyse_zone(flow: pd.DataFrame, s: LeakSettings) -> tuple[pd.DataFrame, dict]:
    det = detect(daily_mnf(flow, s), s)
    return det, summarize(det, s)


def explain_leak(name: str, res: dict, daily_demand_m3: float | None = None) -> str:
    """Plain-language text built from the computed numbers; it never changes a number or a status."""
    st = res["status"]
    if st == "insufficient_data":
        return f"{name}: not enough data yet to learn the normal night flow."
    if st == "normal":
        return (f"{name}: night flow is normal (about {res['baseline_m3h']:.1f} m3/h). "
                "No sign of a new leak.")
    share = ""
    if daily_demand_m3:
        share = f" That is about {100 * res['lost_m3_day'] / daily_demand_m3:.0f}% of the zone's daily demand."
    if st == "watch":
        return (f"{name}: watch. Night flow was above normal for {res['run_days']} day(s) in a row "
                f"(about +{res['leak_m3h']:.1f} m3/h). One or two days can be a refill or irrigation, "
                "so no alert yet.")
    return (f"{name}: suspected leak since {res['since']}. Night flow is about {res['leak_m3h']:.1f} m3/h above "
            f"the zone's normal ({res['baseline_m3h']:.1f} m3/h), which is roughly {res['lost_m3_day']:.0f} m3 per day."
            f"{share} Check the pipes and valves in this zone.")
