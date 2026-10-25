"""Read GeoPackage (.gpkg) vector layers in pure Python (sqlite3 + a small WKB reader), and simplify geometry.

Why: the team exports layers from QGIS as GeoPackage. Reading them here needs no geopandas, GDAL or shapely, so the
demo and `prepare_vectors.py` run anywhere. Supported: 2D Point, LineString, Polygon and their Multi* forms, in the
file's own CRS (the demo uses EPSG:32635). Not a general GIS reader: curves, Z/M values and raster tiles are ignored.
"""
from __future__ import annotations

import json
import math
import sqlite3
import struct
from typing import Iterator

_ENVELOPE_BYTES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


# ---- WKB ------------------------------------------------------------------------------------------

def _read_wkb(buf: bytes, pos: int = 0):
    """Parse one WKB geometry. Returns (geojson geometry dict, next position)."""
    little = buf[pos] == 1
    e = "<" if little else ">"
    (wtype,) = struct.unpack_from(e + "I", buf, pos + 1)
    pos += 5
    base = wtype % 1000                      # 1001 etc. (Z) are read as 2D below
    dims = 2 + (1 if wtype // 1000 in (1, 3) else 0) + (1 if wtype // 1000 in (2, 3) else 0)
    step = 8 * dims

    def points(n):
        nonlocal pos
        out = []
        for _ in range(n):
            x, y = struct.unpack_from(e + "dd", buf, pos)
            out.append([x, y])
            pos += step
        return out

    def count():
        nonlocal pos
        (n,) = struct.unpack_from(e + "I", buf, pos)
        pos += 4
        return n

    if base == 1:
        return {"type": "Point", "coordinates": points(1)[0]}, pos
    if base == 2:
        return {"type": "LineString", "coordinates": points(count())}, pos
    if base == 3:
        return {"type": "Polygon", "coordinates": [points(count()) for _ in range(count())]}, pos
    if base in (4, 5, 6):
        parts = []
        for _ in range(count()):
            g, pos = _read_wkb(buf, pos)
            parts.append(g["coordinates"])
        name = {4: "MultiPoint", 5: "MultiLineString", 6: "MultiPolygon"}[base]
        return {"type": name, "coordinates": parts}, pos
    raise ValueError(f"WKB geometry type {wtype} is not supported")


def parse_gpkg_geometry(blob: bytes | None):
    """GeoPackage geometry blob (header + WKB) -> GeoJSON geometry dict, or None when empty."""
    if not blob or blob[:2] != b"GP":
        return None
    flags = blob[3]
    if flags & 0b10000:                       # empty geometry
        return None
    env = _ENVELOPE_BYTES.get((flags >> 1) & 0b111, 0)
    geom, _ = _read_wkb(blob, 8 + env)
    return geom


# ---- reading a file -------------------------------------------------------------------------------

def layer_info(path: str) -> list[dict]:
    """[{table, geometry_column, geometry_type, srs_id, epsg, count}] for every feature table."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        out = []
        for t, col, gt, srs in con.execute("select table_name, column_name, geometry_type_name, srs_id from gpkg_geometry_columns"):
            org = con.execute("select organization, organization_coordsys_id from gpkg_spatial_ref_sys where srs_id=?", (srs,)).fetchone()
            epsg = org[1] if org and str(org[0]).upper() == "EPSG" else None
            n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
            out.append({"table": t, "geometry_column": col, "geometry_type": gt, "srs_id": srs, "epsg": epsg, "count": n})
        return out
    finally:
        con.close()


def iter_features(path: str, table: str | None = None, drop_columns=()) -> Iterator[dict]:
    """Yield GeoJSON features (geometry in the file's CRS). Attribute columns in `drop_columns` are skipped."""
    info = layer_info(path)
    meta = next((i for i in info if table in (None, i["table"])), None)
    if meta is None:
        raise ValueError(f"no feature table {table!r} in {path}")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cols = [r[1] for r in con.execute(f'pragma table_info("{meta["table"]}")')]
        gcol = meta["geometry_column"]
        keep = [c for c in cols if c not in (gcol, "fid") and c not in drop_columns]
        sql = 'select "%s", %s from "%s"' % (gcol, ", ".join(f'"{c}"' for c in keep), meta["table"])
        for row in con.execute(sql):
            geom = parse_gpkg_geometry(row[0])
            if geom is None:
                continue
            props = {c: (v if not isinstance(v, bytes) else None) for c, v in zip(keep, row[1:])}
            yield {"type": "Feature", "properties": props, "geometry": geom}
    finally:
        con.close()


def read_gpkg(path: str, table: str | None = None, drop_columns=()) -> dict:
    """The whole table as a GeoJSON FeatureCollection with a `crs` member (e.g. EPSG:32635)."""
    meta = next(i for i in layer_info(path) if table in (None, i["table"]))
    fc = {"type": "FeatureCollection", "features": list(iter_features(path, meta["table"], drop_columns))}
    if meta["epsg"]:
        fc["crs"] = {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{meta['epsg']}"}}
    return fc


# ---- simplification (metres, so use it on projected data) ------------------------------------------

def _perp(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == dy == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def douglas_peucker(pts: list, tol: float) -> list:
    """Iterative Douglas-Peucker; keeps the first and last point."""
    if len(pts) < 3 or tol <= 0:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        best, idx = 0.0, -1
        for k in range(i + 1, j):
            d = _perp(pts[k], pts[i], pts[j])
            if d > best:
                best, idx = d, k
        if best > tol:
            keep[idx] = True
            stack += [(i, idx), (idx, j)]
    return [p for p, k in zip(pts, keep) if k]


def ring_area(ring: list) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def simplify_geometry(geom: dict, tol: float, min_ring_area: float = 0.0, decimals: int = 1) -> dict | None:
    """Simplify a geometry (tolerance and areas in CRS units, metres for UTM). Returns None if nothing is left."""
    def rnd(pts):
        return [[round(x, decimals), round(y, decimals)] for x, y in pts]

    def line(pts):
        out = rnd(douglas_peucker(pts, tol))
        return out if len(out) >= 2 else None

    def ring(pts):
        out = douglas_peucker(pts, tol)
        if len(out) < 4 or ring_area(out) < min_ring_area:
            return None
        return rnd(out)

    def polygon(rings):
        outer = ring(rings[0])
        if outer is None:
            return None
        return [outer] + [r for r in (ring(h) for h in rings[1:]) if r is not None]

    t, c = geom["type"], geom["coordinates"]
    if t == "Point":
        return {"type": t, "coordinates": [round(c[0], decimals), round(c[1], decimals)]}
    if t == "LineString":
        l = line(c)
        return {"type": t, "coordinates": l} if l else None
    if t == "MultiLineString":
        ls = [l for l in (line(x) for x in c) if l]
        return {"type": t, "coordinates": ls} if ls else None
    if t == "Polygon":
        p = polygon(c)
        return {"type": t, "coordinates": p} if p else None
    if t == "MultiPolygon":
        ps = [p for p in (polygon(x) for x in c) if p]
        return {"type": t, "coordinates": ps} if ps else None
    return geom


def write_geojson(fc: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False, separators=(",", ":"))
