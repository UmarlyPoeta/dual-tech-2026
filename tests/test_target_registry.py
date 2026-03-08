"""Tests for TargetRegistry."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Detection, Pose, TargetHypothesis, TargetRecord
from mission.target_registry import TargetRegistry


def _make_hyp(label: str = "box") -> TargetHypothesis:
    det = Detection(label=label, confidence=0.9, bbox=(0, 0, 100, 100))
    return TargetHypothesis(object_detection=det, confidence=0.9)


def _make_pose(lat: float = 50.0, lon: float = 20.0) -> Pose:
    return Pose(lat=lat, lon=lon)


def test_register_new_target():
    reg = TargetRegistry(revisit_radius_m=3.0, platform="uav")
    hyp = _make_hyp("red_object")
    pose = _make_pose()
    record = reg.register(hyp, pose)
    assert record is not None
    assert record.class_name == "red_object"
    assert reg.count() == 1


def test_duplicate_suppressed_same_position():
    reg = TargetRegistry(revisit_radius_m=3.0, platform="uav")
    hyp1 = _make_hyp("red_object")
    hyp2 = _make_hyp("red_object")
    pose = _make_pose(50.0, 20.0)
    reg.register(hyp1, pose)
    result = reg.register(hyp2, pose)
    assert result is None
    assert reg.count() == 1


def test_different_class_not_suppressed():
    reg = TargetRegistry(revisit_radius_m=3.0, platform="uav")
    pose = _make_pose(50.0, 20.0)
    reg.register(_make_hyp("red_object"), pose)
    result = reg.register(_make_hyp("blue_object"), pose)
    assert result is not None
    assert reg.count() == 2


def test_far_away_target_not_suppressed():
    reg = TargetRegistry(revisit_radius_m=3.0, platform="uav")
    reg.register(_make_hyp("box"), _make_pose(50.000000, 20.000000))
    # ~111 m per 0.001 deg lat → well beyond 3 m threshold
    result = reg.register(_make_hyp("box"), _make_pose(50.001000, 20.001000))
    assert result is not None
    assert reg.count() == 2


def test_mark_transported():
    reg = TargetRegistry(revisit_radius_m=3.0, platform="ugv")
    hyp = _make_hyp("blue_object")
    pose = _make_pose()
    record = reg.register(hyp, pose)
    assert record is not None
    ok = reg.mark_transported(record.target_id)
    assert ok
    all_recs = reg.all_records()
    assert all_recs[0].transported is True


def test_mark_transported_unknown_id():
    reg = TargetRegistry()
    assert reg.mark_transported("nonexistent") is False
