"""Arm controller — orchestrates servo + stepper for the UGV manipulator.

Coordinates multi-axis movement:
  - Stepper motor for linear axis (arm extension)
  - MG995 servo for wrist rotation
  - SG90 servo for camera tilt

Commands are dispatched from the web GUI or CLI.  All movements enforce
software limits loaded from ``config/hardware/hw_params.yaml``.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from hal.servo import ServoInterface
from hal.stepper import StepperInterface

logger = logging.getLogger(__name__)


class ArmController:
    """Orchestrates the UGV arm (stepper + servos).

    Parameters
    ----------
    arm_stepper:
        Stepper motor for linear arm extension.
    wrist_servo:
        MG995 servo for wrist joint rotation.
    camera_servo:
        SG90 servo for camera tilt.
    grip_servo:
        Optional servo for gripper open/close (if separate from wrist).
    """

    def __init__(
        self,
        arm_stepper: Optional[StepperInterface] = None,
        wrist_servo: Optional[ServoInterface] = None,
        camera_servo: Optional[ServoInterface] = None,
        grip_servo: Optional[ServoInterface] = None,
    ) -> None:
        self._stepper = arm_stepper
        self._wrist = wrist_servo
        self._camera = camera_servo
        self._grip = grip_servo
        self._connected = False

    def connect(self) -> None:
        """Open all actuators."""
        try:
            if self._stepper:
                self._stepper.open()
            if self._wrist:
                self._wrist.open()
            if self._camera:
                self._camera.open()
            if self._grip:
                self._grip.open()
            self._connected = True
            logger.info("ArmController connected (stepper=%s wrist=%s cam=%s grip=%s)",
                        self._stepper is not None, self._wrist is not None,
                        self._camera is not None, self._grip is not None)
        except Exception as e:
            logger.error("ArmController connect failed: %s — emergency stop", e)
            self.emergency_stop()
            raise

    def disconnect(self) -> None:
        """Close all actuators safely."""
        self.emergency_stop()
        if self._stepper:
            self._stepper.close()
        if self._wrist:
            self._wrist.close()
        if self._camera:
            self._camera.close()
        if self._grip:
            self._grip.close()
        self._connected = False
        logger.info("ArmController disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Arm extension (stepper)
    # ------------------------------------------------------------------

    def arm_extend(self, position: int) -> None:
        """Move arm to absolute position (in steps)."""
        if self._stepper is None:
            logger.warning("No stepper configured — arm_extend ignored")
            return
        try:
            self._stepper.move_to(position)
        except Exception as e:
            logger.error("arm_extend failed: %s", e)
            self.emergency_stop()

    def arm_up(self, steps: int = 200) -> None:
        """Extend arm by relative steps."""
        if self._stepper is None:
            return
        try:
            self._stepper.move_relative(steps)
        except Exception as e:
            logger.error("arm_up failed: %s", e)
            self.emergency_stop()

    def arm_down(self, steps: int = 200) -> None:
        """Retract arm by relative steps."""
        if self._stepper is None:
            return
        try:
            self._stepper.move_relative(-steps)
        except Exception as e:
            logger.error("arm_down failed: %s", e)
            self.emergency_stop()

    def arm_home(self) -> None:
        """Return arm to position 0."""
        self.arm_extend(0)

    # ------------------------------------------------------------------
    # Wrist (MG995 servo)
    # ------------------------------------------------------------------

    def wrist_set_angle(self, angle_deg: float) -> None:
        """Set wrist servo angle."""
        if self._wrist is None:
            logger.warning("No wrist servo configured")
            return
        try:
            self._wrist.set_angle(angle_deg)
        except Exception as e:
            logger.error("wrist_set_angle failed: %s", e)

    def wrist_rotate(self, delta_deg: float) -> None:
        """Rotate wrist by a relative angle."""
        if self._wrist is None:
            return
        current = self._wrist.get_angle()
        self.wrist_set_angle(current + delta_deg)

    # ------------------------------------------------------------------
    # Camera tilt (SG90 servo)
    # ------------------------------------------------------------------

    def camera_tilt(self, angle_deg: float) -> None:
        """Set camera tilt angle."""
        if self._camera is None:
            logger.warning("No camera servo configured")
            return
        try:
            self._camera.set_angle(angle_deg)
        except Exception as e:
            logger.error("camera_tilt failed: %s", e)

    def camera_look_down(self) -> None:
        """Tilt camera to look straight down (inspection)."""
        self.camera_tilt(0.0)

    def camera_look_forward(self) -> None:
        """Tilt camera to look forward (navigation)."""
        self.camera_tilt(90.0)

    # ------------------------------------------------------------------
    # Gripper (servo or inherited GripperController)
    # ------------------------------------------------------------------

    def grip_open(self) -> None:
        """Open the gripper via servo."""
        if self._grip is None:
            return
        try:
            self._grip.set_angle(0.0)
        except Exception as e:
            logger.error("grip_open failed: %s", e)

    def grip_close(self) -> None:
        """Close the gripper via servo."""
        if self._grip is None:
            return
        try:
            self._grip.set_angle(180.0)
        except Exception as e:
            logger.error("grip_close failed: %s", e)

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def emergency_stop(self) -> None:
        """Stop all actuators immediately."""
        if self._stepper:
            try:
                self._stepper.stop_motor()
            except Exception:
                pass
        logger.warning("ArmController: emergency stop")

    # ------------------------------------------------------------------
    # Command dispatch (for web GUI integration)
    # ------------------------------------------------------------------

    def handle_command(self, cmd: str, args: dict) -> dict:
        """Dispatch an arm command from the web GUI or CLI.

        Returns a status dict for the caller.
        """
        handlers = {
            "arm_up": lambda: self.arm_up(args.get("steps", 200)),
            "arm_down": lambda: self.arm_down(args.get("steps", 200)),
            "arm_home": lambda: self.arm_home(),
            "arm_extend": lambda: self.arm_extend(args.get("position", 0)),
            "wrist_set": lambda: self.wrist_set_angle(args.get("angle", 90)),
            "wrist_left": lambda: self.wrist_rotate(-10),
            "wrist_right": lambda: self.wrist_rotate(10),
            "camera_tilt": lambda: self.camera_tilt(args.get("angle", 90)),
            "camera_down": lambda: self.camera_look_down(),
            "camera_forward": lambda: self.camera_look_forward(),
            "grip_open": lambda: self.grip_open(),
            "grip_close": lambda: self.grip_close(),
            "arm_stop": lambda: self.emergency_stop(),
        }

        handler = handlers.get(cmd)
        if handler is None:
            return {"ok": False, "error": f"Unknown arm command: {cmd}"}

        try:
            handler()
            return {"ok": True, "cmd": cmd}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def get_telemetry(self) -> dict:
        """Return current arm state for the web GUI."""
        return {
            "arm_position": self._stepper.get_position() if self._stepper else 0,
            "arm_moving": self._stepper.is_moving() if self._stepper else False,
            "wrist_angle": self._wrist.get_angle() if self._wrist else 0.0,
            "camera_angle": self._camera.get_angle() if self._camera else 0.0,
        }
