#!/usr/bin/env python3
"""Sync organizer ROS config mirror from canonical ROS2 location."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "ros2_ws" / "src" / "dt_bringup" / "config" / "organizer_ros.yaml"
TARGET = ROOT / "config" / "organizer_ros.yaml"

HEADER = """# Mirror file generated from:
#   ros2_ws/src/dt_bringup/config/organizer_ros.yaml
# Do not edit manually; run:
#   python scripts/sync_organizer_config.py
"""


def main() -> int:
    if not SOURCE.exists():
        raise FileNotFoundError(f"Canonical organizer config not found: {SOURCE}")

    source_data = yaml.safe_load(SOURCE.read_text(encoding="utf-8")) or {}
    rendered = HEADER + "\n" + yaml.safe_dump(source_data, sort_keys=False)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"Synced {TARGET} from {SOURCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
