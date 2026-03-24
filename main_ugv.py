#!/usr/bin/env python3
"""Entry point for the UGV (ground vehicle) competition mission."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path when running directly
sys.path.insert(0, str(Path(__file__).parent))

from config_loader import load_config
from controllers.ugv.ugv_controller import UGVController
from controllers.ugv.arm_controller import ArmController
from hal.factory import create_camera, create_gps, create_motors, create_servo, create_stepper
from localization.pose import PoseEstimator
from logging_module.logger import DataLogger
from mission.mission_manager import MissionManager
from mission.target_registry import TargetRegistry
from monitoring.health import HealthMonitor, SystemWatchdog
from networking.heartbeat import HeartbeatMonitor
from networking.foxglove_bridge import FoxgloveBridge
from networking.video_streamer import VideoStreamer
from perception.detector import ObjectDetector
from perception.fusion import PerceptionFusion
from perception.qr_reader import QrReader
from web_gui.operator_panel import OperatorPanel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main_ugv")


def main() -> None:
    cfg = load_config("ugv")

    mission_cfg = cfg.get("mission", {})
    ugv_cfg = cfg.get("ugv", {})
    hal_cfg = cfg.get("hal", {})
    mon_cfg = cfg.get("monitoring", {})
    log_cfg = cfg.get("logging", {})
    stream_cfg = cfg.get("streaming", {})
    hb_cfg = cfg.get("heartbeat", {})
    gui_cfg = cfg.get("web_gui", {})
    foxglove_cfg = cfg.get("foxglove", {})
    _classes_raw = cfg.get("classes") or {}
    if "classes" in _classes_raw:          # nowy zagnieżdżony format
        _classes_raw = _classes_raw["classes"]
    class_map: dict[int, str] = {int(k): v for k, v in _classes_raw.items()}
    target_classes: list[str] = cfg.get("target_classes") or []
    transport_classes: list[str] = cfg.get("transport_classes") or []

    model_path = Path("models/best.pt")

    # --- Health & Watchdog ---
    health = HealthMonitor()
    pose_estimator = PoseEstimator()

    # --- Hardware instantiation via HAL ---
    camera = create_camera(hal_cfg.get("camera", {}), health=health)
    gps_reader = create_gps(hal_cfg.get("gps", {}), health=health, on_pose=pose_estimator.update_pose)
    motors = create_motors(hal_cfg.get("motors", {}), ugv_cfg, health=health)

    detector = ObjectDetector(
        model_path=model_path,
        class_map=class_map,
        confidence_threshold=mission_cfg.get("classify_confidence", 0.6),
    )
    qr_reader = QrReader()
    fusion = PerceptionFusion()

    gps_reader.start()

    with DataLogger(log_cfg, platform="ugv") as data_logger:
        registry = TargetRegistry(
            revisit_radius_m=mission_cfg.get("revisit_radius_m_ugv", 2.0),
            platform="ugv",
        )

        controller = UGVController(
            config=ugv_cfg,
            pose_estimator=pose_estimator,
            motor_driver=motors,
            camera_get_frame=camera.get_data,
        )
        controller.connect()

        # --- Watchdog ---
        watchdog = SystemWatchdog(
            health_monitor=health,
            critical_components=mon_cfg.get("critical_components", ["camera", "gps", "mission"]),
            timeout_s=mon_cfg.get("timeout_s", 5.0),
            on_failure=lambda comp, status: controller.emergency_stop()
        )
        watchdog.start()

        # Load search waypoints if available
        wp_file = Path(ugv_cfg.get("search_waypoints_file", "config/ugv_search_waypoints.txt"))
        if wp_file.exists():
            waypoints = []
            with open(wp_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        lat_s, lon_s = line.split(",")
                        waypoints.append((float(lat_s), float(lon_s)))
            controller.load_waypoints(waypoints)

        camera.open()
        detector.load()

        # --- FPV video stream (replaces VNC) ---
        streamer = None
        if stream_cfg.get("enabled", True):
            streamer = VideoStreamer(
                get_frame=camera.get_data,
                port=stream_cfg.get("port", 5000),
                quality=stream_cfg.get("jpeg_quality", 50),
                max_fps=stream_cfg.get("max_fps", 15),
            )
            streamer.start()

        # --- Operator heartbeat ---
        heartbeat = None
        if hb_cfg.get("enabled", True):
            heartbeat = HeartbeatMonitor(
                port=hb_cfg.get("port", 5001),
                timeout_s=hb_cfg.get("timeout_s", 5.0),
                on_timeout=controller.emergency_stop,
            )
            heartbeat.start()

        # --- Arm controller (servo + stepper) ---
        arm = None
        hw_params = cfg.get("hardware", {}).get("params", {}) or {}
        if hw_params:
            servos_cfg = hw_params.get("servos", {})
            steppers_cfg = hw_params.get("steppers", {})
            try:
                cam_servo = create_servo(servos_cfg.get("camera_tilt", {"mode": "mock"}), health=health) if "camera_tilt" in servos_cfg else None
                wrist_servo = create_servo(servos_cfg.get("arm_wrist", {"mode": "mock"}), health=health) if "arm_wrist" in servos_cfg else None
                grip_servo = create_servo(servos_cfg.get("gripper", {"mode": "mock"}), health=health) if "gripper" in servos_cfg else None
                arm_stepper = create_stepper(steppers_cfg.get("arm_linear", {"mode": "mock"}), health=health) if "arm_linear" in steppers_cfg else None
                arm = ArmController(
                    arm_stepper=arm_stepper,
                    wrist_servo=wrist_servo,
                    camera_servo=cam_servo,
                    grip_servo=grip_servo,
                )
                arm.connect()
                logger.info("Arm controller initialized.")
            except Exception:
                logger.warning("Arm controller init failed — running without arm.", exc_info=True)
                arm = None

        # --- Foxglove bridge ---
        foxglove = None
        if foxglove_cfg.get("enabled", False):
            def _get_jpeg() -> bytes | None:
                frame = camera.get_data()
                if frame is None:
                    return None
                import cv2
                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
                return buf.tobytes()

            foxglove = FoxgloveBridge(
                port=foxglove_cfg.get("port", 8765),
                get_telemetry=lambda: {
                    "lat": (p := pose_estimator.get_pose()) and p.lat,
                    "lon": p and p.lon,
                    "alt": p and p.alt,
                    "yaw_deg": p and p.yaw_deg,
                    "state": (manager_ref[0].state_name if manager_ref[0] else "INIT"),
                    "target_count": registry.count(),
                },
                get_health=lambda: {
                    "components": {k: v.value for k, v in health.get_all_statuses().items()},
                },
                get_frame_jpeg=_get_jpeg,
                telemetry_hz=foxglove_cfg.get("telemetry_hz", 2.0),
                health_hz=foxglove_cfg.get("health_hz", 1.0),
                camera_hz=foxglove_cfg.get("camera_hz", 5.0),
            )
            foxglove.start()
            logger.info("Foxglove bridge started on port %d", foxglove_cfg.get("port", 8765))

        # --- Command handler for WebGUI ---
        manager_ref = [None]  # mutable ref for closure

        def _handle_command(cmd: str, args: dict) -> dict:
            max_lin = ugv_cfg.get("max_linear_speed_mps", 0.3)
            max_ang = ugv_cfg.get("max_angular_speed_radps", 0.5)
            if cmd == "move_forward":
                controller.set_velocity(max_lin, 0.0)
            elif cmd == "move_backward":
                controller.set_velocity(-max_lin, 0.0)
            elif cmd == "turn_left":
                controller.set_velocity(0.0, max_ang)
            elif cmd == "turn_right":
                controller.set_velocity(0.0, -max_ang)
            elif cmd == "stop":
                controller.stop()
            elif cmd == "emergency_stop":
                controller.emergency_stop()
            elif cmd == "return_home":
                controller.return_home()
            elif cmd == "gripper_open":
                controller.gripper.open()
            elif cmd == "gripper_close":
                controller.gripper.close()
            elif cmd == "gripper_toggle":
                controller.gripper.toggle()
            elif cmd == "start_mission":
                controller.start_search()
            elif cmd.startswith("arm_") or cmd.startswith("wrist_") or cmd.startswith("camera_") or cmd.startswith("grip_"):
                if arm is not None:
                    return arm.handle_command(cmd, args)
                return {"ok": False, "error": "Arm controller not available"}
            else:
                return {"ok": False, "error": f"Unknown command: {cmd}"}
            return {"ok": True, "cmd": cmd}

        def _get_telemetry() -> dict:
            pose = pose_estimator.get_pose()
            mgr = manager_ref[0]
            return {
                "lat": pose.lat if pose else None,
                "lon": pose.lon if pose else None,
                "alt": pose.alt if pose else None,
                "yaw_deg": pose.yaw_deg if pose else None,
                "state": mgr.state_name if mgr else "INIT",
                "target_count": registry.count(),
                "gripper_open": controller.gripper.is_open,
            }

        def _get_targets() -> list:
            return [
                {
                    "target_id": r.target_id,
                    "class_name": r.class_name,
                    "qr_value": r.qr_value,
                    "lat": r.lat,
                    "lon": r.lon,
                    "transported": r.transported,
                }
                for r in registry.all_records()
            ]

        # --- Web GUI ---
        gui = None
        if gui_cfg.get("enabled", True):
            gui = OperatorPanel(
                port=gui_cfg.get("port", 8080),
                platform="ugv",
                stream_port=stream_cfg.get("port", 5000),
                on_command=_handle_command,
                get_telemetry=_get_telemetry,
                get_targets=_get_targets,
            )
            gui.start()

        mgr = MissionManager(
            config=mission_cfg,
            detector=detector,
            qr_reader=qr_reader,
            fusion=fusion,
            pose_estimator=pose_estimator,
            registry=registry,
            motion=controller,
            data_logger=data_logger,
            health_monitor=health,
            target_classes=target_classes,
            transport_classes=transport_classes,
            enable_transport=True,
        )
        manager_ref[0] = mgr

        try:
            mgr.run(get_frame=camera.get_data)
        finally:
            watchdog.stop()
            if gui is not None:
                gui.stop()
            if foxglove is not None:
                foxglove.stop()
            if streamer is not None:
                streamer.stop()
            if heartbeat is not None:
                heartbeat.stop()
            if arm is not None:
                arm.disconnect()
            camera.close()
            motors.close()
            controller.disconnect()
            gps_reader.stop()

    logger.info("UGV mission finished. %d targets logged.", registry.count())


if __name__ == "__main__":
    main()
