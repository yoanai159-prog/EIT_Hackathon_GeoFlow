"""Layer styles for the web map, and a converter from QGIS styles (.qml).

A style is a small JSON-like dict, kept next to the layer as `<layer>.style.json` (or exported from
QGIS as `<layer>.qml`, which `qml_to_style` reads). Three kinds:

  {"type": "single",      "style": {...}}
  {"type": "categorized", "field": "alert", "categories": [{"value": "red", "label": "Red", "style": {...}}, ...],
                          "default": {...}}
  {"type": "graduated",   "field": "pop", "ranges": [{"min": 0, "max": 100, "label": "0-100", "style": {...}}, ...],
                          "default": {...}}

A symbol `style` may hold: stroke (#rrggbb), stroke_opacity, weight (px), fill (#rrggbb), fill_opacity,
radius (px, points only), dash ("5,5" or None).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

MM_TO_PX = 96.0 / 25.4  # QGIS sizes are in mm by default; the web map uses CSS pixels

DEFAULT_STYLE = {"stroke": "#3366cc", "stroke_opacity": 1.0, "weight": 2, "fill": "#3388ff",
                 "fill_opacity": 0.35, "radius": 6, "dash": None}


def complete(style: dict | None) -> dict:
    """Fill the missing keys of a symbol style with the defaults."""
    out = dict(DEFAULT_STYLE)
    out.update({k: v for k, v in (style or {}).items() if v is not None or k == "dash"})
    return out


def _matches(value, target) -> bool:
    if value is None:
        return False
    if str(value) == str(target):
        return True
    try:
        return float(value) == float(target)
    except (TypeError, ValueError):
        return False


def resolve(spec: dict | None, props: dict) -> tuple[dict, int | None]:
    """Symbol style (completed) for one feature, plus the index of the matching class (or None)."""
    if not spec or spec.get("type", "single") == "single":
        return complete((spec or {}).get("style")), None
    field = spec.get("field")
    value = props.get(field)
    if spec["type"] == "categorized":
        for i, c in enumerate(spec.get("categories", [])):
            if _matches(value, c.get("value")):
                return complete(c.get("style")), i
    elif spec["type"] == "graduated":
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = None
        if v is not None:
            for i, r in enumerate(spec.get("ranges", [])):
                if r["min"] <= v <= r["max"]:
                    return complete(r.get("style")), i
    return complete(spec.get("default")), None


def apply_style(geojson: dict, spec: dict | None) -> dict:
    """Write the resolved style into each feature as `properties["__style__"]` (the map never shows `__` keys)."""
    for f in geojson.get("features", []):
        style, _ = resolve(spec, f.get("properties") or {})
        f.setdefault("properties", {})["__style__"] = style
    return geojson


def legend(spec: dict | None, title: str | None = None, kind: str = "polygon") -> list[dict]:
    """Legend rows: [{"label", "group", "stroke", "fill", "fill_opacity", "dash", "shape"}].

    A single symbol gives one row labelled with the layer title. `kind` is "point", "line" or "polygon" (the swatch shape).
    """
    rows = []
    if not spec or spec.get("type", "single") == "single":
        s = complete((spec or {}).get("style"))
        return [{"label": title or "", "group": None, "stroke": s["stroke"], "fill": s["fill"],
                 "fill_opacity": s["fill_opacity"], "dash": s["dash"], "shape": kind}]
    items = spec.get("categories", []) if spec["type"] == "categorized" else spec.get("ranges", [])
    for it in items:
        s = complete(it.get("style"))
        label = it.get("label") or it.get("value") or f'{it.get("min")} - {it.get("max")}'
        rows.append({"label": str(label), "group": it.get("group"), "stroke": s["stroke"], "fill": s["fill"],
                     "fill_opacity": s["fill_opacity"], "dash": s["dash"], "shape": kind})
    return rows


def faded(spec: dict | None, fill: float = 0.5, stroke: float = 0.7) -> dict:
    """Copy of a style spec with fill and stroke opacity multiplied (a paler look). Values are completed first."""
    import copy

    def f(st):
        c = complete(st)
        c["fill_opacity"] = round(c["fill_opacity"] * fill, 3)
        c["stroke_opacity"] = round(c["stroke_opacity"] * stroke, 3)
        return c

    spec = copy.deepcopy(spec) if spec else {"type": "single", "style": {}}
    if spec.get("type", "single") == "single":
        spec["style"] = f(spec.get("style"))
        return spec
    for key in ("categories", "ranges"):
        for it in spec.get(key, []):
            it["style"] = f(it.get("style"))
    spec["default"] = f(spec.get("default"))
    return spec


# ---- QGIS .qml -> style ----------------------------------------------------------------------------

def _hex(color: str) -> tuple[str, float]:
    """QGIS 'r,g,b,a' (0-255, may carry extra text after the alpha) -> ('#rrggbb', alpha 0-1)."""
    parts = [p.strip() for p in color.split(",")[:4]]
    r, g, b = (max(0, min(255, int(float(p)))) for p in parts[:3])
    a = float(parts[3]) / 255.0 if len(parts) > 3 else 1.0
    return f"#{r:02x}{g:02x}{b:02x}", round(a, 3)


def _props(layer: ET.Element) -> dict:
    out = {}
    for o in layer.iter("Option"):  # QGIS >= 3.x
        if o.get("name") and o.get("value") is not None:
            out[o.get("name")] = o.get("value")
    for p in layer.iter("prop"):  # older style files
        if p.get("k") and p.get("v") is not None:
            out[p.get("k")] = p.get("v")
    return out


def _symbol_style(sym: ET.Element) -> dict:
    """Style of the first symbol layer of a <symbol> element (simple fill, line and marker supported)."""
    layer = sym.find("layer")
    if layer is None:
        return {}
    cls, p = layer.get("class", ""), _props(layer)
    out: dict = {}
    if cls == "SimpleFill":
        if "color" in p:
            out["fill"], out["fill_opacity"] = _hex(p["color"])
        if p.get("style") == "no":
            out["fill_opacity"] = 0.0
        if "outline_color" in p:
            out["stroke"], out["stroke_opacity"] = _hex(p["outline_color"])
        if "outline_width" in p:
            out["weight"] = round(float(p["outline_width"]) * MM_TO_PX, 1)
        if p.get("outline_style") == "no":
            out["stroke_opacity"] = 0.0
        elif p.get("outline_style") in ("dash", "dot", "dash dot"):
            out["dash"] = "6,4"
    elif cls == "SimpleLine":
        if "line_color" in p:
            out["stroke"], out["stroke_opacity"] = _hex(p["line_color"])
        if "line_width" in p:
            out["weight"] = round(float(p["line_width"]) * MM_TO_PX, 1)
        if p.get("line_style") in ("dash", "dot", "dash dot"):
            out["dash"] = "6,4"
    elif cls == "SimpleMarker":
        if "color" in p:
            out["fill"], out["fill_opacity"] = _hex(p["color"])
        if "outline_color" in p:
            out["stroke"], out["stroke_opacity"] = _hex(p["outline_color"])
        if "outline_width" in p:
            out["weight"] = max(1.0, round(float(p["outline_width"]) * MM_TO_PX, 1))
        if "size" in p:
            out["radius"] = max(2.0, round(float(p["size"]) * MM_TO_PX / 2.0, 1))
    return out


def qml_to_style(qml_text: str) -> dict:
    """Convert the renderer of a QGIS .qml file (single, categorized or graduated symbols) to a style dict.

    Only the first symbol layer of each symbol is read, and only simple fills, lines and markers.
    Anything else (SVG markers, gradients, rule-based renderers) falls back to the default style.
    """
    root = ET.fromstring(qml_text)
    rend = root.find(".//renderer-v2")
    if rend is None:
        return {"type": "single", "style": {}}
    symbols = {s.get("name"): _symbol_style(s) for s in rend.findall("./symbols/symbol")}
    kind = rend.get("type")
    if kind == "categorizedSymbol":
        cats = []
        for c in rend.findall("./categories/category"):
            if c.get("render", "true") == "false":
                continue
            val = c.get("value")
            if val == "":
                continue  # QGIS "all other values" category -> becomes the default below
            cats.append({"value": val, "label": c.get("label") or val, "style": symbols.get(c.get("symbol"), {})})
        other = next((symbols.get(c.get("symbol")) for c in rend.findall("./categories/category")
                      if c.get("value") == ""), None)
        spec = {"type": "categorized", "field": rend.get("attr"), "categories": cats}
        if other is not None:
            spec["default"] = other
        return spec
    if kind == "graduatedSymbol":
        rngs = [{"min": float(r.get("lower")), "max": float(r.get("upper")),
                 "label": r.get("label") or f'{r.get("lower")} - {r.get("upper")}',
                 "style": symbols.get(r.get("symbol"), {})}
                for r in rend.findall("./ranges/range") if r.get("render", "true") != "false"]
        return {"type": "graduated", "field": rend.get("attr"), "ranges": rngs}
    first = next(iter(symbols.values()), {})
    return {"type": "single", "style": first}
