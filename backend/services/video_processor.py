"""Video processing pipeline for UrbanFlow AI: read -> track -> annotate -> save.

Only orchestrates the existing ``VehicleTracker``; it does no counting, density or
congestion analysis.

Run:  .venv312/bin/python -m backend.services.video_processor INPUT.mp4 [-o OUT.mp4]
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from backend.config.vision_config import DEFAULT_WINDOW_SECONDS, AnnotationConfig
from backend.schemas.traffic import CongestionLevel, DensityLevel, FrameStats
from backend.services.congestion_analyzer import CongestionAnalyzer
from backend.services.density_analyzer import DensityAnalyzer, Region
from backend.services.detector import PROJECT_ROOT, DetectorError, VehicleDetector
from backend.services.tracker import TrackedVehicle, VehicleTracker
from backend.services.traffic_analytics import TrafficAnalytics
from backend.services.vehicle_counter import CountingLine, VehicleCounter

logger = logging.getLogger(__name__)

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "ai" / "outputs" / "videos"
DEFAULT_FPS = 25.0
FOURCC = "mp4v"


class VideoProcessingError(DetectorError):
    """Base class for video pipeline errors."""


class InvalidVideoError(VideoProcessingError):
    """Missing path, unsupported format, or a video that cannot be opened/read."""


class VideoWriterError(VideoProcessingError):
    """Output video could not be created or written."""


class FrameProcessingError(VideoProcessingError):
    """Tracking failed on a frame."""


@dataclass
class VideoSummary:
    input_path: str
    output_path: str
    frame_count: int
    detection_count: int  # total tracked-vehicle observations over all frames
    unique_track_ids: list[int] = field(default_factory=list)
    fps: float = 0.0
    width: int = 0
    height: int = 0
    skipped_frames: int = 0
    counting: dict[str, Any] | None = None  # VehicleCounter summary (virtual-line crossings)
    analytics: dict[str, Any] | None = None  # unified TrafficAnalytics result

    @property
    def unique_vehicle_count(self) -> int:
        return len(self.unique_track_ids)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["unique_vehicle_count"] = self.unique_vehicle_count
        d["resolution"] = [self.width, self.height]
        return d


_DENSITY_COLORS = {
    DensityLevel.LOW: (80, 200, 80),
    DensityLevel.MODERATE: (0, 220, 220),
    DensityLevel.HIGH: (0, 140, 255),
    DensityLevel.VERY_HIGH: (0, 0, 230),
}
_CONGESTION_COLORS = {
    CongestionLevel.LOW: (80, 200, 80),
    CongestionLevel.MODERATE: (0, 220, 220),
    CongestionLevel.HIGH: (0, 140, 255),
    CongestionLevel.SEVERE: (0, 0, 230),
}
_FONT = cv2.FONT_HERSHEY_SIMPLEX


def _draw_panel(img: np.ndarray, lines: list[str], origin: tuple[int, int], cfg: AnnotationConfig) -> None:
    """Semi-transparent text panel; blends only the small panel ROI (cheap)."""
    if not lines:
        return
    sizes = [cv2.getTextSize(t, _FONT, cfg.font_scale, 1)[0] for t in lines]
    lh = max(sz[1] for sz in sizes) + 6
    pw, ph = max(sz[0] for sz in sizes) + 10, lh * len(lines) + 6
    x, y = origin
    h, w = img.shape[:2]
    x2, y2 = min(x + pw, w), min(y + ph, h)
    if x2 <= x or y2 <= y:
        return
    roi = img[y:y2, x:x2]
    cv2.addWeighted(np.zeros_like(roi), cfg.panel_alpha, roi, 1 - cfg.panel_alpha, 0, dst=roi)
    for i, t in enumerate(lines):
        cv2.putText(img, t, (x + 5, y + lh * (i + 1)), _FONT, cfg.font_scale, (255, 255, 255), 1, cv2.LINE_AA)


def annotate_frame(
    frame: np.ndarray,
    vehicles: list[TrackedVehicle],
    config: AnnotationConfig | None = None,
    lines: list[CountingLine] | None = None,
    regions: list[Region] | None = None,
    stats: FrameStats | None = None,
    line_counts: dict[str, Any] | None = None,
) -> np.ndarray:
    """Return a copy of ``frame`` with overlays drawn.

    With only ``frame`` and ``vehicles`` this draws boxes and 'class #id conf' labels
    (original behaviour). Lines, regions, counts, density and congestion overlays are
    drawn when the corresponding data is supplied and enabled in ``config``.
    """
    cfg = config or AnnotationConfig()
    out = frame.copy()
    h, w = out.shape[:2]

    if cfg.show_regions and regions:
        dens = {d.region: d for d in (stats.densities if stats else [])}
        cong = {c.region: c for c in (stats.congestion if stats else [])}
        for r in regions:
            d, c = dens.get(r.name), cong.get(r.name)
            color = _CONGESTION_COLORS[c.level] if (c and cfg.show_congestion) else (
                _DENSITY_COLORS[d.level] if (d and cfg.show_density) else (200, 200, 200)
            )
            pts = np.round(np.array(r.polygon)).astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(out, [pts], True, color, 2, cv2.LINE_AA)
            parts = [r.name]
            if d and cfg.show_density:
                parts.append(f"{d.vehicle_count} veh {d.level.value}")
            if c and cfg.show_congestion:
                parts.append(f"cong {c.level.value}{' (est.)' if c.is_estimate else ''}")
            lx, ly = int(pts[0, 0, 0]), int(pts[0, 0, 1])
            cv2.putText(out, " | ".join(parts), (max(lx, 0), max(ly - 6, 12)), _FONT, cfg.font_scale, color, 1, cv2.LINE_AA)

    if cfg.show_lines and lines:
        for ln in lines:
            p1 = (int(round(ln.start[0])), int(round(ln.start[1])))
            p2 = (int(round(ln.end[0])), int(round(ln.end[1])))
            cv2.line(out, p1, p2, (255, 255, 0), 2, cv2.LINE_AA)
            cv2.putText(out, ln.name, (max(p1[0], 0), max(p1[1] - 6, 12)), _FONT, cfg.font_scale, (255, 255, 0), 1, cv2.LINE_AA)

    if cfg.show_boxes:
        for v in vehicles:
            x1, y1, x2, y2 = (int(round(c)) for c in v.bbox)
            x1, x2 = max(0, min(x1, w - 1)), max(0, min(x2, w - 1))
            y1, y2 = max(0, min(y1, h - 1)), max(0, min(y2, h - 1))
            color = ((v.track_id * 67) % 200 + 55, (v.track_id * 121) % 200 + 55, (v.track_id * 37) % 200 + 55)
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            if cfg.show_labels:
                label = f"{v.class_name} #{v.track_id} {v.confidence:.2f}"
                (tw, th), base = cv2.getTextSize(label, _FONT, cfg.font_scale, 1)
                top = max(y1 - th - base, 0)
                cv2.rectangle(out, (x1, top), (x1 + tw, top + th + base), color, -1)
                cv2.putText(out, label, (x1, top + th), _FONT, cfg.font_scale, (0, 0, 0), 1, cv2.LINE_AA)

    if cfg.show_counts and line_counts:
        rows = [
            f"{name}: fwd {c['forward']}  rev {c['reverse']}  total {c['total']}"
            for name, c in line_counts.items()
        ]
        _draw_panel(out, rows, (8, 8), cfg)
    return out


class VideoProcessor:
    def __init__(
        self,
        tracker: VehicleTracker,
        output_dir: str | Path = DEFAULT_OUTPUT_DIR,
        counter: VehicleCounter | None = None,
        density: DensityAnalyzer | None = None,
        congestion: CongestionAnalyzer | None = None,
        annotation: AnnotationConfig | None = None,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        """Counter, density and congestion analyzers are optional; with none given the
        processor behaves as before (tracking + annotated video) plus basic analytics."""
        self.tracker = tracker
        self.output_dir = Path(output_dir)
        self.counter = counter
        self.density = density
        self.annotation = annotation or AnnotationConfig()
        self.analytics = TrafficAnalytics(counter, density, congestion, window_seconds)

    def process(self, video_path: str | Path, output_path: str | Path | None = None) -> VideoSummary:
        src = Path(video_path)
        if not src.is_file():
            raise InvalidVideoError(f"Video file not found: {src}")
        if src.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            raise InvalidVideoError(
                f"Unsupported video format '{src.suffix}'. Supported: {sorted(SUPPORTED_VIDEO_EXTENSIONS)}"
            )
        out = Path(output_path) if output_path else self.output_dir / f"{src.stem}_annotated.mp4"
        if out.resolve() == src.resolve():
            raise VideoWriterError("Output path must differ from the input path.")

        cap = cv2.VideoCapture(str(src))
        writer = None
        success = False
        try:
            if not cap.isOpened():
                raise InvalidVideoError(f"Could not open video (corrupted?): {src}")

            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            if not math.isfinite(fps) or fps <= 0:
                logger.warning("Invalid source FPS (%s); using %s", fps, DEFAULT_FPS)
                fps = DEFAULT_FPS

            self.tracker.reset()  # new video -> fresh track state and IDs
            self.analytics.reset(fps)  # also resets counter, density and congestion state
            summary = VideoSummary(str(src), str(out), 0, 0, fps=fps)
            ids: set[int] = set()
            read_index = -1
            lines = self.counter.lines if self.counter else None
            regions = self.density.regions if self.density else None
            cfg = self.annotation

            while True:
                ok, frame = cap.read()
                if not ok:  # end of video (or unreadable tail)
                    break
                read_index += 1  # source frame index, so timestamps survive skipped frames
                if frame is None or frame.size == 0:
                    summary.skipped_frames += 1
                    continue

                if writer is None:
                    summary.height, summary.width = frame.shape[:2]
                    writer = self._open_writer(out, fps, summary.width, summary.height)

                try:
                    vehicles = self.tracker.update(frame)
                except DetectorError as exc:
                    raise FrameProcessingError(f"Frame {summary.frame_count} failed: {exc}") from exc

                try:
                    stats = self.analytics.update(read_index, vehicles)
                except Exception as exc:
                    raise FrameProcessingError(f"Analytics failed on frame {read_index}: {exc}") from exc

                line_counts = None
                if self.counter and cfg.show_counts:
                    line_counts = self.counter.summary()["lines"]
                annotated = annotate_frame(frame, vehicles, cfg, lines, regions, stats, line_counts)
                if annotated.shape[:2] != (summary.height, summary.width):
                    annotated = cv2.resize(annotated, (summary.width, summary.height))
                try:
                    writer.write(annotated)
                except cv2.error as exc:
                    raise VideoWriterError(f"Failed writing frame {summary.frame_count}: {exc}") from exc

                summary.frame_count += 1
                summary.detection_count += len(vehicles)
                ids.update(v.track_id for v in vehicles)

            if summary.frame_count == 0:
                raise InvalidVideoError(f"Video contains no readable frames: {src}")

            summary.unique_track_ids = sorted(ids)
            summary.counting = self.counter.summary() if self.counter else None
            summary.analytics = self.analytics.summary().to_dict()
            success = True
            return summary
        finally:
            cap.release()
            if writer is not None:
                writer.release()
            if not success and out.exists():
                out.unlink(missing_ok=True)  # don't leave a partial output behind

    @staticmethod
    def _open_writer(out: Path, fps: float, width: int, height: int):
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise VideoWriterError(f"Cannot create output directory {out.parent}: {exc}") from exc
        writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*FOURCC), fps, (width, height))
        if not writer.isOpened():
            writer.release()
            raise VideoWriterError(f"Could not initialise VideoWriter for {out}")
        return writer


def _parse_line(text: str) -> CountingLine:
    """'name=x1,y1,x2,y2'"""
    try:
        name, coords = text.split("=", 1)
        x1, y1, x2, y2 = (float(c) for c in coords.split(","))
    except ValueError as exc:
        raise SystemExit(f"Invalid --line '{text}'. Use name=x1,y1,x2,y2") from exc
    return CountingLine(name, (x1, y1), (x2, y2))


def _parse_region(text: str) -> Region:
    """'name=x,y;x,y;x,y[;...]'"""
    try:
        name, pts = text.split("=", 1)
        poly = [tuple(float(c) for c in p.split(",")) for p in pts.split(";")]
        return Region(name, poly)
    except ValueError as exc:
        raise SystemExit(f"Invalid --region '{text}'. Use name=x,y;x,y;x,y ({exc})") from exc


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Track vehicles in a video, run traffic analytics, save an annotated copy.")
    parser.add_argument("video")
    parser.add_argument("-o", "--output")
    parser.add_argument(
        "--model",
        default=None,
        help="Model key ('vehiclenet' or 'yolo26m'); defaults to $URBANFLOW_MODEL or 'yolo26m'.",
    )
    parser.add_argument("--weights", default=None, help="Optional explicit .pt weights path")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="auto", choices=["auto", "mps", "cpu"])
    parser.add_argument("--line", action="append", default=[], help="counting line: name=x1,y1,x2,y2 (repeatable)")
    parser.add_argument("--region", action="append", default=[], help="road region: name=x,y;x,y;x,y (repeatable)")
    parser.add_argument("--window", type=float, default=DEFAULT_WINDOW_SECONDS, help="analytics window in seconds")
    parser.add_argument("--json-out", help="also write the summary JSON to this file")
    parser.add_argument("--minimal-overlay", action="store_true", help="boxes and labels only")
    args = parser.parse_args()
    try:
        detector = VehicleDetector(
            weights_path=args.weights,
            confidence=args.conf,
            image_size=args.imgsz,
            device=args.device,
            model_name=args.model,
        )
        counter = VehicleCounter([_parse_line(t) for t in args.line]) if args.line else None
        density = DensityAnalyzer([_parse_region(t) for t in args.region]) if args.region else None
        processor = VideoProcessor(
            VehicleTracker(detector),
            counter=counter,
            density=density,
            annotation=AnnotationConfig.minimal() if args.minimal_overlay else None,
            window_seconds=args.window,
        )
        result = processor.process(args.video, args.output)
    except (DetectorError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}")
    text = json.dumps(result.to_dict(), indent=2)
    if args.json_out:
        Path(args.json_out).write_text(text)
    print(text)
