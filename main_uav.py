#!/usr/bin/env python3
"""Entry point for the UAV (drone) competition mission."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path when running directly
sys.path.insert(0, str(Path(__file__).parent))

from config_loader import load_config
from controllers.uav.uav_controller import UAVController
from hal.factory import create_camera, create_gps
from localization.pose import PoseEstimator
from logging_module.logger import DataLogger
from mission.mission_manager import MissionManager
from mission.target_registry import TargetRegistry
from monitoring.health import HealthMonitor, SystemWatchdog
from networking.foxglove_bridge import FoxgloveBridge
from networking.heartbeat import HeartbeatMonitor
from networking.video_streamer import VideoStreamer
from perception.detector import ObjectDetector
from perception.fusion import PerceptionFusion
from perception.qr_reader import QrReader
from web_gui.operator_panel import OperatorPanel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main_uav")


def main() -> None:
    cfg = load_config("uav")

    mission_cfg = cfg.get("mission", {})
    uav_cfg = cfg.get("uav", {})
    hal_cfg = cfg.get("hal", {})
    mon_cfg = cfg.get("monitoring", {})
    log_cfg = cfg.get("logging", {})
    stream_cfg = cfg.get("streaming", {})
    hb_cfg = cfg.get("heartbeat", {})
    gui_cfg = cfg.get("web_gui", {})
    foxglove_cfg = cfg.get("foxglove", {})
    class_map: dict[int, str] = {int(k): v for k, v in (cfg.get("classes") or {}).items()}
    target_classes: list[str] = cfg.get("target_classes") or []
    transport_classes: list[str] = cfg.get("transport_classes") or []

    model_path = Path("models/best.pt")

    # --- Health & Watchdog ---
    health = HealthMonitor()
    pose_estimator = PoseEstimator()

    # --- Hardware instantiation via HAL ---
    camera = create_camera(hal_cfg.get("camera", {}), health=health)
    # UAV usually doesn't need external GPS reader if it's via MAVLink, 
    # but we'll instantiate it if config says so.
    gps_reader = None
    if "gps" in hal_cfg:
        gps_reader = create_gps(hal_cfg["gps"], health=health, on_pose=pose_estimator.update_pose)
        gps_reader.start()

    detector = ObjectDetector(
        model_path=model_path,
        class_map=class_map,
        confidence_threshold=mission_cfg.get("classify_confidence", 0.6),
    )
    qr_reader = QrReader()
    fusion = PerceptionFusion()

    with DataLogger(log_cfg, platform="uav") as data_logger:
        registry = TargetRegistry(
            revisit_radius_m=mission_cfg.get("revisit_radius_m_uav", 4.0),
            platform="uav",
        )

        controller = UAVController(
            config=uav_cfg,
            pose_estimator=pose_estimator,
            camera_get_frame=camera.get_data,
        )
        controller.connect()

        camera.open()
        detector.load()

        # --- Watchdog ---
        watchdog = SystemWatchdog(
            health_monitor=health,
            critical_components=mon_cfg.get("critical_components", ["camera", "mission"]),
            timeout_s=mon_cfg.get("timeout_s", 5.0),
            on_failure=lambda comp, status: controller.emergency_stop()
        )
        watchdog.start()

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
        manager_ref = [None]

        def _handle_command(cmd: str, args: dict) -> dict:
            max_speed = uav_cfg.get("max_xy_speed_mps", 0.4)
            max_z = uav_cfg.get("max_z_speed_mps", 0.3)
            if cmd == "move_forward":
                controller.send_velocity(max_speed, 0, 0)
            elif cmd == "move_backward":
                controller.send_velocity(-max_speed, 0, 0)
            elif cmd == "turn_left":
                controller.send_velocity(0, -max_speed, 0, yaw_rate=-0.5)
            elif cmd == "turn_right":
                controller.send_velocity(0, max_speed, 0, yaw_rate=0.5)
            elif cmd == "altitude_up":
                controller.send_velocity(0, 0, -max_z)
            elif cmd == "altitude_down":
                controller.send_velocity(0, 0, max_z)
            elif cmd == "stop":
                controller.send_velocity(0, 0, 0)
            elif cmd == "emergency_stop":
                controller.emergency_stop()
            elif cmd == "return_home":
                controller.return_home()
            elif cmd == "payload_engage":
                controller.payload.engage()
            elif cmd == "payload_release":
                controller.payload.release()
            elif cmd == "payload_toggle":
                if controller.payload.is_engaged:
                    controller.payload.release()
                else:
                    controller.payload.engage()
            elif cmd == "start_mission":
                controller.start_search()
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
                "payload_engaged": controller.payload.is_engaged,
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
                platform="uav",
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
            camera.close()
            controller.disconnect()
            if gps_reader is not None:
                gps_reader.stop()

    logger.info("UAV mission finished. %d targets logged.", registry.count())


if __name__ == "__main__":
    main()
