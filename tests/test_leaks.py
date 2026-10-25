import numpy as np
import pandas as pd

from core.leaks import LeakSettings, detect, summarize, explain_leak

S = LeakSettings()
DAYS = pd.date_range("2026-08-01", periods=60)


def series(seed=0, base=4.0, noise=0.06):
    rng = np.random.default_rng(seed)
    return pd.Series(base * (1 + rng.normal(0, noise, len(DAYS))), DAYS)


def test_clean_zone_is_normal():
    res = summarize(detect(series(), S), S)
    assert res["status"] == "normal"
    assert res["lost_m3_day"] == 0.0


def test_step_leak_is_confirmed_and_dated():
    m = series()
    m.iloc[40:] += 1.6  # +40% from day 40
    res = summarize(detect(m, S), S)
    assert res["status"] == "suspected_leak"
    assert res["since"] == DAYS[40].date()
    assert 1.2 < res["leak_m3h"] < 2.0
    assert res["lost_m3_day"] == res["leak_m3h"] * 24


def test_one_day_spike_is_not_a_leak():
    m = series()
    m.iloc[30] += 3.0
    m.iloc[31:] = m.iloc[31:]  # back to normal afterwards
    assert summarize(detect(m, S), S)["status"] == "normal"


def test_first_days_of_a_leak_are_only_watch():
    m = series()
    m.iloc[-2:] += 1.6  # only 2 days so far, confirm_days = 3
    res = summarize(detect(m, S), S)
    assert res["status"] == "watch"
    assert res["run_days"] == 2


def test_slow_leak_cannot_hide_in_the_baseline():
    m = series()
    m.iloc[25:] += 0.08 * np.arange(len(DAYS) - 25)  # grows 0.08 m3/h per day
    res = summarize(detect(m, S), S)
    assert res["status"] == "suspected_leak"
    assert res["since"] < DAYS[45].date()


def test_missing_days_do_not_reset_or_break():
    m = series()
    m.iloc[40:] += 1.6
    m.iloc[45] = np.nan
    assert summarize(detect(m, S), S)["status"] == "suspected_leak"


def test_learning_period():
    m = series().iloc[:5]
    assert summarize(detect(m, S), S)["status"] == "insufficient_data"


def test_explanation_keeps_the_numbers():
    res = {"status": "suspected_leak", "run_days": 4, "baseline_m3h": 4.0, "leak_m3h": 1.5,
           "lost_m3_day": 36.0, "since": pd.Timestamp("2026-09-12").date()}
    text = explain_leak("Village A", res, 360.0)
    assert "36 m3 per day" in text and "10%" in text and "2026-09-12" in text
