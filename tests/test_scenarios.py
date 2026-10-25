import sqlite3, struct
from pathlib import Path

import pandas as pd

import pilot
from core import gpkg, scenarios as sc, ticha
from core.satellite import consistency

DATA = Path(__file__).resolve().parent.parent / "data"
A = sc.Assumptions()


def test_severity_and_levels():
    assert sc.severity(60, A) == 0 and sc.severity(20, A) == 1 and abs(sc.severity(35, A) - 0.5) < 1e-9
    assert sc.settlement_risk(20, 0.9, False, A)["level"] == "crit"
    assert sc.settlement_risk(20, 0.9, True, A)["risk"] == 0.45


def test_coverage():
    assert sc.drinking_coverage(100, A) == 1.0
    assert sc.drinking_coverage(40, A) == 0.0
    assert 0 < sc.drinking_coverage(50, A) < 1


def _inputs():
    s, src = pilot.load_assumptions(DATA)
    m = ticha.load_monthly(DATA / "ticha" / "ticha_monthly.csv")
    return pilot.with_demand(s, m), src, m


def test_plan_full_and_shortage():
    s, src, _ = _inputs()
    full = sc.plan_supply(250, s, src, A)
    assert full["unmet (m3/day)"].sum() < 1e-6 and full.attrs["coverage"] == 1.0
    low = sc.plan_supply(46, s, src, A)
    assert low["unmet (m3/day)"].sum() > 0
    src2 = src.assign(active=True)
    resc = sc.plan_supply(46, s, src2, A)
    assert resc["unmet (m3/day)"].sum() < low["unmet (m3/day)"].sum()


def test_scenario_paths_and_ladder():
    _, _, m = _inputs()
    p = ticha.scenario_paths(m, 245.0, pd.Timestamp("2026-10-23"), weeks=26)
    assert len(p) == 27 and (p.optimistic >= p.pessimistic - 1e-9).all() and p.baseline.iloc[0] == 245.0
    assert ticha.fastest_decline_pp_week(m) > 0.5
    assert len(ticha.restriction_ladder(m)) == 4


def test_donors():
    s, src = pilot.load_assumptions(DATA)
    b = pd.read_csv(DATA / "pilot" / "bulletin_latest.csv")
    d = pilot.donors(b, src)
    assert not d.available.any() and len(d) == 2


def test_satellite_ref_fill():
    r = consistency(78.66, 85.9, 10.0, ref_fill_pct=93.3)
    assert r["status"] == "consistent"


def _blob(geom_wkb):
    return b"GP" + bytes([0, 1]) + struct.pack("<i", 32635) + geom_wkb


def test_gpkg_roundtrip():
    import tempfile
    tmp_path = Path(tempfile.mkdtemp())
    wkb = struct.pack("<BIdd", 1, 1, 500000.0, 4700000.0)
    p = str(tmp_path / "t.gpkg")
    con = sqlite3.connect(p)
    con.executescript("""create table gpkg_spatial_ref_sys(srs_id int, organization text, organization_coordsys_id int);
    insert into gpkg_spatial_ref_sys values (32635,'EPSG',32635);
    create table gpkg_geometry_columns(table_name text, column_name text, geometry_type_name text, srs_id int);
    insert into gpkg_geometry_columns values ('pts','geom','POINT',32635);
    create table pts(fid integer primary key, geom blob, name text);""")
    con.execute("insert into pts(geom,name) values (?,?)", (_blob(wkb), "a"))
    con.commit(); con.close()
    fc = gpkg.read_gpkg(p)
    assert fc["features"][0]["geometry"]["coordinates"] == [500000.0, 4700000.0]
    assert fc["features"][0]["properties"] == {"name": "a"} and "32635" in fc["crs"]["properties"]["name"]


def test_simplify():
    line = {"type": "LineString", "coordinates": [[0, 0], [5, 0.1], [10, 0]]}
    assert len(gpkg.simplify_geometry(line, 1.0)["coordinates"]) == 2


def test_radar_center_is_water_polygon_centroid():
    lat, lon = pilot.reservoir_center(DATA)
    assert abs(lat - 43.05604) < 1e-4 and abs(lon - 26.75772) < 1e-4


def test_map_page_one_canvas_labels_no_ellipse():
    import map_view
    l = map_view.make_layer("Places", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "A"}, "geometry": {"type": "Point", "coordinates": [500000, 4700000]}}]},
        None, source_epsg=32635, label_field="name", label_minzoom=9)
    html = map_view.map_html([l], radar={"center": [43.05, 26.75], "name": "Ticha", "caption": "x", "scenario": "s",
                                         "rings_km": [10], "visible": True, "nodes": []})
    assert "const REND=L.canvas" in html and "<ellipse" not in html and '"label_field":"name"' in html


def test_story_stages_and_rerouting():
    import pytest
    pytest.importorskip("streamlit")
    import page_story as ps
    s, src, m = _inputs()
    rate = ticha.fastest_decline_pp_week(m)
    path = pd.Series([max(40.0, (40 - rate * w) / 100 * 311.8) for w in range(53)])
    sw = ps.stage_weeks(path, s, A)
    assert sw[4] is not None and sw[4] > (sw[3] or 0)
    v = path[sw[4]]
    act = src.assign(active=True, serves="all")
    none = sc.plan_supply(v, s, src.assign(active=False), A)["unmet (m3/day)"].sum()
    withl = sc.plan_supply(v, s, act, A)["unmet (m3/day)"].sum()
    assert none > 0 and withl < none
    assert "<svg" in ps.flow_svg(sc.plan_supply(v, s, act, A), {}, "Ticha", ["Dibich link"], 18.0)
