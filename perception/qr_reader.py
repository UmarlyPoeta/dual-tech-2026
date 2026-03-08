"""QR code detection and decoding using OpenCV + pyzbar."""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np

from models import QrDetection

logger = logging.getLogger(__name__)


class QrReader:
    """Detects and decodes QR codes in image frames.

    Two backends are tried in order:
    1. ``pyzbar`` — fast and reliable for clear images.
    2. ``cv2.QRCodeDetector`` — OpenCV built-in fallback.
    """

    def __init__(self) -> None:
        self._use_pyzbar = self._check_pyzbar()

    @staticmethod
    def _check_pyzbar() -> bool:
        try:
            import pyzbar.pyzbar  # type: ignore  # noqa: F401
            return True
        except ImportError:
            logger.warning("pyzbar not available; falling back to cv2.QRCodeDetector")
            return False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def decode(self, frame: np.ndarray) -> List[QrDetection]:
        """Decode all QR codes visible in *frame*.

        Parameters
        ----------
        frame:
            BGR image as a NumPy array.

        Returns
        -------
        list of :class:`~models.QrDetection`
        """
        if self._use_pyzbar:
            return self._decode_pyzbar(frame)
        return self._decode_cv2(frame)

    def decode_crop(self, frame: np.ndarray, bbox: Tuple[float, float, float, float]) -> List[QrDetection]:
        """Decode QR codes inside a bounding box crop of *frame*.

        Useful for reading QR codes printed inside detected boxes.
        """
        x1, y1, x2, y2 = (int(v) for v in bbox)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return []
        return self.decode(crop)

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------

    def _decode_pyzbar(self, frame: np.ndarray) -> List[QrDetection]:
        from pyzbar import pyzbar  # type: ignore

        detections: List[QrDetection] = []
        decoded = pyzbar.decode(frame)
        for obj in decoded:
            if obj.type != "QRCODE":
                continue
            payload = obj.data.decode("utf-8", errors="replace")
            rect = obj.rect
            bbox = (
                float(rect.left),
                float(rect.top),
                float(rect.left + rect.width),
                float(rect.top + rect.height),
            )
            detections.append(QrDetection(payload=payload, confidence=1.0, bbox=bbox))
        return detections

    def _decode_cv2(self, frame: np.ndarray) -> List[QrDetection]:
        import cv2  # type: ignore

        detector = cv2.QRCodeDetector()
        retval, decoded_info, points, _ = detector.detectAndDecodeMulti(frame)
        detections: List[QrDetection] = []
        if retval and decoded_info:
            for i, payload in enumerate(decoded_info):
                if not payload:
                    continue
                if points is not None and i < len(points):
                    pts = points[i]
                    xs = pts[:, 0]
                    ys = pts[:, 1]
                    bbox = (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
                else:
                    bbox = (0.0, 0.0, 0.0, 0.0)
                detections.append(QrDetection(payload=payload, confidence=0.9, bbox=bbox))
        return detections
