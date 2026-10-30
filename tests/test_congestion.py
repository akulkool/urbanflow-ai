import json

import pytest

from backend.schemas.traffic import CongestionLevel, DensityLevel, RegionDensity, Trend
from backend.services.congestion_analyzer import (
    CongestionAnalyzer,
    CongestionConfigError,
    CongestionThresholds,
    detect_trend,
)


def dens(count, occ=None, region="A"):
    return RegionDensity(region, count, {}, DensityLevel.LOW, occ, None)


def one(a, count, occ=None, t=0.0, speeds=None):
    return a.update([dens(count, occ)], t, speeds)[0]


@pytest.mark.parametrize("count,level", [
    (0, "LOW"), (3.9, "LOW"), (4, "MODERATE"), (8, "HIGH"), (14, "HIGH"), (15, "SEVERE"), (30, "SEVERE"),
])
def test_count_thresholds(count, level):
    a = CongestionAnalyzer(smoothing_frames=1)
    assert one(a, count).level.value == level


def test_occupancy_can_raise_level():
    a = CongestionAnalyzer(smoothing_frames=1)
    r = one(a, 5, occ=0.7)
    assert r.level == CongestionLevel.SEVERE and r.signals["bbox_coverage"] == "SEVERE"


def test_occupancy_ignored_for_few_vehicles():
    r = one(CongestionAnalyzer(smoothing_frames=1), 1, occ=0.9)  # one big vehicle != congestion
    assert r.level == CongestionLevel.LOW and "bbox_coverage" not in r.signals


def test_custom_thresholds():
    th = CongestionThresholds(count_moderate=1, count_high=2, count_severe=3)
    assert one(CongestionAnalyzer(th, smoothing_frames=1), 2).level == CongestionLevel.HIGH


def test_smoothing_dampens_single_frame_spike():
    a = CongestionAnalyzer(smoothing_frames=10)
    for i in range(9):
        one(a, 0, t=i * 0.04)
    assert one(a, 20, t=0.4).level == CongestionLevel.LOW  # mean 2.0


def test_without_speed_is_marked_model_estimate():
    r = one(CongestionAnalyzer(smoothing_frames=1), 10)
    assert r.is_estimate and r.speed_kmh is None and "calibrated_speed" not in r.signals
    assert "model_estimate" in r.basis


def test_calibrated_speed_used_only_when_supplied():
    a = CongestionAnalyzer(smoothing_frames=1)
    r = one(a, 0, speeds={"A": 8.0})
    assert r.level == CongestionLevel.SEVERE and not r.is_estimate and r.speed_kmh == 8.0
    assert "calibrated" in r.basis
    assert a.summary()["is_estimate"] is False
    assert one(CongestionAnalyzer(smoothing_frames=1), 0, speeds={"A": 60.0}).level == CongestionLevel.LOW


@pytest.mark.parametrize("bad", [-1.0, float("nan"), "fast"])
def test_invalid_speed_rejected(bad):
    with pytest.raises(CongestionConfigError):
        one(CongestionAnalyzer(), 1, speeds={"A": bad})


def test_region_wise_levels_and_empty():
    a = CongestionAnalyzer(smoothing_frames=1)
    out = a.update([dens(0, 0.0, "A"), dens(20, 0.1, "B")], 0.0)
    assert {c.region: c.level.value for c in out} == {"A": "LOW", "B": "SEVERE"}
    assert a.update([], 1.0) == []


def test_direction_congestion_reported_unsupported():
    s = CongestionAnalyzer().summary()
    assert s["direction_congestion"]["supported"] is False


@pytest.mark.parametrize("values,trend", [
    ([], Trend.INSUFFICIENT_DATA),
    ([5], Trend.INSUFFICIENT_DATA),
    ([2, 2, 2, 2], Trend.STABLE),
    ([1, 2, 6, 8], Trend.INCREASING),
    ([9, 8, 2, 1], Trend.DECREASING),
    ([10, 10.5, 10.2, 10.4], Trend.STABLE),
    ([1, 1, 1, 1, 1, 6, 7, 8, 9, 10], Trend.INCREASING),
])
def test_detect_trend(values, trend):
    assert detect_trend(values) == trend


def test_history_sampling_and_trend_from_analyzer():
    a = CongestionAnalyzer(smoothing_frames=1, history_interval_s=1.0)
    for i in range(20):  # 10 fps, count ramps up
        one(a, i, t=i / 10.0)
    h = a.summary()["history"]
    assert len(h) == 2 and h[1]["time_s"] == 1.0  # sampled once per second of video time
    a2 = CongestionAnalyzer(smoothing_frames=1, history_interval_s=0.1)
    for i in range(20):
        one(a2, i, t=i / 10.0)
    assert a2.trend() == Trend.INCREASING
    a2.reset()
    assert a2.trend() == Trend.INSUFFICIENT_DATA and a2.summary()["history"] == []


def test_history_bounded():
    a = CongestionAnalyzer(smoothing_frames=1, history_interval_s=0.01, history_limit=5)
    for i in range(50):
        one(a, 1, t=i)
    assert len(a.summary()["history"]) == 5


def test_summary_serialisable():
    a = CongestionAnalyzer(smoothing_frames=1)
    one(a, 10, 0.3)
    assert json.loads(json.dumps(a.summary()))["regions"]["A"]["peak_level"] == "HIGH"


@pytest.mark.parametrize("kw", [
    {"smoothing_frames": 0}, {"history_interval_s": 0}, {"history_limit": 1},
])
def test_invalid_analyzer_config(kw):
    with pytest.raises(CongestionConfigError):
        CongestionAnalyzer(**kw)


def test_invalid_thresholds():
    with pytest.raises(CongestionConfigError):
        CongestionThresholds(count_moderate=5, count_high=3, count_severe=9)
    with pytest.raises(CongestionConfigError):
        CongestionThresholds(speed_kmh_moderate=10, speed_kmh_high=20, speed_kmh_severe=5)
    with pytest.raises(CongestionConfigError):
        CongestionThresholds(occupancy_severe=1.5)
