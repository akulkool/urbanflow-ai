"""Vehicle detector for UrbanFlow AI (detection only: no tracking/counting/video).

Supports configurable model selection between:
- ``vehiclenet``: Perception365/VehicleNet-Y26m (UVH-26 14 Indian vehicle classes, AGPL-3.0)
  at ``ai/models/VehicleNet-Y26m/weights/best.pt``
- ``yolo26m``: COCO-pretrained YOLO26m fallback at ``ai/models/yolo26m.pt``

Model selection can be configured via ``model_name="vehiclenet"|"yolo26m"``, via
``weights_path=...``, or without modifying code by setting the environment variable
``URBANFLOW_MODEL=vehiclenet``.

Supported classes are matched dynamically by *name* against the loaded model's own
``names`` mapping, so IDs always come from the checkpoint rather than being hardcoded.
No class is ever relabelled.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from backend.config.vision_config import (
    MODEL_ENV_VAR,
    MODEL_REGISTRY,
    PROJECT_ROOT,
    VEHICLENET_WEIGHTS_PATH,
    YOLO26M_WEIGHTS_PATH,
    ModelMetadata,
    resolve_model_selection,
)

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS_PATH = YOLO26M_WEIGHTS_PATH

# Class names kept when present in model.names:
# 1. COCO road vehicle classes (present in yolo26m.pt)
COCO_VEHICLE_NAMES = ("bicycle", "car", "motorcycle", "bus", "truck")
# 2. UVH-26 14 Indian traffic vehicle classes (present in VehicleNet-Y26m best.pt)
VEHICLENET_UVH26_NAMES = (
    "Hatchback",
    "Sedan",
    "SUV",
    "MUV",
    "Bus",
    "Truck",
    "Three-wheeler",
    "Two-wheeler",
    "LCV",
    "Mini-bus",
    "Tempo-traveller",
    "Bicycle",
    "Van",
    "Others",
)
# 3. Additional fine-tuned Indian road vehicle names (case variants / other datasets)
FINE_TUNED_VEHICLE_NAMES = (
    "auto_rickshaw",
    "e_rickshaw",
    "tempo",
    "tractor",
    "cycle_rickshaw",
) + VEHICLENET_UVH26_NAMES

SUPPORTED_CLASS_NAMES = COCO_VEHICLE_NAMES + FINE_TUNED_VEHICLE_NAMES
_SUPPORTED_LOWER = {n.lower() for n in SUPPORTED_CLASS_NAMES}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


class DetectorError(Exception):
    """Base class for detector errors."""


class ModelNotFoundError(DetectorError):
    """Raised when the weights file does not exist."""


class InvalidCheckpointError(DetectorError):
    """Raised when the weights file is corrupted, unreadable, or lacks model class names."""


class DeviceUnavailableError(DetectorError):
    """Raised when the requested inference device is unavailable."""


class InvalidImageError(DetectorError):
    """Raised when the image input is missing or invalid."""


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bbox"] = list(self.bbox)
        return d


def resolve_device(device: str = "auto") -> str:
    """Return 'mps' or 'cpu'. 'auto' prefers MPS. Raises if unavailable."""
    import torch

    device = device.lower()
    mps_ok = bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available()
    if device == "auto":
        return "mps" if mps_ok else "cpu"
    if device == "cpu":
        return "cpu"
    if device == "mps":
        if not mps_ok:
            raise DeviceUnavailableError("MPS device requested but is not available.")
        return "mps"
    raise DeviceUnavailableError(f"Unsupported device '{device}'. Use 'auto', 'mps' or 'cpu'.")


class VehicleDetector:
    def __init__(
        self,
        weights_path: str | Path | None = None,
        confidence: float = 0.25,
        image_size: int = 640,
        device: str = "auto",
        model: Any = None,
        model_name: str | None = None,
    ) -> None:
        """
        ``model`` may be injected (tests, reuse); otherwise weights are resolved from
        ``weights_path``, ``model_name`` ('vehiclenet' or 'yolo26m'), or the
        ``URBANFLOW_MODEL`` environment variable (defaulting to 'yolo26m').
        Weights must already exist on disk; nothing is downloaded.
        """
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1.")
        if not isinstance(image_size, int) or image_size <= 0:
            raise ValueError("image_size must be a positive integer.")
        self.confidence = confidence
        self.image_size = image_size
        self.device = resolve_device(device)
        self.model_key: str = "injected"
        self.weights_path: Path | None = None
        self.metadata: ModelMetadata | None = None

        if model is None:
            key, path, meta = resolve_model_selection(model_name=model_name, weights_path=weights_path)
            if not path.is_file():
                raise ModelNotFoundError(f"Model weights not found: {path}")
            if path.suffix.lower() != ".pt":
                raise InvalidCheckpointError(f"Unsupported checkpoint extension '{path.suffix}' for {path}")
            from ultralytics import YOLO

            try:
                model = YOLO(str(path))
            except Exception as exc:
                raise InvalidCheckpointError(f"Failed to load checkpoint '{path}': {exc}") from exc
            self.model_key = key
            self.weights_path = path
            self.metadata = meta
        self.model = model

        raw_names = getattr(model, "names", None)
        if not isinstance(raw_names, dict) or not raw_names:
            raise InvalidCheckpointError("Loaded model does not expose a valid 'names' mapping.")
        names = dict(raw_names)

        # Verified dynamically against the loaded model: id -> exact model class name
        self.class_map: dict[int, str] = {
            int(i): str(n) for i, n in names.items() if str(n).lower() in _SUPPORTED_LOWER
        }
        present_lower = {n.lower() for n in self.class_map.values()}
        self.missing_classes = [n for n in SUPPORTED_CLASS_NAMES if n.lower() not in present_lower]
        logger.info(
            "Detector [%s] classes (%d): %s",
            self.model_key,
            len(self.class_map),
            self.class_map,
        )

    @property
    def supported_classes(self) -> dict[int, str]:
        return dict(self.class_map)

    def model_info(self) -> dict[str, Any]:
        """Return structured metadata about the active model and its verified classes."""
        return {
            "model_key": self.model_key,
            "weights_path": str(self.weights_path) if self.weights_path else None,
            "device": self.device,
            "confidence": self.confidence,
            "image_size": self.image_size,
            "num_supported_classes": len(self.class_map),
            "supported_classes": dict(self.class_map),
            "metadata": self.metadata.to_dict() if self.metadata else None,
        }

    @staticmethod
    def _load_image(image: str | Path | np.ndarray) -> np.ndarray | str:
        if isinstance(image, np.ndarray):
            if image.ndim != 3 or image.shape[2] != 3 or image.size == 0:
                raise InvalidImageError("Image array must be non-empty with shape (H, W, 3).")
            return image
        if isinstance(image, (str, Path)):
            path = Path(image)
            if not path.is_file():
                raise InvalidImageError(f"Image file not found: {path}")
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                raise InvalidImageError(f"Unsupported image type: {path.suffix}")
            import cv2

            arr = cv2.imread(str(path))
            if arr is None:
                raise InvalidImageError(f"Could not decode image: {path}")
            return arr
        raise InvalidImageError(f"Unsupported image input type: {type(image).__name__}")

    def detect(self, image: str | Path | np.ndarray) -> list[Detection]:
        """Detect supported vehicles in a BGR array or image path."""
        frame = self._load_image(image)
        results = self.model.predict(
            frame,
            conf=self.confidence,
            imgsz=self.image_size,
            device=self.device,
            classes=sorted(self.class_map) or None,
            verbose=False,
        )
        detections: list[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for xyxy, conf, cls in zip(
                boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist()
            ):
                class_id = int(cls)
                if class_id not in self.class_map or conf < self.confidence:
                    continue
                detections.append(
                    Detection(
                        class_id=class_id,
                        class_name=self.class_map[class_id],
                        confidence=round(float(conf), 4),
                        bbox=tuple(round(float(v), 2) for v in xyxy),
                    )
                )
        return detections


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Run the UrbanFlow vehicle detector on an image.")
    parser.add_argument("image")
    parser.add_argument(
        "--model",
        default=None,
        help=f"Model key ('vehiclenet' or 'yolo26m'); defaults to ${MODEL_ENV_VAR} or 'yolo26m'.",
    )
    parser.add_argument("--weights", default=None, help="Optional explicit .pt weights path")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="auto", choices=["auto", "mps", "cpu"])
    args = parser.parse_args()
    try:
        det = VehicleDetector(
            weights_path=args.weights,
            confidence=args.conf,
            image_size=args.imgsz,
            device=args.device,
            model_name=args.model,
        )
        out = [d.to_dict() for d in det.detect(args.image)]
    except (DetectorError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}")
    print(
        json.dumps(
            {
                "model": det.model_key,
                "weights": str(det.weights_path) if det.weights_path else None,
                "device": det.device,
                "count": len(out),
                "detections": out,
            },
            indent=2,
        )
    )
