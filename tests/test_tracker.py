from types import SimpleNamespace

import numpy as np
import pytest

from backend.services.detector import InvalidImageError, VehicleDetector
from backend.services.tracker import TrackingError, VehicleTracker

NAMES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
FRAME = np.zeros((100, 100, 3), dtype=np.uint8)


def _tl(v):
    return SimpleNamespace(tolist=lambda: v)


class FakeTrackerState:
    def __init__(self):
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1


class FakeModel:
    """Scripted per-frame outputs: list of rows (x1,y1,x2,y2,track_id,conf,cls)."""

    def __init__(self, script, names=NAMES):
        self.names = names
        self.script = list(script)
        self.calls = []
        self.predictor = SimpleNamespace(trackers=[FakeTrackerState()])

    def track(self, frame, **kwargs):
        self.calls.append(kwargs)
        rows = self.script.pop(0)
        if isinstance(rows, Exception):
            raise rows
        if not rows:
            return [SimpleNamespace(boxes=SimpleNamespace(id=None, xyxy=_tl([]), conf=_tl([]), cls=_tl([])))]
        boxes = SimpleNamespace(
            xyxy=_tl([r[:4] for r in rows]),
            id=_tl([r[4] for r in rows]),
            conf=_tl([r[5] for r in rows]),
            cls=_tl([r[6] for r in rows]),
        )
        return [SimpleNamespace(boxes=boxes)]


def make(script, names=NAMES):
    model = FakeModel(script, names)
    det = VehicleDetector(model=model, device="cpu", confidence=0.3, image_size=320)
    return VehicleTracker(det), model


def test_persistent_ids_and_structure():
    t, m = make([[(0, 0, 10, 10, 1, 0.9, 2)], [(2, 2, 12, 12, 1, 0.88, 2)]])
    a, b = t.update(FRAME), t.update(FRAME)
    assert a[0].track_id == b[0].track_id == 1
    assert a[0].to_dict() == {
        "track_id": 1, "class_id": 2, "class_name": "car", "confidence": 0.9, "bbox": [0.0, 0.0, 10.0, 10.0]
    }
    assert all(c["persist"] is True for c in m.calls)  # state kept between frames


def test_multiple_vehicles_and_class_names():
    t, _ = make([[(0, 0, 1, 1, 1, 0.9, 2), (5, 5, 9, 9, 2, 0.8, 5), (1, 1, 2, 2, 3, 0.7, 3)]])
    out = t.update(FRAME)
    assert [(v.track_id, v.class_name) for v in out] == [(1, "car"), (2, "bus"), (3, "motorcycle")]


def test_unsupported_class_dropped_not_relabelled():
    t, _ = make([[(0, 0, 1, 1, 1, 0.9, 0)]])  # person
    assert t.update(FRAME) == []


def test_empty_frame_returns_empty_and_continues():
    t, _ = make([[(0, 0, 1, 1, 1, 0.9, 2)], [], [(0, 0, 1, 1, 1, 0.9, 2)]])
    assert len(t.update(FRAME)) == 1
    assert t.update(FRAME) == []
    assert t.update(FRAME)[0].track_id == 1


def test_uses_detector_config_and_class_filter():
    t, m = make([[]])
    t.update(FRAME)
    k = m.calls[0]
    assert (k["conf"], k["imgsz"], k["device"], k["tracker"]) == (0.3, 320, "cpu", "bytetrack.yaml")
    assert k["classes"] == [1, 2, 3, 5, 7]


def test_future_auto_rickshaw_class_passes_through():
    names = {**NAMES, 10: "auto_rickshaw"}
    t, _ = make([[(0, 0, 1, 1, 4, 0.9, 10)]], names)
    assert t.update(FRAME)[0].class_name == "auto_rickshaw"


def test_reset_clears_tracker_state():
    t, m = make([[]])
    t.update(FRAME)
    assert t.frames_processed == 1
    t.reset()
    assert m.predictor.trackers[0].reset_calls == 1 and t.frames_processed == 0


def test_reset_before_any_frame_is_safe():
    t, m = make([])
    m.predictor = None
    t.reset()


@pytest.mark.parametrize("bad", [None, "frame.jpg", np.zeros((10, 10)), np.zeros((0, 0, 3), np.uint8)])
def test_invalid_frames(bad):
    t, m = make([])
    with pytest.raises(InvalidImageError):
        t.update(bad)
    assert m.calls == []


def test_tracking_error_wrapped():
    t, _ = make([RuntimeError("boom")])
    with pytest.raises(TrackingError, match="boom"):
        t.update(FRAME)
    assert t.frames_processed == 0
