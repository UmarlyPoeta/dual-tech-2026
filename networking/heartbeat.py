"""Heartbeat / watchdog — monitors operator connectivity and triggers safe actions.

The :class:`HeartbeatMonitor` runs a tiny HTTP endpoint that the operator's
browser (or a custom client) pings periodically.  If no ping arrives within
``timeout_s`` seconds the monitor fires a configurable *on_timeout* callback
(e.g. emergency-stop).  When pings resume the *on_reconnect* callback fires.

This is **much** more resilient than VNC because:

* The heartbeat is a single tiny HTTP request (< 100 bytes).
* Loss of a few packets does not cause the entire session to freeze.
* The vehicle can autonomously decide what to do during a dropout.
"""

from __future__ import annotations

import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class HeartbeatMonitor:
    """Monitor operator connectivity via periodic HTTP pings.

    Parameters
    ----------
    port:
        TCP port to listen on for heartbeat pings.
    timeout_s:
        Seconds without a ping before the connection is considered lost.
    on_timeout:
        Called once when the connection is considered lost.
    on_reconnect:
        Called once when the connection is restored after a loss.
    """

    def __init__(
        self,
        port: int = 5001,
        timeout_s: float = 5.0,
        on_timeout: Optional[Callable[[], None]] = None,
        on_reconnect: Optional[Callable[[], None]] = None,
    ) -> None:
        self._port = port
        self._timeout_s = timeout_s
        self._on_timeout = on_timeout
        self._on_reconnect = on_reconnect

        self._last_ping: float = 0.0
        self._connected: bool = False
        self._running: bool = False
        self._server: Optional[HTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the heartbeat HTTP server and the watchdog thread."""
        if self._running:
            return
        self._running = True
        self._last_ping = time.monotonic()
        self._connected = False

        monitor = self  # closure reference

        class _Handler(BaseHTTPRequestHandler):
            """Minimal handler — every GET/POST to ``/ping`` counts."""

            def do_GET(self) -> None:  # noqa: N802
                if self.path.rstrip("/") in ("/ping", "/heartbeat", ""):
                    monitor._record_ping()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(b"pong")
                else:
                    self.send_response(404)
                    self.end_headers()

            do_POST = do_GET  # accept both methods

            def log_message(self, format, *args):  # noqa: A002
                # Silence per-request logs
                pass

        self._server = HTTPServer(("0.0.0.0", self._port), _Handler)

        self._server_thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="heartbeat-http",
        )
        self._server_thread.start()

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True, name="heartbeat-watchdog",
        )
        self._watchdog_thread.start()

        logger.info("Heartbeat monitor started on port %d (timeout=%.1fs)", self._port, self._timeout_s)

    def stop(self) -> None:
        """Shut down the heartbeat monitor."""
        self._running = False
        if self._server is not None:
            self._server.shutdown()
        if self._server_thread is not None:
            self._server_thread.join(timeout=3.0)
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=3.0)
        logger.info("Heartbeat monitor stopped.")

    @property
    def is_connected(self) -> bool:
        """``True`` if an operator heartbeat has been received recently."""
        with self._lock:
            return self._connected

    @property
    def seconds_since_last_ping(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_ping

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _record_ping(self) -> None:
        with self._lock:
            self._last_ping = time.monotonic()
            was_connected = self._connected
            self._connected = True

        if not was_connected:
            logger.info("Heartbeat: operator reconnected.")
            if self._on_reconnect is not None:
                try:
                    self._on_reconnect()
                except Exception:
                    logger.exception("Error in on_reconnect callback")

    def _watchdog_loop(self) -> None:
        while self._running:
            time.sleep(1.0)
            with self._lock:
                elapsed = time.monotonic() - self._last_ping
                was_connected = self._connected

            if elapsed > self._timeout_s and was_connected:
                with self._lock:
                    self._connected = False
                logger.warning(
                    "Heartbeat: no ping for %.1fs — connection lost!", elapsed,
                )
                if self._on_timeout is not None:
                    try:
                        self._on_timeout()
                    except Exception:
                        logger.exception("Error in on_timeout callback")
