"""Camera abstraction — automatically detects and uses picamera2 or OpenCV."""

from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Number of consecutive read failures before attempting a reconnect
_FAIL_THRESHOLD = 10
_RECONNECT_COOLDOWN_S = 2.0


class Camera:
    """Thin wrapper around an OpenCV or Picamera2 video source with automatic reconnection.

    On Raspberry Pi OS Bookworm with a CSI camera, it uses `picamera2`.
    Otherwise, it falls back to `cv2.VideoCapture`.

    Parameters
    ----------
    source:
        Camera index (int) or video file / RTSP URL (str).
    width, height:
        Desired capture resolution.
    use_picamera:
        Explicitly use picamera2 if True. If None (default), auto-detect.
    """

    def __init__(
        self,
        source: int | str = 0,
        width: int = 640,
        height: int = 480,
        use_picamera: Optional[bool] = None,
    ) -> None:
        self._source = source
        self._width = width
        self._height = height
        self._use_picamera_flag = use_picamera
        
        self._cap = None  # For OpenCV
        self._picam2 = None  # For Picamera2
        
        self._frame_id = 0
        self._consecutive_failures = 0
        self._last_reconnect: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the capture device. Raises RuntimeError on failure."""
        
        # 1. Attempt Picamera2 if requested or auto-detecting
        if self._use_picamera_flag is not False:
            try:
                from picamera2 import Picamera2
                
                # Check if we can actually initialize a Picamera2 instance
                self._picam2 = Picamera2()
                
                # Configure camera
                config = self._picam2.create_video_configuration(
                    main={"format": "BGR24", "size": (self._width, self._height)}
                )
                self._picam2.configure(config)
                self._picam2.start()
                
                logger.info("Camera: using Picamera2 backend (%dx%d)", self._width, self._height)
                self._consecutive_failures = 0
                self._last_reconnect = time.monotonic()
                return
            except (ImportError, Exception) as e:
                if self._use_picamera_flag is True:
                    raise RuntimeError(f"Picamera2 explicitly requested but failed: {e}")
                logger.debug("Picamera2 not available or no CSI camera found, falling back to OpenCV.")
                self._picam2 = None

        # 2. Fallback to OpenCV
        import cv2
        self._cap = cv2.VideoCapture(self._source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera source: {self._source}")
        
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        
        self._consecutive_failures = 0
        self._last_reconnect = time.monotonic()
        logger.info("Camera: using OpenCV backend (source=%s, %dx%d)", self._source, self._width, self._height)

    def close(self) -> None:
        """Release the capture device."""
        if self._picam2 is not None:
            self._picam2.stop()
            self._picam2 = None
            logger.info("Picamera2 closed.")
            
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            logger.info("OpenCV camera closed.")

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Frame acquisition
    # ------------------------------------------------------------------

    def get_frame(self) -> Optional[np.ndarray]:
        """Return the latest BGR frame, or None on error."""
        
        # Handle Picamera2
        if self._picam2 is not None:
            try:
                frame = self._picam2.capture_array()
                self._consecutive_failures = 0
                self._frame_id += 1
                return frame
            except Exception:
                self._consecutive_failures += 1
                if self._consecutive_failures >= _FAIL_THRESHOLD:
                    self._try_reconnect()
                return None

        # Handle OpenCV
        if self._cap is None:
            return None
            
        ret, frame = self._cap.read()
        if not ret:
            self._consecutive_failures += 1
            if self._consecutive_failures >= _FAIL_THRESHOLD:
                self._try_reconnect()
            return None
            
        self._consecutive_failures = 0
        self._frame_id += 1
        return frame

    @property
    def frame_id(self) -> int:
        return self._frame_id

    @property
    def is_open(self) -> bool:
        return (self._cap is not None and self._cap.isOpened()) or (self._picam2 is not None)

    # ------------------------------------------------------------------
    # Auto-reconnect
    # ------------------------------------------------------------------

    def _try_reconnect(self) -> None:
        """Release and re-open the capture device."""
        now = time.monotonic()
        if now - self._last_reconnect < _RECONNECT_COOLDOWN_S:
            return  # cooldown — don't spam reconnects
            
        self._last_reconnect = now
        logger.warning(
            "Camera: %d consecutive read failures — attempting reconnect",
            self._consecutive_failures
        )
        try:
            self.close()
            self.open()
        except Exception:
            logger.warning("Camera reconnect failed; will retry later.", exc_info=True)
