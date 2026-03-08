"""Servo-based payload dropper for the UAV.

Controls an electromagnet or servo release mechanism that allows the drone
to pick up and drop competition objects.  Integrated with ArduPilot via
MAVLink DO_SET_SERVO commands.

Typical config (in ``config/uav.yaml``)::

    payload:
      servo_channel: 10       # ArduPilot servo output channel
      pwm_engage: 1900        # PWM to engage (hold) the payload
      pwm_release: 1100       # PWM to release (drop) the payload
      settle_time_s: 0.5      # seconds to wait after command
"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class PayloadDropper:
    """Control an electromagnetic or servo payload release on the UAV.

    Parameters
    ----------
    vehicle:
        A connected dronekit ``Vehicle`` instance (or ``None`` for no-op mode).
    servo_channel:
        ArduPilot servo output channel number (1-indexed).
    pwm_engage:
        PWM value (µs) to engage / hold the payload.
    pwm_release:
        PWM value (µs) to release / drop the payload.
    settle_time_s:
        Time to wait after sending a servo command.
    """

    def __init__(
        self,
        vehicle=None,
        servo_channel: int = 10,
        pwm_engage: int = 1900,
        pwm_release: int = 1100,
        settle_time_s: float = 0.5,
    ) -> None:
        self._vehicle = vehicle
        self._channel = servo_channel
        self._pwm_engage = pwm_engage
        self._pwm_release = pwm_release
        self._settle_time_s = settle_time_s
        self._engaged: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_engaged(self) -> bool:
        """``True`` if the payload mechanism is in the 'hold' position."""
        return self._engaged

    def engage(self) -> None:
        """Engage the payload mechanism (hold object)."""
        self._send_pwm(self._pwm_engage)
        self._engaged = True
        logger.info("Payload engaged (channel %d → %d µs).", self._channel, self._pwm_engage)

    def release(self) -> None:
        """Release the payload (drop object)."""
        self._send_pwm(self._pwm_release)
        self._engaged = False
        logger.info("Payload released (channel %d → %d µs).", self._channel, self._pwm_release)

    def set_vehicle(self, vehicle) -> None:
        """Bind to a dronekit Vehicle (called after connect)."""
        self._vehicle = vehicle

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send_pwm(self, pwm: int) -> None:
        if self._vehicle is None:
            logger.debug("Payload dropper: no vehicle — no-op (pwm=%d).", pwm)
            return
        try:
            msg = self._vehicle.message_factory.command_long_encode(
                0, 0,
                183,  # MAV_CMD_DO_SET_SERVO
                0,
                self._channel, pwm, 0, 0, 0, 0, 0,
            )
            self._vehicle.send_mavlink(msg)
            time.sleep(self._settle_time_s)
        except Exception:
            logger.warning("Payload dropper MAVLink send failed.", exc_info=True)
