"""Coordinates for the map: WGS 84 (EPSG:4326) <-> UTM zone 35N (EPSG:32635), in pure Python.

Why pure Python: the map must show coordinates in EPSG:32635 without any heavy GIS stack, and the
code must be testable anywhere. The formulas are the Krueger series (3rd order), accurate to well
under 1 mm inside the zone. `tests/test_geo.py` compares them with pyproj when pyproj is installed.

Zone 35N: central meridian 27 deg E, scale factor 0.9996, false easting 500 000 m, false northing 0.
Bulgaria lies in zones 34N (west of 24 deg E) and 35N (24 to 30 deg E). The project uses 35N for all
of it, as agreed by the team. Points far west of 24 deg E are still computed correctly, but their
scale distortion grows (about 1 in 1000 more at 600 km from the central meridian).
"""
from __future__ import annotations

import math
from typing import Iterable

EPSG_UTM35N = 32635
EPSG_WGS84 = 4326

_A = 6378137.0
_F = 1.0 / 298.257223563
_K0 = 0.9996
_E0 = 500000.0
_LON0 = math.radians(27.0)

_n = _F / (2.0 - _F)
_AA = _A / (1.0 + _n) * (1.0 + _n**2 / 4.0 + _n**4 / 64.0)
_ALPHA = (
    _n / 2.0 - 2.0 * _n**2 / 3.0 + 5.0 * _n**3 / 16.0,
    13.0 * _n**2 / 48.0 - 3.0 * _n**3 / 5.0,
    61.0 * _n**3 / 240.0,
)
_BETA = (
    _n / 2.0 - 2.0 * _n**2 / 3.0 + 37.0 * _n**3 / 96.0,
    _n**2 / 48.0 + _n**3 / 15.0,
    17.0 * _n**3 / 480.0,
)
_DELTA = (
    2.0 * _n - 2.0 * _n**2 / 3.0 - 2.0 * _n**3,
    7.0 * _n**2 / 3.0 - 8.0 * _n**3 / 5.0,
    56.0 * _n**3 / 15.0,
)


def lonlat_to_utm35n(lon: float, lat: float) -> tuple[float, float]:
    """WGS 84 longitude, latitude (degrees) -> (easting, northing) in metres, EPSG:32635."""
    phi, dlam = math.radians(lat), math.radians(lon) - _LON0
    c = 2.0 * math.sqrt(_n) / (1.0 + _n)
    t = math.sinh(math.atanh(math.sin(phi)) - c * math.atanh(c * math.sin(phi)))
    xi_p = math.atan2(t, math.cos(dlam))
    eta_p = math.atanh(math.sin(dlam) / math.sqrt(1.0 + t * t))
    xi = xi_p + sum(a * math.sin(2 * j * xi_p) * math.cosh(2 * j * eta_p) for j, a in enumerate(_ALPHA, 1))
    eta = eta_p + sum(a * math.cos(2 * j * xi_p) * math.sinh(2 * j * eta_p) for j, a in enumerate(_ALPHA, 1))
    return _E0 + _K0 * _AA * eta, _K0 * _AA * xi


def utm35n_to_lonlat(easting: float, northing: float) -> tuple[float, float]:
    """(easting, northing) in metres, EPSG:32635 -> WGS 84 (longitude, latitude) in degrees."""
    xi = northing / (_K0 * _AA)
    eta = (easting - _E0) / (_K0 * _AA)
    xi_p = xi - sum(b * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, b in enumerate(_BETA, 1))
    eta_p = eta - sum(b * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, b in enumerate(_BETA, 1))
    chi = math.asin(math.sin(xi_p) / math.cosh(eta_p))
    phi = chi + sum(d * math.sin(2 * j * chi) for j, d in enumerate(_DELTA, 1))
    lam = _LON0 + math.atan2(math.sinh(eta_p), math.cos(xi_p))
    return math.degrees(lam), math.degrees(phi)


# ---- GeoJSON helpers ---------------------------------------------------------------------------

def _map_coords(coords, fn):
    """Apply fn(x, y) -> (x, y) to every position of a GeoJSON coordinates array, keeping extra values."""
    if coords and isinstance(coords[0], (int, float)):
        x, y = fn(coords[0], coords[1])
        return [x, y, *coords[2:]]
    return [_map_coords(c, fn) for c in coords]


