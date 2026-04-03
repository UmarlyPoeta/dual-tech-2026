"""Tests for GpsReader without real serial hardware."""

from __future__ import annotations

import os
import sys
import threading
import time
import types
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from localization.gps import GpsReader, _INITIAL_BACKOFF_S, _MAX_BACKOFF_S
from models import Pose


# ===================================================================
# GpsReader lifecycle
# ===================================================================


class TestGpsReaderLifecycle:
    def test_initial_pose_is_none(self):
        reader = GpsReader(port="/dev/null")
        assert reader.get_pose() is None

    def test_start_sets_running(self):
        """start() should launch the background thread."""
        reader = GpsReader(port="/dev/null")
        reader.start()
        assert reader._running is True
        reader.stop()

    def test_stop_clears_running(self):
        reader = GpsReader(port="/dev/null")
        reader.start()
        reader.stop()
        assert reader._running is False

    def test_stop_joins_thread(self):
        reader = GpsReader(port="/dev/null")
        reader.start()
        reader.stop()
        assert reader._thread is not None
        assert not reader._thread.is_alive()

    def test_get_pose_thread_safe(self):
        """get_pose() must not raise under concurrent access."""
        reader = GpsReader(port="/dev/null")
        errors = []

        def _writer():
            for i in range(50):
                with reader._lock:
                    reader._latest = Pose(lat=float(i), lon=float(i))
                time.sleep(0.001)

        def _reader():
            for _ in range(50):
                try:
                    reader.get_pose()
                except Exception as e:
                    errors.append(e)
                time.sleep(0.001)

        t1 = threading.Thread(target=_writer)
        t2 = threading.Thread(target=_reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert errors == []


# ===================================================================
# GpsReader — callback & pose injection
# ===================================================================


class TestGpsReaderCallback:
    def test_on_pose_callback_called(self):
        """Injecting a pose via the lock should call on_pose."""
        received: list[Pose] = []
        reader = GpsReader(port="/dev/null", on_pose=received.append)
        # Simulate what the _run loop does:
        pose = Pose(lat=51.5, lon=-0.1)
        with reader._lock:
            reader._latest = pose
        reader._on_pose(pose)
        assert len(received) == 1
        assert received[0].lat == pytest.approx(51.5)

    def test_pose_stored_after_injection(self):
        reader = GpsReader(port="/dev/null")
        pose = Pose(lat=48.8, lon=2.3)
        with reader._lock:
            reader._latest = pose
        result = reader.get_pose()
        assert result is pose


# ===================================================================
# GpsReader — serial failure / no-serial fallback
# ===================================================================


class TestGpsReaderSerialMissing:
    def test_run_exits_gracefully_when_no_serial(self):
        """If serial/pynmea2 is not available the thread should exit cleanly."""
        reader = GpsReader(port="/dev/null")
        reader._running = True

        # Hide serial from the _run method
        with patch.dict(sys.modules, {"serial": None, "pynmea2": None}):
            thread = threading.Thread(target=reader._run)
            thread.start()
            thread.join(timeout=2.0)

        assert not thread.is_alive()


# ===================================================================
# GpsReader — NMEA parsing (mocked serial)
# ===================================================================


class _FakeSerial:
    """Minimal serial port stub that yields a single GPRMC line then blocks."""

    _GPRMC = (
        b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n"
    )

    def __init__(self, *args, **kwargs):
        self._lines = [self._GPRMC, b""]
        self._idx = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def readline(self) -> bytes:
        if self._idx < len(self._lines):
            line = self._lines[self._idx]
            self._idx += 1
            return line
        # Block until reader stops
        time.sleep(0.05)
        return b""


class TestGpsReaderNmea:
    def test_valid_nmea_updates_latest_pose(self):
        """A valid GPRMC sentence should result in a non-None pose."""
        # Build stub modules
        pynmea2 = types.ModuleType("pynmea2")

        class _Msg:
            latitude = 48.11730
            longitude = 11.51667

        def _parse(line: str):
            return _Msg()

        pynmea2.parse = _parse

        serial_mod = types.ModuleType("serial")
        serial_mod.Serial = _FakeSerial

        received: list[Pose] = []
        reader = GpsReader(port="/dev/ttyFAKE", baud_rate=9600, on_pose=received.append)
        reader._running = True

        with patch.dict(sys.modules, {"serial": serial_mod, "pynmea2": pynmea2}):
            # Run for a short time then stop
            reader._running = True

            def _stop_after():
                time.sleep(0.3)
                reader._running = False

            stopper = threading.Thread(target=_stop_after, daemon=True)
            stopper.start()
            reader._run()

        assert len(received) >= 1
        assert received[0].lat == pytest.approx(48.11730, rel=1e-4)
