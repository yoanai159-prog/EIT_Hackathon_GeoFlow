"""Pilot territory Shumen: settlements that depend on Ticha, their demand, and the radar overlay for the map."""
from pathlib import Path

import pandas as pd

from core import scenarios as sc
from core import ticha


def load_assumptions(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = data_dir / "pilot"
    s = pd.read_csv(d / "settlements.csv")
    s["critical_facility"] = s["critical_facility"].astype(bool)
    return s, pd.read_csv(d / "sources.csv")


def with_demand(settlements: pd.DataFrame, monthly: pd.DataFrame) -> pd.DataFrame:
    """Add `demand_m3_day`: the drinking-water allocation of the latest schedule month, split between the settlements of a
    group by population (an assumption: the schedule gives one figure for Shumen and Veliki Preslav together)."""
    last = monthly.iloc[-1]
    days = last.date.days_in_month
    total = {"shumen_vpreslav": last.drinking_shumen_vpreslav_mm3, "targovishte": last.drinking_targovishte_mm3}
    out = settlements.copy()
    pop_by_group = out.groupby("supply_group").population.transform("sum")
    out["demand_m3_day"] = [total[g] * 1e6 / days * p / tot for g, p, tot in zip(out.supply_group, out.population, pop_by_group)]
    out.attrs["month"] = f"{last.date:%B %Y}"
    return out


def donors(bulletin: pd.DataFrame, sources: pd.DataFrame) -> pd.DataFrame:
    """Sources with the real state of the donor reservoir from the latest bulletin; a link works only if the donor is full enough."""
    b = bulletin.set_index("reservoir")
    s = sources.copy()
    s["donor_fill_pct"] = [float(b.fill_pct.get(n, float("nan"))) for n in s.donor_reservoir]
    s["donor_usable_mm3"] = [float(b.usable_mm3.get(n, float("nan"))) for n in s.donor_reservoir]
    s["available"] = s.active.astype(bool) & (s.donor_fill_pct >= s.min_donor_fill_pct)
    return s


def reservoir_center(data_dir: Path, default=(43.0556, 26.7559)) -> tuple[float, float]:
    """(lat, lon) of the centre of the Ticha water polygon (Sentinel-2, current extent); the radar starts here."""
    f = data_dir / "satellite_observations.csv"
    try:
        o = pd.read_csv(f).set_index("role").loc["current"]
        return float(o.centroid_lat), float(o.centroid_lon)
    except Exception:
        return default


def radar_config(settlements: pd.DataFrame, plan: pd.DataFrame, fill_pct: float, a: sc.Assumptions, scenario: str,
                 visible: bool, center=(43.0556, 26.7559)) -> dict:
    """Config for the radar overlay of map_view: Ticha in the middle, one risk marker per dependent settlement."""
    nodes = []
    p = plan.set_index("settlement")
    for r in settlements.itertuples():
        risk = sc.settlement_risk(fill_pct, r.dependence, r.backup_m3_day > 0, a)
        row = p.loc[r.name]
        nodes.append({"name": r.name, "lat": r.lat, "lon": r.lon, "level": risk["level"], "risk_pct": round(risk["risk"] * 100),
                      "share": float(r.dependence), "backup": bool(r.backup_m3_day > 0),
                      "rows": [["Population", f"{int(r.population):,}"], ["Demand, m3/day", f"{r.demand_m3_day:,.0f}"],
                               ["Dependence on Ticha", f"{r.dependence:.0%} (assumption)"],
                               ["From Ticha, m3/day", f"{row['from reservoir (m3/day)']:,.0f}"],
                               ["Unmet, m3/day", f"{row['unmet (m3/day)']:,.0f}"], ["Action", risk["action"]]]})
    return {"center": list(center), "name": "Ticha", "caption": f"{fill_pct:.1f}% full", "scenario": scenario,
            "rings_km": [10, 20, 30], "visible": visible, "nodes": nodes}
