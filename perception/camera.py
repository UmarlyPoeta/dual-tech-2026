"""Camera abstraction — wraps OpenCV VideoCapture."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class Camera:
    """Thin wrapper around an OpenCV video source.

    Parameters
    ----------
    source:
        Camera index (int) or video file / RTSP URL (str).
    width, height:
        Desired capture resolution.  The driver may silently ignore these.
    """

    def __init__(self, source: int | str = 0, width: int = 640, height: int = 480) -> None:
        self._source = source
        self._width = width
        self._height = height
        self._cap = None
        self._frame_id = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the capture device.  Raises RuntimeError on failure."""
        import cv2  # type: ignore

        self._cap = cv2.VideoCapture(self._source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera source: {self._source}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        logger.info("Camera opened (source=%s, %dx%d)", self._source, self._width, self._height)

    def close(self) -> None:
        """Release the capture device."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("Camera closed.")

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Frame acquisition
    # ------------------------------------------------------------------

    def get_frame(self) -> Optional[np.ndarray]:
        """Return the latest BGR frame, or ``None`` on error."""
        if self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret:
            logger.warning("Failed to read frame (source=%s)", self._source)
            return None
        self._frame_id += 1
        return frame

    @property
    def frame_id(self) -> int:
        return self._frame_id

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()
