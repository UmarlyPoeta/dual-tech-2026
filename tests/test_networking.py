"""Tests for the networking package — video streamer and heartbeat monitor."""

from __future__ import annotations

import socket
import sys
import threading
import time
import types
from http.client import HTTPConnection
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from networking.heartbeat import HeartbeatMonitor
from networking.video_streamer import VideoStreamer


# ---------------------------------------------------------------------------
# Minimal cv2 stub so VideoStreamer JPEG encoding works without OpenCV
# ---------------------------------------------------------------------------

def _make_fake_cv2():
    """Return a cv2 module stub that encodes frames as minimal JPEG bytes."""
    fake = types.ModuleType("cv2")
    fake.IMWRITE_JPEG_QUALITY = 1

    def imencode(_ext, frame, params=None):  # noqa: ANN001
        # Return a tiny valid JPEG (FF D8 … FF D9) regardless of input
        jpeg_bytes = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xd9"
        )

        class _Buf:
            def tobytes(self):
                return jpeg_bytes

        return True, _Buf()

    fake.imencode = imencode
    return fake


if "cv2" not in sys.modules:
    sys.modules["cv2"] = _make_fake_cv2()


def _free_port() -> int:
    """Find an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ===================================================================
# HeartbeatMonitor tests
# ===================================================================


class TestHeartbeatMonitor:
    """Unit tests for the operator heartbeat monitor."""

    @pytest.fixture()
    def monitor(self):
        """Start a monitor on a free port."""
        port = _free_port()
        m = HeartbeatMonitor(port=port, timeout_s=2.0)
        m.start()
        time.sleep(0.3)  # let server bind
        yield m, port
        m.stop()

    def test_start_stop(self):
        port = _free_port()
        m = HeartbeatMonitor(port=port, timeout_s=1.0)
        m.start()
        time.sleep(0.2)
        m.stop()

    def test_ping_marks_connected(self, monitor):
        m, port = monitor
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/ping")
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.read() == b"pong"
        conn.close()
        assert m.is_connected is True

    def test_heartbeat_endpoint(self, monitor):
        m, port = monitor
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/heartbeat")
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()

    def test_timeout_fires_callback(self):
        cb = MagicMock()
        port = _free_port()
        m = HeartbeatMonitor(port=port, timeout_s=1.0, on_timeout=cb)
        m.start()
        # Send a first ping to set connected=True
        time.sleep(0.3)
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/ping")
        conn.getresponse()
        conn.close()
        assert m.is_connected is True
        # Now wait for timeout
        time.sleep(2.5)
        cb.assert_called()
        assert m.is_connected is False
        m.stop()

    def test_reconnect_fires_callback(self):
        on_reconnect = MagicMock()
        port = _free_port()
        m = HeartbeatMonitor(port=port, timeout_s=1.0, on_reconnect=on_reconnect)
        m.start()
        time.sleep(0.3)
        # First ping should fire on_reconnect (was not connected before)
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/ping")
        conn.getresponse()
        conn.close()
        time.sleep(0.2)
        on_reconnect.assert_called()
        m.stop()

    def test_seconds_since_last_ping(self, monitor):
        m, port = monitor
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/ping")
        conn.getresponse()
        conn.close()
        time.sleep(0.1)
        assert m.seconds_since_last_ping < 1.0


# ===================================================================
# VideoStreamer tests
# ===================================================================


class TestVideoStreamer:
    """Unit tests for the MJPEG video streamer."""

    @staticmethod
    def _make_frame() -> np.ndarray:
        """Return a small synthetic BGR frame."""
        return np.zeros((48, 64, 3), dtype=np.uint8)

    @pytest.fixture()
    def streamer(self):
        """Start a streamer on a free port."""
        port = _free_port()
        s = VideoStreamer(
            get_frame=self._make_frame,
            port=port,
            quality=30,
            max_fps=10,
        )
        s.start()
        time.sleep(0.5)  # let server + producer start
        yield s, port
        s.stop()

    def test_start_stop(self):
        port = _free_port()
        s = VideoStreamer(get_frame=self._make_frame, port=port, quality=30, max_fps=5)
        s.start()
        time.sleep(0.3)
        s.stop()

    def test_health_endpoint(self, streamer):
        s, port = streamer
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.read() == b"ok"
        conn.close()

    def test_snapshot_returns_jpeg(self, streamer):
        s, port = streamer
        # Wait for at least one frame to be produced
        time.sleep(0.5)
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/snapshot")
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "image/jpeg"
        data = resp.read()
        # JPEG files start with FF D8
        assert data[:2] == b"\xff\xd8"
        conn.close()

    def test_index_returns_html(self, streamer):
        s, port = streamer
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/index")
        resp = conn.getresponse()
        assert resp.status == 200
        assert "text/html" in resp.getheader("Content-Type")
        body = resp.read()
        assert b"<img" in body
        conn.close()

    def test_stream_returns_mjpeg(self, streamer):
        s, port = streamer
        time.sleep(0.5)
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/stream")
        resp = conn.getresponse()
        assert resp.status == 200
        content_type = resp.getheader("Content-Type")
        assert "multipart/x-mixed-replace" in content_type
        # Read a chunk — should contain JPEG data
        chunk = resp.read(4096)
        assert b"--frame" in chunk
        conn.close()

    def test_none_frame_returns_503_snapshot(self):
        """If get_frame returns None, /snapshot should return 503."""
        port = _free_port()
        s = VideoStreamer(get_frame=lambda: None, port=port, quality=30, max_fps=5)
        s.start()
        time.sleep(0.5)
        conn = HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/snapshot")
        resp = conn.getresponse()
        assert resp.status == 503
        conn.close()
        s.stop()
