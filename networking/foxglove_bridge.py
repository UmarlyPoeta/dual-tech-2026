#!/usr/bin/env python3
"""Foxglove Studio WebSocket bridge for Dual Tech 2026.

Implements a subset of the Foxglove WebSocket protocol (v1) to stream
telemetry, detections, health, and compressed camera frames to Foxglove
Studio for live visualisation.

Protocol reference:
  https://docs.foxglove.dev/docs/connecting-to-data/frameworks/custom/#foxglove-websocket

Can run standalone or be integrated into the main mission process via
:class:`FoxgloveBridge`.

Standalone usage:
    python networking/foxglove_bridge.py --port 8765
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Channel IDs (1-indexed per Foxglove protocol)
CH_TELEMETRY = 1
CH_DETECTIONS = 2
CH_HEALTH = 3
CH_CAMERA = 4

CHANNELS = [
    {
        "id": CH_TELEMETRY,
        "topic": "/telemetry",
        "encoding": "json",
        "schemaName": "dualtech.Telemetry",
        "schema": json.dumps({
            "type": "object",
            "properties": {
                "timestamp": {"type": "number"},
                "lat": {"type": ["number", "null"]},
                "lon": {"type": ["number", "null"]},
                "alt": {"type": ["number", "null"]},
                "yaw_deg": {"type": ["number", "null"]},
                "speed_mps": {"type": ["number", "null"]},
                "state": {"type": "string"},
                "target_count": {"type": "integer"},
            },
        }),
    },
    {
        "id": CH_DETECTIONS,
        "topic": "/detections",
        "encoding": "json",
        "schemaName": "dualtech.Detections",
        "schema": json.dumps({
            "type": "object",
            "properties": {
                "timestamp": {"type": "number"},
                "detections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "confidence": {"type": "number"},
                            "bbox": {
                                "type": "array",
                                "items": {"type": "number"},
                            },
                        },
                    },
                },
            },
        }),
    },
    {
        "id": CH_HEALTH,
        "topic": "/health",
        "encoding": "json",
        "schemaName": "dualtech.Health",
        "schema": json.dumps({
            "type": "object",
            "properties": {
                "timestamp": {"type": "number"},
                "components": {"type": "object"},
                "cpu_temp_c": {"type": ["number", "null"]},
            },
        }),
    },
    {
        "id": CH_CAMERA,
        "topic": "/camera/compressed",
        "encoding": "json",
        "schemaName": "foxglove.CompressedImage",
        "schema": json.dumps({
            "type": "object",
            "properties": {
                "timestamp": {"type": "number"},
                "format": {"type": "string"},
                "data": {"type": "string"},
            },
        }),
    },
]


class FoxgloveBridge:
    """WebSocket bridge that streams data to Foxglove Studio clients.

    Parameters
    ----------
    port:
        TCP port for the WebSocket server.
    get_telemetry:
        Callback returning a telemetry dict.
    get_health:
        Callback returning a health/component-status dict.
    get_frame_jpeg:
        Callback returning a JPEG-encoded bytes object (or None).
    telemetry_hz:
        Publishing rate for telemetry channel.
    health_hz:
        Publishing rate for health channel.
    camera_hz:
        Publishing rate for camera channel.
    """

    def __init__(
        self,
        port: int = 8765,
        get_telemetry: Optional[Callable[[], Dict[str, Any]]] = None,
        get_health: Optional[Callable[[], Dict[str, Any]]] = None,
        get_frame_jpeg: Optional[Callable[[], Optional[bytes]]] = None,
        telemetry_hz: float = 2.0,
        health_hz: float = 1.0,
        camera_hz: float = 5.0,
    ) -> None:
        self._port = port
        self._get_telemetry = get_telemetry or (lambda: {})
        self._get_health = get_health or (lambda: {})
        self._get_frame_jpeg = get_frame_jpeg
        self._telemetry_hz = telemetry_hz
        self._health_hz = health_hz
        self._camera_hz = camera_hz

        self._clients: Set[Any] = set()
        self._subscriptions: Dict[Any, Set[int]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        """Start the bridge in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="foxglove-bridge")
        self._thread.start()
        logger.info("Foxglove bridge starting on port %d", self._port)

    def stop(self) -> None:
        """Stop the bridge."""
        self._running = False
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        logger.info("Foxglove bridge stopped.")

    def publish_detections(self, detections: list[dict]) -> None:
        """Push detection data to all subscribed clients (called from detector)."""
        msg = {
            "timestamp": time.time(),
            "detections": detections,
        }
        self._broadcast(CH_DETECTIONS, msg)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Run the asyncio event loop in the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            logger.exception("Foxglove bridge loop error")
        finally:
            self._loop.close()

    async def _serve(self) -> None:
        try:
            import websockets  # type: ignore
            from websockets.asyncio.server import serve  # type: ignore
        except ImportError:
            logger.error("websockets library not installed — pip install websockets")
            return

        async with serve(self._handler, "0.0.0.0", self._port) as server:
            logger.info("Foxglove WebSocket server listening on ws://0.0.0.0:%d", self._port)

            tasks = [
                asyncio.create_task(self._publish_loop("telemetry", CH_TELEMETRY,
                                                       self._get_telemetry, self._telemetry_hz)),
                asyncio.create_task(self._publish_loop("health", CH_HEALTH,
                                                       self._get_health, self._health_hz)),
            ]
            if self._get_frame_jpeg is not None:
                tasks.append(asyncio.create_task(self._camera_loop()))

            # Run until stopped
            while self._running:
                await asyncio.sleep(0.5)

            for task in tasks:
                task.cancel()

    async def _handler(self, websocket: Any) -> None:
        """Handle a single Foxglove client connection."""
        self._clients.add(websocket)
        self._subscriptions[websocket] = set()
        logger.info("Foxglove client connected: %s", websocket.remote_address)

        # Send serverInfo
        server_info = {
            "op": "serverInfo",
            "name": "Dual Tech 2026",
            "capabilities": ["clientPublish"],
            "supportedEncodings": ["json"],
            "metadata": {},
            "sessionId": str(id(self)),
        }
        await websocket.send(json.dumps(server_info))

        # Send available channels
        advertise = {
            "op": "advertise",
            "channels": CHANNELS,
        }
        await websocket.send(json.dumps(advertise))

        try:
            async for raw_msg in websocket:
                try:
                    msg = json.loads(raw_msg)
                    op = msg.get("op")

                    if op == "subscribe":
                        for sub in msg.get("subscriptions", []):
                            ch_id = sub.get("channelId")
                            if ch_id:
                                self._subscriptions[websocket].add(ch_id)
                                logger.debug("Client subscribed to channel %d", ch_id)

                    elif op == "unsubscribe":
                        for sub_id in msg.get("subscriptionIds", []):
                            self._subscriptions[websocket].discard(sub_id)

                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        finally:
            self._clients.discard(websocket)
            self._subscriptions.pop(websocket, None)
            logger.info("Foxglove client disconnected")

    async def _publish_loop(self, name: str, channel_id: int,
                            getter: Callable, hz: float) -> None:
        """Periodically publish data from a getter function."""
        interval = 1.0 / hz if hz > 0 else 1.0
        while self._running:
            try:
                data = getter()
                if data:
                    data["timestamp"] = time.time()
                    self._broadcast(channel_id, data)
            except Exception:
                logger.debug("Foxglove publish error on %s", name, exc_info=True)
            await asyncio.sleep(interval)

    async def _camera_loop(self) -> None:
        """Publish compressed camera frames."""
        import base64
        interval = 1.0 / self._camera_hz if self._camera_hz > 0 else 0.2
        while self._running:
            try:
                jpeg_bytes = self._get_frame_jpeg()
                if jpeg_bytes is not None:
                    msg = {
                        "timestamp": time.time(),
                        "format": "jpeg",
                        "data": base64.b64encode(jpeg_bytes).decode("ascii"),
                    }
                    self._broadcast(CH_CAMERA, msg)
            except Exception:
                pass
            await asyncio.sleep(interval)

    def _broadcast(self, channel_id: int, data: dict) -> None:
        """Send a message to all clients subscribed to a channel."""
        if not self._clients or self._loop is None:
            return

        payload = json.dumps({
            "op": "messageData",
            "subscriptionId": channel_id,
            "timestamp": int(data.get("timestamp", time.time()) * 1e9),
            "data": data,
        })

        for client in list(self._clients):
            subs = self._subscriptions.get(client, set())
            if channel_id in subs:
                try:
                    asyncio.run_coroutine_threadsafe(client.send(payload), self._loop)
                except Exception:
                    pass


# ===========================================================================
# Standalone entry point
# ===========================================================================

def _read_cpu_temp() -> Optional[float]:
    try:
        return int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000.0
    except Exception:
        return None


def _standalone_main(port: int) -> None:
    """Run the bridge standalone, polling data from the core service HTTP API."""
    import urllib.request

    CORE_BASE = "http://localhost:8080"

    def get_telemetry() -> dict:
        try:
            with urllib.request.urlopen(f"{CORE_BASE}/api/telemetry", timeout=2) as resp:
                return json.loads(resp.read())
        except Exception:
            return {}

    def get_health() -> dict:
        temp = _read_cpu_temp()
        try:
            with urllib.request.urlopen(f"{CORE_BASE}/api/health", timeout=2) as resp:
                data = json.loads(resp.read())
                data["cpu_temp_c"] = temp
                return data
        except Exception:
            return {"status": "unreachable", "cpu_temp_c": temp}

    bridge = FoxgloveBridge(
        port=port,
        get_telemetry=get_telemetry,
        get_health=get_health,
    )
    bridge._running = True
    bridge._run_loop()  # Blocks in this thread


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    port = 8765
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])

    logger.info("Starting standalone Foxglove bridge on port %d", port)
    _standalone_main(port)
