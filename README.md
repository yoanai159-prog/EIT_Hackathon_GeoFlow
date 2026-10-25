# Drought early warning: demo

A small, runnable demo of an early-warning platform for reservoirs and the settlements that depend on them.
It was built for EIT Water Hackathon Sofia 2026.

> **Most data in this repository are simulated** (everything except `data/ticha/` and the satellite files). Reservoir and village names, locations and numbers are invented.
> The demo is not a hydrological model and must not be used for operational decisions.

## What is new in this version (DryRadar, pilot Shumen)

- **Platform shell.** Left navigation: Map, Reservoir, Analytics, Scenarios, Settings, Simulated demo, About. Logo in `assets/`.
- **Map, Shumen only.** Pale OSM vector layers (land use, municipalities, reservoirs, rivers, settlements) with one legend per layer, shown
  only while the layer is on. Base map switch: OSM, pale OSM, none. UTM 35N (EPSG:32635) coordinates, scale bar, click popups.
  Sentinel-2 water extents of Ticha and a radar overlay of the dependent settlements. The big points elsewhere in the country are gone.
- **Reservoir.** Real Ticha data: traffic light, 14-day forecast (water balance from the bulletins) with a tested error, and the satellite
  section checked against the bulletin of the same day (05.10.2026).
- **Scenarios (module 2).** Optimistic, baseline, pessimistic and stress-test paths; priority by settlement; rerouting to other sources;
  expected restrictions on other uses from the history of restrictions. Dependence, backup sources and transfer links are
  **demonstration assumptions**, editable on the page.
- **Vector import.** `python prepare_vectors.py <folder with .gpkg>` makes light GeoJSON in UTM 35N; the cadastre is summarised, not drawn.
- **Corrections round 2.** About is the first page; object names on the map; click popups fixed (one shared canvas); urbanised cadastral
  parcels of the town of Shumen; radar starts at the centre of the Ticha water polygon (no ellipse); Reservoir page starts with the satellite
  view and ends with the trend and forecast (marked as demo); every chart names its axes, units and source; the 2026 long-range test was removed.
- **Demo scenario** (page, or `streamlit run demo_scenario.py`): a hypothetical drought at Ticha, step by step (normal, early warning, prepare, shortage),
  with the priority plan, the alternative source and the water it covers. Real Ticha data; the decline and the links are assumptions.
- The *Simulated demo* page keeps the old invented network and the leak detection.

## What it shows

1. **Reservoir status.** Fill against the seasonal norm, rate of decline, weeks to a critical threshold (with a range).
2. **Traffic light.** Green, yellow, orange or red from transparent, tunable rules.
3. **Trend forecast.** A linear trend with an interval from the fastest and slowest recent decline.
4. **Ranked settlements.** Risk from how much each settlement depends on reservoirs in alert, after backup sources.
5. **Early leak detection.** Minimum night flow per supply zone against its own normal; flags a suspected leak after
   a few days and estimates the water lost (m3/day). Simulated hourly inflow data.
6. **Plain-language explanation.** Built from the computed numbers. A language model could reword it, but it never
   changes a number or a class.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Optional: `pip install -r requirements-vectors.txt` (read .gpkg and .shp), `pip install -r requirements-satellite.txt` (refresh the satellite files).
The map needs internet in the browser (OpenStreetMap tiles and the Leaflet script).

The app opens at http://localhost:8501. Use the sidebar to change the critical threshold and the number of weeks
used for the trend, and watch the alert levels and the ranking change.

To regenerate the simulated data: `python generate_data.py`. To run the tests: `pytest`.

## Repository layout

| Path | What it is |
| --- | --- |
| `app.py` | Streamlit interface: map, reservoirs, settlements at risk, about |
| `core/logic.py` | The rules: reservoir status, traffic light, forecast, settlement risk, explanation |
| `core/geo.py` | WGS 84 <-> UTM 35N (EPSG:32635) in pure Python, GeoJSON reprojection |
| `core/styles.py` | Layer styles (single, categorized, graduated) and the QGIS `.qml` converter |
| `core/ticha.py` | Ticha: seasonal norm, trend tests, balance forecast, backtest, scenarios |
| `map_view.py` | The web map (Leaflet page) and the loader for `data/vectors/` |
| `ticha_tab.py` | The Ticha tab |
| `data/ticha/` | REAL MOEW data for Ticha (schedules, bulletins) and its known problems |
| `data/vectors/` | Your own vector layers (see its README) |
| `core/leaks.py` | Leak detection from the minimum night flow of a supply zone |
| `leak_tab.py` | The Leaks tab |
| `generate_leak_data.py` | Creates `data/flow_observations.csv` (simulated hourly inflow, two zones with an injected leak) |
| `data/` | Simulated CSV files (reservoirs, observations, settlements, supply links) |
| `generate_data.py` | Creates the files in `data/` |
| `tests/test_logic.py` | Unit tests for the rules |
| `docs/data_schema.md` | How the demo files map to the full 11-table data model |
| `.github/workflows/ci.yml` | Runs the tests on every push and pull request |

## The rules

- **Deviation** D = fill − seasonal norm, in percentage points (pp).
- **Weeks to threshold** W = (fill − critical fill) / weekly decline. No crossing is reported when the reservoir is not falling.
- **Traffic light** (illustrative defaults):

| Level | Condition |
| --- | --- |
| Green | none of the below |
| Yellow | D < −10 pp, or W ≤ 12 weeks |
| Orange | D ≤ −25 pp, or W < 8 weeks |
| Red | W < 4 weeks, or fill ≤ critical + 5 pp |

- **Settlement exposure** = sum over reservoirs of supply share × (1 − backup share) × alert factor
  (green 0, yellow 0.4, orange 0.7, red 1), capped at 1.
- **Settlement score** = 100 × exposure × (0.7 + 0.2 × population term + 0.1 × critical facility).
  Classes: high ≥ 50, medium ≥ 25, otherwise low. A settlement that depends only on green reservoirs scores 0.

All thresholds and weights are illustrative. In a real pilot they are agreed with the reservoir operator, the water
utility and the basin directorate.

## Limits

- The forecast is a trend or a water balance, not a model of inflow, rainfall or evaporation. For Ticha it is tested to about 4 weeks; beyond that only scenarios are shown (2026 had a wet spring that no past-volume model foresaw).
- The map draws OpenStreetMap tiles in Web Mercator (EPSG:3857); a browser map cannot show them in another projection. Coordinates, the grid and the attributes are in EPSG:32635. Public OSM tile servers are for light use: a public deployment needs its own tile provider.
- Level and volume from satellite images need the reservoir's level–area–volume curve; this demo uses fill in percent only.
- Results should always be shown with their interval and their source.

## Next steps for a pilot

1. Replace the simulated files in `data/` with real observations (Ticha already has them) (Sentinel-1 and Sentinel-2 surface area, operator data, sensors).
2. Add the level–area–volume curve per reservoir and compute volume from it.
3. Add drought indices (SPI, SPEI, soil moisture, FAPAR) from Copernicus and EDO.
4. Agree thresholds and the supply links with the operator.

## Publish it on GitHub

```bash
git init
git add .
git commit -m "Drought early warning demo"
git branch -M main
git remote add origin https://github.com/<your-user>/drought-early-warning-demo.git
git push -u origin main
```

To host the app for free, deploy it from the repository on Streamlit Community Cloud
(choose `app.py` as the main file). Add a licence file of your choice (for example MIT) before making the repository public.
