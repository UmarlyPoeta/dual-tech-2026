"""HAL Factory — Helper to instantiate hardware based on config."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from hal.camera import CameraInterface, RealCamera, MockCamera
from hal.gps import GpsInterface, RealGps, MockGps, ReplayGps
from hal.gpio import GpioInterface, RealGpioMotor, MockGpioMotor
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
