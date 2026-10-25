"""Generate SIMULATED hourly inflow data for four supply zones, two of them with an injected leak.

Run:  python generate_leak_data.py      (writes data/flow_observations.csv)
Zones are the demo settlements. All numbers are invented; every row has quality_flag = "simulated".
"""
import csv
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "data"
rng = np.random.default_rng(7)

START = datetime(2026, 8, 1)
DAYS = 84                                     # to 2026-10-23
# Typical day profile (hourly weights); normalised below so the mean is 1. Night hours are the quietest.
PROFILE = np.array([0.35, 0.30, 0.25, 0.25, 0.30, 0.55, 1.10, 1.50, 1.40, 1.20, 1.10, 1.10,
                    1.20, 1.10, 1.00, 1.00, 1.10, 1.30, 1.50, 1.40, 1.20, 0.90, 0.60, 0.45])
PROFILE = PROFILE / PROFILE.mean()

# settlement_id: mean demand in m3/day (from supply_links.csv)
ZONES = {101: 360.0, 103: 342.0, 105: 160.0, 106: 85.0}


def leak_m3h(zone, ts):
    """Injected leaks (the only difference between a leaking and a healthy zone)."""
    if zone == 101 and ts >= datetime(2026, 9, 12):          # older leak that keeps growing
        return 1.4 + 0.04 * (ts - datetime(2026, 9, 12)).days
    if zone == 106 and ts >= datetime(2026, 10, 18):         # new small leak
        return 0.45
    return 0.0


def spike_m3h(zone, ts):
    """A harmless one-day event (for example a tank refill) that must NOT raise an alert."""
    if zone == 103 and ts.date() == datetime(2026, 10, 1).date():
        return 2.5
    return 0.0


rows = []
for zone, per_day in ZONES.items():
    mean_h = per_day / 24.0
    for d in range(DAYS):
        day_factor = 1.0 + rng.normal(0, 0.03) + (0.05 if (START + timedelta(days=d)).weekday() >= 5 else 0.0)
        for h in range(24):
            ts = START + timedelta(days=d, hours=h)
            legit = mean_h * PROFILE[h] * day_factor * (1.0 + rng.normal(0, 0.06))
            flow = max(legit + leak_m3h(zone, ts) + spike_m3h(zone, ts), 0.0)
            rows.append((zone, ts.strftime("%Y-%m-%d %H:%M"), round(flow, 2), "simulated"))

with open(OUT / "flow_observations.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["settlement_id", "ts", "inflow_m3_h", "quality_flag"])
    w.writerows(rows)
print("Wrote", OUT / "flow_observations.csv", len(rows), "rows")
