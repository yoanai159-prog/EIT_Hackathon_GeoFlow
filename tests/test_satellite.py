import pytest
from core.satellite import area_pct_of_full, consistency, expected_area_pct


def test_area_share():
    assert area_pct_of_full(5, 10) == 50


def test_area_share_rejects_bad_reference():
    with pytest.raises(ValueError):
        area_pct_of_full(1, 0)


def test_expected_area_bounds():
    assert expected_area_pct(100) == pytest.approx(100)
    assert expected_area_pct(0) == 0
    assert expected_area_pct(50) > 50  # area shrinks slower than volume


def test_consistency_classes():
    exp = expected_area_pct(40)
    assert consistency(40, exp)["status"] == "consistent"
    assert consistency(40, exp - 30)["status"] == "less_water_than_reported"
    assert consistency(40, exp + 30)["status"] == "more_water_than_reported"
