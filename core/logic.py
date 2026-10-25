"""Transparent rules for the demo: reservoir status, traffic light, forecast and settlement risk.

All thresholds and weights are illustrative defaults. In a real pilot they are
agreed with the reservoir operator, the water utility and the basin directorate.
Units: fill in %, volume in m3, rates in pp (percentage points) per week.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

ALERT_ORDER = ["green", "yellow", "orange", "red"]
# How strongly a reservoir alert level feeds into the risk of the villages that depend on it.
ALERT_FACTOR = {"green": 0.0, "yellow": 0.4, "orange": 0.7, "red": 1.0}


@dataclass(frozen=True)
class Settings:
    """Parameters that can be tuned in the app."""

    critical_fill_pct: float = 20.0   # below this, supply is at risk
    window_weeks: int = 4             # how many recent weeks give the rate of decline
    high_score: float = 50.0          # settlement risk class thresholds
    medium_score: float = 25.0


def reservoir_status(obs: pd.DataFrame, total_capacity_m3: float, s: Settings) -> dict:
    """Current state and time to the critical threshold for one reservoir.

    obs needs the columns obs_date, fill_pct and season_norm_pct, one row per week.
    """
    obs = obs.sort_values("obs_date")
    fills = obs["fill_pct"].astype(float).tolist()
    norms = obs["season_norm_pct"].astype(float).tolist()
    fill_now, norm_now = fills[-1], norms[-1]
    deviation = fill_now - norm_now  # pp, negative = below the seasonal norm

    drops = [fills[i - 1] - fills[i] for i in range(1, len(fills))][-s.window_weeks:]
    rate = sum(drops) / len(drops) if drops else 0.0  # positive = falling
    room = fill_now - s.critical_fill_pct

    def weeks(r: float) -> float | None:
        if r <= 0:
            return None  # not falling: no threshold crossing expected
        return max(room, 0.0) / r

    status = {
        "fill_pct": fill_now,
        "norm_pct": norm_now,
        "deviation_pp": deviation,
        "rate_pp_week": rate,
        "weeks_to_threshold": weeks(rate),
        "weeks_min": weeks(max(drops)) if drops else None,   # fastest decline, earliest crossing
        "weeks_max": weeks(min(drops)) if drops else None,   # slowest decline, latest crossing
        "rate_fast": max(drops) if drops else 0.0,           # pp per week, fastest recent decline
        "rate_slow": min(drops) if drops else 0.0,           # pp per week, slowest recent decline
        "volume_m3": fill_now / 100.0 * total_capacity_m3,
    }
    status["alert_level"] = traffic_light(status, s)
    return status


def traffic_light(st: dict, s: Settings) -> str:
    """Illustrative rules; the most severe satisfied condition wins."""
    d, w, f = st["deviation_pp"], st["weeks_to_threshold"], st["fill_pct"]
    level = "green"
    if d < -10 or (w is not None and w <= 12):
        level = "yellow"
    if d <= -25 or (w is not None and w < 8):
        level = "orange"
    if (w is not None and w < 4) or f <= s.critical_fill_pct + 5:
        level = "red"
    return level


def forecast(status: dict, horizon_weeks: int = 8) -> pd.DataFrame:
    """Simple linear trend with an interval from the fastest and slowest recent decline."""
    fill = status["fill_pct"]
    rows = []
    for h in range(horizon_weeks + 1):
        rows.append(
            {
                "week_ahead": h,
                "central": min(100.0, max(0.0, fill - status["rate_pp_week"] * h)),
                "lower": min(100.0, max(0.0, fill - status["rate_fast"] * h)),
                "upper": min(100.0, max(0.0, fill - status["rate_slow"] * h)),
            }
        )
    return pd.DataFrame(rows)


def settlement_risk(
    settlements: pd.DataFrame,
    links: pd.DataFrame,
    alerts: dict[int, str],
    weeks_to_threshold: dict[int, float | None],
    s: Settings,
) -> pd.DataFrame:
    """Rank settlements. score = 100 x exposure x (0.7 + 0.2 x population term + 0.1 x critical facility).

    exposure = sum over reservoirs of: supply share x (1 - backup share) x alert factor, capped at 1.
    A settlement that depends only on green reservoirs therefore scores 0.
    """
    rows = []
    for _, st in settlements.iterrows():
        sl = links[links["settlement_id"] == st["settlement_id"]]
        exposure = 0.0
        worst_alert = "green"
        weeks_list = []
        for _, ln in sl.iterrows():
            rid = int(ln["reservoir_id"])
            level = alerts.get(rid, "green")
            share = float(ln["supply_share_pct"]) / 100.0
            backup = float(ln["backup_share_pct"]) / 100.0
            exposure += share * (1.0 - backup) * ALERT_FACTOR[level]
            if ALERT_ORDER.index(level) > ALERT_ORDER.index(worst_alert):
                worst_alert = level
            w = weeks_to_threshold.get(rid)
            if w is not None and ALERT_FACTOR[level] > 0:
                weeks_list.append(w)
        exposure = min(exposure, 1.0)
        pop_term = min(float(st["population"]) / 4000.0, 1.0)
        crit = 1.0 if int(st["has_critical_facility"]) else 0.0
        score = 100.0 * exposure * (0.7 + 0.2 * pop_term + 0.1 * crit)
        cls = "high" if score >= s.high_score else "medium" if score >= s.medium_score else "low"
        rows.append(
            {
                "settlement_id": st["settlement_id"],
                "name": st["name"],
                "population": int(st["population"]),
                "critical_facility": bool(crit),
                "exposure_pct": round(exposure * 100.0, 1),
                "risk_score": round(score, 1),
                "risk_class": cls,
                "worst_reservoir_alert": worst_alert,
                "weeks_to_threshold": min(weeks_list) if weeks_list else None,
                "lat": st["lat"],
                "lon": st["lon"],
            }
        )
    out = pd.DataFrame(rows).sort_values("risk_score", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", out.index + 1)
    return out


def explain(row: pd.Series, reservoir_names: str = "") -> str:
    """Plain-language explanation built from computed numbers. A language model could rewrite it,
    but it never changes the numbers or the class."""
    w = row["weeks_to_threshold"]
    when = f"about {w:.1f} weeks" if w is not None and pd.notna(w) else "no crossing is expected at the current rate"
    return (
        f"{row['name']}: {row['risk_class']} risk (score {row['risk_score']:.0f} of 100). "
        f"Dependence on reservoirs in alert, after backup sources: {row['exposure_pct']:.0f}%. "
        f"Worst reservoir alert level: {row['worst_reservoir_alert']}. "
        f"Time to the critical threshold of the most affected reservoir: {when}. "
        f"Population: {row['population']:,}"
        + ("; has a critical facility (hospital or school)." if row["critical_facility"] else ".")
    )
