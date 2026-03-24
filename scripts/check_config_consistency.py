#!/usr/bin/env python3
"""Consistency checks for SSOT configuration and startup definitions."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)


def check_hw_config() -> None:
    canonical = ROOT / "config" / "hardware" / "hw_params.yaml"
    legacy = ROOT / "configs" / "hw_params.yaml"
    _load_yaml(canonical)
    _assert(not legacy.exists(), f"Legacy hardware config should not exist: {legacy}")


def check_organizer_mirror() -> None:
    canonical = ROOT / "ros2_ws" / "src" / "dt_bringup" / "config" / "organizer_ros.yaml"
    mirror = ROOT / "config" / "organizer_ros.yaml"
    canonical_data = _load_yaml(canonical)
    mirror_data = _load_yaml(mirror)
    _assert(
        canonical_data == mirror_data,
        "Organizer config mirror is out of sync. Run: python scripts/sync_organizer_config.py",
    )


def check_docker_uses_requirements() -> None:
    dockerfile = ROOT / "docker" / "RPi5.Dockerfile"
    content = dockerfile.read_text(encoding="utf-8")
    _assert(
        re.search(r"pip install .*?-r requirements\.txt", content) is not None,
        "Dockerfile must install dependencies from requirements.txt",
    )


def main() -> int:
    check_hw_config()
    check_organizer_mirror()
    check_docker_uses_requirements()
    print("Config consistency checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
