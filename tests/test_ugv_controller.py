"""Tests for L298NDriver and UGVController GPIO-based motor control."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Mock gpiozero before importing the driver (no real GPIO on CI)
# ---------------------------------------------------------------------------

class FakeDigitalOutputDevice:
    """Minimal stand-in for gpiozero.DigitalOutputDevice."""

    def __init__(self, pin: int) -> None:
        self.pin = pin
        self._value = False

    def on(self) -> None:
        self._value = True

    def off(self) -> None:
        self._value = False

    @property
    def value(self) -> bool:
        return self._value

    def close(self) -> None:
        self._value = False


class FakePWMOutputDevice:
    """Minimal stand-in for gpiozero.PWMOutputDevice."""

    def __init__(self, pin: int, frequency: int = 1000) -> None:
        self.pin = pin
        self.frequency = frequency
        self._value = 0.0

    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, v: float) -> None:
        self._value = max(0.0, min(1.0, v))

    def close(self) -> None:
        self._value = 0.0


_fake_gpiozero = MagicMock()
_fake_gpiozero.DigitalOutputDevice = FakeDigitalOutputDevice
_fake_gpiozero.PWMOutputDevice = FakePWMOutputDevice
sys.modules.setdefault("gpiozero", _fake_gpiozero)

from controllers.ugv.l298n_driver import L298NDriver  # noqa: E402


# ===================================================================
# L298NDriver tests
# ===================================================================


class TestL298NDriver:
    """Unit tests for the L298N GPIO motor driver."""

    @pytest.fixture()
    def driver(self) -> L298NDriver:
        drv = L298NDriver(
            left_in1=17, left_in2=27, left_ena=18,
            right_in3=22, right_in4=23, right_enb=13,
        )
        drv.connect()
        return drv

    def test_connect_sets_connected(self, driver: L298NDriver) -> None:
        assert driver.is_connected is True

    def test_disconnect_clears_flag(self, driver: L298NDriver) -> None:
        driver.disconnect()
        assert driver.is_connected is False

    def test_stop_sets_zero(self, driver: L298NDriver) -> None:
        driver.set_speeds(0.8, -0.5)
        driver.stop()
        assert driver._left_ena.value == 0.0
        assert driver._right_enb.value == 0.0

    def test_forward(self, driver: L298NDriver) -> None:
        driver.set_speeds(0.7, 0.7)
        # Left motor forward: in1=HIGH, in2=LOW
        assert driver._left_in1.value is True
        assert driver._left_in2.value is False
        assert abs(driver._left_ena.value - 0.7) < 1e-6
        # Right motor forward: in3=HIGH, in4=LOW
        assert driver._right_in3.value is True
        assert driver._right_in4.value is False
        assert abs(driver._right_enb.value - 0.7) < 1e-6

    def test_reverse(self, driver: L298NDriver) -> None:
        driver.set_speeds(-0.5, -0.5)
        # Left motor reverse: in1=LOW, in2=HIGH
        assert driver._left_in1.value is False
        assert driver._left_in2.value is True
        assert abs(driver._left_ena.value - 0.5) < 1e-6
        # Right motor reverse: in3=LOW, in4=HIGH
        assert driver._right_in3.value is False
        assert driver._right_in4.value is True
        assert abs(driver._right_enb.value - 0.5) < 1e-6

    def test_clamp_speed(self, driver: L298NDriver) -> None:
        driver.set_speeds(2.0, -2.0)
        assert driver._left_ena.value == 1.0
        assert driver._right_enb.value == 1.0

    def test_stop_on_disconnected_is_noop(self) -> None:
        drv = L298NDriver(
            left_in1=17, left_in2=27, left_ena=18,
            right_in3=22, right_in4=23, right_enb=13,
        )
        # Should not raise even though not connected
        drv.stop()


# ===================================================================
# UGVController tests (with mocked L298NDriver)
# ===================================================================


class TestUGVController:
    """Unit tests for UGVController using the GPIO-based driver."""

    @pytest.fixture()
    def controller(self):
        from controllers.ugv.ugv_controller import UGVController

        cfg = {
            "left_motor": {"in1": 17, "in2": 27, "ena": 18},
            "right_motor": {"in3": 22, "in4": 23, "enb": 13},
            "pwm_frequency_hz": 1000,
            "max_linear_speed_mps": 0.3,
            "max_angular_speed_radps": 0.5,
        }
        pose_estimator = MagicMock()
        ctrl = UGVController(config=cfg, pose_estimator=pose_estimator)
        ctrl.connect()
        return ctrl

    def test_precheck_after_connect(self, controller) -> None:
        controller.precheck()  # should not raise

    def test_precheck_before_connect_raises(self) -> None:
        from controllers.ugv.ugv_controller import UGVController

        cfg = {
            "left_motor": {"in1": 17, "in2": 27, "ena": 18},
            "right_motor": {"in3": 22, "in4": 23, "enb": 13},
        }
        ctrl = UGVController(config=cfg, pose_estimator=MagicMock())
        with pytest.raises(RuntimeError, match="GPIO driver not connected"):
            ctrl.precheck()

    def test_set_velocity_forward(self, controller) -> None:
        controller.set_velocity(linear=0.3, angular=0.0)
        # Both motors should be forward at full normalised speed
        assert controller._driver._left_ena.value > 0
        assert controller._driver._right_enb.value > 0
        assert controller._driver._left_in1.value is True
        assert controller._driver._right_in3.value is True

    def test_set_velocity_stop(self, controller) -> None:
        controller.set_velocity(linear=0.3, angular=0.0)
        controller.stop()
        assert controller._driver._left_ena.value == 0.0
        assert controller._driver._right_enb.value == 0.0

    def test_disconnect(self, controller) -> None:
        controller.disconnect()
        assert controller._driver.is_connected is False