def _iter_positions(coords) -> Iterable[list]:
    if coords and isinstance(coords[0], (int, float)):
        yield coords
    else:
        for c in coords:
            yield from _iter_positions(c)


def _geometry_coords(geom: dict) -> list:
    if geom.get("type") == "GeometryCollection":
        return [g.get("coordinates", []) for g in geom.get("geometries", [])]
    return geom.get("coordinates", [])


def declared_epsg(geojson: dict) -> int | None:
    """EPSG code from the old GeoJSON `crs` member (QGIS writes it), or None when absent.

    "urn:ogc:def:crs:OGC:1.3:CRS84" and EPSG:4326 give 4326.
    """
    name = ((geojson.get("crs") or {}).get("properties") or {}).get("name", "")
    if not name:
        return None
    if "CRS84" in name:
        return EPSG_WGS84
    digits = "".join(ch if ch.isdigit() else " " for ch in name.split("EPSG")[-1]).split()
    return int(digits[0]) if digits else None


def guess_epsg(geojson: dict) -> int:
    """EPSG code of a GeoJSON: declared one, else 32635 when coordinates are clearly in metres, else 4326."""
    code = declared_epsg(geojson)
    if code is not None:
        return code
    feats = geojson.get("features", [geojson] if geojson.get("type") == "Feature" else [])
    for f in feats:
        geom = f.get("geometry") or {}
        for pos in _iter_positions(_geometry_coords(geom)):
            return EPSG_UTM35N if abs(pos[0]) > 360 or abs(pos[1]) > 180 else EPSG_WGS84
    return EPSG_WGS84


def geojson_to_wgs84(geojson: dict, source_epsg: int | None = None) -> dict:
    """Return a copy of a GeoJSON FeatureCollection with coordinates in WGS 84 (lon, lat).

    Supported source systems without extra libraries: 4326 and 32635. Any other code raises
    ValueError; for those, read the file with geopandas (see map_view.load_vector_dir).
    """
    epsg = source_epsg or guess_epsg(geojson)
    if epsg == EPSG_WGS84:
        fn = None
    elif epsg == EPSG_UTM35N:
        fn = utm35n_to_lonlat
    else:
        raise ValueError(f"EPSG:{epsg} is not supported without geopandas; reproject to 32635 or 4326")

    def conv(geom):
        if not geom or fn is None:
            return geom
        g = dict(geom)
        if g.get("type") == "GeometryCollection":
            g["geometries"] = [conv(x) for x in g.get("geometries", [])]
        else:
            g["coordinates"] = _map_coords(g.get("coordinates", []), fn)
        return g

    out = {"type": "FeatureCollection", "features": []}
    feats = geojson.get("features", [geojson] if geojson.get("type") == "Feature" else [])
    for f in feats:
        out["features"].append({"type": "Feature", "properties": dict(f.get("properties") or {}),
                                "geometry": conv(f.get("geometry"))})
    return out


def round_coords(geojson: dict, decimals: int = 6) -> dict:
    """Round all coordinates in place (6 decimals of a degree is about 0.1 m) to keep the map page small."""
    for f in geojson.get("features", []):
        g = f.get("geometry") or {}
        if g.get("type") == "GeometryCollection":
            for x in g.get("geometries", []):
                x["coordinates"] = _map_coords(x.get("coordinates", []), lambda a, b: (round(a, decimals), round(b, decimals)))
        elif g:
            g["coordinates"] = _map_coords(g.get("coordinates", []), lambda a, b: (round(a, decimals), round(b, decimals)))
    return geojson


def add_utm_attributes(geojson_wgs84: dict) -> dict:
    """Add UTM 35N coordinates (metres, rounded) to the properties of point features. Edits in place."""
    for f in geojson_wgs84.get("features", []):
        g = f.get("geometry") or {}
        if g.get("type") == "Point":
            e, n = lonlat_to_utm35n(g["coordinates"][0], g["coordinates"][1])
            f["properties"]["UTM35N_E_m"] = round(e)
            f["properties"]["UTM35N_N_m"] = round(n)
    return geojson_wgs84


def bounds(geojson_wgs84: dict):
    """[[south, west], [north, east]] of all positions, or None when empty."""
    xs, ys = [], []
    for f in geojson_wgs84.get("features", []):
        for pos in _iter_positions(_geometry_coords(f.get("geometry") or {})):
            xs.append(pos[0]); ys.append(pos[1])
    return [[min(ys), min(xs)], [max(ys), max(xs)]] if xs else None
