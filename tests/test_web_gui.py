"""Tests for WebGUI operator panel, gripper controller, and payload dropper."""

from __future__ import annotations

import json
import socket
import time
from http.client import HTTPConnection
from unittest.mock import MagicMock

import pytest

from controllers.uav.payload_dropper import PayloadDropper
from web_gui.operator_panel import OperatorPanel


def _free_port() -> int:
    """Find an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ===================================================================
# GripperController tests
# ===================================================================


class TestGripperController:
    """Unit tests for the UGV gripper."""

    def _make_gripper(self):
        """Create a GripperController without real GPIO (stays in no-op mode)."""
        from controllers.ugv.gripper import GripperController

        g = GripperController(servo_pin=99, pwm_open=0.1, pwm_closed=0.8, transit_time_s=0.0)
        # Do NOT call connect() — no GPIO available in CI, stays in no-op mode
        return g

    def test_initial_state_is_open(self):
        g = self._make_gripper()
        assert g.is_open is True

    def test_close_changes_state(self):
        g = self._make_gripper()
        g.close()
        assert g.is_open is False

    def test_open_after_close(self):
        g = self._make_gripper()
        g.close()
        g.open()
        assert g.is_open is True

    def test_toggle(self):
        g = self._make_gripper()
        assert g.is_open is True
        g.toggle()
        assert g.is_open is False
        g.toggle()
        assert g.is_open is True

    def test_grab_closes(self):
        g = self._make_gripper()
        g.grab()
        assert g.is_open is False

    def test_release_opens(self):
        g = self._make_gripper()
        g.close()
        g.release()
        assert g.is_open is True

    def test_not_connected_by_default(self):
        g = self._make_gripper()
        assert g.is_connected is False


# ===================================================================
# PayloadDropper tests
# ===================================================================


class TestPayloadDropper:
    """Unit tests for the UAV payload dropper."""

    def test_initial_state_disengaged(self):
        p = PayloadDropper(vehicle=None)
        assert p.is_engaged is False

    def test_engage(self):
        p = PayloadDropper(vehicle=None)
        p.engage()
        assert p.is_engaged is True

    def test_release(self):
        p = PayloadDropper(vehicle=None)
        p.engage()
        p.release()
        assert p.is_engaged is False

    def test_set_vehicle(self):
        p = PayloadDropper(vehicle=None)
        mock_vehicle = MagicMock()
        p.set_vehicle(mock_vehicle)
        # Engage should now try to send a MAVLink command
        p.engage()
        assert p.is_engaged is True
        mock_vehicle.message_factory.command_long_encode.assert_called()

    def test_noop_without_vehicle(self):
        """Engage/release without a vehicle should not raise."""
        p = PayloadDropper(vehicle=None, settle_time_s=0.0)
        p.engage()
        p.release()
        assert p.is_engaged is False


# ===================================================================
# OperatorPanel tests
# ===================================================================


class TestOperatorPanel:
    """Unit tests for the web GUI operator panel."""

    @pytest.fixture()
    def panel(self):
        """Start a panel on a free port."""
        port = _free_port()
        on_cmd = MagicMock(return_value={"ok": True})
        get_tel = MagicMock(return_value={"lat": 51.0, "lon": 17.0, "alt": None, "yaw_deg": None, "state": "SEARCH", "target_count": 3})
        get_tgt = MagicMock(return_value=[{"class_name": "box", "qr_value": "ABC", "lat": 51.0, "lon": 17.0}])
        p = OperatorPanel(
            port=port,
            platform="ugv",
            stream_port=5000,
            on_command=on_cmd,
            get_telemetry=get_tel,
            get_targets=get_tgt,
        )
        p.start()
        time.sleep(0.3)
        yield p, port, on_cmd, get_tel, get_tgt
        p.stop()

    def test_start_stop(self):
        port = _free_port()
        p = OperatorPanel(port=port, platform="ugv")
        p.start()
        time.sleep(0.2)
        p.stop()

    def test_index_returns_html(self, panel):
        p, port, *_ = panel
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/")
        resp = conn.getresponse()
        assert resp.status == 200
        assert "text/html" in resp.getheader("Content-Type")
        body = resp.read()
        assert b"Operator" in body
        assert b"UGV" in body
        conn.close()

    def test_health_endpoint(self, panel):
        p, port, *_ = panel
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        assert resp.status == 200
        data = json.loads(resp.read())
        assert data["status"] == "ok"
        assert data["platform"] == "ugv"
        conn.close()

    def test_telemetry_endpoint(self, panel):
        p, port, _, get_tel, _ = panel
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/api/telemetry")
        resp = conn.getresponse()
        assert resp.status == 200
        data = json.loads(resp.read())
        assert data["lat"] == 51.0
        assert data["state"] == "SEARCH"
        get_tel.assert_called()
        conn.close()

    def test_targets_endpoint(self, panel):
        p, port, _, _, get_tgt = panel
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/api/targets")
        resp = conn.getresponse()
        assert resp.status == 200
        data = json.loads(resp.read())
        assert len(data) == 1
        assert data[0]["class_name"] == "box"
        conn.close()

    def test_command_endpoint(self, panel):
        p, port, on_cmd, *_ = panel
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        body = json.dumps({"cmd": "move_forward", "args": {}})
        conn.request("POST", "/api/command", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        data = json.loads(resp.read())
        assert data["ok"] is True
        on_cmd.assert_called_with("move_forward", {})
        conn.close()

    def test_command_with_args(self, panel):
        p, port, on_cmd, *_ = panel
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        body = json.dumps({"cmd": "gripper_toggle", "args": {"force": True}})
        conn.request("POST", "/api/command", body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        on_cmd.assert_called_with("gripper_toggle", {"force": True})
        conn.close()

    def test_404_for_unknown_path(self, panel):
        p, port, *_ = panel
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/nonexistent")
        resp = conn.getresponse()
        assert resp.status == 404
        conn.close()

    def test_uav_platform_html(self):
        """UAV platform variant renders payload controls."""
        port = _free_port()
        p = OperatorPanel(port=port, platform="uav", stream_port=5000)
        p.start()
        time.sleep(0.3)
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read()
        assert b"UAV" in body
        assert b"Payload" in body
        conn.close()
        p.stop()
