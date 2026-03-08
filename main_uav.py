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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main_uav")


def main() -> None:
    cfg = load_config("uav")

    mission_cfg = cfg.get("mission", {})
    uav_cfg = cfg.get("uav", {})
    log_cfg = cfg.get("logging", {})
    stream_cfg = cfg.get("streaming", {})
    hb_cfg = cfg.get("heartbeat", {})
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

    with DataLogger(log_cfg, platform="uav") as data_logger:
        registry = TargetRegistry(
            revisit_radius_m=mission_cfg.get("revisit_radius_m_uav", 4.0),
            platform="uav",
        )

        controller = UAVController(
            config=uav_cfg,
            pose_estimator=pose_estimator,
            camera_get_frame=camera.get_frame,
        )
        controller.connect()

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

        manager = MissionManager(
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

        try:
            manager.run(get_frame=camera.get_frame)
        finally:
            if streamer is not None:
                streamer.stop()
            if heartbeat is not None:
                heartbeat.stop()
            camera.close()
            controller.disconnect()

    logger.info("UAV mission finished. %d targets logged.", registry.count())


if __name__ == "__main__":
    main()
