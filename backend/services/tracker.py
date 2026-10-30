"""ByteTrack vehicle tracking for UrbanFlow AI (tracking only).

Reuses the YOLO model already loaded by ``VehicleDetector`` (no second weight load)
and the detector's verified class map. Classes are never relabelled: names and IDs
come straight from the model, so e.g. ``auto_rickshaw`` appears only if a future
fine-tuned model defines it.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from backend.services.detector import DetectorError, InvalidImageError, VehicleDetector

logger = logging.getLogger(__name__)

TRACKER_CONFIG = "bytetrack.yaml"  # bundled with Ultralytics; nothing is downloaded


class TrackingError(DetectorError):
    """Raised when the underlying tracking call fails."""


@dataclass(frozen=True)
class TrackedVehicle:
    track_id: int
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bbox"] = list(self.bbox)
        return d


class VehicleTracker:
    """Stateful tracker. Call ``update(frame)`` on consecutive frames of ONE video,
    and ``reset()`` before starting another video."""

    def __init__(self, detector: VehicleDetector, tracker_config: str = TRACKER_CONFIG) -> None:
        self.detector = detector
        self.tracker_config = tracker_config
        self.frames_processed = 0

    def update(self, frame: np.ndarray) -> list[TrackedVehicle]:
        """Track vehicles in the next BGR frame. Returns [] when nothing is tracked."""
        if (
            not isinstance(frame, np.ndarray)
            or frame.ndim != 3
            or frame.shape[2] != 3
            or frame.size == 0
        ):
            raise InvalidImageError("Frame must be a non-empty numpy array with shape (H, W, 3).")

        det = self.detector
        try:
            results = det.model.track(
                frame,
                persist=True,
                tracker=self.tracker_config,
                conf=det.confidence,
                imgsz=det.image_size,
                device=det.device,
                classes=sorted(det.class_map) or None,
                verbose=False,
            )
        except Exception as exc:  # state may be inconsistent; caller can reset()
            raise TrackingError(f"Tracking failed: {exc}") from exc

        self.frames_processed += 1
        tracked: list[TrackedVehicle] = []
        for result in results:
            boxes = result.boxes
            if boxes is None or boxes.id is None:  # no confirmed tracks this frame
                continue
            for xyxy, tid, conf, cls in zip(
                boxes.xyxy.tolist(), boxes.id.tolist(), boxes.conf.tolist(), boxes.cls.tolist()
            ):
                class_id = int(cls)
                if class_id not in det.class_map:
                    continue
                tracked.append(
                    TrackedVehicle(
                        track_id=int(tid),
                        class_id=class_id,
                        class_name=det.class_map[class_id],
                        confidence=round(float(conf), 4),
                        bbox=tuple(round(float(v), 2) for v in xyxy),
                    )
                )
        return tracked

    def reset(self) -> None:
        """Clear all track state and restart IDs at 1 (call between videos)."""
        predictor = getattr(self.detector.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", None) or []:
            tracker.reset()
        self.frames_processed = 0
        logger.info("Tracker state reset.")
