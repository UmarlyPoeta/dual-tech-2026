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


class FakeMotorActuator:
    """Minimal Actuator stub for UGVController tests.

    Records the last state applied via set_state() so tests can inspect it
    without needing real GPIO hardware.
    """

    def __init__(self) -> None:
        self._last_state: dict = {}
        self._connected = False

    def open(self) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def set_state(self, state: dict) -> None:
        self._last_state = dict(state)

    @property
    def is_connected(self) -> bool:
        return self._connected


class TestUGVController:
    """Unit tests for UGVController using a stub motor actuator."""

    @pytest.fixture()
    def fake_driver(self) -> FakeMotorActuator:
        return FakeMotorActuator()

    @pytest.fixture()
    def controller(self, fake_driver: FakeMotorActuator):
        from controllers.ugv.ugv_controller import UGVController

        cfg = {
            "max_linear_speed_mps": 0.3,
            "max_angular_speed_radps": 0.5,
        }
        pose_estimator = MagicMock()
        ctrl = UGVController(
            config=cfg,
            pose_estimator=pose_estimator,
            motor_driver=fake_driver,
        )
        ctrl.connect()
        return ctrl

    def test_precheck_after_connect(self, controller) -> None:
        controller.precheck()  # should not raise

    def test_precheck_without_driver(self) -> None:
        """precheck() should run silently even without a motor driver."""
        from controllers.ugv.ugv_controller import UGVController

        ctrl = UGVController(config={}, pose_estimator=MagicMock())
        ctrl.precheck()  # no driver → no raise, just logs

    def test_set_velocity_forward(self, controller, fake_driver: FakeMotorActuator) -> None:
        controller.set_velocity(linear=0.3, angular=0.0)
        state = fake_driver._last_state
        assert state["left"] > 0
        assert state["right"] > 0
        assert state["left"] == pytest.approx(1.0, abs=1e-6)
        assert state["right"] == pytest.approx(1.0, abs=1e-6)

    def test_set_velocity_reverse(self, controller, fake_driver: FakeMotorActuator) -> None:
        controller.set_velocity(linear=-0.3, angular=0.0)
        state = fake_driver._last_state
        assert state["left"] < 0
        assert state["right"] < 0

    def test_set_velocity_turn(self, controller, fake_driver: FakeMotorActuator) -> None:
        """Positive angular should produce left > right (left turn)."""
        controller.set_velocity(linear=0.0, angular=0.5)
        state = fake_driver._last_state
        assert state["left"] > state["right"]

    def test_set_velocity_stop(self, controller, fake_driver: FakeMotorActuator) -> None:
        controller.set_velocity(linear=0.3, angular=0.0)
        controller.stop()
        state = fake_driver._last_state
        assert state["left"] == 0.0
        assert state["right"] == 0.0

    def test_driver_connected_after_connect(self, controller, fake_driver: FakeMotorActuator) -> None:
        assert fake_driver.is_connected is True

    def test_disconnect(self, controller, fake_driver: FakeMotorActuator) -> None:
        controller.disconnect()
        assert fake_driver.is_connected is False

    def test_no_driver_stop_is_noop(self) -> None:
        """stop() with no driver should not raise."""
        from controllers.ugv.ugv_controller import UGVController

        ctrl = UGVController(config={}, pose_estimator=MagicMock())
        ctrl.stop()  # _driver is None → no-op

    def test_load_waypoints(self, controller) -> None:
        wps = [(50.0, 20.0), (50.001, 20.001)]
        controller.load_waypoints(wps)
        assert controller._waypoints == wps
        assert controller._wp_index == 0
