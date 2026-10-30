"""Configuration for the vision analytics pipeline (model selection, annotation, windows).

Model Attribution & Licence Notice:
- VehicleNet-Y26m:
  - Author: Perception365
  - Repository: https://huggingface.co/Perception365/VehicleNet-Y26m
  - Dataset: UVH-26 (14 Indian road vehicle classes)
  - Checkpoint: ai/models/VehicleNet-Y26m/weights/best.pt
  - Licence: GNU Affero General Public License v3.0 (AGPL-3.0)
- YOLO26m (fallback):
  - Checkpoint: ai/models/yolo26m.pt
  - Framework: Ultralytics YOLO (AGPL-3.0)
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODEL_ENV_VAR = "URBANFLOW_MODEL"
DEFAULT_MODEL_KEY = "yolo26m"

YOLO26M_WEIGHTS_PATH = PROJECT_ROOT / "ai" / "models" / "yolo26m.pt"
VEHICLENET_WEIGHTS_PATH = PROJECT_ROOT / "ai" / "models" / "VehicleNet-Y26m" / "weights" / "best.pt"

DEFAULT_WINDOW_SECONDS = 10.0


@dataclass(frozen=True)
class ModelMetadata:
    key: str
    name: str
    author: str
    repository_url: str
    license: str
    architecture: str
    dataset: str
    weights_path: Path
    download_date: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["weights_path"] = str(self.weights_path)
        return d


MODEL_REGISTRY: dict[str, ModelMetadata] = {
    "vehiclenet": ModelMetadata(
        key="vehiclenet",
        name="VehicleNet-Y26m",
        author="Perception365",
        repository_url="https://huggingface.co/Perception365/VehicleNet-Y26m",
        license="AGPL-3.0",
        architecture="YOLO26m (DetectionModel, 14 classes)",
        dataset="UVH-26 (Indian traffic vehicle dataset)",
        weights_path=VEHICLENET_WEIGHTS_PATH,
        download_date="2026-10-30",
        notes=(
            "Academic research and hackathon demonstration use only. "
            "Trained on UVH-26 with 14 Indian traffic vehicle classes."
        ),
    ),
    "yolo26m": ModelMetadata(
        key="yolo26m",
        name="YOLO26m (COCO Pretrained)",
        author="Ultralytics",
        repository_url="https://github.com/ultralytics/ultralytics",
        license="AGPL-3.0",
        architecture="YOLO26m (DetectionModel, 80 COCO classes)",
        dataset="COCO",
        weights_path=YOLO26M_WEIGHTS_PATH,
        download_date="2026-10-30",
        notes="Fallback COCO-pretrained detector; filters to supported road vehicle classes.",
    ),
}

MODEL_ALIASES: dict[str, str] = {
    "vehiclenet": "vehiclenet",
    "vehiclenet-y26m": "vehiclenet",
    "vehiclenet_y26m": "vehiclenet",
    "uvh26": "vehiclenet",
    "yolo26m": "yolo26m",
    "yolo": "yolo26m",
    "coco": "yolo26m",
    "default": "yolo26m",
}


def resolve_model_selection(
    model_name: str | None = None,
    weights_path: str | Path | None = None,
) -> tuple[str, Path, ModelMetadata | None]:
    """Resolve (model_key, weights_path, metadata) from explicit args or URBANFLOW_MODEL."""
    if weights_path is not None:
        p = Path(weights_path)
        for key, meta in MODEL_REGISTRY.items():
            if p.resolve() == meta.weights_path.resolve():
                return key, p, meta
        return "custom", p, None

    raw = (model_name if model_name is not None else os.environ.get(MODEL_ENV_VAR, DEFAULT_MODEL_KEY)).strip()
    if not raw:
        raw = DEFAULT_MODEL_KEY
    lower = raw.lower()
    if lower in MODEL_ALIASES:
        canonical = MODEL_ALIASES[lower]
        meta = MODEL_REGISTRY[canonical]
        return canonical, meta.weights_path, meta

    # Allow passing a direct file path in model_name or URBANFLOW_MODEL
    candidate_path = Path(raw)
    if candidate_path.suffix.lower() == ".pt" or "/" in raw or "\\" in raw:
        return "custom", candidate_path, None

    raise ValueError(
        f"Unsupported model selection '{raw}'. Supported model names: {sorted(MODEL_REGISTRY)} "
        f"(or set {MODEL_ENV_VAR} to 'vehiclenet' or 'yolo26m')."
    )


@dataclass(frozen=True)
class AnnotationConfig:
    """Toggle overlays on the annotated video. Disable features to reduce clutter/cost."""

    show_boxes: bool = True
    show_labels: bool = True  # class name, track ID, confidence
    show_lines: bool = True  # virtual counting lines
    show_counts: bool = True  # directional crossing counts panel
    show_regions: bool = True  # road-region outlines
    show_density: bool = True  # density level per region (count-based)
    show_congestion: bool = True  # congestion level per region (estimate)
    font_scale: float = 0.5
    panel_alpha: float = 0.55

    @classmethod
    def minimal(cls) -> "AnnotationConfig":
        """Boxes and labels only (previous behaviour)."""
        return cls(show_lines=False, show_counts=False, show_regions=False, show_density=False, show_congestion=False)
