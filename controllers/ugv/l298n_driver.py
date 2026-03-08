"""L298N motor driver — direct GPIO control via *gpiozero* on Raspberry Pi 5.

Provides a thin abstraction around six GPIO pins (IN1, IN2, ENA, IN3, IN4,
ENB) so that :class:`~controllers.ugv.ugv_controller.UGVController` can set
motor speeds without knowing the pin-level details.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class L298NDriver:
    """Drive two DC motors through an L298N H-bridge connected to GPIO pins.

    Parameters
    ----------
    left_in1, left_in2:
        BCM pin numbers for direction control of the *left* motor.
    left_ena:
        BCM pin number for the PWM-capable enable pin of the *left* motor.
    right_in3, right_in4:
        BCM pin numbers for direction control of the *right* motor.
    right_enb:
        BCM pin number for the PWM-capable enable pin of the *right* motor.
    pwm_frequency:
        PWM frequency in Hz (default 1000).
    """

    def __init__(
        self,
        left_in1: int,
        left_in2: int,
        left_ena: int,
        right_in3: int,
        right_in4: int,
        right_enb: int,
        pwm_frequency: int = 1000,
    ) -> None:
        self._pin_cfg = {
            "left_in1": left_in1,
            "left_in2": left_in2,
            "left_ena": left_ena,
            "right_in3": right_in3,
            "right_in4": right_in4,
            "right_enb": right_enb,
        }
        self._pwm_frequency = pwm_frequency

        # These will be set in connect()
        self._left_in1 = None
        self._left_in2 = None
        self._left_ena = None
        self._right_in3 = None
        self._right_in4 = None
        self._right_enb = None
        self._connected = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Initialise GPIO pins and PWM outputs."""
        from gpiozero import DigitalOutputDevice, PWMOutputDevice  # type: ignore

        self._left_in1 = DigitalOutputDevice(self._pin_cfg["left_in1"])
        self._left_in2 = DigitalOutputDevice(self._pin_cfg["left_in2"])
        self._left_ena = PWMOutputDevice(
            self._pin_cfg["left_ena"], frequency=self._pwm_frequency,
        )

        self._right_in3 = DigitalOutputDevice(self._pin_cfg["right_in3"])
        self._right_in4 = DigitalOutputDevice(self._pin_cfg["right_in4"])
        self._right_enb = PWMOutputDevice(
            self._pin_cfg["right_enb"], frequency=self._pwm_frequency,
        )

        self._connected = True
        logger.info(
            "L298N GPIO driver connected (pins: %s, PWM %d Hz)",
            self._pin_cfg,
            self._pwm_frequency,
        )

    def disconnect(self) -> None:
        """Stop motors and release GPIO resources."""
        self.stop()
        for dev in (
            self._left_in1,
            self._left_in2,
            self._left_ena,
            self._right_in3,
            self._right_in4,
            self._right_enb,
        ):
            if dev is not None:
                dev.close()
        self._connected = False
        logger.info("L298N GPIO driver disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Motor control
    # ------------------------------------------------------------------

    def set_speeds(self, left: float, right: float) -> None:
        """Set both motor speeds simultaneously.

        Parameters
        ----------
        left, right:
            Speed values in the range ``[-1.0, 1.0]``.
            Positive = forward, negative = reverse.
        """
        self._set_motor(
            left,
            self._left_in1,
            self._left_in2,
            self._left_ena,
        )
        self._set_motor(
            right,
            self._right_in3,
            self._right_in4,
            self._right_enb,
        )

    def stop(self) -> None:
        """Coast-stop both motors (all direction pins LOW, PWM 0)."""
        if not self._connected:
            return
        self.set_speeds(0.0, 0.0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _set_motor(
        speed: float,
        in_a: Optional[object],
        in_b: Optional[object],
        enable: Optional[object],
    ) -> None:
        """Apply *speed* to a single motor channel.

        ``speed`` is clamped to ``[-1.0, 1.0]``.
        """
        if in_a is None or in_b is None or enable is None:
            return

        speed = max(-1.0, min(1.0, speed))

        if speed > 0:
            in_a.on()
            in_b.off()
        elif speed < 0:
            in_a.off()
            in_b.on()
        else:
            in_a.off()
            in_b.off()

        enable.value = abs(speed)
