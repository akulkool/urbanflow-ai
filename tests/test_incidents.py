import json

import pytest

from backend.schemas.traffic import (
    CongestionLevel,
    DensityLevel,
    FrameStats,
    RegionCongestion,
    RegionDensity,
)
from backend.services.incident_manager import (
    CandidateDetectionConfig,
    IncidentCategory,
    IncidentError,
    IncidentIntelligenceService,
    IncidentNotFoundError,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    InvalidIncidentTransitionError,
    classify_incident_severity,
)
from backend.services.road_network import (
    InvalidCoordinatesError,
    RoadSegmentNotFoundError,
    create_bengaluru_demo_network,
)
from backend.services.tracker import TrackedVehicle


def make_service() -> IncidentIntelligenceService:
    net = create_bengaluru_demo_network()
    cfg = CandidateDetectionConfig(
        stationary_px_threshold=5.0,
        stationary_min_duration_s=3.0,
        stationary_min_frames=3,
        density_spike_min_delta=5,
        congestion_jump_min_ranks=2,
        dedup_cooldown_s=30.0,
    )
    return IncidentIntelligenceService(road_network=net, candidate_config=cfg)


def test_create_and_get_incident():
    svc = make_service()
    inc = svc.create_incident(
        category="accident",
        title="Collision near Silk Board flyover",
        description="Two-wheeler and car involved",
        affected_roads=["seg_kora_silk"],
        coordinates={"lat": 12.9176, "lon": 77.6233},
    )
    assert inc.id.startswith("inc_")
    assert inc.category == IncidentCategory.ACCIDENT.value
    assert inc.status == IncidentStatus.REPORTED
    assert inc.source == IncidentSource.MANUAL_REPORT
    assert inc.severity == IncidentSeverity.HIGH
    assert "accident" in inc.severity_reason
    assert inc.region == "orr_south"
    assert inc.is_active_for_routing is True

    fetched = svc.get_incident(inc.id)
    assert fetched.to_dict() == inc.to_dict()
    assert json.loads(json.dumps(inc.to_dict()))["id"] == inc.id


def test_all_supported_incident_categories():
    svc = make_service()
    categories = [
        "accident",
        "vehicle_breakdown",
        "road_obstruction",
        "road_closure",
        "waterlogging",
        "construction_work",
        "unusual_congestion",
        "stationary_vehicle",
    ]
    for idx, cat in enumerate(categories):
        inc = svc.create_incident(
            category=cat,
            title=f"Event {idx}",
            allow_duplicate=True,
        )
        assert inc.category == cat


def test_severity_classification_rules():
    sev1, reason1 = classify_incident_severity("stationary_vehicle", {"stationary_duration_s": 5.0})
    assert sev1 == IncidentSeverity.LOW and "Base severity" in reason1

    sev2, reason2 = classify_incident_severity("stationary_vehicle", {"stationary_duration_s": 35.0})
    assert sev2 == IncidentSeverity.HIGH and "stationary duration" in reason2

    sev3, reason3 = classify_incident_severity("vehicle_breakdown", {"vehicle_class": "bus"})
    assert sev3 == IncidentSeverity.HIGH and "heavy vehicle" in reason3

    sev4, reason4 = classify_incident_severity("waterlogging", {"road_blocked": True})
    assert sev4 == IncidentSeverity.CRITICAL and "blockage" in reason4


def test_duplicate_incident_prevention():
    svc = make_service()
    first = svc.create_incident(
        category="waterlogging",
        title="Bellandur underpass waterlogging",
        affected_roads=["seg_silk_bell"],
        evidence={"density_delta": 4},
    )
    second = svc.create_incident(
        category="waterlogging",
        title="Duplicate report of Bellandur waterlogging",
        affected_roads=["seg_silk_bell"],
        evidence={"density_delta": 18},
    )
    assert first.id == second.id
    # Evidence updated and severity escalated to CRITICAL from density_delta=18
    assert second.severity == IncidentSeverity.CRITICAL
    assert len(svc.list_incidents()) == 1


def test_incident_lifecycle_confirm_dismiss_resolve_reopen():
    svc = make_service()
    cand = svc.create_incident(
        category="road_obstruction",
        title="Debris candidate on Old Madras Road",
        affected_roads=["seg_indira_krp"],
        source="auto_cv",
    )
    assert cand.status == IncidentStatus.CANDIDATE

    confirmed = svc.confirm_incident(cand.id, notes="Verified by CCTV operator")
    assert confirmed.status == IncidentStatus.CONFIRMED
    assert confirmed.confirmed_at is not None

    resolved = svc.resolve_incident(cand.id, resolution_notes="Cleared by marshals")
    assert resolved.status == IncidentStatus.RESOLVED
    assert resolved.resolved_at is not None
    assert resolved.is_active_for_routing is False

    # Cannot dismiss a resolved incident
    with pytest.raises(InvalidIncidentTransitionError):
        svc.dismiss_incident(cand.id)

    reopened = svc.reopen_incident(cand.id, as_confirmed=True, notes="Obstruction recurred")
    assert reopened.status == IncidentStatus.CONFIRMED
    assert reopened.resolved_at is None
    assert reopened.is_active_for_routing is True


