"""Satellite layer: an independent check of reported reservoir fill.

Sentinel-2 gives the water SURFACE AREA, not the volume. This module turns two areas
(a full-pool reference and a current one) into a share of the full area and compares it
with what the operator reports. Pure functions only (no rasterio), so the app and the
tests run without the heavy geospatial stack.

ILLUSTRATIVE ASSUMPTION: volume ~ area ** AREA_VOLUME_EXPONENT (about 1.5 for a V-shaped
valley). In a real pilot, replace it with the reservoir's level-area-volume curve.
"""

AREA_VOLUME_EXPONENT = 1.5


def area_pct_of_full(area_km2: float, full_area_km2: float) -> float:
    """Current water area as a percentage of the full-pool reference area."""
    if full_area_km2 <= 0:
        raise ValueError("full_area_km2 must be positive")
    return 100.0 * area_km2 / full_area_km2


def expected_area_pct(fill_pct: float, exponent: float = AREA_VOLUME_EXPONENT, ref_fill_pct: float = 100.0) -> float:
    """Area share (%) of the reference scene that a reported fill (%) should produce, under V ~ A**exponent.

    ref_fill_pct is the fill of the reference scene. It is 100 when the reference shows the full pool; use the
    real fill of that day when it is lower (for example 93 for Ticha in early May 2026).
    """
    fill = min(max(fill_pct, 0.0), 100.0) / 100.0
    ref = min(max(ref_fill_pct, 1e-6), 100.0) / 100.0
    return 100.0 * (fill / ref) ** (1.0 / exponent)


def consistency(fill_pct: float, area_pct: float, tolerance_pp: float = 15.0,
                exponent: float = AREA_VOLUME_EXPONENT, ref_fill_pct: float = 100.0) -> dict:
    """Compare operator-reported fill with the satellite-observed area share."""
    exp_area = expected_area_pct(fill_pct, exponent, ref_fill_pct)
    gap = area_pct - exp_area
    if gap < -tolerance_pp:
        status = "less_water_than_reported"
    elif gap > tolerance_pp:
        status = "more_water_than_reported"
    else:
        status = "consistent"
    return {"status": status, "expected_area_pct": exp_area, "gap_pp": gap}


MESSAGES = {
    "consistent": "The satellite agrees with the reported fill (within the tolerance).",
    "less_water_than_reported": (
        "The satellite sees LESS water than the reported fill implies. Check the operator "
        "data, and check the scene for clouds, shadows or ice."
    ),
    "more_water_than_reported": (
        "The satellite sees MORE water than the reported fill implies. Check the operator "
        "data and the reference (full-pool) scene."
    ),
}
