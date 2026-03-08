"""Perception fusion — merges raw detections into :class:`~models.TargetHypothesis` objects."""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np

from models import Detection, QrDetection, TargetHypothesis

logger = logging.getLogger(__name__)


def _bbox_center(bbox: Tuple[float, float, float, float]) -> Tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _bbox_iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    """Intersection-over-Union of two axis-aligned bounding boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    intersection = iw * ih

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection

    if union <= 0.0:
        return 0.0
    return intersection / union


class PerceptionFusion:
    """Merges lists of :class:`~models.Detection` and :class:`~models.QrDetection` objects
    into :class:`~models.TargetHypothesis` instances.

    Strategy
    --------
    * Box detections and object detections are matched by IoU overlap.
    * QR detections are associated by checking whether their bbox centre lies
      inside the nearest box bbox.
    * Each unique spatial cluster yields one :class:`~models.TargetHypothesis`.

    Parameters
    ----------
    iou_threshold:
        Minimum IoU to consider two bboxes as the same physical object.
    """

    def __init__(self, iou_threshold: float = 0.3) -> None:
        self._iou_threshold = iou_threshold

    def fuse(
        self,
        box_detections: List[Detection],
        object_detections: List[Detection],
        qr_detections: List[QrDetection],
        target_classes: Optional[List[str]] = None,
    ) -> List[TargetHypothesis]:
        """Combine raw perception results into fused hypotheses.

        Parameters
        ----------
        box_detections:
            Detections with label ``"box"`` (or similar container).
        object_detections:
            Detections of objects *inside* boxes (non-box classes).
        qr_detections:
            Decoded QR codes.
        target_classes:
            If given, only hypotheses whose class is in this list are returned.
        """
        hypotheses: List[TargetHypothesis] = []

        # Start with boxes as anchors
        used_objects: set[int] = set()
        used_qrs: set[int] = set()

        for box_det in box_detections:
            hyp = TargetHypothesis(box_detection=box_det, confidence=box_det.confidence)

            # Match an object detection by IoU
            best_obj_idx: Optional[int] = None
            best_iou = self._iou_threshold
            for i, obj in enumerate(object_detections):
                if i in used_objects:
                    continue
                iou = _bbox_iou(box_det.bbox, obj.bbox)
                if iou >= best_iou:
                    best_iou = iou
                    best_obj_idx = i

            if best_obj_idx is not None:
                hyp.object_detection = object_detections[best_obj_idx]
                used_objects.add(best_obj_idx)
                hyp.confidence = max(hyp.confidence, hyp.object_detection.confidence)

            # Match a QR detection whose centre is inside the box bbox
            bx1, by1, bx2, by2 = box_det.bbox
            for j, qr in enumerate(qr_detections):
                if j in used_qrs:
                    continue
                cx, cy = _bbox_center(qr.bbox)
                if bx1 <= cx <= bx2 and by1 <= cy <= by2:
                    hyp.qr_detection = qr
                    used_qrs.add(j)
                    break

            hypotheses.append(hyp)

        # Add orphan object detections (no matching box)
        for i, obj in enumerate(object_detections):
            if i in used_objects:
                continue
            hyp = TargetHypothesis(object_detection=obj, confidence=obj.confidence)
            # Try to attach an orphan QR
            ox1, oy1, ox2, oy2 = obj.bbox
            for j, qr in enumerate(qr_detections):
                if j in used_qrs:
                    continue
                cx, cy = _bbox_center(qr.bbox)
                if ox1 <= cx <= ox2 and oy1 <= cy <= oy2:
                    hyp.qr_detection = qr
                    used_qrs.add(j)
                    break
            hypotheses.append(hyp)

        # Filter by target classes if requested.
        # Keep a hypothesis if its effective class_name is a target, OR if the
        # hypothesis was anchored on a box and "box" itself is a target class
        # (so a box containing an unclassified object still appears in results).
        if target_classes is not None:
            hypotheses = [
                h for h in hypotheses
                if h.class_name in target_classes
                or (h.box_detection is not None and "box" in target_classes)
            ]

        return hypotheses
