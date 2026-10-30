from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import torch

from backend.config.vision_config import (
    MODEL_ENV_VAR,
    MODEL_REGISTRY,
    VEHICLENET_WEIGHTS_PATH,
    YOLO26M_WEIGHTS_PATH,
    resolve_model_selection,
)
from backend.services.density_analyzer import DensityAnalyzer, Region
from backend.services.detector import (
    VEHICLENET_UVH26_NAMES,
    InvalidCheckpointError,
    ModelNotFoundError,
    VehicleDetector,
)
from backend.services.tracker import VehicleTracker
from backend.services.vehicle_counter import CountingLine, VehicleCounter
from backend.services.video_processor import VideoProcessor

SAMPLE_IMAGE = Path(__file__).resolve().parents[1] / "ai" / "videos" / "samples" / "bus.jpg"

EXPECTED_VEHICLENET_NAMES = {
    0: "Hatchback",
    1: "Sedan",
    2: "SUV",
    3: "MUV",
    4: "Bus",
    5: "Truck",
    6: "Three-wheeler",
    7: "Two-wheeler",
    8: "LCV",
    9: "Mini-bus",
    10: "Tempo-traveller",
    11: "Bicycle",
    12: "Van",
    13: "Others",
}


class FakeVehicleNetModel:
    def __init__(self, rows=(), track_rows=()):
        self.names = dict(EXPECTED_VEHICLENET_NAMES)
        self.rows = list(rows)
        self.track_rows = list(track_rows)
        self.predict_kwargs = None
        self.track_kwargs = None
        self.predictor = SimpleNamespace(trackers=[SimpleNamespace(reset=lambda: None)])

    def predict(self, frame, **kwargs):
        self.predict_kwargs = kwargs
        boxes = SimpleNamespace(
            xyxy=SimpleNamespace(tolist=lambda: [r[:4] for r in self.rows]),
            conf=SimpleNamespace(tolist=lambda: [r[4] for r in self.rows]),
            cls=SimpleNamespace(tolist=lambda: [r[5] for r in self.rows]),
        )
        return [SimpleNamespace(boxes=boxes)]

    def track(self, frame, **kwargs):
        self.track_kwargs = kwargs
        r = self.track_rows.pop(0) if self.track_rows else []
        if not r:
            return [
                SimpleNamespace(
                    boxes=SimpleNamespace(
                        id=None,
                        xyxy=SimpleNamespace(tolist=lambda: []),
                        conf=SimpleNamespace(tolist=lambda: []),
                        cls=SimpleNamespace(tolist=lambda: []),
                    )
                )
            ]
        boxes = SimpleNamespace(
            xyxy=SimpleNamespace(tolist=lambda: [x[:4] for x in r]),
            id=SimpleNamespace(tolist=lambda: [x[4] for x in r]),
            conf=SimpleNamespace(tolist=lambda: [x[5] for x in r]),
            cls=SimpleNamespace(tolist=lambda: [x[6] for x in r]),
        )
        return [SimpleNamespace(boxes=boxes)]


def test_model_registry_metadata_and_licence():
    meta = MODEL_REGISTRY["vehiclenet"]
    assert meta.name == "VehicleNet-Y26m"
    assert meta.author == "Perception365"
    assert meta.repository_url == "https://huggingface.co/Perception365/VehicleNet-Y26m"
    assert meta.license == "AGPL-3.0"
    assert meta.weights_path == VEHICLENET_WEIGHTS_PATH


def test_model_selection_via_argument_and_env_var(monkeypatch):
    monkeypatch.delenv(MODEL_ENV_VAR, raising=False)
    key_default, path_default, _ = resolve_model_selection()
    assert key_default == "yolo26m" and path_default == YOLO26M_WEIGHTS_PATH

    monkeypatch.setenv(MODEL_ENV_VAR, "vehiclenet")
    key_env, path_env, meta_env = resolve_model_selection()
    assert key_env == "vehiclenet" and path_env == VEHICLENET_WEIGHTS_PATH
    assert meta_env is not None and meta_env.author == "Perception365"

    # Explicit argument overrides environment variable
    key_arg, path_arg, _ = resolve_model_selection(model_name="yolo26m")
    assert key_arg == "yolo26m" and path_arg == YOLO26M_WEIGHTS_PATH

    with pytest.raises(ValueError, match="Unsupported model selection"):
        resolve_model_selection(model_name="nonexistent_model_name")


