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
from localization.gps import GpsReader
from localization.pose import PoseEstimator
from logging_module.logger import DataLogger
from mission.mission_manager import MissionManager
from mission.target_registry import TargetRegistry
from networking.heartbeat import HeartbeatMonitor
from networking.video_streamer import VideoStreamer
from perception.camera import Camera
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
    log_cfg = cfg.get("logging", {})
    stream_cfg = cfg.get("streaming", {})
    hb_cfg = cfg.get("heartbeat", {})
    gui_cfg = cfg.get("web_gui", {})
    class_map: dict[int, str] = {int(k): v for k, v in (cfg.get("classes") or {}).items()}
    target_classes: list[str] = cfg.get("target_classes") or []
    transport_classes: list[str] = cfg.get("transport_classes") or []

    model_path = Path("models/best.pt")

    camera = Camera(source=0)
    detector = ObjectDetector(
        model_path=model_path,
        class_map=class_map,
        confidence_threshold=mission_cfg.get("classify_confidence", 0.6),
    )
    qr_reader = QrReader()
    fusion = PerceptionFusion()
    pose_estimator = PoseEstimator()

    # GPS reader feeds pose estimator via callback
    gps_reader = GpsReader(on_pose=pose_estimator.update_pose)
    gps_reader.start()

    with DataLogger(log_cfg, platform="ugv") as data_logger:
        registry = TargetRegistry(
            revisit_radius_m=mission_cfg.get("revisit_radius_m_ugv", 2.0),
            platform="ugv",
        )

        controller = UGVController(
            config=ugv_cfg,
            pose_estimator=pose_estimator,
            camera_get_frame=camera.get_frame,
        )
        controller.connect()

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
                get_frame=camera.get_frame,
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
            target_classes=target_classes,
            transport_classes=transport_classes,
            enable_transport=True,
        )
        manager_ref[0] = mgr

        try:
            mgr.run(get_frame=camera.get_frame)
        finally:
            if gui is not None:
                gui.stop()
            if streamer is not None:
                streamer.stop()
            if heartbeat is not None:
                heartbeat.stop()
            camera.close()
            controller.disconnect()
            gps_reader.stop()

    logger.info("UGV mission finished. %d targets logged.", registry.count())


if __name__ == "__main__":
    main()
