"""Shared configuration loader — merges common + platform-specific YAML files with ENV overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_HW_PARAMS_PATH = DEFAULT_CONFIG_DIR / "hardware" / "hw_params.yaml"
LEGACY_HW_PARAMS_PATH = PROJECT_ROOT / "configs" / "hw_params.yaml"


def _load_yaml(path: str | Path) -> Dict[str, Any]:
    if not Path(path).exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, update: dict) -> dict:
    """Recursively merge two dictionaries."""
    for k, v in update.items():
        if isinstance(v, dict) and k in base and isinstance(base[k], dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _env_override(cfg: dict, prefix: str = "DT_") -> None:
    """Override config values from environment variables.
    
    Example: DT_CAMERA_SOURCE=1 will override cfg['camera']['source'] = 1
    (if the key exists or is added).
    """
    for env_name, env_val in os.environ.items():
        if not env_name.startswith(prefix):
            continue
            
        # DT_HAL__CAMERA__SOURCE=1 -> ['hal', 'camera', 'source']
        parts = env_name[len(prefix):].lower().split("__")
        
        # Traverse and update
        curr = cfg
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                # Try to convert to int/float/bool if possible
                if env_val.lower() == "true":
                    val: Any = True
                elif env_val.lower() == "false":
                    val = False
                else:
                    try:
                        if "." in env_val:
                            val = float(env_val)
                        else:
                            val = int(env_val)
                    except ValueError:
                        val = env_val
                curr[part] = val
            else:
                if part not in curr or not isinstance(curr[part], dict):
                    curr[part] = {}
                curr = curr[part]


def resolve_hw_params_path(
    preferred_path: str | Path | None = None,
    *,
    create_parent: bool = False,
) -> Path:
    """Resolve the hardware params path with backward compatibility.

    Priority:
      1) explicit ``preferred_path`` argument
      2) ``DT_HW_PARAMS_PATH`` environment variable
      3) canonical path: ``config/hardware/hw_params.yaml``
      4) legacy fallback if only legacy file exists: ``configs/hw_params.yaml``
    """
    env_path = os.getenv("DT_HW_PARAMS_PATH")
    if preferred_path:
        path = Path(preferred_path)
    elif env_path:
        path = Path(env_path)
    elif DEFAULT_HW_PARAMS_PATH.exists():
        path = DEFAULT_HW_PARAMS_PATH
    elif LEGACY_HW_PARAMS_PATH.exists():
        path = LEGACY_HW_PARAMS_PATH
    else:
        path = DEFAULT_HW_PARAMS_PATH

    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_hw_params(path: str | Path | None = None) -> Dict[str, Any]:
    """Load hardware calibration parameters."""
    hw_path = resolve_hw_params_path(path)
    return _load_yaml(hw_path)


def load_config(platform: str, config_dir: str | Path = "config") -> Dict[str, Any]:
    """Load and merge configuration files with environment overrides.

    Parameters
    ----------
    platform:
        Either ``"uav"`` or ``"ugv"``.
    config_dir:
        Directory containing the YAML config files.
    """
    config_dir = Path(config_dir)
    if not config_dir.is_absolute():
        config_dir = PROJECT_ROOT / config_dir

    # 1. Start with common config
    cfg = _load_yaml(config_dir / "common.yaml")
    
    # 2. Merge platform-specific config
    platform_cfg = _load_yaml(config_dir / f"{platform}.yaml")
    _deep_merge(cfg, platform_cfg)
    
    # 3. Merge classes (usually constant but can be overridden)
    classes = _load_yaml(config_dir / "classes.yaml")
    _deep_merge(cfg, {"classes": classes})

    # 4. Apply environment overrides (DT_ prefix)
    _env_override(cfg)
    
    cfg["hardware"] = {
        "params_path": str(resolve_hw_params_path()),
        "params": load_hw_params(),
    }
    cfg["platform"] = platform
    return cfg