def test_vehiclenet_all_14_classes_extracted_and_mapped():
    fake = FakeVehicleNetModel(
        rows=[
            (10, 10, 50, 50, 0.91, 6),  # Three-wheeler
            (60, 60, 90, 90, 0.87, 7),  # Two-wheeler
            (100, 100, 180, 180, 0.94, 4),  # Bus
            (200, 200, 260, 260, 0.82, 10),  # Tempo-traveller
        ]
    )
    det = VehicleDetector(model=fake, device="cpu")
    assert len(det.supported_classes) == 14
    assert det.supported_classes == EXPECTED_VEHICLENET_NAMES
    assert set(det.supported_classes.values()) == set(VEHICLENET_UVH26_NAMES)

    frame = np.zeros((300, 300, 3), dtype=np.uint8)
    out = det.detect(frame)
    assert [(d.class_id, d.class_name) for d in out] == [
        (6, "Three-wheeler"),
        (7, "Two-wheeler"),
        (4, "Bus"),
        (10, "Tempo-traveller"),
    ]
    assert fake.predict_kwargs["classes"] == list(range(14))


def test_missing_and_invalid_checkpoint_errors(tmp_path):
    with pytest.raises(ModelNotFoundError):
        VehicleDetector(weights_path=tmp_path / "missing_best.pt", device="cpu")

    bad_ext = tmp_path / "weights.bin"
    bad_ext.write_bytes(b"123")
    with pytest.raises(InvalidCheckpointError, match="Unsupported checkpoint extension"):
        VehicleDetector(weights_path=bad_ext, device="cpu")

    corrupt_pt = tmp_path / "corrupt.pt"
    corrupt_pt.write_bytes(b"not a valid pytorch zip archive")
    with pytest.raises(InvalidCheckpointError, match="Failed to load checkpoint"):
        VehicleDetector(weights_path=corrupt_pt, device="cpu")

    # Model without valid names mapping
    with pytest.raises(InvalidCheckpointError, match="valid 'names' mapping"):
        VehicleDetector(model=SimpleNamespace(names={}), device="cpu")


def test_cpu_fallback_when_mps_unavailable(monkeypatch):
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    det = VehicleDetector(model=FakeVehicleNetModel(), device="auto")
    assert det.device == "cpu"


def test_vehiclenet_tracker_and_video_processor_compatibility(tmp_path):
    # Track 1: Three-wheeler moving down across y=100; Track 2: Two-wheeler moving up across y=100
    script = [
        [(40, 50, 60, 80, 1, 0.92, 6), (120, 110, 140, 130, 2, 0.88, 7)],
        [(40, 65, 60, 95, 1, 0.91, 6), (120, 95, 140, 115, 2, 0.89, 7)],
        [(40, 100, 60, 130, 1, 0.93, 6), (120, 50, 140, 70, 2, 0.90, 7)],
    ]
    fake = FakeVehicleNetModel(track_rows=script)
    det = VehicleDetector(model=fake, device="cpu")
    tracker = VehicleTracker(det)
    counter = VehicleCounter(CountingLine("gate", (0, 100), (200, 100)))
    density = DensityAnalyzer(Region("zone", [(0, 0), (200, 0), (200, 200), (0, 200)]))

    vid_path = tmp_path / "input.mp4"
    writer = cv2.VideoWriter(str(vid_path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (200, 200))
    for _ in range(3):
        writer.write(np.full((200, 200, 3), 25, dtype=np.uint8))
    writer.release()

    proc = VideoProcessor(tracker, output_dir=tmp_path / "out", counter=counter, density=density)
    summary = proc.process(vid_path)
    assert summary.frame_count == 3
    assert summary.unique_track_ids == [1, 2]
    assert summary.counting["by_class"] == {"Three-wheeler": 1, "Two-wheeler": 1}
    assert summary.analytics["unique_vehicles_by_class"] == {"Three-wheeler": 1, "Two-wheeler": 1}


@pytest.mark.skipif(not VEHICLENET_WEIGHTS_PATH.is_file(), reason="VehicleNet-Y26m checkpoint not present")
def test_real_vehiclenet_checkpoint_cpu_and_mps_inference():
    det_cpu = VehicleDetector(model_name="vehiclenet", device="cpu")
    assert det_cpu.model_key == "vehiclenet"
    assert det_cpu.supported_classes == EXPECTED_VEHICLENET_NAMES
    info = det_cpu.model_info()
    assert info["num_supported_classes"] == 14
    assert info["metadata"]["license"] == "AGPL-3.0"

    # Empty black frame returns no detections
    empty = np.zeros((320, 320, 3), dtype=np.uint8)
    assert det_cpu.detect(empty) == []

    if SAMPLE_IMAGE.is_file():
        dets_cpu = det_cpu.detect(SAMPLE_IMAGE)
        assert len(dets_cpu) >= 1
        assert dets_cpu[0].class_id == 4 and dets_cpu[0].class_name == "Bus"
        assert 0.25 <= dets_cpu[0].confidence <= 1.0
        x1, y1, x2, y2 = dets_cpu[0].bbox
        assert 0 <= x1 < x2 and 0 <= y1 < y2

        if torch.backends.mps.is_available():
            det_mps = VehicleDetector(model_name="vehiclenet", device="mps")
            assert det_mps.device == "mps"
            dets_mps = det_mps.detect(SAMPLE_IMAGE)
            assert len(dets_mps) == len(dets_cpu)
            assert dets_mps[0].class_name == "Bus"
