"""GPS reader — reads NMEA sentences from a serial GPS module."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from models import Pose

logger = logging.getLogger(__name__)


class GpsReader:
    """Reads GPS data in a background thread and exposes the latest fix.

    Parameters
    ----------
    port:
        Serial device path, e.g. ``"/dev/ttyAMA0"``.
    baud_rate:
        Baud rate for the serial connection.
    on_pose:
        Optional callback called with each new :class:`~models.Pose` fix.
        Useful for feeding a :class:`~localization.pose.PoseEstimator`.
    """

    def __init__(
        self,
        port: str = "/dev/ttyAMA0",
        baud_rate: int = 9600,
        on_pose: Optional[Callable[[Pose], None]] = None,
    ) -> None:
        self._port = port
        self._baud_rate = baud_rate
        self._on_pose = on_pose
        self._latest: Optional[Pose] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open serial port and start background reader thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="gps-reader")
        self._thread.start()
        logger.info("GPS reader started (port=%s, baud=%d)", self._port, self._baud_rate)

    def stop(self) -> None:
        """Stop the background reader thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        logger.info("GPS reader stopped.")

    # ------------------------------------------------------------------
    # Data access
    # ------------------------------------------------------------------

    def get_pose(self) -> Optional[Pose]:
        """Return the most recent GPS fix, or ``None`` if not yet available."""
        with self._lock:
            return self._latest

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        try:
            import serial  # type: ignore
            import pynmea2  # type: ignore
        except ImportError as exc:
            logger.error("GPS dependencies not available: %s", exc)
            return

        try:
            with serial.Serial(self._port, self._baud_rate, timeout=1.0) as ser:
                while self._running:
                    try:
                        line = ser.readline().decode("ascii", errors="replace").strip()
                        if not line:
                            continue
                        msg = pynmea2.parse(line)
                        if hasattr(msg, "latitude") and hasattr(msg, "longitude"):
                            if msg.latitude and msg.longitude:
                                pose = Pose(lat=float(msg.latitude), lon=float(msg.longitude))
                                with self._lock:
                                    self._latest = pose
                                if self._on_pose is not None:
                                    self._on_pose(pose)
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.debug("GPS parse error: %s", exc)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("GPS serial error: %s", exc)
