import cv2
import numpy as np
import pytest

from backend.services import video_processor as vp
from backend.services.detector import InvalidImageError
from backend.services.tracker import TrackedVehicle, TrackingError
from backend.services.video_processor import (
    FrameProcessingError,
    InvalidVideoError,
    VideoProcessor,
    VideoWriterError,
)


def make_video(path, n=5, size=(64, 48), fps=10):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    assert w.isOpened()
    for i in range(n):
        w.write(np.full((size[1], size[0], 3), 20 * i, np.uint8))
    w.release()
    return path


def vehicle(tid, cls="car"):
    return TrackedVehicle(tid, 2, cls, 0.9, (5.0, 5.0, 30.0, 30.0))


class FakeTracker:
    def __init__(self, per_frame=None, fail_on=None):
        self.per_frame = per_frame or []
        self.fail_on = fail_on
        self.frames = []
        self.resets = 0
        self.events = []

    def reset(self):
        self.resets += 1
        self.events.append("reset")

    def update(self, frame):
        i = len(self.frames)
        self.frames.append(frame.shape)
        if self.fail_on == i:
            raise TrackingError("boom")
        return self.per_frame[i] if i < len(self.per_frame) else []


def test_successful_processing_and_summary(tmp_path):
    src = make_video(tmp_path / "in.mp4", n=5)
    tracker = FakeTracker([[vehicle(1)], [vehicle(1), vehicle(2, "bus")], [], [vehicle(2)], [vehicle(3)]])
    out = tmp_path / "out" / "o.mp4"
    s = VideoProcessor(tracker).process(src, out)
    assert s.frame_count == 5 and len(tracker.frames) == 5
    assert s.detection_count == 5
    assert s.unique_track_ids == [1, 2, 3] and s.unique_vehicle_count == 3
    assert (s.width, s.height) == (64, 48) and s.fps == pytest.approx(10, abs=0.5)
    assert s.output_path == str(out) and s.to_dict()["resolution"] == [64, 48]


def test_annotated_output_preserves_size_fps_and_draws(tmp_path):
    src = make_video(tmp_path / "in.mp4", n=4)
    out = tmp_path / "o.mp4"
    VideoProcessor(FakeTracker([[vehicle(1)]] * 4)).process(src, out)
    cap = cv2.VideoCapture(str(out))
    assert cap.isOpened()
    assert (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))) == (64, 48)
    assert cap.get(cv2.CAP_PROP_FPS) == pytest.approx(10, abs=0.5)
    n = 0
    while cap.read()[0]:
        n += 1
    cap.release()
    assert n == 4


def test_annotate_frame_draws_without_mutating_input():
    frame = np.zeros((100, 100, 3), np.uint8)
    out = vp.annotate_frame(frame, [vehicle(7)])
    assert frame.sum() == 0 and out.sum() > 0
    assert vp.annotate_frame(frame, []).sum() == 0


def test_default_output_path(tmp_path):
    src = make_video(tmp_path / "clip.mp4", n=2)
    s = VideoProcessor(FakeTracker(), output_dir=tmp_path / "res").process(src)
    assert s.output_path == str(tmp_path / "res" / "clip_annotated.mp4")
    assert (tmp_path / "res" / "clip_annotated.mp4").is_file()


def test_empty_video_raises_and_cleans_output(tmp_path):
    src = tmp_path / "empty.mp4"
    cv2.VideoWriter(str(src), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48)).release()
    out = tmp_path / "o.mp4"
    with pytest.raises(InvalidVideoError):
        VideoProcessor(FakeTracker()).process(src, out)
    assert not out.exists()


def test_invalid_paths_and_formats(tmp_path):
    p = VideoProcessor(FakeTracker())
    with pytest.raises(InvalidVideoError, match="not found"):
        p.process(tmp_path / "nope.mp4")
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(InvalidVideoError, match="Unsupported"):
        p.process(txt)
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video at all")
    with pytest.raises(InvalidVideoError):
        p.process(bad, tmp_path / "o.mp4")


def test_output_same_as_input_rejected(tmp_path):
    src = make_video(tmp_path / "in.mp4", n=2)
    with pytest.raises(VideoWriterError):
        VideoProcessor(FakeTracker()).process(src, src)
    assert src.exists()


def test_frame_failure_wrapped_and_output_removed(tmp_path):
    src = make_video(tmp_path / "in.mp4", n=4)
    out = tmp_path / "o.mp4"
    with pytest.raises(FrameProcessingError, match="Frame 2"):
        VideoProcessor(FakeTracker(fail_on=2)).process(src, out)
    assert not out.exists()


