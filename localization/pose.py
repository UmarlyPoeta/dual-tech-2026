"""Pose estimator — maintains a fused pose from GPS and other sources."""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

from models import Pose


class PoseEstimator:
    """Aggregates pose data from one or more sources.

    Sources push updates via :meth:`update_gps`, :meth:`update_heading`, etc.
    Consumers call :meth:`get_pose` to read the latest estimate.
    """

    def __init__(self) -> None:
        self._lat: Optional[float] = None
        self._lon: Optional[float] = None
        self._alt: Optional[float] = None
        self._yaw_deg: Optional[float] = None
        self._pitch_deg: Optional[float] = None
        self._lock = threading.Lock()
        self._last_update: float = 0.0

    # ------------------------------------------------------------------
    # Update methods (called from sensor threads)
    # ------------------------------------------------------------------

    def update_gps(self, lat: float, lon: float, alt: Optional[float] = None) -> None:
        with self._lock:
            self._lat = lat
            self._lon = lon
            if alt is not None:
                self._alt = alt
            self._last_update = time.time()

    def update_heading(self, yaw_deg: float) -> None:
        with self._lock:
            self._yaw_deg = yaw_deg

    def update_pitch(self, pitch_deg: float) -> None:
        with self._lock:
            self._pitch_deg = pitch_deg

    def update_pose(self, pose: Pose) -> None:
        """Bulk update from a :class:`~models.Pose` object."""
        with self._lock:
            if pose.lat:
                self._lat = pose.lat
            if pose.lon:
                self._lon = pose.lon
            if pose.alt is not None:
                self._alt = pose.alt
            if pose.yaw_deg is not None:
                self._yaw_deg = pose.yaw_deg
            if pose.pitch_deg is not None:
                self._pitch_deg = pose.pitch_deg
            self._last_update = time.time()

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    def get_pose(self) -> Optional[Pose]:
        with self._lock:
            if self._lat is None or self._lon is None:
                return None
            return Pose(
                lat=self._lat,
                lon=self._lon,
                alt=self._alt,
                yaw_deg=self._yaw_deg,
                pitch_deg=self._pitch_deg,
            )

    @property
    def age_seconds(self) -> float:
        """Seconds since the last GPS update."""
        if self._last_update == 0.0:
            return float("inf")
        return time.time() - self._last_update

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Return the great-circle distance in metres between two GPS points."""
        r = 6_371_000.0  # Earth radius in metres
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
