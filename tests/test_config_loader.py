"""Tests for config_loader — deep merge, env overrides, path resolution, load_config."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config_loader import (
    _deep_merge,
    _env_override,
    load_config,
    load_hw_params,
    resolve_hw_params_path,
)


# ===================================================================
# _deep_merge
# ===================================================================


class TestDeepMerge:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        update = {"b": 99, "c": 3}
        result = _deep_merge(base, update)
        assert result == {"a": 1, "b": 99, "c": 3}

    def test_nested_merge(self):
        base = {"outer": {"x": 1, "y": 2}}
        update = {"outer": {"y": 99, "z": 3}}
        result = _deep_merge(base, update)
        assert result == {"outer": {"x": 1, "y": 99, "z": 3}}

    def test_nested_replaces_non_dict(self):
        base = {"key": "string_value"}
        update = {"key": {"nested": True}}
        result = _deep_merge(base, update)
        assert result == {"key": {"nested": True}}

    def test_empty_update(self):
        base = {"a": 1}
        result = _deep_merge(base, {})
        assert result == {"a": 1}

    def test_empty_base(self):
        result = _deep_merge({}, {"x": 42})
        assert result == {"x": 42}

    def test_returns_base_dict(self):
        base = {"a": 1}
        result = _deep_merge(base, {"b": 2})
        assert result is base  # in-place merge

    def test_deeply_nested(self):
        base = {"l1": {"l2": {"l3": 1}}}
        update = {"l1": {"l2": {"l4": 2}}}
        _deep_merge(base, update)
        assert base["l1"]["l2"] == {"l3": 1, "l4": 2}


# ===================================================================
# _env_override
# ===================================================================


class TestEnvOverride:
    def test_sets_string_value(self):
        cfg: dict = {}
        with patch.dict(os.environ, {"DT_CAMERA__SOURCE": "usb0"}):
            _env_override(cfg)
        assert cfg == {"camera": {"source": "usb0"}}

    def test_casts_integer(self):
        cfg: dict = {}
        with patch.dict(os.environ, {"DT_FOO__BAR": "42"}):
            _env_override(cfg)
        assert cfg["foo"]["bar"] == 42
        assert isinstance(cfg["foo"]["bar"], int)

    def test_casts_float(self):
        cfg: dict = {}
        with patch.dict(os.environ, {"DT_FOO__RATE": "3.14"}):
            _env_override(cfg)
        assert cfg["foo"]["rate"] == pytest.approx(3.14)

    def test_casts_true(self):
        cfg: dict = {}
        with patch.dict(os.environ, {"DT_DEBUG": "true"}):
            _env_override(cfg)
        assert cfg["debug"] is True

    def test_casts_false(self):
        cfg: dict = {}
        with patch.dict(os.environ, {"DT_DEBUG": "false"}):
            _env_override(cfg)
        assert cfg["debug"] is False

    def test_ignores_non_dt_prefix(self):
        cfg: dict = {}
        with patch.dict(os.environ, {"HOME": "/root", "PATH": "/usr/bin"}):
            _env_override(cfg)
        assert cfg == {}

    def test_custom_prefix(self):
        cfg: dict = {}
        with patch.dict(os.environ, {"MY_KEY": "val"}):
            _env_override(cfg, prefix="MY_")
        assert cfg == {"key": "val"}

    def test_overrides_existing_value(self):
        cfg = {"port": 5000}
        with patch.dict(os.environ, {"DT_PORT": "9000"}):
            _env_override(cfg)
        assert cfg["port"] == 9000


# ===================================================================
# resolve_hw_params_path
# ===================================================================


class TestResolveHwParamsPath:
    def test_explicit_path_takes_priority(self, tmp_path):
        explicit = tmp_path / "explicit.yaml"
        explicit.touch()
        result = resolve_hw_params_path(explicit)
        assert result == explicit

    def test_env_var_path(self, tmp_path):
        env_path = tmp_path / "env.yaml"
        env_path.touch()
        with patch.dict(os.environ, {"DT_HW_PARAMS_PATH": str(env_path)}):
            result = resolve_hw_params_path()
        assert result == env_path

    def test_create_parent_creates_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "hw_params.yaml"
        result = resolve_hw_params_path(nested, create_parent=True)
        assert nested.parent.exists()
        assert result == nested

    def test_returns_path_type(self, tmp_path):
        f = tmp_path / "params.yaml"
        f.touch()
        result = resolve_hw_params_path(f)
        assert isinstance(result, Path)


# ===================================================================
# load_hw_params
# ===================================================================


class TestLoadHwParams:
    def test_returns_dict_from_yaml(self, tmp_path):
        yaml_file = tmp_path / "hw.yaml"
        yaml_file.write_text("servo:\n  min_pulse: 500\n  max_pulse: 2500\n")
        result = load_hw_params(yaml_file)
        assert result["servo"]["min_pulse"] == 500

    def test_missing_file_returns_empty(self, tmp_path):
        result = load_hw_params(tmp_path / "nonexistent.yaml")
        assert result == {}


# ===================================================================
# load_config
# ===================================================================


class TestLoadConfig:
    def test_load_uav_config(self):
        """smoke-test: loading 'uav' config from the real config dir."""
        cfg = load_config("uav")
        assert cfg["platform"] == "uav"
        assert isinstance(cfg, dict)

    def test_load_ugv_config(self):
        cfg = load_config("ugv")
        assert cfg["platform"] == "ugv"

    def test_env_override_applied(self):
        """DT_ environment variables must override values from YAML."""
        with patch.dict(os.environ, {"DT_MISSION__MAX_TARGETS": "7"}):
            cfg = load_config("uav")
        assert cfg["mission"]["max_targets"] == 7

    def test_hardware_key_present(self):
        cfg = load_config("uav")
        assert "hardware" in cfg
        assert "params_path" in cfg["hardware"]
