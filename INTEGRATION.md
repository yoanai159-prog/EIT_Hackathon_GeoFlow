# What changed in this version

This folder is the complete demo, ready to run. It merges the colleague's satellite and leak-detection code with the
team's work:

1. `satellite_tab.py`, `core/satellite.py`, `satellite_update.py` (real Sentinel-2 water surface for Ticha) and
   `leak_tab.py`, `core/leaks.py` (simulated leak detection) are kept as they were. Only the satellite map changed:
   it now uses the same OSM map as the Map tab, with popups.
2. New Map tab: `map_view.py`, `core/geo.py`, `core/styles.py`. `pydeck` is no longer needed.
3. New tab "Ticha (real data)": `ticha_tab.py`, `core/ticha.py`, `data/ticha/`.
4. Tests: `tests/test_geo.py`, `tests/test_ticha.py` (the colleague's tests are unchanged).

Run: `pip install -r requirements.txt` then `streamlit run app.py`. Tests: `pytest`.
