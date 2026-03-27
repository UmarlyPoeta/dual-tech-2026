"""GPIO HAL — Abstraction for real and mock GPIO control."""

from __future__ import annotations

import logging
from typing import Dict, Optional

from hal.base import Actuator
from monitoring.health import ComponentStatus, HealthMonitor

logger = logging.getLogger(__name__)


class GpioInterface(Actuator[Dict[str, float]]):
    """Generic interface for GPIO-based actuators (motors, servos)."""
    pass


class RealGpioMotor(GpioInterface):
    """L298N motor driver using real GPIO (gpiozero)."""

    def __init__(
        self,
        pins: Dict[str, int],
        pwm_frequency: int = 1000,
        health_monitor: Optional[HealthMonitor] = None,
    ) -> None:
        self._pins = pins
        self._pwm_freq = pwm_frequency
        self._health = health_monitor
        self._devices = {}

    def open(self) -> None:
        try:
            from gpiozero import DigitalOutputDevice, PWMOutputDevice
            self._devices["left_in1"] = DigitalOutputDevice(self._pins["left_in1"])
            self._devices["left_in2"] = DigitalOutputDevice(self._pins["left_in2"])
            self._devices["left_ena"] = PWMOutputDevice(self._pins["left_ena"], frequency=self._pwm_freq)
            self._devices["right_in3"] = DigitalOutputDevice(self._pins["right_in3"])
            self._devices["right_in4"] = DigitalOutputDevice(self._pins["right_in4"])
            self._devices["right_enb"] = PWMOutputDevice(self._pins["right_enb"], frequency=self._pwm_freq)
            logger.info("GPIO: RealGpioMotor initialized (pins=%s)", self._pins)
            if self._health:
                self._health.heartbeat("motors", ComponentStatus.OK)
        except Exception as e:
            logger.error("GPIO: Failed to init real motor: %s", e)
            if self._health:
                self._health.heartbeat("motors", ComponentStatus.ERROR)
            raise

    def close(self) -> None:
        for dev in self._devices.values():
            dev.close()
        self._devices.clear()

    def set_state(self, state: Dict[str, float]) -> None:
        """state example: {'left': 0.5, 'right': -0.5}"""
        left = state.get("left", 0.0)
        right = state.get("right", 0.0)
        
        self._drive_motor(left, self._devices["left_in1"], self._devices["left_in2"], self._devices["left_ena"])
        self._drive_motor(right, self._devices["right_in3"], self._devices["right_in4"], self._devices["right_enb"])
        
        if self._health:
            self._health.heartbeat("motors", ComponentStatus.OK)

    def _drive_motor(self, speed, in1, in2, ena):
        speed = max(-1.0, min(1.0, speed))
        if speed > 0:
            in1.on(); in2.off()
        elif speed < 0:
            in1.off(); in2.on()
        else:
            in1.off(); in2.off()
        ena.value = abs(speed)


class MockGpioMotor(GpioInterface):
    """Mock motor driver that just logs commands."""

    def __init__(self, health_monitor: Optional[HealthMonitor] = None) -> None:
        self._health = health_monitor

    def open(self) -> None:
        logger.info("GPIO: MockGpioMotor initialized")
        if self._health:
            self._health.heartbeat("motors", ComponentStatus.OK)

    def close(self) -> None:
        pass

    def set_state(self, state: Dict[str, float]) -> None:
        # logger.debug("GPIO: Mock Motor State: %s", state)
        if self._health:
            self._health.heartbeat("motors", ComponentStatus.OK)
