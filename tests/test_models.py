"""Tests for shared data models."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Detection, Pose, QrDetection, TargetHypothesis, TargetRecord


def test_detection_defaults():
    d = Detection(label="box", confidence=0.9, bbox=(0, 0, 100, 100))
    assert d.label == "box"
    assert d.confidence == 0.9
    assert d.bbox == (0, 0, 100, 100)
    assert d.id  # auto-generated UUID
    assert d.timestamp > 0


def test_qr_detection():
    qr = QrDetection(payload="HELLO", confidence=1.0, bbox=(10, 10, 50, 50))
    assert qr.payload == "HELLO"


def test_pose_optional_fields():
    p = Pose(lat=50.0, lon=20.0)
    assert p.alt is None
    assert p.yaw_deg is None


def test_target_hypothesis_class_name_from_object():
    obj_det = Detection(label="red_object", confidence=0.8, bbox=(0, 0, 50, 50))
    hyp = TargetHypothesis(object_detection=obj_det)
    assert hyp.class_name == "red_object"


def test_target_hypothesis_class_name_from_box_fallback():
    box_det = Detection(label="box", confidence=0.7, bbox=(0, 0, 100, 100))
    hyp = TargetHypothesis(box_detection=box_det)
    assert hyp.class_name == "box"


def test_target_hypothesis_qr_value():
    qr = QrDetection(payload="QR123", confidence=1.0, bbox=(5, 5, 45, 45))
    hyp = TargetHypothesis(qr_detection=qr)
    assert hyp.qr_value == "QR123"


def test_target_hypothesis_no_detections():
    hyp = TargetHypothesis()
    assert hyp.class_name is None
    assert hyp.qr_value is None


def test_target_record_defaults():
    rec = TargetRecord(
        target_id="abc-123",
        source_platform="uav",
        class_name="blue_object",
        qr_value="CODE42",
        lat=50.123,
        lon=19.456,
    )
    assert not rec.transported
    assert rec.alt is None
    assert rec.timestamp > 0
