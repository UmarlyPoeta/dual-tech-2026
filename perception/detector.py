"""YOLO-based object detector using Ultralytics."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from models import Detection

logger = logging.getLogger(__name__)


class ObjectDetector:
    """Wraps an Ultralytics YOLO model for inference.

    Parameters
    ----------
    model_path:
        Path to the ``*.pt`` YOLO weights file.
    class_map:
        Mapping of integer class ID → label string.
    confidence_threshold:
        Detections below this score are discarded.
    device:
        Inference device, e.g. ``"cpu"`` or ``"cuda:0"``.
    """

    def __init__(
        self,
        model_path: str | Path,
        class_map: Dict[int, str],
        confidence_threshold: float = 0.5,
        device: str = "cpu",
    ) -> None:
        self._model_path = Path(model_path)
        self._class_map = class_map
        self._confidence_threshold = confidence_threshold
        self._device = device
        self._model = None
        self._frame_id = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load model weights into memory.  Must be called before :meth:`detect`."""
        if not self._model_path.exists():
            logger.warning("YOLO model not found at %s — detector disabled.", self._model_path)
            self._model = None
            return
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as exc:
            logger.warning("Ultralytics not available (%s) — detector disabled.", exc)
            self._model = None
            return
        self._model = YOLO(str(self._model_path))
        logger.info("YOLO model loaded from %s (device=%s)", self._model_path, self._device)

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Run inference on *frame* and return a list of :class:`Detection` objects."""
        if self._model is None:
            return []

        self._frame_id += 1
        results = self._model(frame, device=self._device, verbose=False)
        detections: List[Detection] = []

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                conf = float(box.conf[0])
                if conf < self._confidence_threshold:
                    continue
                cls_id = int(box.cls[0])
                label = self._class_map.get(cls_id, str(cls_id))
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(
                    Detection(
                        label=label,
                        confidence=conf,
                        bbox=(x1, y1, x2, y2),
                        frame_id=self._frame_id,
                    )
                )

        return detections

    def set_confidence_threshold(self, threshold: float) -> None:
        self._confidence_threshold = threshold