def test_invalid_frame_error_also_wrapped(tmp_path):
    class T(FakeTracker):
        def update(self, frame):
            raise InvalidImageError("bad")

    with pytest.raises(FrameProcessingError):
        VideoProcessor(T()).process(make_video(tmp_path / "in.mp4", n=2), tmp_path / "o.mp4")


class SpyCapture:
    def __init__(self, frames, fail_after=None):
        self.frames, self.released, self.i = frames, False, 0
        self.fail_after = fail_after

    def isOpened(self):
        return True

    def get(self, prop):
        return 10.0

    def read(self):
        if self.fail_after is not None and self.i >= self.fail_after:
            raise RuntimeError("decode crash")
        if self.i >= len(self.frames):
            return False, None
        f = self.frames[self.i]
        self.i += 1
        return True, f

    def release(self):
        self.released = True


class SpyWriter:
    def __init__(self, opened=True, fail_write=False):
        self.opened, self.fail_write = opened, fail_write
        self.released, self.written = False, 0

    def isOpened(self):
        return self.opened

    def write(self, f):
        if self.fail_write:
            raise cv2.error("write failed")
        self.written += 1

    def release(self):
        self.released = True


def patch_cv(monkeypatch, tmp_path, cap, writer):
    src = tmp_path / "x.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(vp.cv2, "VideoCapture", lambda p: cap)
    monkeypatch.setattr(vp.cv2, "VideoWriter", lambda *a, **k: writer)
    return src


FR = np.zeros((48, 64, 3), np.uint8)


def test_resources_released_on_success(monkeypatch, tmp_path):
    cap, w = SpyCapture([FR, FR]), SpyWriter()
    src = patch_cv(monkeypatch, tmp_path, cap, w)
    VideoProcessor(FakeTracker()).process(src, tmp_path / "o.mp4")
    assert cap.released and w.released and w.written == 2


def test_resources_released_on_tracker_error(monkeypatch, tmp_path):
    cap, w = SpyCapture([FR, FR]), SpyWriter()
    src = patch_cv(monkeypatch, tmp_path, cap, w)
    with pytest.raises(FrameProcessingError):
        VideoProcessor(FakeTracker(fail_on=1)).process(src, tmp_path / "o.mp4")
    assert cap.released and w.released


def test_resources_released_on_unexpected_error(monkeypatch, tmp_path):
    cap, w = SpyCapture([FR, FR], fail_after=1), SpyWriter()
    src = patch_cv(monkeypatch, tmp_path, cap, w)
    with pytest.raises(RuntimeError):
        VideoProcessor(FakeTracker()).process(src, tmp_path / "o.mp4")
    assert cap.released and w.released


def test_writer_init_failure_releases_capture(monkeypatch, tmp_path):
    cap, w = SpyCapture([FR]), SpyWriter(opened=False)
    src = patch_cv(monkeypatch, tmp_path, cap, w)
    with pytest.raises(VideoWriterError):
        VideoProcessor(FakeTracker()).process(src, tmp_path / "o.mp4")
    assert cap.released and w.released


def test_writer_write_failure(monkeypatch, tmp_path):
    cap, w = SpyCapture([FR]), SpyWriter(fail_write=True)
    src = patch_cv(monkeypatch, tmp_path, cap, w)
    with pytest.raises(VideoWriterError):
        VideoProcessor(FakeTracker()).process(src, tmp_path / "o.mp4")
    assert cap.released and w.released


def test_empty_frames_skipped(monkeypatch, tmp_path):
    cap, w = SpyCapture([FR, None, np.zeros((0, 0, 3), np.uint8), FR]), SpyWriter()
    src = patch_cv(monkeypatch, tmp_path, cap, w)
    s = VideoProcessor(FakeTracker()).process(src, tmp_path / "o.mp4")
    assert s.frame_count == 2 and s.skipped_frames == 2


def test_tracker_reset_between_videos(tmp_path):
    a = make_video(tmp_path / "a.mp4", n=2)
    b = make_video(tmp_path / "b.mp4", n=3)
    tracker = FakeTracker()
    proc = VideoProcessor(tracker, output_dir=tmp_path / "o")
    proc.process(a)
    assert tracker.resets == 1 and len(tracker.frames) == 2
    proc.process(b)
    assert tracker.resets == 2 and len(tracker.frames) == 5


def test_reset_not_called_for_invalid_video(tmp_path):
    tracker = FakeTracker()
    with pytest.raises(InvalidVideoError):
        VideoProcessor(tracker).process(tmp_path / "missing.mp4")
    assert tracker.resets == 0
