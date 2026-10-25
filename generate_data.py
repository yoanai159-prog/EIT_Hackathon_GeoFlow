"""Generate the SIMULATED example data in ./data (no real reservoirs, no real measurements).

Run:  python generate_data.py
The names, coordinates and numbers are invented for the demo. Observations are flagged
quality_flag = "simulated" so they are never mixed with real data.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)
rng = random.Random(42)

WEEKS = 12
END = date(2026, 10, 3)

# reservoir_id, name, capacity_m3, lat, lon, fill_at_end, weekly_decline, norm_start, norm_end
RESERVOIRS = [
    (1, "Reservoir Alpha", 790_000, 42.70, 24.90, 34.0, 2.3, 66.0, 61.0),
    (2, "Reservoir Beta", 1_450_000, 42.95, 25.70, 71.0, 0.6, 68.0, 66.0),
    (3, "Reservoir Gamma", 520_000, 42.40, 25.30, 24.0, 2.8, 60.0, 55.0),
]

# Reservoir Alpha follows the exact numbers used in the pitch (34% full, norm 61%, 2.25 pp per week).
EXPLICIT = {
    1: (
        [64, 61, 58, 55, 52, 49, 46, 43, 41, 38, 36, 34],
        [67, 66, 65, 64, 64, 63, 62, 62, 61, 61, 61, 61],
    )
}

# settlement_id, name, lat, lon, population, has_critical_facility
SETTLEMENTS = [
    (101, "Village A", 42.74, 24.82, 2400, 1),
    (102, "Village B", 42.66, 24.97, 1150, 0),
    (103, "Village C", 42.78, 25.02, 3800, 1),
    (104, "Village D", 42.90, 25.55, 600, 0),
    (105, "Village E", 42.36, 25.22, 1800, 0),
    (106, "Village F", 42.45, 25.40, 950, 1),
    (107, "Village G", 43.02, 25.78, 3100, 1),
    (108, "Village H", 42.58, 25.35, 700, 0),
]

# reservoir_id, settlement_id, supply_share_pct, backup_share_pct, daily_demand_m3
LINKS = [
    (1, 101, 100, 0, 360.0),
    (1, 102, 100, 40, 172.5),
    (1, 103, 60, 60, 342.0),
    (2, 104, 100, 0, 90.0),
    (2, 107, 100, 0, 280.0),
    (2, 108, 50, 30, 60.0),
    (3, 105, 100, 0, 160.0),
    (3, 106, 70, 20, 85.0),
    (3, 108, 50, 30, 60.0),
]


def write(name, header, rows):
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    write(
        "reservoirs.csv",
        ["reservoir_id", "name", "total_capacity_m3", "lat", "lon"],
        [(r[0], r[1], r[2], r[3], r[4]) for r in RESERVOIRS],
    )
    write(
        "settlements.csv",
        ["settlement_id", "name", "lat", "lon", "population", "has_critical_facility"],
        SETTLEMENTS,
    )
    write(
        "supply_links.csv",
        ["reservoir_id", "settlement_id", "supply_share_pct", "backup_share_pct", "daily_demand_m3"],
        LINKS,
    )

    obs = []
    for rid, _name, _cap, _lat, _lon, fill_end, decline, n0, n1 in RESERVOIRS:
        if rid in EXPLICIT:
            fills, norms = EXPLICIT[rid]
        else:
            # walk backwards from the end value so each reservoir finishes at its target fill
            fills = [fill_end]
            for _ in range(WEEKS - 1):
                fills.append(fills[-1] + decline + rng.uniform(-0.4, 0.4))
            fills.reverse()
            norms = [n0 + (n1 - n0) * i / (WEEKS - 1) for i in range(WEEKS)]
        for i in range(WEEKS):
            d = END - timedelta(weeks=WEEKS - 1 - i)
            norm = norms[i]
            obs.append(
                (rid, d.isoformat(), round(fills[i], 1), round(norm, 1), round(rng.uniform(0, 4), 1), "simulated")
            )
    write(
        "reservoir_observations.csv",
        ["reservoir_id", "obs_date", "fill_pct", "season_norm_pct", "rain_mm", "quality_flag"],
        obs,
    )
    print("Simulated data written to", OUT)


if __name__ == "__main__":
    main()
