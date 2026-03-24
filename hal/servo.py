"""Servo HAL — pigpio-based jitter-free PWM for SG90 / MG995 servos.

Uses the pigpio daemon for hardware-timed PWM on any GPIO pin.
Falls back to gpiozero software PWM if pigpiod is unavailable.

Implements the :class:`~hal.base.Actuator` interface with state type
``dict`` containing ``{"angle_deg": float}``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from hal.base import Actuator
from monitoring.health import ComponentStatus, HealthMonitor

logger = logging.getLogger(__name__)


class ServoInterface(Actuator[Dict[str, float]]):
    """Abstract servo interface."""

    def get_angle(self) -> float:
        """Return current servo angle in degrees."""
        raise NotImplementedError

    def set_angle(self, angle_deg: float) -> None:
        """Set servo to an absolute angle (clamped to safe limits)."""
        self.set_state({"angle_deg": angle_deg})


class PigpioServo(ServoInterface):
    """Hardware-timed servo using pigpio daemon.

    Parameters
    ----------
    pin:
        BCM GPIO pin number.
    min_pulse_us:
        Minimum pulse width in microseconds (fully counter-clockwise).
    max_pulse_us:
        Maximum pulse width in microseconds (fully clockwise).
    min_angle_deg:
        Software lower limit in degrees.
    max_angle_deg:
        Software upper limit in degrees.
    default_angle_deg:
        Angle to set on open().
    health_monitor:
        Optional health monitor for heartbeat reporting.
    """

    def __init__(
        self,
        pin: int,
        min_pulse_us: int = 500,
        max_pulse_us: int = 2500,
        min_angle_deg: float = 0.0,
        max_angle_deg: float = 180.0,
        default_angle_deg: float = 90.0,
        name: str = "servo",
        health_monitor: Optional[HealthMonitor] = None,
    ) -> None:
        self._pin = pin
        self._min_pulse = min_pulse_us
        self._max_pulse = max_pulse_us
        self._min_angle = min_angle_deg
        self._max_angle = max_angle_deg
        self._default_angle = default_angle_deg
        self._name = name
        self._health = health_monitor
        self._pi = None
        self._current_angle: float = default_angle_deg

    def open(self) -> None:
        try:
            import pigpio  # type: ignore
            self._pi = pigpio.pi()
            if not self._pi.connected:
                raise RuntimeError("pigpiod not running — start with: sudo systemctl start pigpiod")
            self._pi.set_mode(self._pin, pigpio.OUTPUT)
            self.set_angle(self._default_angle)
            logger.info("PigpioServo '%s' opened on pin %d (range %d-%d us)",
                        self._name, self._pin, self._min_pulse, self._max_pulse)
        except Exception as e:
            logger.error("PigpioServo '%s' init failed: %s", self._name, e)
            if self._health:
                self._health.heartbeat(self._name, ComponentStatus.ERROR)
            raise

    def close(self) -> None:
        if self._pi is not None:
            try:
                self._pi.set_servo_pulsewidth(self._pin, 0)
                self._pi.stop()
            except Exception:
                pass
            self._pi = None
        logger.info("PigpioServo '%s' closed.", self._name)

    def set_state(self, state: Dict[str, float]) -> None:
        angle = state.get("angle_deg", self._current_angle)
        angle = max(self._min_angle, min(self._max_angle, angle))

        pulse_range = self._max_pulse - self._min_pulse
        angle_range = self._max_angle - self._min_angle
        if angle_range <= 0:
            pulse_us = self._min_pulse
        else:
            pulse_us = self._min_pulse + int((angle - self._min_angle) / angle_range * pulse_range)

        try:
            if self._pi is None:
                raise RuntimeError("Servo not opened")
            self._pi.set_servo_pulsewidth(self._pin, pulse_us)
            self._current_angle = angle
            if self._health:
                self._health.heartbeat(self._name, ComponentStatus.OK)
        except Exception as e:
            logger.error("PigpioServo '%s' set_state failed: %s — going to neutral", self._name, e)
            self._emergency_neutral()
            if self._health:
                self._health.heartbeat(self._name, ComponentStatus.ERROR)

    def get_angle(self) -> float:
        return self._current_angle

    def _emergency_neutral(self) -> None:
        """Attempt to send servo to neutral on error."""
        try:
            if self._pi is not None:
                mid_pulse = (self._min_pulse + self._max_pulse) // 2
                self._pi.set_servo_pulsewidth(self._pin, mid_pulse)
        except Exception:
            pass


class GpiozeroServo(ServoInterface):
    """Software-PWM fallback using gpiozero (higher jitter than pigpio)."""

    def __init__(
        self,
        pin: int,
        min_angle_deg: float = 0.0,
        max_angle_deg: float = 180.0,
        default_angle_deg: float = 90.0,
        name: str = "servo",
        health_monitor: Optional[HealthMonitor] = None,
    ) -> None:
        self._pin = pin
        self._min_angle = min_angle_deg
        self._max_angle = max_angle_deg
        self._default_angle = default_angle_deg
        self._name = name
        self._health = health_monitor
        self._servo = None
        self._current_angle: float = default_angle_deg

    def open(self) -> None:
        try:
            from gpiozero import Servo  # type: ignore
            self._servo = Servo(self._pin)
            self.set_angle(self._default_angle)
            logger.info("GpiozeroServo '%s' opened on pin %d (software PWM)", self._name, self._pin)
        except Exception as e:
            logger.error("GpiozeroServo '%s' init failed: %s", self._name, e)
            if self._health:
                self._health.heartbeat(self._name, ComponentStatus.ERROR)
            raise

    def close(self) -> None:
        if self._servo is not None:
            try:
                self._servo.close()
            except Exception:
                pass
            self._servo = None

    def set_state(self, state: Dict[str, float]) -> None:
        angle = state.get("angle_deg", self._current_angle)
        angle = max(self._min_angle, min(self._max_angle, angle))

        angle_range = self._max_angle - self._min_angle
        if angle_range <= 0:
            value = 0.0
        else:
            value = (angle - self._min_angle) / angle_range * 2.0 - 1.0

        try:
            if self._servo is None:
                raise RuntimeError("Servo not opened")
            self._servo.value = max(-1.0, min(1.0, value))
            self._current_angle = angle
            if self._health:
                self._health.heartbeat(self._name, ComponentStatus.OK)
        except Exception as e:
            logger.error("GpiozeroServo '%s' failed: %s", self._name, e)
            if self._health:
                self._health.heartbeat(self._name, ComponentStatus.ERROR)

    def get_angle(self) -> float:
        return self._current_angle


class MockServo(ServoInterface):
    """Mock servo for testing without hardware."""

    def __init__(
        self,
        name: str = "servo",
        health_monitor: Optional[HealthMonitor] = None,
        **kwargs: Any,
    ) -> None:
        self._name = name
        self._health = health_monitor
        self._current_angle: float = kwargs.get("default_angle_deg", 90.0)

    def open(self) -> None:
        logger.info("MockServo '%s' opened.", self._name)

    def close(self) -> None:
        logger.info("MockServo '%s' closed.", self._name)

    def set_state(self, state: Dict[str, float]) -> None:
        self._current_angle = state.get("angle_deg", self._current_angle)
        if self._health:
            self._health.heartbeat(self._name, ComponentStatus.OK)

    def get_angle(self) -> float:
        return self._current_angle
