"""HAL Factory — Helper to instantiate hardware based on config."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from hal.camera import CameraInterface, RealCamera, MockCamera
from hal.gps import GpsInterface, RealGps, MockGps, ReplayGps
from hal.gpio import GpioInterface, RealGpioMotor, MockGpioMotor
from hal.servo import ServoInterface, PigpioServo, GpiozeroServo, MockServo
from hal.stepper import StepperInterface, GpiodStepper, MockStepper
from monitoring.health import HealthMonitor

logger = logging.getLogger(__name__)


def create_camera(cfg: Dict[str, Any], health: Optional[HealthMonitor] = None) -> CameraInterface:
    mode = cfg.get("mode", "real")
    if mode == "mock":
        return MockCamera(
            width=cfg.get("width", 640),
            height=cfg.get("height", 480),
            health_monitor=health
        )
    return RealCamera(
        source=cfg.get("source", 0),
        width=cfg.get("width", 640),
        height=cfg.get("height", 480),
        use_picamera=cfg.get("use_picamera"),
        health_monitor=health
    )


def create_gps(cfg: Dict[str, Any], health: Optional[HealthMonitor] = None, on_pose=None) -> GpsInterface:
    mode = cfg.get("mode", "real")
    if mode == "mock":
        return MockGps(on_pose=on_pose, health_monitor=health)
    if mode == "replay":
        return ReplayGps(log_file=cfg.get("log_file", "logs/gps.log"), on_pose=on_pose, health_monitor=health)
    return RealGps(
        port=cfg.get("port", "/dev/ttyAMA10"),
        baud_rate=cfg.get("baud", 38400),
        on_pose=on_pose,
        health_monitor=health
    )


def create_motors(cfg: Dict[str, Any], platform_cfg: Dict[str, Any], health: Optional[HealthMonitor] = None) -> GpioInterface:
    mode = cfg.get("mode", "real")
    if mode == "mock":
        return MockGpioMotor(health_monitor=health)
    
    # Extract pins from platform-specific UGV config
    left = platform_cfg.get("left_motor", {})
    right = platform_cfg.get("right_motor", {})
    pins = {
        "left_in1": left.get("in1", 17),
        "left_in2": left.get("in2", 27),
        "left_ena": left.get("ena", 18),
        "right_in3": right.get("in3", 22),
        "right_in4": right.get("in4", 23),
        "right_enb": right.get("enb", 13),
    }
    return RealGpioMotor(pins=pins, pwm_frequency=platform_cfg.get("pwm_frequency_hz", 1000), health_monitor=health)


def create_servo(cfg: Dict[str, Any], health: Optional[HealthMonitor] = None) -> ServoInterface:
    """Create a servo actuator (pigpio preferred, gpiozero fallback, mock for testing)."""
    mode = cfg.get("mode", "real")
    name = cfg.get("name", "servo")
    kwargs = {
        "pin": cfg.get("pin", 18),
        "min_pulse_us": cfg.get("min_pulse_us", 500),
        "max_pulse_us": cfg.get("max_pulse_us", 2500),
        "min_angle_deg": cfg.get("min_angle_deg", 0.0),
        "max_angle_deg": cfg.get("max_angle_deg", 180.0),
        "default_angle_deg": cfg.get("default_angle_deg", 90.0),
        "name": name,
        "health_monitor": health,
    }

    if mode == "mock":
        return MockServo(name=name, health_monitor=health, **kwargs)

    # Try pigpio first (hardware PWM), fall back to gpiozero when daemon is
    # unavailable (common on some Pi5 userspace/package combinations).
    try:
        import pigpio  # type: ignore

        probe = pigpio.pi()
        connected = bool(probe.connected)
        try:
            probe.stop()
        except Exception:
            pass

        if connected:
            servo = PigpioServo(**kwargs)
            logger.info("Using pigpio for servo '%s'", name)
            return servo
        logger.warning("pigpiod unavailable for servo '%s' — using gpiozero fallback", name)
    except Exception as exc:
        logger.warning("pigpio unavailable for servo '%s' (%s) — using gpiozero fallback", name, exc)

    return GpiozeroServo(
        pin=kwargs["pin"],
        min_angle_deg=kwargs["min_angle_deg"],
        max_angle_deg=kwargs["max_angle_deg"],
        default_angle_deg=kwargs["default_angle_deg"],
        name=name,
        health_monitor=health,
    )


def create_stepper(cfg: Dict[str, Any], health: Optional[HealthMonitor] = None) -> StepperInterface:
    """Create a stepper motor actuator (gpiod real driver or mock)."""
    mode = cfg.get("mode", "real")
    name = cfg.get("name", "stepper")

    if mode == "mock":
        return MockStepper(
            name=name,
            health_monitor=health,
            min_position=cfg.get("min_position", 0),
            max_position=cfg.get("max_position", 10000),
        )

    return GpiodStepper(
        step_pin=cfg.get("step_pin", 20),
        dir_pin=cfg.get("dir_pin", 21),
        enable_pin=cfg.get("enable_pin", -1),
        steps_per_rev=cfg.get("steps_per_rev", 200),
        max_speed_sps=cfg.get("max_speed_sps", 800),
        acceleration_sps2=cfg.get("acceleration_sps2", 2000),
        min_position=cfg.get("min_position", 0),
        max_position=cfg.get("max_position", 10000),
        gpiochip=cfg.get("gpiochip", "gpiochip4"),
        name=name,
        health_monitor=health,
    )
