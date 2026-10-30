import json

import pytest

from backend.services.tracker import TrackedVehicle
from backend.services.vehicle_counter import (
    CountingLine,
    LineConfigError,
    VehicleCounter,
)

# Horizontal line y=100 from x=0..200, running A->B along +x.
# signed distance = (y-100): y>100 (below) is positive, y<100 (above) is negative.
LINE = CountingLine("main", (0, 100), (200, 100))


def veh(tid, y, x=100, cls="car", cid=2):
    """Vehicle whose bottom-centre is (x, y)."""
    return TrackedVehicle(tid, cid, cls, 0.9, (x - 10, y - 30, x + 10, y))


def run(counter, frames):
    return [counter.update(f) for f in frames]


def test_forward_crossing():
    c = VehicleCounter(LINE)
    ev = run(c, [[veh(1, 80)], [veh(1, 90)], [veh(1, 140)]])
    assert [len(e) for e in ev] == [0, 0, 1]
    assert ev[2][0].direction == "forward" and ev[2][0].track_id == 1
    s = c.summary()
    assert s["total"] == 1 and s["by_class"] == {"car": 1}


def test_directions_are_opposite_and_correct():
    f = VehicleCounter(LINE)
    r = VehicleCounter(LINE)
    f.update([veh(1, 130)])
    ef = f.update([veh(1, 80)])  # positive -> negative
    r.update([veh(1, 80)])
    er = r.update([veh(1, 130)])  # negative -> positive
    assert ef[0].direction == "reverse" and er[0].direction == "forward"
    assert f.summary()["lines"]["main"]["reverse"] == 1
    assert r.summary()["lines"]["main"]["forward"] == 1


def test_multiple_vehicles_and_classes():
    c = VehicleCounter(LINE)
    c.update([veh(1, 140), veh(2, 60, cls="bus", cid=5), veh(3, 150, cls="motorcycle", cid=3)])
    c.update([veh(1, 70), veh(2, 140, cls="bus", cid=5), veh(3, 160, cls="motorcycle", cid=3)])
    s = c.summary()
    assert s["total"] == 2
    assert s["by_class"] == {"bus": 1, "car": 1}
    assert s["lines"]["main"]["forward"] == 1 and s["lines"]["main"]["reverse"] == 1


def test_future_class_names_counted_as_given():
    c = VehicleCounter(LINE)
    c.update([veh(1, 140, cls="auto_rickshaw", cid=10)])
    c.update([veh(1, 60, cls="auto_rickshaw", cid=10)])
    assert c.summary()["by_class"] == {"auto_rickshaw": 1}


def test_duplicate_crossing_prevented():
    c = VehicleCounter(LINE)
    run(c, [[veh(1, 140)], [veh(1, 60)], [veh(1, 140)], [veh(1, 60)], [veh(1, 140)], [veh(1, 60)]])
    s = c.summary()["lines"]["main"]
    assert s["forward"] == 1 and s["reverse"] == 1 and s["total"] == 2  # once per direction


def test_jitter_near_line_not_counted():
    c = VehicleCounter(LINE, tolerance=5)
    # vehicle approaches then jitters +/-3 px around the line
    run(c, [[veh(1, 140)], [veh(1, 103)], [veh(1, 97)], [veh(1, 102)], [veh(1, 98)], [veh(1, 104)]])
    assert c.summary()["total"] == 0


def test_jitter_then_real_crossing_counts_once():
    c = VehicleCounter(LINE, tolerance=5)
    run(c, [[veh(1, 140)], [veh(1, 101)], [veh(1, 99)], [veh(1, 102)], [veh(1, 70)], [veh(1, 98)]])
    assert c.summary()["total"] == 1


def test_appearing_near_or_beyond_line_not_counted():
    c = VehicleCounter(LINE)
    run(c, [[veh(1, 102)], [veh(1, 101)], [veh(2, 60)], [veh(2, 50)]])
    assert c.summary()["total"] == 0


def test_crossing_outside_segment_extent_not_counted():
    c = VehicleCounter(LINE)
    run(c, [[veh(1, 140, x=400)], [veh(1, 60, x=400)]])  # past end of the segment
    assert c.summary()["total"] == 0


def test_disappear_and_reappear_not_double_counted():
    c = VehicleCounter(LINE, max_missing_frames=3)
    run(c, [[veh(1, 140)], [veh(1, 60)]])  # counted forward
    run(c, [[]] * 10)  # gone long enough to prune state
    assert c.active_tracks == 0
    run(c, [[veh(1, 140)], [veh(1, 60)]])  # same ID re-enters, same direction
    assert c.summary()["total"] == 1


def test_disappear_mid_approach_then_cross():
    c = VehicleCounter(LINE, max_missing_frames=30)
    run(c, [[veh(1, 140)], [], [], [veh(1, 60)]])
    assert c.summary()["total"] == 1


def test_lost_track_state_pruned_and_pending_crossing_not_invented():
    c = VehicleCounter(LINE, max_missing_frames=2)
    run(c, [[veh(1, 140)], [], [], [], [], [veh(1, 60)]])
    assert c.summary()["total"] == 0  # history forgotten; no guessed crossing


def test_reset_between_videos():
    c = VehicleCounter(LINE)
    run(c, [[veh(1, 140)], [veh(1, 60)]])
    assert c.summary()["total"] == 1
    c.reset()
    s = c.summary()
    assert s["total"] == 0 and s["frames_processed"] == 0 and c.active_tracks == 0
    run(c, [[veh(1, 140)], [veh(1, 60)]])  # IDs restart at 1 in a new video
    assert c.summary()["total"] == 1


def test_empty_frames():
    c = VehicleCounter(LINE)
    assert c.update([]) == []
    assert c.summary() == {
        "frames_processed": 1,
        "total": 0,
        "by_class": {},
        "lines": c.summary()["lines"],
    }


def test_multiple_lines_independent():
    l2 = CountingLine("second", (0, 50), (200, 50))
    c = VehicleCounter([LINE, l2])
    run(c, [[veh(1, 140)], [veh(1, 80)], [veh(1, 20)]])
    s = c.summary()
    assert s["lines"]["main"]["total"] == 1 and s["lines"]["second"]["total"] == 1
    assert s["total"] == 2


def test_summary_json_serialisable():
    c = VehicleCounter(LINE)
    run(c, [[veh(1, 140)], [veh(1, 60)]])
    assert json.loads(json.dumps(c.summary()))["total"] == 1


def test_deterministic():
    frames = [[veh(1, 140), veh(2, 60)], [veh(1, 60), veh(2, 140)]]
    a, b = VehicleCounter(LINE), VehicleCounter(LINE)
    run(a, frames), run(b, frames)
    assert a.summary() == b.summary()


@pytest.mark.parametrize(
    "args",
    [
        ("l", (0, 0), (0, 0)),
        ("l", (0, 0), (1,)),
        ("l", (0, 0), (float("nan"), 1)),
        ("l", (0, 0), ("a", 1)),
        ("l", None, (1, 1)),
        ("", (0, 0), (1, 1)),
    ],
)
def test_invalid_line_config(args):
    with pytest.raises(LineConfigError):
        CountingLine(*args)


def test_invalid_counter_config():
    with pytest.raises(LineConfigError):
        VehicleCounter([])
    with pytest.raises(LineConfigError):
        VehicleCounter("not a line")
    with pytest.raises(LineConfigError):
        VehicleCounter(LINE, tolerance=-1)
    with pytest.raises(LineConfigError):
        VehicleCounter(LINE, max_missing_frames=-1)
    with pytest.raises(LineConfigError):
        VehicleCounter([LINE, LINE])