def test_false_positive_dismissal():
    svc = make_service()
    cand = svc.create_incident(
        category="stationary_vehicle",
        title="Parked auto-rickshaw candidate",
        source="auto_cv",
    )
    dismissed = svc.dismiss_incident(cand.id, reason="Authorized roadside halt")
    assert dismissed.status == IncidentStatus.DISMISSED
    assert dismissed.dismissed_at is not None
    assert dismissed.is_active_for_routing is False

    # Cannot confirm or resolve a dismissed incident without reopening
    with pytest.raises(InvalidIncidentTransitionError):
        svc.confirm_incident(cand.id)
    with pytest.raises(InvalidIncidentTransitionError):
        svc.resolve_incident(cand.id)


def test_update_incident_fields():
    svc = make_service()
    inc = svc.create_incident(
        category="construction_work",
        title="Metro pillar work",
        affected_roads=["seg_krp_white"],
    )
    updated = svc.update_incident(
        inc.id,
        title="Metro Phase 2 barricade expansion",
        severity="HIGH",
        severity_reason="Two lanes closed during peak hour",
        affected_roads=["seg_krp_white", "seg_mara_white"],
        coordinates={"lat": 12.98, "lon": 77.72},
    )
    assert updated.title == "Metro Phase 2 barricade expansion"
    assert updated.severity == IncidentSeverity.HIGH
    assert updated.affected_roads == ["seg_krp_white", "seg_mara_white"]
    assert updated.coordinates.lat == pytest.approx(12.98)


def test_stationary_vehicle_candidate_detection_does_not_claim_accident():
    svc = make_service()
    auto = TrackedVehicle(track_id=42, class_id=10, class_name="auto_rickshaw", confidence=0.91, bbox=(100, 100, 140, 140))
    moving_car = TrackedVehicle(track_id=7, class_id=2, class_name="car", confidence=0.95, bbox=(10, 10, 50, 50))

    emitted = []
    for f_idx, t_s in enumerate([0.0, 1.0, 2.0, 3.5]):
        car_now = TrackedVehicle(7, 2, "car", 0.95, (10 + 30 * f_idx, 10, 50 + 30 * f_idx, 50))
        d = RegionDensity("orr_east", 2, {"auto_rickshaw": 1, "car": 1}, DensityLevel.LOW, 0.05, None)
        st = FrameStats(frame_index=f_idx, time_s=t_s, vehicle_count=2, track_ids=[7, 42], densities=[d])
        emitted.extend(svc.evaluate_frame_candidates(st, [auto, car_now]))

    assert len(emitted) == 1
    cand = emitted[0]
    assert cand.category == IncidentCategory.STATIONARY_VEHICLE.value
    assert cand.category != IncidentCategory.ACCIDENT.value
    assert cand.status == IncidentStatus.CANDIDATE
    assert cand.source == IncidentSource.AUTO_CV
    assert "not confirmed as an accident" in cand.description
    assert cand.evidence["vehicle_class"] == "auto_rickshaw"
    assert cand.evidence["track_id"] == 42


def test_sudden_density_and_congestion_candidate_detection():
    svc = make_service()
    f0 = FrameStats(
        0,
        0.0,
        2,
        [1, 2],
        densities=[RegionDensity("orr_south", 2, {"car": 2}, DensityLevel.LOW, 0.05, None)],
        congestion=[RegionCongestion("orr_south", CongestionLevel.LOW, 2.0, 0.05, None, {}, "est", True)],
    )
    f1 = FrameStats(
        10,
        1.0,
        12,
        list(range(12)),
        densities=[RegionDensity("orr_south", 12, {"car": 12}, DensityLevel.HIGH, 0.45, None)],
        congestion=[RegionCongestion("orr_south", CongestionLevel.SEVERE, 12.0, 0.45, None, {}, "est", True)],
    )
    assert svc.evaluate_frame_candidates(f0, []) == []
    cands = svc.evaluate_frame_candidates(f1, [])
    signals = {c.evidence["signal"] for c in cands}
    assert "sudden_density_increase" in signals
    assert "sudden_congestion_increase" in signals
    assert all(c.status == IncidentStatus.CANDIDATE for c in cands)


def test_flow_anomaly_candidate_detection():
    svc = make_service()
    cand = svc.evaluate_flow_anomaly(
        region="orr_east",
        previous_window_crossings=20,
        current_window_crossings=2,
        current_congestion_level="SEVERE",
    )
    assert cand is not None
    assert cand.category == IncidentCategory.ROAD_OBSTRUCTION.value
    assert cand.status == IncidentStatus.CANDIDATE
    assert "seg_indira_mara" in cand.affected_roads


def test_invalid_incident_inputs_and_ids():
    svc = make_service()
    with pytest.raises(IncidentNotFoundError):
        svc.get_incident("inc_nonexistent")
    with pytest.raises(IncidentError):
        svc.create_incident(category="alien_invasion", title="Invalid category")
    with pytest.raises(IncidentError):
        svc.create_incident(category="accident", title="   ")
    with pytest.raises(RoadSegmentNotFoundError):
        svc.create_incident(category="accident", title="Bad road", affected_roads=["seg_unknown"])
    with pytest.raises(InvalidCoordinatesError):
        svc.create_incident(category="accident", title="Bad coords", coordinates={"lat": 999.0, "lon": 77.0})
