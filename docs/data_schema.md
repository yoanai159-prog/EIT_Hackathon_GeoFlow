# Data schema

The demo uses four simulated CSV files in `data/`. They are a small subset of the full 11-table model of the
platform (PostgreSQL/PostGIS). Units are in the field names: `_m3` cubic metres, `_pct` percent, `_ha` hectares, `_m` metres.
An empty value means "unknown", not zero.

| Demo file | Full-model table | Fields in the demo |
| --- | --- | --- |
| `reservoirs.csv` | `reservoir` | reservoir_id, name, total_capacity_m3, lat, lon |
| `reservoir_observations.csv` | `reservoir_observation` | reservoir_id, obs_date, fill_pct, season_norm_pct, rain_mm, quality_flag |
| `settlements.csv` | `settlement` | settlement_id, name, lat, lon, population, has_critical_facility |
| `flow_observations.csv` | `flow_observation` (time series, TimescaleDB) | settlement_id (the supply zone), ts, inflow_m3_h, quality_flag |
| `supply_links.csv` | `supply_link` | reservoir_id, settlement_id, supply_share_pct, backup_share_pct, daily_demand_m3 |

Computed in `core/logic.py` (these correspond to `forecast` and `risk_assessment` in the full model):
alert level, weeks to threshold, forecast interval, settlement exposure, risk score, risk class and rank.

Not in the demo, but in the full model: `data_source` (every number links to a source), `municipality`,
`reservoir_curve` (level, area and volume), `drought_indicator` (SPI, SPEI, SMA, FAPAR and others) and `citizen_report`.

Every simulated observation has `quality_flag = simulated`, so it cannot be mixed with real data.

## Real data added (Ticha) and map layers

| File | Full-model table | Fields |
| --- | --- | --- |
| `data/ticha/ticha_monthly.csv` | `reservoir_observation` (monthly) + a release plan per use | year, month, avail_mm3, usable_mm3, release_total_mm3, drinking_shumen_vpreslav_mm3, drinking_targovishte_mm3, irrigation_mm3, min_flow_mm3, energy_mm3, fill_pct, source |
| `data/ticha/ticha_daily.csv` | `reservoir_observation` (daily) | date, avail_mm3, fill_pct, usable_mm3, usable_pct, inflow_m3s, outflow_m3s, trend, source_file, source |
| `data/satellite_*.csv/geojson` | `reservoir_observation` (satellite) | water area, scene, cloud cover |
| `data/vectors/*` | spatial layers of the model (municipality, water network, ...) | any attributes; coordinates in EPSG:32635 recommended |

Spatial reference: UTM zone 35N, EPSG:32635, for stored vector data and for the coordinates shown on the map.
