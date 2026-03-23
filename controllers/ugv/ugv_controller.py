"""UGV (ground vehicle) controller — drives L298N motor driver via GPIO on Raspberry Pi 5."""

from __future__ import annotations

import logging
import math
import time
from typing import Optional

import numpy as np

from controllers.ugv.gripper import GripperController
from hal.base import Actuator
from localization.pose import PoseEstimator
from models import TargetHypothesis
from motion.motion_interface import MotionInterface

logger = logging.getLogger(__name__)


class UGVController(MotionInterface):
    """Controls the tracked ground vehicle via GPIO pins and an L298N H-bridge.

    Motor speeds are normalised to ``[-1.0, 1.0]`` and forwarded to
    :class:`~controllers.ugv.l298n_driver.L298NDriver`.

    Parameters
    ----------
    config:
        Parsed UGV configuration dict (from ``config/ugv.yaml``).
    pose_estimator:
        Shared :class:`~localization.pose.PoseEstimator`.
    camera_get_frame:
        Callable returning the latest BGR frame.
    """

    def __init__(
        self,
        config: dict,
        pose_estimator: PoseEstimator,
        motor_driver: Optional[Actuator] = None,
        camera_get_frame=None,
    ) -> None:
        self._cfg = config
        self._pose_estimator = pose_estimator
        self._camera_get_frame = camera_get_frame
        self._driver = motor_driver

        # Gripper
        grip_cfg = self._cfg.get("gripper", {})
        self._gripper = GripperController(
            servo_pin=grip_cfg.get("servo_pin", 12),
            pwm_open=grip_cfg.get("pwm_open", 0.1),
            pwm_closed=grip_cfg.get("pwm_closed", 0.8),
            transit_time_s=grip_cfg.get("transit_time_s", 0.6),
        )

        self._waypoints: list[tuple[float, float]] = []
        self._wp_index = 0

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        if self._driver:
            self._driver.open()
        self._gripper.connect()
        logger.info("UGV GPIO driver connected.")

    def disconnect(self) -> None:
        self.stop()
        self._gripper.disconnect()
        if self._driver:
            self._driver.close()

    def load_waypoints(self, waypoints: list[tuple[float, float]]) -> None:
        """Load a list of (lat, lon) search waypoints."""
        self._waypoints = list(waypoints)
        self._wp_index = 0
        logger.info("UGV: %d waypoints loaded.", len(self._waypoints))

    @property
    def gripper(self) -> GripperController:
        """Access the gripper controller."""
        return self._gripper

    # ------------------------------------------------------------------
    # MotionInterface — lifecycle
    # ------------------------------------------------------------------

    def precheck(self) -> None:
        logger.info("UGV precheck OK.")

    def start_search(self) -> None:
        logger.info("UGV: starting search pattern.")
        self._drive_waypoints_async()

    def return_home(self) -> None:
        self.stop()
        logger.info("UGV: stopped at end of mission.")

    def emergency_stop(self) -> None:
        self.stop()
        logger.warning("UGV: emergency stop.")

    # ------------------------------------------------------------------
    # MotionInterface — target interaction
    # ------------------------------------------------------------------

    def inspect_target(self, hypothesis: TargetHypothesis) -> None:
        """Stop and position camera close to the target box."""
        self.stop()
        time.sleep(0.5)
        logger.info("UGV: inspecting target.")

    def resume_search(self) -> None:
        """Continue towards the next waypoint."""
        logger.info("UGV: resuming search.")
        self._drive_waypoints_async()

    def transport_target(self, hypothesis: TargetHypothesis) -> None:
        """Grab target with gripper, drive to drop zone, and release."""
        # Grab the target
        self._gripper.grab()

        drop_lat = self._cfg.get("drop_zone_lat", 0.0)
        drop_lon = self._cfg.get("drop_zone_lon", 0.0)
        if drop_lat == 0.0 and drop_lon == 0.0:
            logger.warning("Drop zone not configured — skipping transport.")
            self._gripper.release()
            return
        logger.info("UGV: transporting to drop zone.")
        self._drive_to_gps(drop_lat, drop_lon)
        self._trigger_release()

    # ------------------------------------------------------------------
    # MotionInterface — sensor
    # ------------------------------------------------------------------

    def get_inspect_frame(self) -> Optional[np.ndarray]:
        if self._camera_get_frame is not None:
            return self._camera_get_frame()
        return None

    # ------------------------------------------------------------------
    # MotionInterface — mission lifecycle
    # ------------------------------------------------------------------

    def check_mission_complete(self, state_machine) -> None:
        from mission.state_machine import MissionState

        if self._wp_index >= len(self._waypoints) and state_machine.state == MissionState.SEARCH:
            logger.info("UGV: all waypoints visited — returning home.")
            state_machine.transition_to(MissionState.RETURN_HOME)

    # ------------------------------------------------------------------
    # Low-level motor control
    # ------------------------------------------------------------------

    def set_velocity(self, linear: float, angular: float) -> None:
        """Set differential drive velocity.

        Parameters
        ----------
        linear:
            Forward speed in m/s (positive = forward).
        angular:
            Rotation rate in rad/s (positive = left turn).
        """
        max_lin = self._cfg.get("max_linear_speed_mps", 0.3)
        linear = max(-max_lin, min(max_lin, linear))

        # Normalize to [-1, 1]
        base = linear / max_lin if max_lin > 0 else 0.0
        # Scale angular so that max_angular_speed_radps alone does not
        # saturate the motor outputs; 0.5 keeps headroom for combined
        # linear + angular commands.
        turn = angular * 0.5

        left = max(-1.0, min(1.0, base + turn))
        right = max(-1.0, min(1.0, base - turn))
        if self._driver:
            self._driver.set_state({"left": left, "right": right})

    def stop(self) -> None:
        if self._driver:
            self._driver.set_state({"left": 0.0, "right": 0.0})

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def _drive_waypoints_async(self) -> None:
        """Non-blocking: advances to next waypoint in background thread."""
        import threading

        def _worker():
            while self._wp_index < len(self._waypoints):
                lat, lon = self._waypoints[self._wp_index]
                self._drive_to_gps(lat, lon)
                self._wp_index += 1

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _drive_to_gps(self, target_lat: float, target_lon: float) -> None:
        """Proportional controller: drive towards a GPS waypoint."""
        max_speed = self._cfg.get("max_linear_speed_mps", 0.3)
        max_ang = self._cfg.get("max_angular_speed_radps", 0.5)
        arrival_threshold = 1.5  # metres

        while True:
            pose = self._pose_estimator.get_pose()
            if pose is None:
                time.sleep(0.1)
                continue

            dist = PoseEstimator.haversine_distance(pose.lat, pose.lon, target_lat, target_lon)
            if dist < arrival_threshold:
                self.stop()
                return

            # Bearing to target
            bearing = self._bearing(pose.lat, pose.lon, target_lat, target_lon)
            heading = pose.yaw_deg or 0.0
            angle_err = self._angle_diff(bearing, heading)

            # Simple P-controller
            linear = min(max_speed, dist * 0.3)
            angular = max(-max_ang, min(max_ang, angle_err * 0.02))
            self.set_velocity(linear, angular)
            time.sleep(0.1)

    @staticmethod
    def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Compute compass bearing from point 1 to point 2 (degrees, 0=N)."""
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dl = math.radians(lon2 - lon1)
        x = math.sin(dl) * math.cos(phi2)
        y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dl)
        return (math.degrees(math.atan2(x, y)) + 360) % 360

    @staticmethod
    def _angle_diff(a: float, b: float) -> float:
        """Signed angle difference (a − b) in [−180, 180] degrees."""
        diff = (a - b + 180) % 360 - 180
        return diff

    def _trigger_release(self) -> None:
        """Release the gripper to drop the transported object."""
        self._gripper.release()
        logger.info("UGV: gripper released at drop zone.")
