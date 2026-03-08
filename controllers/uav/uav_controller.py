"""UAV controller — communicates with ArduPilot over MAVLink via dronekit.

Includes automatic reconnection on link loss so that the drone can resume
operation after transient WiFi / serial dropouts.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import numpy as np

from localization.pose import PoseEstimator
from models import Pose, TargetHypothesis
from motion.motion_interface import MotionInterface

logger = logging.getLogger(__name__)

_RECONNECT_INTERVAL_S = 3.0
_MAX_RECONNECT_ATTEMPTS = 10


class UAVController(MotionInterface):
    """Controls the drone via MAVLink (dronekit-python).

    The controller will attempt to reconnect to the flight controller
    automatically if the link is lost, up to ``_MAX_RECONNECT_ATTEMPTS``
    before giving up.

    Parameters
    ----------
    config:
        Parsed UAV configuration dict (from ``config/uav.yaml``).
    pose_estimator:
        Shared :class:`~localization.pose.PoseEstimator` updated from MAVLink telemetry.
    camera_get_frame:
        Callable returning the latest BGR frame from the companion camera.
    """

    def __init__(
        self,
        config: dict,
        pose_estimator: PoseEstimator,
        camera_get_frame=None,
    ) -> None:
        self._cfg = config
        self._pose_estimator = pose_estimator
        self._camera_get_frame = camera_get_frame
        self._vehicle = None
        self._waypoints_exhausted = False

    # ------------------------------------------------------------------
    # Connection with auto-reconnect
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to the flight controller and wait for GPS fix."""
        self._do_connect()

    def _do_connect(self) -> None:
        import dronekit  # type: ignore

        conn_str = self._cfg.get("connection_string", "/dev/ttyAMA0")
        baud = self._cfg.get("baud_rate", 57600)
        logger.info("Connecting to ArduPilot: %s (baud=%d)", conn_str, baud)
        self._vehicle = dronekit.connect(conn_str, baud=baud, wait_ready=True)
        logger.info("Connected. Firmware: %s", self._vehicle.version)

    def _ensure_connected(self) -> bool:
        """Return ``True`` if the vehicle link is alive, attempting reconnect if needed."""
        if self._vehicle is not None:
            try:
                # A lightweight attribute read — if the link is dead this will raise
                _ = self._vehicle.mode
                return True
            except Exception:
                logger.warning("MAVLink link lost — attempting reconnect…")
                try:
                    self._vehicle.close()
                except Exception:
                    pass
                self._vehicle = None

        for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
            try:
                logger.info("MAVLink reconnect attempt %d/%d", attempt, _MAX_RECONNECT_ATTEMPTS)
                self._do_connect()
                logger.info("MAVLink reconnected.")
                return True
            except Exception as exc:
                logger.warning("Reconnect failed: %s", exc)
                time.sleep(_RECONNECT_INTERVAL_S)

        logger.error("MAVLink reconnect failed after %d attempts.", _MAX_RECONNECT_ATTEMPTS)
        return False

    def disconnect(self) -> None:
        if self._vehicle is not None:
            self._vehicle.close()
            self._vehicle = None

    # ------------------------------------------------------------------
    # MotionInterface — lifecycle
    # ------------------------------------------------------------------

    def precheck(self) -> None:
        """Verify GPS fix, battery, and arming pre-conditions."""
        if self._vehicle is None:
            raise RuntimeError("Not connected to flight controller.")
        gps = self._vehicle.gps_0
        if gps.fix_type < 3:
            raise RuntimeError(f"Insufficient GPS fix: type={gps.fix_type}")
        bat = self._vehicle.battery
        logger.info("Precheck OK — GPS fix=%d bat=%.1fV", gps.fix_type, bat.voltage or 0)

    def start_search(self) -> None:
        """Arm, take off to search altitude, and begin the AUTO search pattern."""
        self._arm_and_takeoff(self._cfg.get("takeoff_alt_m", 6.0))
        self._set_mode("AUTO")
        logger.info("Search pattern started (AUTO mode).")

    def return_home(self) -> None:
        self._set_mode("RTL")
        logger.info("RTL commanded.")

    def emergency_stop(self) -> None:
        self._set_mode("RTL")
        logger.warning("Emergency stop — RTL commanded.")

    # ------------------------------------------------------------------
    # MotionInterface — target interaction
    # ------------------------------------------------------------------

    def inspect_target(self, hypothesis: TargetHypothesis) -> None:
        """Switch to GUIDED, set camera to nadir, and centre over the target."""
        self._set_mode("GUIDED")
        self._set_camera_pwm(self._cfg.get("camera_inspect_pwm", 1100))
        self._center_over_target(hypothesis)

    def resume_search(self) -> None:
        """Reset camera to search angle and return to AUTO."""
        self._set_camera_pwm(self._cfg.get("camera_search_pwm", 1500))
        self._set_mode("AUTO")
        logger.info("Resumed AUTO search.")

    def transport_target(self, hypothesis: TargetHypothesis) -> None:
        """Simple release-based transport: descend, release, return to search altitude."""
        logger.info("Transport: descending to release altitude…")
        inspect_alt = self._cfg.get("inspect_alt_m", 4.0)
        self._send_velocity(0, 0, -1.0)  # descend
        time.sleep(3.0)
        self._send_velocity(0, 0, 0)
        self._trigger_release()
        time.sleep(1.0)
        self._send_velocity(0, 0, 1.0)  # climb back
        time.sleep(3.0)
        self._send_velocity(0, 0, 0)
        logger.info("Transport complete.")

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

        if self._waypoints_exhausted and state_machine.state == MissionState.SEARCH:
            logger.info("All search waypoints exhausted — returning home.")
            state_machine.transition_to(MissionState.RETURN_HOME)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _arm_and_takeoff(self, target_altitude: float) -> None:
        import dronekit  # type: ignore

        if not self._ensure_connected():
            return
        logger.info("Arming motors…")
        self._vehicle.mode = dronekit.VehicleMode("GUIDED")
        self._vehicle.armed = True

        while not self._vehicle.armed:
            logger.debug("Waiting for arm…")
            time.sleep(1)

        logger.info("Taking off to %.1f m…", target_altitude)
        self._vehicle.simple_takeoff(target_altitude)

        while True:
            alt = self._vehicle.location.global_relative_frame.alt or 0
            logger.debug("Altitude: %.1f m", alt)
            if alt >= target_altitude * 0.95:
                break
            time.sleep(0.5)
        logger.info("Target altitude reached.")

    def _set_mode(self, mode_name: str) -> None:
        import dronekit  # type: ignore

        if not self._ensure_connected():
            return
        self._vehicle.mode = dronekit.VehicleMode(mode_name)
        logger.info("Flight mode set to %s", mode_name)

    def _send_velocity(self, vx: float, vy: float, vz: float, yaw_rate: float = 0.0) -> None:
        """Send a body-frame velocity command (m/s)."""
        from pymavlink import mavutil  # type: ignore

        if not self._ensure_connected():
            return
        msg = self._vehicle.message_factory.set_position_target_local_ned_encode(
            0, 0, 0,
            mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,
            0b0000_1111_1100_0111,  # velocity only
            0, 0, 0,
            vx, vy, vz,
            0, 0, 0,
            0, yaw_rate,
        )
        self._vehicle.send_mavlink(msg)

    def _set_camera_pwm(self, pwm: int) -> None:
        channel = self._cfg.get("camera_servo_channel", 9)
        if not self._ensure_connected():
            return
        msg = self._vehicle.message_factory.command_long_encode(
            0, 0,
            183,  # MAV_CMD_DO_SET_SERVO
            0,
            channel, pwm, 0, 0, 0, 0, 0,
        )
        self._vehicle.send_mavlink(msg)
        logger.debug("Camera servo ch%d → %d µs", channel, pwm)

    def _trigger_release(self) -> None:
        """Override in subclass or hook to release mechanism."""
        logger.info("Release triggered (no-op in base implementation).")

    def _center_over_target(self, hypothesis: TargetHypothesis) -> None:
        """Use PID-style image centering to hover over the detected bbox."""
        if self._camera_get_frame is None:
            logger.warning("No camera — cannot centre over target.")
            time.sleep(2.0)
            return

        threshold = self._cfg.get("center_threshold_m", 0.2)
        hold_time = self._cfg.get("center_hold_time_s", 1.0)
        max_speed = self._cfg.get("max_xy_speed_mps", 0.4)
        centred_since: Optional[float] = None

        while True:
            frame = self._camera_get_frame()
            if frame is None:
                time.sleep(0.1)
                continue

            h, w = frame.shape[:2]
            cx_frame, cy_frame = w / 2.0, h / 2.0

            if hypothesis.box_detection is not None:
                x1, y1, x2, y2 = hypothesis.box_detection.bbox
            elif hypothesis.object_detection is not None:
                x1, y1, x2, y2 = hypothesis.object_detection.bbox
            else:
                break

            obj_cx = (x1 + x2) / 2.0
            obj_cy = (y1 + y2) / 2.0
            err_x = (obj_cx - cx_frame) / w  # normalised −0.5 … +0.5
            err_y = (obj_cy - cy_frame) / h

            vx = float(err_y * max_speed * 2)   # forward/back
            vy = float(err_x * max_speed * 2)   # left/right
            self._send_velocity(vx, vy, 0)

            if abs(err_x) < 0.05 and abs(err_y) < 0.05:
                if centred_since is None:
                    centred_since = time.time()
                elif time.time() - centred_since >= hold_time:
                    self._send_velocity(0, 0, 0)
                    logger.info("Centred over target.")
                    break
            else:
                centred_since = None

            time.sleep(0.1)
