"""Tests for the transparent rules. Run with:  pytest"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.logic import Settings, forecast, reservoir_status, settlement_risk, traffic_light  # noqa: E402

S = Settings()


def obs(fills, norms=None):
    n = len(fills)
    norms = norms or [60.0] * n
    return pd.DataFrame(
        {
            "obs_date": pd.date_range("2026-08-01", periods=n, freq="7D"),
            "fill_pct": fills,
            "season_norm_pct": norms,
        }
    )


def test_demo_reservoir_is_orange():
    # the example used in the pitch: 34% full, norm 61%, falling 2.25 pp per week
    o = obs([43, 41, 38, 36, 34], [62, 61, 61, 61, 61])
    st = reservoir_status(o, 790_000, S)
    assert round(st["deviation_pp"]) == -27
    assert round(st["rate_pp_week"], 2) == 2.25
    assert abs(st["weeks_to_threshold"] - 6.2) < 0.1
    assert st["weeks_min"] < st["weeks_to_threshold"] < st["weeks_max"]
    assert st["alert_level"] == "orange"
    assert round(st["volume_m3"]) == 268_600


def test_stable_reservoir_is_green_and_has_no_crossing():
    st = reservoir_status(obs([70, 70, 70, 70], [68] * 4), 1_000_000, S)
    assert st["weeks_to_threshold"] is None
    assert st["alert_level"] == "green"


def test_near_critical_level_is_red():
    st = reservoir_status(obs([30, 28, 26, 24], [55] * 4), 500_000, S)
    assert st["alert_level"] == "red"


def test_rising_reservoir_has_no_weeks_to_threshold():
    st = reservoir_status(obs([40, 42, 44, 46], [50] * 4), 500_000, S)
    assert st["weeks_to_threshold"] is None


def test_traffic_light_never_improves_with_a_lower_fill():
    order = ["green", "yellow", "orange", "red"]
    levels = []
    for fill in [80, 60, 45, 35, 28, 22]:
        # same 2 pp per week decline, norm fixed at 70
        o = obs([fill + 6, fill + 4, fill + 2, fill], [70] * 4)
        levels.append(order.index(reservoir_status(o, 1, S)["alert_level"]))
    assert levels == sorted(levels)


def test_forecast_interval_brackets_central_line():
    st = reservoir_status(obs([43, 41, 38, 36, 34]), 790_000, S)
    fc = forecast(st, 8)
    assert len(fc) == 9
    assert (fc["lower"] <= fc["central"] + 1e-9).all()
    assert (fc["central"] <= fc["upper"] + 1e-9).all()
    assert fc["lower"].min() >= 0 and fc["upper"].max() <= 100


def _settlements():
    return pd.DataFrame(
        {
            "settlement_id": [1, 2, 3],
            "name": ["A", "B", "C"],
            "population": [2400, 2400, 2400],
            "has_critical_facility": [1, 1, 1],
            "lat": [0, 0, 0],
            "lon": [0, 0, 0],
        }
    )


def _links():
    return pd.DataFrame(
        {
            "reservoir_id": [1, 1, 2],
            "settlement_id": [1, 2, 3],
            "supply_share_pct": [100, 100, 100],
            "backup_share_pct": [0, 60, 0],
            "daily_demand_m3": [100.0, 100.0, 100.0],
        }
    )


def test_green_reservoir_gives_zero_risk():
    r = settlement_risk(_settlements(), _links(), {1: "orange", 2: "green"}, {1: 6.0, 2: None}, S)
    c = r[r["name"] == "C"].iloc[0]
    assert c["risk_score"] == 0 and c["risk_class"] == "low"


def test_backup_lowers_risk_and_ranking_is_sorted():
    r = settlement_risk(_settlements(), _links(), {1: "orange", 2: "green"}, {1: 6.0, 2: None}, S)
    a = r[r["name"] == "A"].iloc[0]
    b = r[r["name"] == "B"].iloc[0]
    assert a["risk_score"] > b["risk_score"]
    assert list(r["risk_score"]) == sorted(r["risk_score"], reverse=True)
    assert list(r["rank"]) == [1, 2, 3]


def test_worse_alert_never_lowers_risk():
    scores = []
    for level in ["green", "yellow", "orange", "red"]:
        r = settlement_risk(_settlements(), _links(), {1: level, 2: "green"}, {1: 6.0, 2: None}, S)
        scores.append(r[r["name"] == "A"].iloc[0]["risk_score"])
    assert scores == sorted(scores)


def test_score_stays_in_range():
    r = settlement_risk(_settlements(), _links(), {1: "red", 2: "red"}, {1: 1.0, 2: 1.0}, S)
    assert r["risk_score"].between(0, 100).all()


def test_traffic_light_function_matches_status():
    st = {"deviation_pp": -30.0, "weeks_to_threshold": 10.0, "fill_pct": 40.0}
    assert traffic_light(st, S) == "orange"
