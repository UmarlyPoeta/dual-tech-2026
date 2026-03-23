#!/usr/bin/env python3
"""
Dual-Tech 2026 Pre-flight Hardware Checklist.
Tests HAL components (Camera, GPS, Motors) in isolation.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

from config_loader import load_config
from hal.factory import create_camera, create_gps, create_motors
from monitoring.health import ComponentStatus, HealthMonitor

# Configure logging for clear output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("pre-flight")

def run_checklist():
    # 1. Platform selection
    platform = sys.argv[1] if len(sys.argv) > 1 else "ugv"
    logger.info("====================================================")
    logger.info(f"   PRE-FLIGHT CHECKLIST: {platform.upper()}")
    logger.info("====================================================")
    
    try:
        cfg = load_config(platform)
    except Exception as e:
        logger.error(f"Failed to load config for {platform}: {e}")
        return

    hal_cfg = cfg.get("hal", {})
    health = HealthMonitor()

    # --- 1. CAMERA TEST ---
    logger.info("[CHECK 1/3] CAMERA")
    try:
        cam_cfg = hal_cfg.get("camera", {})
        logger.info(f"  Mode: {cam_cfg.get('mode')}, Source: {cam_cfg.get('source')}")
        camera = create_camera(cam_cfg, health=health)
        camera.open()
        
        # Try to grab a few frames to ensure stability
        success_frames = 0
        for _ in range(5):
            frame = camera.get_data()
            if frame is not None:
                success_frames += 1
            time.sleep(0.1)
            
        if success_frames > 0:
            logger.info(f"  [OK] Camera is producing frames ({success_frames}/5 captured).")
            if hasattr(frame, "shape"):
                logger.info(f"  Resolution: {frame.shape[1]}x{frame.shape[0]}")
        else:
            logger.error("  [FAIL] Camera opened but returned 0 valid frames.")
        camera.close()
    except Exception as e:
        logger.error(f"  [FAIL] Camera initialization failed: {e}")

    # --- 2. GPS TEST ---
    logger.info("[CHECK 2/3] GPS")
    try:
        gps_cfg = hal_cfg.get("gps", {})
        logger.info(f"  Mode: {gps_cfg.get('mode')}, Port: {gps_cfg.get('port')}")
        gps = create_gps(gps_cfg, health=health)
        gps.start()
        
        logger.info("  Waiting 3s for data/fix...")
        time.sleep(3.0)
        
        pose = gps.get_data()
        if pose:
            logger.info(f"  [OK] GPS reporting: Lat={pose.lat:.6f}, Lon={pose.lon:.6f}")
        else:
            logger.warning("  [WARN] GPS started but no Pose data received (Check serial or sky view).")
        gps.stop()
    except Exception as e:
        logger.error(f"  [FAIL] GPS initialization failed: {e}")

    # --- 3. MOTORS TEST (UGV only) ---
    if platform == "ugv":
        logger.info("[CHECK 3/3] MOTORS (UGV)")
        try:
            mot_cfg = hal_cfg.get("motors", {})
            logger.info(f"  Mode: {mot_cfg.get('mode')}")
            motors = create_motors(mot_cfg, cfg.get("ugv", {}), health=health)
            motors.open()
            
            logger.info("  Action: Pulsing Left Motor (0.3 speed, 0.5s)...")
            motors.set_state({"left": 0.3, "right": 0.0})
            time.sleep(0.5)
            
            logger.info("  Action: Pulsing Right Motor (0.3 speed, 0.5s)...")
            motors.set_state({"left": 0.0, "right": 0.3})
            time.sleep(0.5)
            
            motors.set_state({"left": 0.0, "right": 0.0})
            logger.info("  [OK] Motors pulsed and reset to zero.")
            motors.close()
        except Exception as e:
            logger.error(f"  [FAIL] Motors initialization failed: {e}")
    else:
        logger.info("[CHECK 3/3] MOTORS: Skipping for UAV (FCU controlled).")

    # --- FINAL REPORT ---
    logger.info("====================================================")
    logger.info("   FINAL HEALTH REPORT")
    logger.info("====================================================")
    statuses = health.get_all_statuses()
    if not statuses:
        logger.error("No hardware components reported health. Check factory/config.")
    else:
        for name, status in statuses.items():
            status_str = status.value
            logger.info(f"  {name:10}: {status_str}")
    logger.info("====================================================")

if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python3 test_hardware.py [uav|ugv]")
        sys.exit(0)
    run_checklist()
