"""Tests for monitoring/health — HealthMonitor and SystemWatchdog."""

from __future__ import annotations

import os
import sys
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from monitoring.health import ComponentStatus, HealthMonitor, SystemWatchdog


# ===================================================================
# HealthMonitor — heartbeat / status
# ===================================================================


class TestHealthMonitor:
    @pytest.fixture()
    def monitor(self) -> HealthMonitor:
        return HealthMonitor()

    def test_unknown_component_returns_stale(self, monitor: HealthMonitor) -> None:
        status = monitor.get_status("nonexistent")
        assert status == ComponentStatus.STALE

    def test_heartbeat_then_get_ok(self, monitor: HealthMonitor) -> None:
        monitor.heartbeat("camera", ComponentStatus.OK)
        assert monitor.get_status("camera") == ComponentStatus.OK

    def test_heartbeat_warning(self, monitor: HealthMonitor) -> None:
        monitor.heartbeat("gps", ComponentStatus.WARNING)
        assert monitor.get_status("gps") == ComponentStatus.WARNING

    def test_heartbeat_error(self, monitor: HealthMonitor) -> None:
        monitor.heartbeat("motor", ComponentStatus.ERROR)
        assert monitor.get_status("motor") == ComponentStatus.ERROR

    def test_stale_after_timeout(self, monitor: HealthMonitor) -> None:
        monitor.heartbeat("sensor")
        # Use a very short timeout so the heartbeat is immediately stale
        status = monitor.get_status("sensor", timeout_s=0.0)
        assert status == ComponentStatus.STALE

    def test_get_all_statuses_returns_all_components(self, monitor: HealthMonitor) -> None:
        monitor.heartbeat("cam", ComponentStatus.OK)
        monitor.heartbeat("gps", ComponentStatus.WARNING)
        result = monitor.get_all_statuses()
        assert "cam" in result
        assert "gps" in result

    def test_get_all_statuses_stale_entry(self, monitor: HealthMonitor) -> None:
        monitor.heartbeat("old_sensor")
        result = monitor.get_all_statuses(timeout_s=0.0)
        assert result["old_sensor"] == ComponentStatus.STALE

    def test_multiple_heartbeats_update_status(self, monitor: HealthMonitor) -> None:
        monitor.heartbeat("cam", ComponentStatus.OK)
        monitor.heartbeat("cam", ComponentStatus.ERROR)
        assert monitor.get_status("cam") == ComponentStatus.ERROR

    def test_thread_safety(self, monitor: HealthMonitor) -> None:
        """Many concurrent heartbeats should not raise."""
        errors = []

        def _worker(name: str) -> None:
            for _ in range(50):
                try:
                    monitor.heartbeat(name, ComponentStatus.OK)
                    monitor.get_status(name)
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=_worker, args=(f"comp_{i}",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# ===================================================================
# HealthMonitor — thermal
# ===================================================================


class TestHealthMonitorThermal:
    def test_update_thermal_no_file(self):
        m = HealthMonitor()
        # Neither thermal zone file nor state file exists → silently no-op
        m.update_thermal()
        assert m.cpu_temp_c is None
        assert m.thermal_throttle is False

    def test_throttle_set_when_temp_critical(self, tmp_path):
        m = HealthMonitor()
        # Simulate a thermal zone reading of 90 °C (value in millidegrees)
        thermal_zone = tmp_path / "temp"
        thermal_zone.write_text("90000\n")
        import monitoring.health as mh
        with patch.object(mh, "_THERMAL_ZONE", thermal_zone):
            m.update_thermal()
        assert m.thermal_throttle is True
        assert m.cpu_temp_c == pytest.approx(90.0)

    def test_throttle_set_when_temp_high(self, tmp_path):
        m = HealthMonitor()
        thermal_zone = tmp_path / "temp"
        thermal_zone.write_text("82000\n")
        import monitoring.health as mh
        with patch.object(mh, "_THERMAL_ZONE", thermal_zone):
            m.update_thermal()
        assert m.thermal_throttle is True

    def test_throttle_cleared_when_temp_normal(self, tmp_path):
        m = HealthMonitor()
        thermal_zone = tmp_path / "temp"
        import monitoring.health as mh
        # First set it to throttled
        thermal_zone.write_text("82000\n")
        with patch.object(mh, "_THERMAL_ZONE", thermal_zone):
            m.update_thermal()
        assert m.thermal_throttle is True
        # Then cool down
        thermal_zone.write_text("60000\n")
        with patch.object(mh, "_THERMAL_ZONE", thermal_zone):
            m.update_thermal()
        assert m.thermal_throttle is False


# ===================================================================
# HealthMonitor — disk space
# ===================================================================


class TestHealthMonitorDisk:
    def test_check_disk_space_returns_dict(self):
        result = HealthMonitor.check_disk_space(".")
        assert "total_gb" in result
        assert "free_gb" in result
        assert "used_pct" in result
        assert result["total_gb"] > 0
        assert 0.0 <= result["used_pct"] <= 100.0

    def test_check_disk_space_path_arg(self, tmp_path):
        result = HealthMonitor.check_disk_space(str(tmp_path))
        assert isinstance(result["free_gb"], float)


# ===================================================================
# SystemWatchdog
# ===================================================================


class TestSystemWatchdog:
    def test_start_stop(self):
        m = HealthMonitor()
        wd = SystemWatchdog(m, critical_components=[], timeout_s=1.0)
        wd.start()
        time.sleep(0.2)
        wd.stop()

    def test_no_callback_for_healthy_component(self):
        cb = MagicMock()
        m = HealthMonitor()
        m.heartbeat("cam", ComponentStatus.OK)
        wd = SystemWatchdog(m, critical_components=["cam"], timeout_s=2.0, on_failure=cb)
        wd.start()
        time.sleep(0.4)
        wd.stop()
        cb.assert_not_called()

    def test_callback_for_stale_component(self):
        cb = MagicMock()
        m = HealthMonitor()
        m.heartbeat("cam", ComponentStatus.OK)
        # Use a tiny timeout so the heartbeat immediately goes stale
        wd = SystemWatchdog(m, critical_components=["cam"], timeout_s=0.05, on_failure=cb)
        wd.start()
        time.sleep(0.4)
        wd.stop()
        cb.assert_called()
        # First arg of first call should be the component name
        assert cb.call_args_list[0][0][0] == "cam"

    def test_callback_for_error_component(self):
        cb = MagicMock()
        m = HealthMonitor()
        m.heartbeat("gps", ComponentStatus.ERROR)
        wd = SystemWatchdog(m, critical_components=["gps"], timeout_s=5.0, on_failure=cb)
        wd.start()
        time.sleep(0.4)
        wd.stop()
        cb.assert_called()

    def test_exception_in_callback_does_not_crash_watchdog(self):
        def bad_cb(name, status):
            raise RuntimeError("boom")

        m = HealthMonitor()
        m.heartbeat("sensor", ComponentStatus.ERROR)
        wd = SystemWatchdog(m, critical_components=["sensor"], timeout_s=5.0, on_failure=bad_cb)
        wd.start()
        time.sleep(0.4)
        wd.stop()  # should not propagate the RuntimeError

    def test_uncritical_component_does_not_fire_callback(self):
        cb = MagicMock()
        m = HealthMonitor()
        m.heartbeat("cam", ComponentStatus.ERROR)
        # 'gps' is critical and healthy; 'cam' is not critical
        m.heartbeat("gps", ComponentStatus.OK)
        wd = SystemWatchdog(m, critical_components=["gps"], timeout_s=5.0, on_failure=cb)
        wd.start()
        time.sleep(0.3)
        wd.stop()
        cb.assert_not_called()
