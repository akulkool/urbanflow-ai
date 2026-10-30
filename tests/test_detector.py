from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.services import detector as det_mod
from backend.services.detector import (
    DeviceUnavailableError,
    InvalidImageError,
    ModelNotFoundError,
    VehicleDetector,
)

COCO_NAMES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck", 9: "traffic light"}
SAMPLE = Path(__file__).resolve().parents[1] / "ai" / "videos" / "samples" / "bus.jpg"


class FakeModel:
    def __init__(self, names, rows):
        self.names = names
        self.rows = rows  # (x1, y1, x2, y2, conf, cls)
        self.kwargs = None

    def predict(self, frame, **kwargs):
        self.kwargs = kwargs
        r = self.rows
        boxes = SimpleNamespace(
            xyxy=SimpleNamespace(tolist=lambda: [x[:4] for x in r]),
            conf=SimpleNamespace(tolist=lambda: [x[4] for x in r]),
            cls=SimpleNamespace(tolist=lambda: [x[5] for x in r]),
        )
        return [SimpleNamespace(boxes=boxes)]


def make(rows=(), names=COCO_NAMES, **kw):
    return VehicleDetector(model=FakeModel(names, list(rows)), device="cpu", **kw)


FRAME = np.zeros((100, 100, 3), dtype=np.uint8)


def test_filters_to_vehicle_classes_and_structure():
    d = make([(1, 2, 3, 4, 0.9, 2), (0, 0, 5, 5, 0.8, 0), (5, 5, 9, 9, 0.7, 5)])
    out = d.detect(FRAME)
    assert [x.class_name for x in out] == ["car", "bus"]
    assert out[0].to_dict() == {"class_id": 2, "class_name": "car", "confidence": 0.9, "bbox": [1.0, 2.0, 3.0, 4.0]}


def test_no_auto_rickshaw_in_coco_model():
    d = make()
    assert "auto_rickshaw" not in d.supported_classes.values()
    assert "auto_rickshaw" in d.missing_classes


def test_auto_rickshaw_only_from_model_defined_class():
    names = {**COCO_NAMES, 10: "auto_rickshaw"}
    d = make([(0, 0, 1, 1, 0.9, 10)], names=names)
    assert d.detect(FRAME)[0].class_name == "auto_rickshaw"


def test_config_passed_and_threshold_enforced():
    d = make([(0, 0, 1, 1, 0.3, 2)], confidence=0.5, image_size=320)
    assert d.detect(FRAME) == []
    assert d.model.kwargs["conf"] == 0.5 and d.model.kwargs["imgsz"] == 320
    assert d.model.kwargs["classes"] == [1, 2, 3, 5, 7]


@pytest.mark.parametrize("kw", [{"confidence": 1.5}, {"image_size": 0}])
def test_invalid_config(kw):
    with pytest.raises(ValueError):
        make(**kw)


def test_missing_weights(tmp_path):
    with pytest.raises(ModelNotFoundError):
        VehicleDetector(weights_path=tmp_path / "nope.pt", device="cpu")


def test_unavailable_and_unknown_device(monkeypatch):
    import torch

    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    with pytest.raises(DeviceUnavailableError):
        det_mod.resolve_device("mps")
    assert det_mod.resolve_device("auto") == "cpu"
    with pytest.raises(DeviceUnavailableError):
        det_mod.resolve_device("cuda")


@pytest.mark.parametrize("bad", [None, 123, np.zeros((10, 10)), np.zeros((0, 0, 3), np.uint8)])
def test_invalid_array_inputs(bad):
    with pytest.raises(InvalidImageError):
        make().detect(bad)


def test_invalid_file_inputs(tmp_path):
    d = make()
    with pytest.raises(InvalidImageError):
        d.detect(tmp_path / "missing.jpg")
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(InvalidImageError):
        d.detect(txt)
    corrupt = tmp_path / "bad.jpg"
    corrupt.write_bytes(b"not an image")
    with pytest.raises(InvalidImageError):
        d.detect(corrupt)


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample image missing")
def test_sample_image_loads_with_mock_model():
    d = make([(0, 0, 10, 10, 0.9, 5)])
    assert d.detect(SAMPLE)[0].class_name == "bus"
