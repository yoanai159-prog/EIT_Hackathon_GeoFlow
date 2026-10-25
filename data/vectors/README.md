# Your own vector layers

Put files here and they appear on the Map tab (layer list, popups with all attributes, legend).

| What | How |
| --- | --- |
| Layer | `name.geojson` (best: exported from QGIS in **EPSG:32635**), or `.gpkg` / `.shp` (needs `pip install geopandas`) |
| Style | `name.style.json` next to it, **or** the QGIS style `name.qml` (Layer Properties > Style > Save as QML) |

- GeoJSON in EPSG:32635 or EPSG:4326 is read directly. If the file has no CRS member and the coordinates are in metres,
  EPSG:32635 is assumed. Other systems: reproject in QGIS first, or use `.gpkg` with geopandas.
- Point features get `UTM35N_E_m` and `UTM35N_N_m` (metres) in the popup.
- Styles: single symbol, categorized and graduated, simple fills, lines and markers. Other QGIS symbol types fall back to the default.
- Sub-folders are not read. See `_examples/` for a layer with a style (copy it up one level to see it).

- `Cadastre_urban.geojson` (made by `prepare_vectors.py`) holds only the urbanised parcels of the town of Shumen (about 11 thousand, 4 MB). Other parcels and the buildings are summarised in `data/pilot/cadastre_summary.csv`.
