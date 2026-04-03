"""Tests for HAL mock implementations — MockServo and MockStepper."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hal.servo import MockServo, ServoInterface
from hal.stepper import MockStepper, StepperInterface
from monitoring.health import ComponentStatus, HealthMonitor


# ===================================================================
# MockServo
# ===================================================================


class TestMockServo:
    @pytest.fixture()
    def servo(self) -> MockServo:
        s = MockServo(name="test_servo", default_angle_deg=90.0)
        s.open()
        return s

    def test_default_angle(self, servo: MockServo):
        assert servo.get_angle() == pytest.approx(90.0)

    def test_set_angle(self, servo: MockServo):
        servo.set_angle(45.0)
        assert servo.get_angle() == pytest.approx(45.0)

    def test_set_state_dict(self, servo: MockServo):
        servo.set_state({"angle_deg": 120.0})
        assert servo.get_angle() == pytest.approx(120.0)

    def test_set_state_preserves_current_if_no_key(self, servo: MockServo):
        servo.set_angle(60.0)
        servo.set_state({})  # no angle_deg → keep current
        assert servo.get_angle() == pytest.approx(60.0)

    def test_open_close_no_raise(self, servo: MockServo):
        servo.close()  # should not raise

    def test_health_heartbeat_called(self):
        health = HealthMonitor()
        servo = MockServo(name="srv", health_monitor=health, default_angle_deg=90.0)
        servo.open()
        servo.set_angle(30.0)
        status = health.get_status("srv")
        assert status == ComponentStatus.OK

    def test_inherits_servo_interface(self):
        servo = MockServo()
        assert isinstance(servo, ServoInterface)


# ===================================================================
# MockStepper
# ===================================================================


class TestMockStepper:
    @pytest.fixture()
    def stepper(self) -> MockStepper:
        s = MockStepper(name="test_stepper", min_position=0, max_position=1000)
        s.open()
        return s

    def test_initial_position_zero(self, stepper: MockStepper):
        assert stepper.get_position() == 0

    def test_move_to_absolute(self, stepper: MockStepper):
        stepper.move_to(500)
        assert stepper.get_position() == 500

    def test_move_relative_positive(self, stepper: MockStepper):
        stepper.move_to(100)
        stepper.move_relative(50)
        assert stepper.get_position() == 150

    def test_move_relative_negative(self, stepper: MockStepper):
        stepper.move_to(200)
        stepper.move_relative(-80)
        assert stepper.get_position() == 120

    def test_position_clamped_to_max(self, stepper: MockStepper):
        stepper.move_to(9999)
        assert stepper.get_position() == 1000

    def test_position_clamped_to_min(self, stepper: MockStepper):
        stepper.move_to(-500)
        assert stepper.get_position() == 0

    def test_is_moving_returns_false(self, stepper: MockStepper):
        assert stepper.is_moving() is False

    def test_stop_motor_no_raise(self, stepper: MockStepper):
        stepper.stop_motor()  # no-op but must not raise

    def test_set_state_with_target_position(self, stepper: MockStepper):
        stepper.set_state({"target_position": 300})
        assert stepper.get_position() == 300

    def test_set_state_ignores_missing_key(self, stepper: MockStepper):
        stepper.move_to(200)
        stepper.set_state({})  # no target_position → no change
        assert stepper.get_position() == 200

    def test_open_close_no_raise(self, stepper: MockStepper):
        stepper.close()

    def test_health_heartbeat_called(self):
        health = HealthMonitor()
        st = MockStepper(name="stp", health_monitor=health)
        st.open()
        st.move_to(100)
        assert health.get_status("stp") == ComponentStatus.OK

    def test_inherits_stepper_interface(self):
        s = MockStepper()
        assert isinstance(s, StepperInterface)
