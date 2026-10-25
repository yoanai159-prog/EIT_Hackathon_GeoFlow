"""Tests for UTM 35N coordinates, GeoJSON reprojection, styles (incl. QGIS .qml) and the map page."""
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import map_view  # noqa: E402
from core import geo, styles  # noqa: E402

A, F = 6378137.0, 1 / 298.257223563
E2 = F * (2 - F)


def meridian_arc(phi, steps=20000):
    """Independent check: arc length from the equator by Simpson integration."""
    h, total = phi / steps, 0.0
    for i in range(steps + 1):
        p = i * h
        w = 1 if i in (0, steps) else (4 if i % 2 else 2)
        total += w * A * (1 - E2) / (1 - E2 * math.sin(p) ** 2) ** 1.5
    return total * h / 3


@pytest.mark.parametrize("lat", [41.5, 43.05, 44.2])
def test_central_meridian_matches_meridian_arc(lat):
    e, n = geo.lonlat_to_utm35n(27.0, lat)
    assert e == pytest.approx(500000.0, abs=1e-6)
    assert n == pytest.approx(0.9996 * meridian_arc(math.radians(lat)), abs=0.001)


@pytest.mark.parametrize("lon,lat", [(26.8, 43.05), (22.4, 41.9), (28.6, 44.2), (25.0, 42.7)])
def test_roundtrip_is_sub_millimetre(lon, lat):
    e, n = geo.lonlat_to_utm35n(lon, lat)
    lon2, lat2 = geo.utm35n_to_lonlat(e, n)
    assert abs(lon2 - lon) < 1e-8 and abs(lat2 - lat) < 1e-8  # 1e-8 deg is about 1 mm


def test_agrees_with_pyproj_when_installed():
    pyproj = pytest.importorskip("pyproj")
    t = pyproj.Transformer.from_crs(4326, 32635, always_xy=True)
    for lon, lat in [(26.8, 43.05), (22.4, 41.9), (28.6, 44.2)]:
        e, n = geo.lonlat_to_utm35n(lon, lat)
        e2, n2 = t.transform(lon, lat)
        assert abs(e - e2) < 0.002 and abs(n - n2) < 0.002


