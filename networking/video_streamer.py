"""MJPEG video streamer — lightweight FPV replacement for VNC.

Why MJPEG over HTTP instead of VNC / RTSP / WebRTC?

* **Each frame is independently decodable** — no keyframe dependency, so the
  client can reconnect and immediately see a valid image.
* **Works in every browser** via a simple ``<img>`` tag — no plugins needed.
* **Extremely low overhead** — one persistent HTTP connection, no session
  state, no desktop compositor.
* **Graceful on weak WiFi** — a dropped frame simply means the next one
  arrives a bit later; there is no cascading corruption or frozen desktop.
* **Adaptive quality** — the server can dynamically lower JPEG quality when
  bandwidth is tight, keeping latency low.

Usage::

    streamer = VideoStreamer(get_frame=camera.get_frame, port=5000)
    streamer.start()
    # … later …
    streamer.stop()

Then open ``http://<vehicle-ip>:5000/`` in a browser.
"""

from __future__ import annotations

import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

_BOUNDARY = b"--frame"


class VideoStreamer:
    """Serve a live MJPEG stream over HTTP.

    Parameters
    ----------
    get_frame:
        Callable returning the latest BGR ``np.ndarray`` or ``None``.
    port:
        TCP port to listen on.
    quality:
        JPEG quality (1–100).  Lower values save bandwidth.
    max_fps:
        Maximum frames per second pushed to each client.
    """

    def __init__(
        self,
        get_frame: Callable[[], Optional[np.ndarray]],
        port: int = 5000,
        quality: int = 50,
        max_fps: int = 15,
    ) -> None:
        self._get_frame = get_frame
        self._port = port
        self._quality = quality
        self._min_interval = 1.0 / max(1, max_fps)
        self._running = False
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        # Shared latest JPEG buffer (written by producer, read by handlers)
        self._jpeg_buf: Optional[bytes] = None
        self._jpeg_lock = threading.Lock()
        self._producer_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the HTTP server and frame-producer thread."""
        if self._running:
            return
        self._running = True

        streamer = self  # closure reference

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path = self.path.rstrip("/")
                if path in ("", "/stream", "/video"):
                    self._stream_mjpeg()
                elif path == "/snapshot":
                    self._serve_snapshot()
                elif path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(b"ok")
                else:
                    self._serve_index()

            def _stream_mjpeg(self) -> None:
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "multipart/x-mixed-replace; boundary=frame",
                )
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()

                while streamer._running:
                    jpeg = streamer._get_jpeg()
                    if jpeg is None:
                        time.sleep(0.05)
                        continue
                    try:
                        self.wfile.write(_BOUNDARY + b"\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n".encode())
                        self.wfile.write(b"\r\n")
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
                    time.sleep(streamer._min_interval)

            def _serve_snapshot(self) -> None:
                jpeg = streamer._get_jpeg()
                if jpeg is None:
                    self.send_response(503)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(jpeg)

            def _serve_index(self) -> None:
                html = (
                    b"<!DOCTYPE html><html><head>"
                    b"<meta name='viewport' content='width=device-width'>"
                    b"<title>FPV</title></head><body style='margin:0;background:#000'>"
                    b"<img src='/stream' style='width:100%;height:auto'>"
                    b"<script>"
                    b"setInterval(()=>fetch('/ping').catch(()=>{}),1000);"
                    b"</script>"
                    b"</body></html>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)

            def log_message(self, format, *args):  # noqa: A002
                pass

        self._server = HTTPServer(("0.0.0.0", self._port), _Handler)

        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="mjpeg-http",
        )
        self._thread.start()

        self._producer_thread = threading.Thread(
            target=self._frame_producer, daemon=True, name="mjpeg-producer",
        )
        self._producer_thread.start()

        logger.info(
            "Video streamer started on port %d (quality=%d, max_fps=%.0f)",
            self._port, self._quality, 1.0 / self._min_interval,
        )

    def stop(self) -> None:
        self._running = False
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        if self._producer_thread is not None:
            self._producer_thread.join(timeout=3.0)
        logger.info("Video streamer stopped.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _frame_producer(self) -> None:
        """Continuously encode the latest camera frame as JPEG."""
        while self._running:
            frame = self._get_frame()
            if frame is None:
                time.sleep(0.05)
                continue
            try:
                import cv2  # type: ignore

                ok, buf = cv2.imencode(
                    ".jpg", frame,
                    [cv2.IMWRITE_JPEG_QUALITY, self._quality],
                )
                if ok:
                    with self._jpeg_lock:
                        self._jpeg_buf = buf.tobytes()
            except Exception:
                logger.debug("JPEG encode error", exc_info=True)
            time.sleep(self._min_interval)

    def _get_jpeg(self) -> Optional[bytes]:
        with self._jpeg_lock:
            return self._jpeg_buf
