"""Shared configuration loader — merges common + platform-specific YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


def _load_yaml(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(platform: str, config_dir: str | Path = "config") -> Dict[str, Any]:
    """Load and merge configuration files.

    Returns a flat dict with keys:
    * ``mission`` — from ``common.yaml``
    * ``logging`` — from ``common.yaml``
    * ``classes`` — from ``classes.yaml``
    * ``uav`` or ``ugv`` — from the platform-specific YAML
    * ``platform`` — the string ``"uav"`` or ``"ugv"``

    Parameters
    ----------
    platform:
        Either ``"uav"`` or ``"ugv"``.
    config_dir:
        Directory containing the YAML config files.
    """
    config_dir = Path(config_dir)

    common = _load_yaml(config_dir / "common.yaml")
    classes = _load_yaml(config_dir / "classes.yaml")
    platform_cfg = _load_yaml(config_dir / f"{platform}.yaml")

    cfg = {**common, **classes, **platform_cfg, "platform": platform}
    return cfg
