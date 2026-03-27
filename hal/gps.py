"""GPS HAL — Abstraction for real, mock, and replay GPS data."""

from __future__ import annotations

import abc
import logging
import threading
import time
from typing import Callable, Optional

from hal.base import Sensor
from models import Pose
from monitoring.health import ComponentStatus, HealthMonitor

logger = logging.getLogger(__name__)


class GpsInterface(Sensor[Pose]):
    """Interface for GPS sensors."""
    
    @abc.abstractmethod
    def start(self) -> None:
        pass

    @abc.abstractmethod
    def stop(self) -> None:
        pass


class RealGps(GpsInterface):
    """Production GPS reader using serial NMEA."""

    def __init__(
        self,
        port: str = "/dev/ttyAMA10",
        baud_rate: int = 38400,
        on_pose: Optional[Callable[[Pose], None]] = None,
        health_monitor: Optional[HealthMonitor] = None,
    ) -> None:
        self._port = port
        self._baud_rate = baud_rate
        self._on_pose = on_pose
        self._health = health_monitor
        
        self._latest: Optional[Pose] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def open(self) -> None:
        self.start()

    def close(self) -> None:
        self.stop()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="gps-real")
        self._thread.start()
        logger.info("GPS: RealGps started on %s", self._port)
        if self._health:
            # Service is alive, waiting for first valid NMEA fix.
            self._health.heartbeat("gps", ComponentStatus.WARNING)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def get_data(self) -> Optional[Pose]:
        with self._lock:
            return self._latest

    def _run(self) -> None:
        try:
            import serial
            import pynmea2
        except ImportError:
            logger.error("GPS: serial or pynmea2 not found")
            if self._health:
                self._health.heartbeat("gps", ComponentStatus.ERROR)
            return

        backoff = 1.0
        while self._running:
            try:
                with serial.Serial(self._port, self._baud_rate, timeout=1.0) as ser:
                    backoff = 1.0
                    while self._running:
                        line = ser.readline().decode("ascii", errors="replace").strip()
                        if not line:
                            if self._health:
                                self._health.heartbeat("gps", ComponentStatus.WARNING)
                            continue
                        try:
                            msg = pynmea2.parse(line)
                            if hasattr(msg, "latitude") and hasattr(msg, "longitude"):
                                if msg.latitude and msg.longitude:
                                    pose = Pose(lat=float(msg.latitude), lon=float(msg.longitude))
                                    with self._lock:
                                        self._latest = pose
                                    if self._health:
                                        self._health.heartbeat("gps", ComponentStatus.OK)
                                    if self._on_pose:
                                        self._on_pose(pose)
                        except Exception:
                            pass
            except Exception as e:
                logger.warning("GPS: Serial error: %s", e)
                if self._health:
                    self._health.heartbeat("gps", ComponentStatus.WARNING)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)


class MockGps(GpsInterface):
    """Mock GPS that simulates a slow movement."""

    def __init__(
        self,
        start_lat: float = 52.2297,
        start_lon: float = 21.0122,
        on_pose: Optional[Callable[[Pose], None]] = None,
        health_monitor: Optional[HealthMonitor] = None,
    ) -> None:
        self._lat = start_lat
        self._lon = start_lon
        self._on_pose = on_pose
        self._health = health_monitor
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def open(self) -> None:
        self.start()

    def close(self) -> None:
        self.stop()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="gps-mock")
        self._thread.start()
        logger.info("GPS: MockGps started")

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def get_data(self) -> Optional[Pose]:
        return Pose(lat=self._lat, lon=self._lon)

    def _run(self) -> None:
        while self._running:
            # Simulate slight drift/movement (approx 1m per second)
            self._lat += 0.00001
            self._lon += 0.00001
            pose = Pose(lat=self._lat, lon=self._lon)
            if self._on_pose:
                self._on_pose(pose)
            if self._health:
                self._health.heartbeat("gps", ComponentStatus.OK)
            time.sleep(1.0)


class ReplayGps(GpsInterface):
    """Replay GPS data from a NMEA log file."""

    def __init__(
        self,
        log_file: str,
        on_pose: Optional[Callable[[Pose], None]] = None,
        health_monitor: Optional[HealthMonitor] = None,
    ) -> None:
        self._log_file = log_file
        self._on_pose = on_pose
        self._health = health_monitor
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._latest: Optional[Pose] = None

    def open(self) -> None:
        self.start()

    def close(self) -> None:
        self.stop()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="gps-replay")
        self._thread.start()
        logger.info("GPS: ReplayGps started from %s", self._log_file)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def get_data(self) -> Optional[Pose]:
        return self._latest

    def _run(self) -> None:
        import pynmea2
        while self._running:
            try:
                with open(self._log_file, "r") as f:
                    for line in f:
                        if not self._running:
                            break
                        try:
                            msg = pynmea2.parse(line)
                            if hasattr(msg, "latitude") and hasattr(msg, "longitude"):
                                if msg.latitude and msg.longitude:
                                    self._latest = Pose(lat=float(msg.latitude), lon=float(msg.longitude))
                                    if self._on_pose:
                                        self._on_pose(self._latest)
                                    if self._health:
                                        self._health.heartbeat("gps", ComponentStatus.OK)
                                    time.sleep(1.0)
                        except Exception:
                            continue
            except Exception as e:
                logger.error("GPS: Replay error: %s", e)
                if self._health:
                    self._health.heartbeat("gps", ComponentStatus.ERROR)
                break
