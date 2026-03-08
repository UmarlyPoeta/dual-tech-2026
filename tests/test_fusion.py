"""Tests for PerceptionFusion."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from models import Detection, QrDetection
from perception.fusion import PerceptionFusion, _bbox_iou, _bbox_center


def _det(label, bbox, conf=0.9):
    return Detection(label=label, confidence=conf, bbox=bbox)


def _qr(payload, bbox):
    return QrDetection(payload=payload, confidence=1.0, bbox=bbox)


# ------------------------------------------------------------------
# Unit tests for geometry helpers
# ------------------------------------------------------------------

def test_bbox_iou_identical():
    box = (0.0, 0.0, 100.0, 100.0)
    assert _bbox_iou(box, box) == pytest.approx(1.0)


def test_bbox_iou_no_overlap():
    a = (0.0, 0.0, 50.0, 50.0)
    b = (100.0, 100.0, 200.0, 200.0)
    assert _bbox_iou(a, b) == pytest.approx(0.0)


def test_bbox_iou_partial():
    a = (0.0, 0.0, 100.0, 100.0)
    b = (50.0, 0.0, 150.0, 100.0)
    # Intersection = 50×100 = 5000; Union = 100×100 + 100×100 - 5000 = 15000
    assert _bbox_iou(a, b) == pytest.approx(5000 / 15000)


def test_bbox_center():
    cx, cy = _bbox_center((0.0, 0.0, 100.0, 80.0))
    assert cx == pytest.approx(50.0)
    assert cy == pytest.approx(40.0)


# ------------------------------------------------------------------
# Fusion tests
# ------------------------------------------------------------------


def test_fuse_box_with_overlapping_object():
    fusion = PerceptionFusion(iou_threshold=0.3)
    box = _det("box", (0, 0, 100, 100))
    obj = _det("red_object", (10, 10, 90, 90))
    hypotheses = fusion.fuse([box], [obj], [])
    assert len(hypotheses) == 1
    h = hypotheses[0]
    assert h.box_detection is not None
    assert h.object_detection is not None
    assert h.object_detection.label == "red_object"


def test_fuse_box_with_qr_inside():
    fusion = PerceptionFusion()
    box = _det("box", (0, 0, 200, 200))
    qr = _qr("CODE42", (50, 50, 150, 150))
    hypotheses = fusion.fuse([box], [], [qr])
    assert len(hypotheses) == 1
    assert hypotheses[0].qr_value == "CODE42"


def test_fuse_qr_outside_box_not_attached():
    fusion = PerceptionFusion()
    box = _det("box", (0, 0, 100, 100))
    qr = _qr("OUTSIDE", (200, 200, 300, 300))
    hypotheses = fusion.fuse([box], [], [qr])
    assert hypotheses[0].qr_value is None


def test_fuse_orphan_object_detection():
    fusion = PerceptionFusion(iou_threshold=0.5)
    obj = _det("green_object", (300, 300, 400, 400))
    hypotheses = fusion.fuse([], [obj], [])
    assert len(hypotheses) == 1
    assert hypotheses[0].object_detection.label == "green_object"
    assert hypotheses[0].box_detection is None


def test_fuse_target_class_filter():
    fusion = PerceptionFusion()
    box = _det("box", (0, 0, 100, 100))
    obj = _det("person", (5, 5, 90, 90))
    hypotheses = fusion.fuse([box], [obj], [], target_classes=["box", "red_object"])
    # person is not in target_classes, but box is — so the hypothesis remains
    # because box detection is present
    assert len(hypotheses) == 1


def test_fuse_empty_inputs():
    fusion = PerceptionFusion()
    hypotheses = fusion.fuse([], [], [])
    assert hypotheses == []
