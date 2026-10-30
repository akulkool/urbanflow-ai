import numpy as np
import pytest

from backend.schemas.traffic import DensityLevel
from backend.services.density_analyzer import (
    DensityAnalyzer,
    DensityThresholds,
    Region,
    RegionConfigError,
)
from backend.services.tracker import TrackedVehicle

SQUARE = [(0, 0), (100, 0), (100, 100), (0, 100)]


def veh(tid, x, y, cls="car", w=20, h=20):
    """Vehicle whose bottom-centre ground point is (x, y)."""
    return TrackedVehicle(tid, 2, cls, 0.9, (x - w / 2, y - h, x + w / 2, y))


def test_count_and_class_distribution():
    a = DensityAnalyzer(Region("A", SQUARE))
    out = a.update([veh(1, 50, 50), veh(2, 30, 60, "bus"), veh(3, 70, 80, "car")])[0]
    assert out.vehicle_count == 3
    assert out.by_class == {"bus": 1, "car": 2}
    assert out.density_basis == "vehicle_count"


def test_vehicle_outside_region_ignored():
    out = DensityAnalyzer(Region("A", SQUARE)).update([veh(1, 500, 500)])[0]
    assert out.vehicle_count == 0 and out.by_class == {} and out.level == DensityLevel.LOW


def test_empty_frame_and_empty_region():
    a = DensityAnalyzer([Region("A", SQUARE), Region("B", [(200, 0), (300, 0), (300, 100)])])
    out = a.update([])
    assert [(d.region, d.vehicle_count, d.level, d.occupancy_estimate) for d in out] == [
        ("A", 0, DensityLevel.LOW, 0.0),
        ("B", 0, DensityLevel.LOW, 0.0),
    ]


@pytest.mark.parametrize("count,level", [
    (0, "LOW"), (3, "LOW"), (4, "MODERATE"), (7, "MODERATE"),
    (8, "HIGH"), (14, "HIGH"), (15, "VERY_HIGH"), (40, "VERY_HIGH"),
])
def test_density_level_thresholds(count, level):
    a = DensityAnalyzer(Region("A", SQUARE))
    vs = [veh(i, 10 + (i % 8) * 10, 20 + (i // 8) * 10, w=2, h=2) for i in range(count)]
    assert a.update(vs)[0].level.value == level


def test_custom_thresholds_global_and_per_region():
    r1 = Region("A", SQUARE)
    r2 = Region("B", SQUARE, thresholds=DensityThresholds(1, 2, 3))
    out = DensityAnalyzer([r1, r2], DensityThresholds(2, 4, 6)).update([veh(1, 50, 50), veh(2, 40, 50)])
    assert out[0].level == DensityLevel.MODERATE and out[1].level == DensityLevel.HIGH


def test_multiple_regions_independent():
    a = DensityAnalyzer([Region("L", [(0, 0), (100, 0), (100, 100), (0, 100)]),
                         Region("R", [(100, 0), (200, 0), (200, 100), (100, 100)])])
    out = a.update([veh(1, 50, 50), veh(2, 150, 50), veh(3, 160, 60)])
    assert {d.region: d.vehicle_count for d in out} == {"L": 1, "R": 2}


def test_occupancy_is_bbox_coverage_estimate():
    a = DensityAnalyzer(Region("A", SQUARE))
    d = a.update([veh(1, 50, 50, w=50, h=50)])[0]  # box (25,0)-(75,50) -> 2500 / 10000
    assert d.occupancy_estimate == pytest.approx(0.25, abs=0.02)
    assert d.occupancy_basis == "image_plane_bbox_coverage_estimate"


def test_overlapping_boxes_not_double_counted_in_coverage():
    a = DensityAnalyzer(Region("A", SQUARE))
    one = a.update([veh(1, 50, 50, w=40, h=40)])[0].occupancy_estimate
    two = a.update([veh(1, 50, 50, w=40, h=40), veh(2, 50, 50, w=40, h=40)])[0].occupancy_estimate
    assert two == pytest.approx(one)


def test_coverage_clipped_to_polygon():
    tri = Region("T", [(0, 0), (100, 0), (0, 100)])  # half of the bounding square
    d = DensityAnalyzer(tri).update([veh(1, 10, 50, w=300, h=300)])[0]
    assert d.occupancy_estimate == pytest.approx(0.75, abs=0.03)  # box bottom at y=50 covers 75% of the triangle


def test_vehicles_per_100m_only_with_calibrated_length():
    a = DensityAnalyzer([Region("A", SQUARE, road_length_m=50), Region("B", SQUARE)])
    out = a.update([veh(1, 50, 50), veh(2, 60, 60)])
    assert out[0].vehicles_per_100m == pytest.approx(4.0) and out[1].vehicles_per_100m is None


def test_history_summary_and_reset():
    a = DensityAnalyzer(Region("A", SQUARE))
    a.update([])
    a.update([veh(1, 50, 50), veh(2, 40, 40, "bus")])
    a.update([veh(1, 50, 50)])
    s = a.summary()["regions"]["A"]
    assert s["frames"] == 3 and s["max_vehicle_count"] == 2
    assert s["mean_vehicle_count"] == pytest.approx(1.0)
    assert s["mean_vehicles_per_frame_by_class"] == {"bus": 0.333, "car": 0.667}
    assert s["level_frame_fractions"]["LOW"] == 1.0 and s["peak_level"] == "LOW"
    assert "not measured road occupancy" in a.summary()["note"]
    a.reset()
    assert a.summary()["regions"]["A"]["frames"] == 0


def test_future_class_names_flow_through():
    d = DensityAnalyzer(Region("A", SQUARE)).update([veh(1, 50, 50, "auto_rickshaw")])[0]
    assert d.by_class == {"auto_rickshaw": 1}


@pytest.mark.parametrize("name,poly", [
    ("", SQUARE), ("A", [(0, 0), (1, 1)]), ("A", [(0, 0), (1, 1), (2, 2)]),
    ("A", [(0, 0), (1, 0), (float("nan"), 1)]), ("A", "bad"),
])
def test_invalid_regions(name, poly):
    with pytest.raises(RegionConfigError):
        Region(name, poly)


def test_invalid_config():
    with pytest.raises(RegionConfigError):
        Region("A", SQUARE, road_length_m=0)
    with pytest.raises(RegionConfigError):
        DensityThresholds(5, 3, 10)
    with pytest.raises(RegionConfigError):
        DensityAnalyzer([])
    with pytest.raises(RegionConfigError):
        DensityAnalyzer([Region("A", SQUARE), Region("A", SQUARE)])
