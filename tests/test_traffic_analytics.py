import json

import cv2
import numpy as np
import pytest

from backend.config.vision_config import AnnotationConfig
from backend.schemas.traffic import FrameStats
from backend.services import video_processor as vp
from backend.services.congestion_analyzer import CongestionAnalyzer, CongestionConfigError
from backend.services.density_analyzer import DensityAnalyzer, Region
from backend.services.tracker import TrackedVehicle, TrackingError
from backend.services.traffic_analytics import AnalyticsConfigError, TrafficAnalytics
from backend.services.vehicle_counter import CountingLine, VehicleCounter
from backend.services.video_processor import FrameProcessingError, VideoProcessor

W = H = 200
LINE = CountingLine("main", (0, 100), (200, 100))
FULL = Region("road", [(0, 0), (W, 0), (W, H), (0, H)])


def veh(tid, x, y, cls="car", cid=2):
    return TrackedVehicle(tid, cid, cls, 0.9, (x - 10, y - 20, x + 10, y))


def make_video(path, n=30, fps=10):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    for i in range(n):
        w.write(np.full((H, W, 3), 30, np.uint8))
    w.release()
    return path


def traffic(i):
    """Car moves down across y=100 (forward); bus moves up (reverse); one auto_rickshaw sits still."""
    return [
        veh(1, 50, 40 + 4 * i),
        veh(2, 150, 160 - 4 * i, "bus", 5),
        veh(3, 100, 30, "auto_rickshaw", 10),
    ]


class ScriptedTracker:
    def __init__(self, fn=traffic, fail_on=None):
        self.fn, self.fail_on, self.i, self.resets = fn, fail_on, 0, 0

    def reset(self):
        self.resets += 1
        self.i = 0

    def update(self, frame):
        if self.fail_on == self.i:
            raise TrackingError("boom")
        v = self.fn(self.i)
        self.i += 1
        return v


def build(tmp_path, **kw):
    return VideoProcessor(
        ScriptedTracker(kw.pop("fn", traffic), kw.pop("fail_on", None)),
        output_dir=tmp_path / "out",
        counter=kw.pop("counter", VehicleCounter(LINE)),
        density=kw.pop("density", DensityAnalyzer(FULL)),
        window_seconds=kw.pop("window_seconds", 1.0),
        **kw,
    )


# ---------- integrated pipeline ----------
def test_end_to_end_counting_integration(tmp_path):
    src = make_video(tmp_path / "v.mp4")
    s = build(tmp_path).process(src)
    assert s.frame_count == 30
    c = s.counting["lines"]["main"]
    assert (c["forward"], c["reverse"], c["total"]) == (1, 1, 2)
    assert s.counting["by_class"] == {"bus": 1, "car": 1}
    assert c["by_direction_and_class"] == {"forward": {"car": 1}, "reverse": {"bus": 1}}
    # stationary auto_rickshaw is detected/tracked but never counted (no crossing)
    assert "auto_rickshaw" not in s.counting["by_class"]
    a = s.analytics
    assert a["unique_vehicles"] == 3 and a["total_detections"] == 90
    assert a["unique_vehicles_by_class"] == {"auto_rickshaw": 1, "bus": 1, "car": 1}
    assert a["crossings"] == s.counting


def test_analytics_windows_use_fps_timestamps(tmp_path):
    s = build(tmp_path).process(make_video(tmp_path / "v.mp4", n=30, fps=10))
    ws = s.analytics["windows"]
    assert [w["window_index"] for w in ws] == [0, 1, 2]
    assert [(w["start_s"], w["end_s"], w["frames"]) for w in ws] == [(0, 1, 10), (1, 2, 10), (2, 3, 10)]
    assert sum(w["crossings_by_direction"].get("forward", 0) for w in ws) == 1
    assert ws[1]["crossings_by_direction"] == {"forward": 1, "reverse": 1}
    assert ws[1]["crossings_by_class"] == {"bus": 1, "car": 1}
    assert ws[0]["mean_vehicles_per_frame"] == 3.0
    assert s.analytics["duration_s"] == 3.0 and s.analytics["fps"] == pytest.approx(10, abs=0.5)


