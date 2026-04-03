"""Tests for ArmController using MockServo and MockStepper."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from controllers.ugv.arm_controller import ArmController
from hal.servo import MockServo
from hal.stepper import MockStepper


# ===================================================================
# Helpers
# ===================================================================


def _make_arm(
    has_stepper: bool = True,
    has_wrist: bool = True,
    has_camera: bool = True,
    has_grip: bool = True,
) -> tuple[ArmController, MockStepper | None, MockServo | None, MockServo | None, MockServo | None]:
    stepper = MockStepper(name="arm") if has_stepper else None
    wrist = MockServo(name="wrist") if has_wrist else None
    camera = MockServo(name="camera") if has_camera else None
    grip = MockServo(name="grip") if has_grip else None
    arm = ArmController(
        arm_stepper=stepper,
        wrist_servo=wrist,
        camera_servo=camera,
        grip_servo=grip,
    )
    return arm, stepper, wrist, camera, grip


# ===================================================================
# Lifecycle tests
# ===================================================================


class TestArmControllerLifecycle:
    def test_not_connected_before_connect(self):
        arm, *_ = _make_arm()
        assert arm.is_connected is False

    def test_connect_sets_connected(self):
        arm, *_ = _make_arm()
        arm.connect()
        assert arm.is_connected is True

    def test_disconnect_clears_connected(self):
        arm, *_ = _make_arm()
        arm.connect()
        arm.disconnect()
        assert arm.is_connected is False

    def test_connect_no_actuators(self):
        arm = ArmController()
        arm.connect()
        assert arm.is_connected is True

    def test_connect_failure_propagates(self):
        bad_stepper = MagicMock()
        bad_stepper.open.side_effect = RuntimeError("GPIO error")
        arm = ArmController(arm_stepper=bad_stepper)
        with pytest.raises(RuntimeError, match="GPIO error"):
            arm.connect()

    def test_emergency_stop_called_on_connect_failure(self):
        bad_stepper = MagicMock()
        bad_stepper.open.side_effect = RuntimeError("fail")
        arm = ArmController(arm_stepper=bad_stepper)
        try:
            arm.connect()
        except RuntimeError:
            pass
        bad_stepper.stop_motor.assert_called()


# ===================================================================
# Arm extension (stepper)
# ===================================================================


class TestArmStepper:
    @pytest.fixture()
    def arm(self):
        a, *_ = _make_arm()
        a.connect()
        return a

    def test_arm_extend_moves_to_position(self, arm: ArmController):
        arm.arm_extend(500)
        assert arm._stepper.get_position() == 500

    def test_arm_home_returns_to_zero(self, arm: ArmController):
        arm.arm_extend(300)
        arm.arm_home()
        assert arm._stepper.get_position() == 0

    def test_arm_up_relative(self, arm: ArmController):
        arm.arm_extend(100)
        arm.arm_up(50)
        assert arm._stepper.get_position() == 150

    def test_arm_down_relative(self, arm: ArmController):
        arm.arm_extend(200)
        arm.arm_down(80)
        assert arm._stepper.get_position() == 120

    def test_arm_extend_no_stepper(self):
        arm = ArmController()
        arm.connect()
        arm.arm_extend(100)  # no-op, no raise

    def test_arm_up_no_stepper(self):
        arm = ArmController()
        arm.connect()
        arm.arm_up()  # no-op

    def test_arm_down_no_stepper(self):
        arm = ArmController()
        arm.connect()
        arm.arm_down()  # no-op


# ===================================================================
# Wrist servo
# ===================================================================


class TestArmWrist:
    @pytest.fixture()
    def arm(self):
        a, *_ = _make_arm()
        a.connect()
        return a

    def test_wrist_set_angle(self, arm: ArmController):
        arm.wrist_set_angle(45.0)
        assert arm._wrist.get_angle() == pytest.approx(45.0)

    def test_wrist_rotate_adds_to_current(self, arm: ArmController):
        arm.wrist_set_angle(90.0)
        arm.wrist_rotate(15.0)
        assert arm._wrist.get_angle() == pytest.approx(105.0)

    def test_wrist_rotate_negative(self, arm: ArmController):
        arm.wrist_set_angle(90.0)
        arm.wrist_rotate(-20.0)
        assert arm._wrist.get_angle() == pytest.approx(70.0)

    def test_wrist_no_servo_is_noop(self):
        arm = ArmController()
        arm.connect()
        arm.wrist_set_angle(45.0)  # no-op

    def test_wrist_rotate_no_servo_is_noop(self):
        arm = ArmController()
        arm.connect()
        arm.wrist_rotate(10)  # no-op


# ===================================================================
# Camera tilt servo
# ===================================================================


class TestArmCamera:
    @pytest.fixture()
    def arm(self):
        a, *_ = _make_arm()
        a.connect()
        return a

    def test_camera_tilt_angle(self, arm: ArmController):
        arm.camera_tilt(45.0)
        assert arm._camera.get_angle() == pytest.approx(45.0)

    def test_camera_look_down(self, arm: ArmController):
        arm.camera_look_down()
        assert arm._camera.get_angle() == pytest.approx(0.0)

    def test_camera_look_forward(self, arm: ArmController):
        arm.camera_look_forward()
        assert arm._camera.get_angle() == pytest.approx(90.0)

    def test_camera_tilt_no_servo_is_noop(self):
        arm = ArmController()
        arm.connect()
        arm.camera_tilt(45.0)  # no-op


# ===================================================================
# Gripper (via servo)
# ===================================================================


class TestArmGrip:
    @pytest.fixture()
    def arm(self):
        a, *_ = _make_arm()
        a.connect()
        return a

    def test_grip_open_sets_zero(self, arm: ArmController):
        arm.grip_close()
        arm.grip_open()
        assert arm._grip.get_angle() == pytest.approx(0.0)

    def test_grip_close_sets_180(self, arm: ArmController):
        arm.grip_close()
        assert arm._grip.get_angle() == pytest.approx(180.0)

    def test_grip_no_servo_is_noop(self):
        arm = ArmController()
        arm.connect()
        arm.grip_open()
        arm.grip_close()  # no-op


# ===================================================================
# Command dispatch
# ===================================================================


class TestArmCommandDispatch:
    @pytest.fixture()
    def arm(self):
        a, *_ = _make_arm()
        a.connect()
        return a

    @pytest.mark.parametrize("cmd,args,expected_angle", [
        ("camera_down", {}, 0.0),
        ("camera_forward", {}, 90.0),
        ("wrist_set", {"angle": 45.0}, 45.0),
        ("camera_tilt", {"angle": 30.0}, 30.0),
    ])
    def test_servo_commands(self, arm, cmd, args, expected_angle):
        result = arm.handle_command(cmd, args)
        assert result["ok"] is True

    def test_arm_up_command(self, arm):
        arm.arm_extend(0)
        result = arm.handle_command("arm_up", {"steps": 100})
        assert result["ok"] is True
        assert arm._stepper.get_position() == 100

    def test_arm_down_command(self, arm):
        arm.arm_extend(200)
        result = arm.handle_command("arm_down", {"steps": 50})
        assert result["ok"] is True
        assert arm._stepper.get_position() == 150

    def test_arm_home_command(self, arm):
        arm.arm_extend(400)
        result = arm.handle_command("arm_home", {})
        assert result["ok"] is True
        assert arm._stepper.get_position() == 0

    def test_grip_open_command(self, arm):
        result = arm.handle_command("grip_open", {})
        assert result["ok"] is True

    def test_grip_close_command(self, arm):
        result = arm.handle_command("grip_close", {})
        assert result["ok"] is True

    def test_wrist_left_command(self, arm):
        arm.wrist_set_angle(90.0)
        arm.handle_command("wrist_left", {})
        assert arm._wrist.get_angle() == pytest.approx(80.0)

    def test_wrist_right_command(self, arm):
        arm.wrist_set_angle(90.0)
        arm.handle_command("wrist_right", {})
        assert arm._wrist.get_angle() == pytest.approx(100.0)

    def test_arm_stop_command(self, arm):
        result = arm.handle_command("arm_stop", {})
        assert result["ok"] is True

    def test_unknown_command_returns_error(self, arm):
        result = arm.handle_command("fly_away", {})
        assert result["ok"] is False
        assert "Unknown arm command" in result["error"]


# ===================================================================
# Telemetry
# ===================================================================


class TestArmTelemetry:
    def test_telemetry_with_all_actuators(self):
        arm, stepper, wrist, camera, _ = _make_arm(has_grip=False)
        arm.connect()
        arm.arm_extend(100)
        arm.wrist_set_angle(45.0)
        arm.camera_tilt(30.0)
        telem = arm.get_telemetry()
        assert telem["arm_position"] == 100
        assert telem["wrist_angle"] == pytest.approx(45.0)
        assert telem["camera_angle"] == pytest.approx(30.0)
        assert telem["arm_moving"] is False

    def test_telemetry_without_actuators(self):
        arm = ArmController()
        arm.connect()
        telem = arm.get_telemetry()
        assert telem["arm_position"] == 0
        assert telem["wrist_angle"] == 0.0
        assert telem["camera_angle"] == 0.0