def test_geojson_utm_to_wgs84_and_guess():
    e, n = geo.lonlat_to_utm35n(26.8, 43.05)
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"a": 1}, "geometry": {"type": "Point", "coordinates": [e, n]}},
        {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": [[e, n], [e + 1000, n]]}}]}
    assert geo.guess_epsg(gj) == 32635                     # metres, no crs member
    out = geo.geojson_to_wgs84(gj)
    lon, lat = out["features"][0]["geometry"]["coordinates"]
    assert (lon, lat) == (pytest.approx(26.8, abs=1e-8), pytest.approx(43.05, abs=1e-8))
    assert gj["features"][0]["geometry"]["coordinates"][0] == e   # input is not modified
    gj["crs"] = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32635"}}
    assert geo.declared_epsg(gj) == 32635
    gj["crs"]["properties"]["name"] = "urn:ogc:def:crs:OGC:1.3:CRS84"
    assert geo.declared_epsg(gj) == 4326


def test_unsupported_crs_is_refused():
    with pytest.raises(ValueError):
        geo.geojson_to_wgs84({"type": "FeatureCollection", "features": []}, source_epsg=32634)


def test_utm_attributes_only_for_points():
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [26.8, 43.05]}},
        {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": [[26, 43], [27, 43]]}}]}
    geo.add_utm_attributes(gj)
    assert gj["features"][0]["properties"]["UTM35N_E_m"] == round(geo.lonlat_to_utm35n(26.8, 43.05)[0])
    assert "UTM35N_E_m" not in gj["features"][1]["properties"]


# ---- styles -------------------------------------------------------------------------------------

CAT = {"type": "categorized", "field": "alert",
       "categories": [{"value": "red", "label": "Red", "style": {"fill": "#d62828"}},
                      {"value": "green", "label": "Green", "style": {"fill": "#2ea043"}}],
       "default": {"fill": "#999999"}}


def test_categorized_and_default():
    assert styles.resolve(CAT, {"alert": "red"})[0]["fill"] == "#d62828"
    assert styles.resolve(CAT, {"alert": "blue"})[0]["fill"] == "#999999"
    assert [r["label"] for r in styles.legend(CAT)] == ["Red", "Green"]


def test_graduated():
    spec = {"type": "graduated", "field": "pop", "ranges": [
        {"min": 0, "max": 999, "style": {"radius": 4}}, {"min": 1000, "max": 99999, "style": {"radius": 9}}]}
    assert styles.resolve(spec, {"pop": 1150})[0]["radius"] == 9
    assert styles.resolve(spec, {"pop": "30"})[0]["radius"] == 4
    assert styles.resolve(spec, {"pop": None})[0]["radius"] == styles.DEFAULT_STYLE["radius"]


QML = """<qgis><renderer-v2 type="categorizedSymbol" attr="alert">
<categories><category symbol="0" value="red" label="Red" render="true"/>
<category symbol="1" value="" label="other" render="true"/></categories>
<symbols>
<symbol name="0" type="fill"><layer class="SimpleFill"><Option type="Map">
<Option name="color" value="214,40,40,128" type="QString"/><Option name="outline_color" value="20,20,20,255" type="QString"/>
<Option name="outline_width" value="0.5" type="QString"/></Option></layer></symbol>
<symbol name="1" type="fill"><layer class="SimpleFill"><prop k="color" v="200,200,200,255"/></layer></symbol>
</symbols></renderer-v2></qgis>"""


def test_qml_categorized():
    spec = styles.qml_to_style(QML)
    assert spec["type"] == "categorized" and spec["field"] == "alert"
    s = spec["categories"][0]["style"]
    assert s["fill"] == "#d62828" and s["fill_opacity"] == pytest.approx(0.502, abs=1e-3)
    assert s["weight"] == pytest.approx(0.5 * 96 / 25.4, abs=0.1)
    assert spec["default"]["fill"] == "#c8c8c8"          # QGIS "all other values"


def test_qml_marker_and_graduated():
    qml = ('<qgis><renderer-v2 type="graduatedSymbol" attr="pop"><ranges>'
           '<range lower="0" upper="999" symbol="0" label="small" render="true"/></ranges><symbols>'
           '<symbol name="0" type="marker"><layer class="SimpleMarker"><prop k="color" v="1,2,3,255"/>'
           '<prop k="size" v="2"/></layer></symbol></symbols></renderer-v2></qgis>')
    spec = styles.qml_to_style(qml)
    assert spec["ranges"][0]["max"] == 999 and spec["ranges"][0]["style"]["fill"] == "#010203"
    assert spec["ranges"][0]["style"]["radius"] == pytest.approx(2 * 96 / 25.4 / 2, abs=0.1)


# ---- map page -----------------------------------------------------------------------------------

def test_points_geojson_handles_nan_and_numpy():
    df = pd.DataFrame({"name": ["A", "B"], "lon": [26.8, 26.9], "lat": [43.0, 43.1], "x": [1.5, float("nan")]})
    gj = map_view.points_geojson(df, props=["name", "x"])
    assert gj["features"][1]["properties"]["x"] is None
    json.dumps(gj)  # must be serialisable


def test_layer_and_page():
    df = pd.DataFrame({"name": ["</script><b>x"], "lon": [26.8], "lat": [43.0], "alert": ["red"]})
    lay = map_view.make_layer("Test layer", map_view.points_geojson(df), CAT)
    f = lay["geojson"]["features"][0]["properties"]
    assert map_view.feature_style(lay, 0)["fill"] == "#d62828" and "UTM35N_E_m" in f
    html = map_view.map_html([lay], fit=True)
    assert "tile.openstreetmap.org" in html and "L.control.scale" in html and "EPSG:32635" in html
    assert "</script><b>x" not in html          # cannot break out of the script element
    assert "__CFG__" not in html and "__LV__" not in html


def test_load_vector_dir(tmp_path=None):
    d = Path(tempfile.mkdtemp())
    e, n = geo.lonlat_to_utm35n(26.8, 43.05)
    (d / "lakes.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"kind": "a"}, "geometry": {"type": "Point", "coordinates": [e, n]}}]}))
    (d / "lakes.style.json").write_text(json.dumps({"type": "single", "style": {"fill": "#ff0000"}}))
    (d / "bad.geojson").write_text("not json")
    layers, msgs = map_view.load_vector_dir(d)
    assert [l["title"] for l in layers] == ["lakes"]
    assert map_view.feature_style(layers[0], 0)["fill"] == "#ff0000"
    assert any("bad.geojson" in m for m in msgs)
    shutil.rmtree(d)


def test_javascript_is_valid_and_matches_python():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    html = map_view.map_html([])
    script = html.split("<script>")[1].split("</script>")[0]
    d = Path(tempfile.mkdtemp())
    (d / "page.js").write_text(script)
    chk = subprocess.run([node, "--check", str(d / "page.js")], capture_output=True, text=True)
    assert chk.returncode == 0, chk.stderr
    utm = script[script.index("const A="):script.index("/* ---- map, base layers")]
    pts = [(26.8, 43.05), (22.4, 41.9), (28.6, 44.2)]
    (d / "u.js").write_text(utm + "\nconsole.log(JSON.stringify(%s.map(p=>{const u=toUTM(p[0],p[1]);const b=fromUTM(u[0],u[1]);return [u[0],u[1],b[0],b[1]];})));"
                            % json.dumps(pts))
    out = json.loads(subprocess.run([node, str(d / "u.js")], capture_output=True, text=True, check=True).stdout)
    for (lon, lat), (e, n, lon2, lat2) in zip(pts, out):
        pe, pn = geo.lonlat_to_utm35n(lon, lat)
        assert abs(e - pe) < 1e-3 and abs(n - pn) < 1e-3
        assert abs(lon2 - lon) < 1e-8 and abs(lat2 - lat) < 1e-8
    shutil.rmtree(d)