def test_density_and_congestion_in_summary(tmp_path):
    s = build(tmp_path).process(make_video(tmp_path / "v.mp4"))
    a = s.analytics
    r = a["density"]["regions"]["road"]
    assert r["mean_vehicle_count"] == 3.0 and r["peak_level"] == "LOW"
    assert r["mean_vehicles_per_frame_by_class"] == {"auto_rickshaw": 1.0, "bus": 1.0, "car": 1.0}
    assert a["congestion"]["is_estimate"] is True
    assert a["congestion"]["regions"]["road"]["peak_level"] == "LOW"
    assert a["traffic_trend"] in {"stable", "increasing", "decreasing", "insufficient_data"}


def test_summary_json_serialisable(tmp_path):
    s = build(tmp_path).process(make_video(tmp_path / "v.mp4"))
    d = json.loads(json.dumps(s.to_dict()))
    assert d["analytics"]["notes"] and d["resolution"] == [W, H]


def test_multiple_counting_lines_and_directions(tmp_path):
    l2 = CountingLine("upper", (0, 70), (200, 70))
    s = build(tmp_path, counter=VehicleCounter([LINE, l2])).process(make_video(tmp_path / "v.mp4"))
    lines = s.counting["lines"]
    assert lines["main"]["total"] == 2 and lines["upper"]["total"] == 2
    assert s.counting["total"] == 4


def test_output_video_annotated_with_overlays(tmp_path):
    src = make_video(tmp_path / "v.mp4", n=20)
    p = build(tmp_path)
    s = p.process(src)
    cap = cv2.VideoCapture(s.output_path)
    ok, frame = cap.read()
    cap.release()
    assert ok and frame.shape[:2] == (H, W)
    assert np.abs(frame.astype(int) - 30).sum() > 0  # overlays differ from the plain source


def test_reset_between_videos_resets_all_state(tmp_path):
    p = build(tmp_path)
    s1 = p.process(make_video(tmp_path / "a.mp4"))
    s2 = p.process(make_video(tmp_path / "b.mp4"))
    assert p.tracker.resets == 2
    assert s1.counting == s2.counting  # same script, fresh state, no carry-over
    assert s2.counting["lines"]["main"]["total"] == 2
    assert s2.analytics["total_detections"] == 90
    assert s2.analytics["density"]["regions"]["road"]["frames"] == 30


def test_regression_without_analyzers_still_works(tmp_path):
    p = VideoProcessor(ScriptedTracker(), output_dir=tmp_path / "o")
    s = p.process(make_video(tmp_path / "v.mp4", n=5))
    assert s.counting is None and s.frame_count == 5 and s.unique_track_ids == [1, 2, 3]
    assert s.analytics["crossings"] is None and s.analytics["density"] is None
    assert any("No road regions" in n for n in s.analytics["notes"])


def test_analytics_failure_wrapped_and_output_removed(tmp_path):
    class Boom(VehicleCounter):
        def update(self, vehicles):
            raise RuntimeError("counter bug")

    p = build(tmp_path, counter=Boom(LINE))
    out = tmp_path / "o.mp4"
    with pytest.raises(FrameProcessingError, match="Analytics failed"):
        p.process(make_video(tmp_path / "v.mp4", n=3), out)
    assert not out.exists()


def test_tracker_failure_still_wrapped(tmp_path):
    with pytest.raises(FrameProcessingError):
        build(tmp_path, fail_on=2).process(make_video(tmp_path / "v.mp4", n=5))


# ---------- TrafficAnalytics unit ----------
def test_analytics_frame_stats_and_empty_frames():
    ta = TrafficAnalytics(VehicleCounter(LINE), DensityAnalyzer(FULL), window_seconds=1.0)
    ta.reset(10.0)
    st = ta.update(0, [])
    assert isinstance(st, FrameStats) and st.vehicle_count == 0 and st.crossings == []
    st = ta.update(1, [veh(1, 50, 50)])
    assert st.track_ids == [1] and st.time_s == pytest.approx(0.1)
    assert st.densities[0].vehicle_count == 1 and st.congestion[0].is_estimate
    r = ta.summary()
    assert r.frames == 2 and r.frame_stats["max_vehicles_in_frame"] == 1 and r.frame_stats["peak_frame_index"] == 1
    json.dumps(r.to_dict())


