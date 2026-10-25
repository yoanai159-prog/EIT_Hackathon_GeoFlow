"""Tests for the Ticha real-data functions (core/ticha.py) and the shipped data files."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import ticha  # noqa: E402


def synthetic_daily(net_mm3_day=-0.1, days=30, v0=200.0):
    """Daily bulletins whose volume falls by exactly net_mm3_day, with inflow/outflow consistent with it."""
    idx = pd.date_range("2026-09-01", periods=days)
    q = net_mm3_day / ticha.MM3_PER_M3S_DAY            # m3/s
    return pd.DataFrame({"date": idx, "avail_mm3": [v0 + net_mm3_day * i for i in range(days)],
                         "inflow_m3s": 0.0, "outflow_m3s": -q})


def test_mann_kendall_and_theil_sen_on_a_line():
    tau, p = ticha.mann_kendall(range(12))
    assert tau == pytest.approx(1.0) and p < 0.001
    assert ticha.theil_sen([2014, 2015, 2016, 2017], [10, 8, 6, 4]) == pytest.approx(-2.0)
    tau, p = ticha.mann_kendall([5, 5, 5, 5, 5])
    assert tau == 0.0 and p == 1.0


def test_mann_kendall_agrees_with_scipy_roughly():
    stats = pytest.importorskip("scipy.stats")
    y = [242, 265, 247, 242, 264, 205, 155, 217, 243, 211, 170, 150]
    tau, p = ticha.mann_kendall(y)
    t2, p2 = stats.kendalltau(range(12), y)
    assert tau == pytest.approx(t2, abs=0.02) and abs(p - p2) < 0.01


def test_norm_interpolates_and_wraps():
    norm = pd.Series({m: float(m) for m in range(1, 13)})
    assert ticha.norm_at(norm, pd.Timestamp("2026-03-16")) == pytest.approx(3.0, abs=0.05)   # mid-March
    # 1 January lies between mid-December (12) and mid-January (1), so the value is in between
    assert 5.0 < ticha.norm_at(norm, pd.Timestamp("2026-01-01")) < 8.0
    assert 5.0 < ticha.norm_at(norm, pd.Timestamp("2026-12-31")) < 9.0


def test_balance_forecast_continues_the_rate():
    d = synthetic_daily(-0.1)
    fc = ticha.balance_forecast(d, horizon_days=10)
    assert fc.central.iloc[0] == pytest.approx(d.avail_mm3.iloc[-1])
    assert fc.central.iloc[10] == pytest.approx(d.avail_mm3.iloc[-1] - 1.0, abs=1e-6)
    assert (fc.lower <= fc.central + 1e-9).all() and (fc.central <= fc.upper + 1e-9).all()


def test_backtest_is_exact_for_a_steady_fall():
    bt = ticha.backtest_balance(synthetic_daily(-0.1, days=60), horizons=(7, 14))
    assert (bt.balance_MAE_mm3 < 1e-9).all()
    assert (bt.persistence_MAE_mm3 > 0.5).all()


def test_analog_ensemble_adds_past_changes():
    rows = []
    for y in range(2014, 2020):
        for m in range(1, 13):
            rows.append({"year": y, "month": m, "avail_mm3": 100.0 + (y - 2014) + m})   # +1 per month
    ens = ticha.analog_ensemble(pd.DataFrame(rows), 2019, 6, 3)
    assert ens.shape == (3, 5)
    assert ens.iloc[:, 0].tolist() == [100 + 5 + 7, 100 + 5 + 8, 100 + 5 + 9]   # 2019-06 value is 100+5+6, plus 1, 2, 3
    assert np.allclose(ens.diff().dropna().values, 1.0)    # each scenario rises by 1 per month, like the data


# ---- the shipped data -----------------------------------------------------------------------------

def test_monthly_data_is_consistent():
    m = ticha.load_monthly(ROOT / "data/ticha/ticha_monthly.csv")
    assert not m.duplicated(["year", "month"]).any()
    parts = m[["drinking_shumen_vpreslav_mm3", "drinking_targovishte_mm3", "irrigation_mm3", "min_flow_mm3", "energy_mm3"]].sum(axis=1)
    bad = m[(parts - m.release_total_mm3).abs() > 0.05]
    assert set(zip(bad.year, bad.month)) <= {(2018, 8)}          # one known inconsistency in the source
    assert ((m.avail_mm3 - m.usable_mm3 - 40).abs() < 0.01).sum() >= len(m) - 2   # usable = available - dead volume (2018-04 typo)
    assert m.query("year == 2026 and month == 10").fill_pct.iloc[0] == pytest.approx(79.2, abs=0.05)


def test_daily_balance_closes():
    d = ticha.load_daily(ROOT / "data/ticha/ticha_daily.csv")
    assert d.date.is_unique and len(d) >= 40
    s = d.set_index("date")
    step = s.avail_mm3.diff()[s.index.to_series().diff().dt.days == 1]
    bal = ticha.daily_net(d).reindex(step.index)
    assert (step - bal).abs().max() < 0.01       # change of the volume = (inflow - outflow) x 0.0864
