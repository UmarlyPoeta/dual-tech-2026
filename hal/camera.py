"""Camera HAL — Abstraction for real and mock video sources."""

from __future__ import annotations

import abc
import logging
import time
from typing import Optional

import numpy as np
from hal.base import Sensor
from monitoring.health import ComponentStatus, HealthMonitor

logger = logging.getLogger(__name__)


class CameraInterface(Sensor[np.ndarray]):
    """Interface for camera sensors."""

    @property
    @abc.abstractmethod
    def frame_id(self) -> int:
        pass

    @abc.abstractmethod
    def get_frame(self) -> Optional[np.ndarray]:
        pass


class RealCamera(CameraInterface):
    """Production camera using Picamera2 or OpenCV with auto-reconnect."""

    def __init__(
        self,
        source: int | str = 0,
        width: int = 640,
        height: int = 480,
        use_picamera: Optional[bool] = None,
        health_monitor: Optional[HealthMonitor] = None,
    ) -> None:
        self._source = source
        self._width = width
        self._height = height
        self._use_picamera_flag = use_picamera
        self._health = health_monitor

        self._cap = None
        self._picam2 = None
        self._frame_id = 0
        self._consecutive_failures = 0
        self._last_reconnect: float = 0.0
        self._fail_threshold = 10
        self._reconnect_cooldown_s = 2.0

    def open(self) -> None:
        if self._use_picamera_flag is not False:
            try:
                from picamera2 import Picamera2
                self._picam2 = Picamera2()
                # Newer libcamera/PiSP stacks on Pi5 may reject BGR24 in the
                # main stream; try a small list of broadly supported formats.
                last_err: Optional[Exception] = None
                for fmt in ("RGB888", "XRGB8888", "XBGR8888", "BGR24"):
                    try:
                        config = self._picam2.create_video_configuration(
                            main={"format": fmt, "size": (self._width, self._height)}
                        )
                        self._picam2.configure(config)
                        logger.info("Camera: Picamera2 main format=%s", fmt)
                        break
                    except Exception as exc:
                        last_err = exc
                else:
                    raise RuntimeError(f"No supported Picamera2 format found: {last_err}")
                self._picam2.start()
                logger.info("Camera: RealCamera using Picamera2 (%dx%d)", self._width, self._height)
                if self._health:
                    self._health.heartbeat("camera", ComponentStatus.OK)
                return
            except (ImportError, Exception):
                if self._use_picamera_flag is True:
                    raise
                self._picam2 = None

        import cv2
        self._cap = cv2.VideoCapture(self._source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera source: {self._source}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        logger.info("Camera: RealCamera using OpenCV (source=%s, %dx%d)", self._source, self._width, self._height)

    def close(self) -> None:
        if self._picam2 is not None:
            self._picam2.stop()
            self._picam2 = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def get_data(self) -> Optional[np.ndarray]:
        frame = None
        if self._picam2 is not None:
            try:
                frame = self._picam2.capture_array()
                # Downstream code expects BGR. Picamera2 commonly returns RGB/RGBA.
                if frame is not None and len(frame.shape) == 3:
                    channels = frame.shape[2]
                    if channels == 4:
                        import cv2

                        frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
                    elif channels == 3:
                        import cv2

                        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            except Exception:
                frame = None
        elif self._cap is not None:
            ret, frame = self._cap.read()
            if not ret:
                frame = None

        if frame is not None:
            self._consecutive_failures = 0
            self._frame_id += 1
            if self._health:
                self._health.heartbeat("camera", ComponentStatus.OK)
            return frame
        else:
            self._consecutive_failures += 1
            if self._health:
                self._health.heartbeat("camera", ComponentStatus.WARNING)
            if self._consecutive_failures >= self._fail_threshold:
                self._try_reconnect()
            return None

    def _try_reconnect(self) -> None:
        now = time.monotonic()
        if now - self._last_reconnect < self._reconnect_cooldown_s:
            return
        self._last_reconnect = now
        logger.warning("Camera: Reconnecting after %d failures", self._consecutive_failures)
        try:
            self.close()
            self.open()
        except Exception:
            if self._health:
                self._health.heartbeat("camera", ComponentStatus.ERROR)

    @property
    def frame_id(self) -> int:
        return self._frame_id

    def get_frame(self) -> Optional[np.ndarray]:
        """Alias for get_data() for backward compatibility."""
        return self.get_data()


class MockCamera(CameraInterface):
    """Mock camera that generates a test pattern with a moving timestamp."""

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        health_monitor: Optional[HealthMonitor] = None,
    ) -> None:
        self._width = width
        self._height = height
        self._fps = fps
        self._health = health_monitor
        self._frame_id = 0
        self._start_time = time.monotonic()

    def open(self) -> None:
        logger.info("Camera: MockCamera initialized (%dx%d)", self._width, self._height)

    def close(self) -> None:
        pass

    def get_data(self) -> Optional[np.ndarray]:
        import cv2
        frame = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        
        # Draw some moving patterns
        t = time.monotonic() - self._start_time
        cx = int(self._width / 2 + 100 * np.sin(t * 2))
        cy = int(self._height / 2 + 100 * np.cos(t * 2))
        cv2.circle(frame, (cx, cy), 50, (0, 255, 0), -1)
        
        cv2.putText(
            frame, f"MOCK CAMERA | Frame: {self._frame_id} | T: {t:.2f}s",
            (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2
        )
        
        self._frame_id += 1
        if self._health:
            self._health.heartbeat("camera", ComponentStatus.OK)
        
        # Simulate FPS
        time.sleep(1.0 / self._fps)
        return frame

    @property
    def frame_id(self) -> int:
        return self._frame_id

    def get_frame(self) -> Optional[np.ndarray]:
        """Alias for get_data() for backward compatibility."""
        return self.get_data()