def test_analytics_trend_without_regions_uses_window_means():
    ta = TrafficAnalytics(window_seconds=1.0)
    ta.reset(1.0)
    for i, n in enumerate([1, 1, 5, 6]):  # 1 fps, 1 frame per window
        ta.update(i, [veh(j, 10, 10) for j in range(n)])
    assert ta.summary().traffic_trend == "increasing"


def test_analytics_trend_with_regions_increasing():
    ta = TrafficAnalytics(
        density=DensityAnalyzer(FULL), congestion=CongestionAnalyzer(smoothing_frames=1, history_interval_s=1.0)
    )
    ta.reset(1.0)
    for i in range(10):
        ta.update(i, [veh(j, 10 + j, 10 + j) for j in range(i)])
    assert ta.summary().traffic_trend == "increasing"


def test_analytics_summary_before_any_frame():
    ta = TrafficAnalytics(VehicleCounter(LINE))
    r = ta.summary()
    assert r.frames == 0 and r.duration_s == 0.0 and r.windows == []


def test_speeds_pass_through_marks_non_estimate():
    ta = TrafficAnalytics(density=DensityAnalyzer(FULL))
    ta.reset(10.0)
    st = ta.update(0, [veh(1, 50, 50)], speeds_kmh={"road": 5.0})
    assert st.congestion[0].level.value == "SEVERE" and not st.congestion[0].is_estimate


def test_invalid_analytics_config():
    with pytest.raises(AnalyticsConfigError):
        TrafficAnalytics(window_seconds=0)
    with pytest.raises(AnalyticsConfigError):
        TrafficAnalytics(congestion=CongestionAnalyzer())
    ta = TrafficAnalytics()
    with pytest.raises(AnalyticsConfigError):
        ta.reset(0)
    with pytest.raises(CongestionConfigError):
        TrafficAnalytics(density=DensityAnalyzer(FULL)).update(0, [veh(1, 5, 5)], {"road": -1})


# ---------- annotation ----------
def blank():
    return np.zeros((H, W, 3), np.uint8)


def stats_for(vehicles):
    ta = TrafficAnalytics(VehicleCounter(LINE), DensityAnalyzer(FULL))
    ta.reset(10.0)
    return ta.update(0, vehicles)


def test_annotate_backward_compatible_defaults():
    f = blank()
    out = vp.annotate_frame(f, [veh(7, 100, 100)])
    assert f.sum() == 0 and out.sum() > 0


def test_annotate_flags_disable_features():
    v = [veh(1, 100, 150)]
    st = stats_for(v)
    full = vp.annotate_frame(blank(), v, AnnotationConfig(), [LINE], [FULL], st, {"main": {"forward": 1, "reverse": 2, "total": 3}})
    minimal = vp.annotate_frame(blank(), v, AnnotationConfig.minimal(), [LINE], [FULL], st, {"main": {"forward": 1, "reverse": 2, "total": 3}})
    none = vp.annotate_frame(blank(), v, AnnotationConfig(False, False, False, False, False, False, False))
    assert none.sum() == 0
    assert full.sum() > minimal.sum() > 0
    only_line = vp.annotate_frame(blank(), [], AnnotationConfig(show_regions=False, show_counts=False), [LINE])
    assert only_line[100].sum() > 0  # counting line drawn at y=100


def test_annotate_counts_panel_and_region_outline():
    st = stats_for([])
    counts = vp.annotate_frame(blank(), [], AnnotationConfig(show_lines=False, show_regions=False), None, None, None,
                               {"main": {"forward": 1, "reverse": 2, "total": 3}})
    assert counts[:30, :200].sum() > 0
    region = vp.annotate_frame(blank(), [], AnnotationConfig(), None, [FULL], st)
    assert region[0].sum() > 0  # polygon outline on top edge
