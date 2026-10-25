"""Prepare the Shumen vector layers for the web map. Run once after exporting GeoPackages from QGIS:

    python prepare_vectors.py  <folder with the .gpkg and .qml files>

For each light layer it writes data/vectors/<name>.geojson (EPSG:32635, simplified, rounded to 0.1 m) and copies <name>.qml.
Of the heavy cadastre only the URBANISED parcels of Shumen municipality go to the browser (Cadastre_urban.geojson); the rest is not sent; they are summarised per
settlement in data/pilot/cadastre_summary.csv instead. Needs only the Python standard library and this repo.
"""
import csv
import shutil
import sqlite3
import sys
from pathlib import Path

from core import gpkg

HERE = Path(__file__).parent
OUT = HERE / "data" / "vectors"
LAYERS = {   # name: (simplify tolerance m, minimum polygon part area m2, columns to drop)
    "Shumen_Muni": (30, 0, ("GID_0", "GID_1", "NL_NAME_1", "VARNAME_2", "NL_NAME_2", "CC_2", "ENGTYPE_2", "COUNTRY")),
    "Settlements_OSM": (0, 0, ()),
    "Reservoirs_OSM": (4, 400, ()),
    "Rivers_OSM": (8, 0, ("osm_id_2", "code_2", "fclass_2", "name_2")),
    "Landuse_OSM": (12, 2500, ("osm_id_2", "code_2", "fclass_2", "name_2")),
}


def main(src: Path):
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (tol, min_area, drop) in LAYERS.items():
        f = src / f"{name}.gpkg"
        if not f.exists():
            print("missing", f)
            continue
        fc = gpkg.read_gpkg(str(f), drop_columns=drop)
        n0 = len(fc["features"])
        feats = []
        for ft in fc["features"]:
            g = gpkg.simplify_geometry(ft["geometry"], tol, min_area, decimals=1)
            if g is not None:
                ft["geometry"] = g
                feats.append(ft)
        fc["features"] = feats
        path = OUT / f"{name}.geojson"
        gpkg.write_geojson(fc, str(path))
        if (src / f"{name}.qml").exists():
            shutil.copy(src / f"{name}.qml", OUT / f"{name}.qml")
        print(f"{name}: {n0} -> {len(feats)} features, {path.stat().st_size / 1e6:.2f} MB")
    urban_parcels(src)
    cadastre_summary(src)


def urban_parcels(src: Path, municipality="Шумен", place="гр.Шумен", tol=2.0, decimals=0):
    """Urbanised cadastral parcels of the town of Shumen (the other parcel types and villages stay out: 24 thousand
    urbanised parcels in the municipality would make the page 13 MB; set place=None for all of them).
    Keeps a few attributes. Written to data/vectors/Cadastre_urban.geojson (EPSG:32635)."""
    f = src / "Cadastral_parcels.gpkg"
    if not f.exists():
        print("missing", f)
        return
    keep = ("cadnum", "usetype", "naseleno_myasto", "AREA")
    feats = []
    for ft in gpkg.iter_features(str(f), "Cadastral_parcels"):
        pr = ft["properties"]
        if pr.get("obshtina") != municipality or not str(pr.get("purptype") or "").startswith("Урбан") \
                or (place and pr.get("naseleno_myasto") != place):
            continue
        g = gpkg.simplify_geometry(ft["geometry"], tol, 0, decimals=decimals)
        if g is None:
            continue
        p = {k: pr.get(k) for k in keep}
        p["AREA"] = round(p["AREA"] or 0)
        feats.append({"type": "Feature", "properties": {k: v for k, v in p.items() if v not in (None, "")}, "geometry": g})
    fc = {"type": "FeatureCollection", "features": feats,
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32635"}}}
    path = OUT / "Cadastre_urban.geojson"
    gpkg.write_geojson(fc, str(path))
    print(f"Cadastre_urban: {len(feats)} parcels, {path.stat().st_size / 1e6:.2f} MB")


def cadastre_summary(src: Path):
    """Buildings and parcels per settlement, straight from the GeoPackage tables (no geometry needed)."""
    rows = []
    b = src / "Cadastral_buildings.gpkg"
    if b.exists():
        con = sqlite3.connect(f"file:{b}?mode=ro", uri=True)
        for place, n, foot, floor in con.execute(
                'select naseleno_myasto, count(*), sum(AREA), sum(AREA * coalesce(flrcount, 1)) from Cadastral_buildings group by 1 order by 3 desc'):
            rows.append({"table": "buildings", "place": place, "count": n, "footprint_m2": round(foot or 0), "floor_area_m2": round(floor or 0)})
        con.close()
    p = src / "Cadastral_parcels.gpkg"
    if p.exists():
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        for place, purpose, n, area in con.execute(
                'select naseleno_myasto, purptype, count(*), sum(AREA) from Cadastral_parcels group by 1, 2'):
            rows.append({"table": "parcels:" + str(purpose), "place": place, "count": n, "footprint_m2": round(area or 0), "floor_area_m2": ""})
        con.close()
    if rows:
        d = HERE / "data" / "pilot"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "cadastre_summary.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print("cadastre_summary.csv:", len(rows), "rows")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("."))
