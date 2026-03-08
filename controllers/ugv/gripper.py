"""Servo-based gripper controller for the UGV.

Controls a gripper mechanism via a PWM servo channel connected to the
Raspberry Pi GPIO.  The gripper is used to pick up competition objects
so the UGV can transport them to the drop zone.

Typical servo config (in ``config/ugv.yaml``)::

    gripper:
      servo_pin: 12          # BCM pin for gripper servo
      pwm_open: 0.1          # duty cycle for fully open
      pwm_closed: 0.8        # duty cycle for fully closed
      transit_time_s: 0.6    # seconds to wait for servo travel

"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class GripperController:
    """Control a servo-driven gripper on the UGV.

    Parameters
    ----------
    servo_pin:
        BCM pin number driving the gripper servo.
    pwm_open:
        Duty-cycle value (0.0–1.0) for the open position.
    pwm_closed:
        Duty-cycle value (0.0–1.0) for the closed position.
    transit_time_s:
        Time (seconds) to wait for the servo to reach its target.
    """

    def __init__(
        self,
        servo_pin: int = 12,
        pwm_open: float = 0.1,
        pwm_closed: float = 0.8,
        transit_time_s: float = 0.6,
    ) -> None:
        self._pin = servo_pin
        self._pwm_open = pwm_open
        self._pwm_closed = pwm_closed
        self._transit_time_s = transit_time_s
        self._servo = None
        self._is_open: bool = True
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Initialise the servo GPIO."""
        try:
            from gpiozero import Servo  # type: ignore

            self._servo = Servo(self._pin)
            self._connected = True
            self.open()
            logger.info("Gripper connected on BCM pin %d", self._pin)
        except Exception:
            logger.warning("Gripper servo init failed (pin %d) — running in no-op mode.", self._pin)
            self._connected = False

    def disconnect(self) -> None:
        """Release the servo GPIO."""
        if self._servo is not None:
            try:
                self.open()
                self._servo.close()
            except Exception:
                pass
        self._connected = False
        logger.info("Gripper disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_open(self) -> bool:
        return self._is_open

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the gripper (release object)."""
        self._set_position(self._pwm_open)
        self._is_open = True
        logger.info("Gripper opened.")

    def close(self) -> None:
        """Close the gripper (grab object)."""
        self._set_position(self._pwm_closed)
        self._is_open = False
        logger.info("Gripper closed.")

    def toggle(self) -> None:
        """Toggle between open and closed."""
        if self._is_open:
            self.close()
        else:
            self.open()

    def grab(self) -> None:
        """Close gripper and wait for transit to finish."""
        self.close()
        time.sleep(self._transit_time_s)

    def release(self) -> None:
        """Open gripper and wait for transit to finish."""
        self.open()
        time.sleep(self._transit_time_s)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _set_position(self, duty: float) -> None:
        """Set the servo PWM to the given duty cycle."""
        if self._servo is None:
            logger.debug("Gripper servo not connected — no-op.")
            return
        # gpiozero Servo expects value in [-1, 1]; map duty 0..1 → -1..+1
        value = max(-1.0, min(1.0, duty * 2.0 - 1.0))
        self._servo.value = value
        time.sleep(self._transit_time_s)
