"""Module 2: decisions. If reservoir X cannot cover the settlements that depend on it, who gets the water first,
and where does the missing water come from?

All rules are explicit and editable. Real inputs: the reservoir volume (bulletins), the monthly release plan per use
(schedules) and the history of restrictions (`core.ticha.restriction_ladder`). Everything about the settlements'
dependence on the reservoir, their backup sources and the transfer links is a DEMONSTRATION ASSUMPTION until the water
utilities (ViK) and the basin directorate confirm it. Volumes in mln m3 unless the name says otherwise; flows in m3/day.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

CAPACITY_MM3 = 311.8
DEAD_MM3 = 40.0

# Risk levels as in the team's radar prototype: risk = severity x dependence x (0.5 with a backup source)
LEVELS = [("ok", "Low", 0.15), ("warn", "Attention", 0.35), ("high", "High", 0.60), ("crit", "Critical", 9.0)]
ACTIONS = {
    "ok": "Watch the bulletins.",
    "warn": "Warn the water utility and the municipality.",
    "high": "Prepare a restriction plan and the backup source.",
    "crit": "Restrictions and alternative supply now.",
}


@dataclass(frozen=True)
class Assumptions:
    risk_starts_fill_pct: float = 50.0     # below this fill the risk starts to grow (prototype value)
    critical_fill_pct: float = 20.0        # critical threshold (same as the sidebar setting)
    backup_factor: float = 0.5             # a backup source halves the risk (prototype value)


def level_for(risk: float) -> tuple[str, str]:
    for key, name, mx in LEVELS:
        if risk < mx:
            return key, name
    return LEVELS[-1][0], LEVELS[-1][1]


def severity(fill_pct: float, a: Assumptions) -> float:
    """0 at `risk_starts_fill_pct` and above, 1 at the critical fill and below, linear in between."""
    span = a.risk_starts_fill_pct - a.critical_fill_pct
    return float(min(1.0, max(0.0, (a.risk_starts_fill_pct - fill_pct) / span))) if span > 0 else 0.0


def settlement_risk(fill_pct: float, dependence: float, has_backup: bool, a: Assumptions) -> dict:
    r = severity(fill_pct, a) * dependence * (a.backup_factor if has_backup else 1.0)
    key, name = level_for(r)
    return {"risk": r, "level": key, "level_name": name, "action": ACTIONS[key]}


def drinking_coverage(volume_mm3: float, a: Assumptions) -> float:
    """Share of the drinking-water demand the reservoir can still deliver (0 to 1).

    Full coverage down to the critical volume. Below it only the water above the dead volume is left, so the
    coverage falls linearly to 0 at the dead volume. An illustrative rule, to be agreed with the operator.
    """
    v_crit = a.critical_fill_pct / 100.0 * CAPACITY_MM3
    if volume_mm3 >= v_crit:
        return 1.0
    return float(max(0.0, (volume_mm3 - DEAD_MM3) / (v_crit - DEAD_MM3)))


def week_reaching(path: pd.Series, a: Assumptions, dependence: float, has_backup: bool) -> dict:
    """First week at which the risk level is Attention, High and Critical along a volume path (index = week)."""
    out = {"warn": None, "high": None, "crit": None}
    order = ["ok", "warn", "high", "crit"]
    for wk, v in path.items():
        lvl = settlement_risk(v / CAPACITY_MM3 * 100.0, dependence, has_backup, a)["level"]
        for k in ("warn", "high", "crit"):
            if out[k] is None and order.index(lvl) >= order.index(k):
                out[k] = int(wk)
    return out


def priority_order(settlements: pd.DataFrame) -> pd.DataFrame:
    """Priority 1 first: critical facilities, then larger population. A user-set `priority` column wins when present."""
    s = settlements.copy()
    if "priority" in s.columns and s["priority"].notna().all():
        return s.sort_values("priority").reset_index(drop=True)
    crit = s["critical_facility"].astype(bool) if "critical_facility" in s else pd.Series(False, index=s.index)
    s["_k"] = list(zip(~crit, -s["population"]))
    s = s.sort_values("_k").drop(columns="_k").reset_index(drop=True)
    s["priority"] = range(1, len(s) + 1)
    return s


def plan_supply(volume_mm3: float, settlements: pd.DataFrame, sources: pd.DataFrame, a: Assumptions) -> pd.DataFrame:
    """Who gets what when the reservoir holds `volume_mm3`.

    settlements: name, population, demand_m3_day (the settlement's total drinking-water demand), dependence (0 to 1,
        the share of it that comes from the reservoir), backup_m3_day (local backup source), priority (optional).
    sources: name, kind ("transfer"), capacity_m3_day, serves (settlement name, or "all"), active (bool).
    Steps, in the order of priority of the settlements:
        1. the reservoir delivers `coverage` x demand to the settlement, until its deliverable water is used up;
        2. a local backup source covers what is missing, up to its capacity;
        3. transfer links (from other reservoirs) cover what is still missing, up to their capacities;
        4. anything left is unmet: restrictions are needed.
    """
    cov = drinking_coverage(volume_mm3, a)
    s = priority_order(settlements)
    need = (s["demand_m3_day"] * s["dependence"]).to_numpy(float)          # from the reservoir
    other = (s["demand_m3_day"] * (1 - s["dependence"])).to_numpy(float)   # from its own other sources
    deliverable = cov * need.sum()
    pool = {r.name: float(r.capacity_m3_day) for r in sources.itertuples() if bool(getattr(r, "active", True))}
    serves = {r.name: str(r.serves) for r in sources.itertuples()}
    rows, all_parts = [], {}
    for i, r in enumerate(s.itertuples()):
        from_res = min(need[i], deliverable)
        deliverable -= from_res
        gap = need[i] - from_res
        backup = min(gap, float(getattr(r, "backup_m3_day", 0.0) or 0.0))
        gap -= backup
        used, parts_i = [], []
        for name in list(pool):
            if gap <= 1e-9:
                break
            if serves[name] not in ("all", r.name):
                continue
            take = min(gap, pool[name])
            if take > 0:
                pool[name] -= take
                gap -= take
                used.append(f"{name} {take:,.0f}")
                parts_i.append((name, float(take)))
                all_parts[r.name] = parts_i
        transfer = need[i] - from_res - backup - gap
        if need[i] - from_res <= 1e-9:
            action = "Supplied by the reservoir."
        else:
            parts = (["own backup source"] if backup > 0 else []) + ([f"transfer: {'; '.join(used)}"] if used else [])
            action = ("Reroute: " + " + ".join(parts)) if gap <= 1e-9 else \
                     ("Restrictions needed: " + f"{gap:,.0f} m3/day unmet" + (" (after " + " + ".join(parts) + ")" if parts else "") + ".")
        rows.append({"priority": int(r.priority), "settlement": r.name, "population": int(r.population),
                     "demand (m3/day)": r.demand_m3_day, "from reservoir (m3/day)": from_res + 0.0,
                     "own backup (m3/day)": backup, "transfer link (m3/day)": max(transfer, 0.0),
                     "unmet (m3/day)": max(gap, 0.0), "own other sources (m3/day)": other[i],
                     "action": action})
    out = pd.DataFrame(rows)
    out.attrs["coverage"] = cov
    out.attrs["parts"] = all_parts      # settlement -> [(source name, m3/day)]
    return out
