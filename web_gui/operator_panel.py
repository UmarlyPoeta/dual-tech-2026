"""Browser-based operator control panel.

Serves a self-contained single-page application that provides:

* **Live FPV** via the existing MJPEG stream
* **Keyboard control** for UGV (WASD + QE for gripper) and UAV (arrows + altitude)
* **Telemetry dashboard** — GPS, heading, mission state, battery
* **Mission control** — start/stop, emergency stop, return-home
* **Gripper / payload** controls
* **Target log** — live view of detected targets

The GUI communicates with the vehicle via a JSON command API over HTTP.
Keyboard presses are sent as POST requests.  The panel periodically polls
``/api/telemetry`` to update the dashboard.

The design intentionally avoids WebSockets for maximum resilience on weak
WiFi — every command and poll is an independent HTTP request that either
succeeds or fails atomically.  The browser simply retries on the next cycle.

Usage::

    panel = OperatorPanel(port=8080, platform="ugv", ...)
    panel.start()
"""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class OperatorPanel:
    """Self-contained HTTP server for the operator control panel.

    Parameters
    ----------
    port:
        TCP port to listen on.
    platform:
        ``"ugv"`` or ``"uav"`` — controls which keyboard bindings are shown.
    stream_port:
        Port number of the MJPEG video streamer (embedded in the page).
    on_command:
        Callback ``(cmd: str, args: dict) -> dict`` invoked for every operator
        command.  Must return a JSON-serialisable dict for the response.
    get_telemetry:
        Callable returning a dict of current telemetry data.
    get_targets:
        Callable returning a list of target-record dicts.
    """

    def __init__(
        self,
        port: int = 8080,
        platform: str = "ugv",
        stream_port: int = 5000,
        on_command: Optional[Callable[[str, dict], dict]] = None,
        get_telemetry: Optional[Callable[[], Dict[str, Any]]] = None,
        get_targets: Optional[Callable[[], List[dict]]] = None,
    ) -> None:
        self._port = port
        self._platform = platform
        self._stream_port = stream_port
        self._on_command = on_command or (lambda cmd, args: {"ok": True})
        self._get_telemetry = get_telemetry or (lambda: {})
        self._get_targets = get_targets or (lambda: [])
        self._running = False
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        panel = self  # closure

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?")[0].rstrip("/")
                if path in ("", "/index", "/index.html"):
                    self._serve_html()
                elif path == "/api/telemetry":
                    self._serve_json(panel._get_telemetry())
                elif path == "/api/targets":
                    self._serve_json(panel._get_targets())
                elif path == "/api/health":
                    self._serve_json({"status": "ok", "platform": panel._platform})
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self) -> None:  # noqa: N802
                path = self.path.split("?")[0].rstrip("/")
                if path == "/api/command":
                    self._handle_command()
                else:
                    self.send_response(404)
                    self.end_headers()

            def _handle_command(self) -> None:
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length) if length > 0 else b"{}"
                    data = json.loads(body)
                    cmd = data.get("cmd", "")
                    args = data.get("args", {})
                    result = panel._on_command(cmd, args)
                    self._serve_json(result)
                except Exception as exc:
                    logger.warning("Command error: %s", exc)
                    self._serve_json({"error": str(exc)}, status=400)

            def _serve_json(self, obj, status: int = 200) -> None:
                body = json.dumps(obj, default=str).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def _serve_html(self) -> None:
                html = _build_html(panel._platform, panel._stream_port)
                body = html.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def log_message(self, format, *args):  # noqa: A002
                pass

        self._server = HTTPServer(("0.0.0.0", self._port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="operator-panel",
        )
        self._thread.start()
        logger.info("Operator panel started: http://0.0.0.0:%d/", self._port)

    def stop(self) -> None:
        self._running = False
        if self._server is not None:
            self._server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        logger.info("Operator panel stopped.")


# ======================================================================
# Embedded HTML/JS/CSS — fully self-contained, no external dependencies
# ======================================================================

def _build_html(platform: str, stream_port: int) -> str:
    """Return the complete HTML page for the operator panel."""
    is_ugv = platform == "ugv"
    kb_help = (
        "W/S = forward/back, A/D = turn, SPACE = stop, "
        "G = gripper toggle, R = release, T = transport, "
        "H = return home, E = emergency stop"
    ) if is_ugv else (
        "W/S = forward/back, A/D = left/right, "
        "↑/↓ = altitude, SPACE = stop/hover, "
        "P = payload toggle, R = release, T = transport, "
        "H = return home / RTL, E = emergency stop"
    )
    
    if is_ugv:
      mech_buttons = "".join([
          "<button class='btn-secondary' onclick=\"send('gripper_open')\">Open</button>",
          "<button class='btn-secondary' onclick=\"send('gripper_close')\">Close</button>",
          "<button class='btn-secondary' onclick=\"send('gripper_toggle')\">Toggle</button>",
      ])
    else:
      mech_buttons = "".join([
          "<button class='btn-secondary' onclick=\"send('payload_engage')\">Engage</button>",
          "<button class='btn-secondary' onclick=\"send('payload_release')\">Release</button>",
      ])

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Operator Panel — {platform.upper()}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: 'Segoe UI', system-ui, sans-serif;
  background: #0a0a0f;
  color: #e0e0e0;
  overflow: hidden;
  height: 100vh;
}}
.grid {{
  display: grid;
  grid-template-columns: 1fr 340px;
  grid-template-rows: auto 1fr auto;
  gap: 8px;
  padding: 8px;
  height: 100vh;
}}
header {{
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 6px 12px;
  background: #151520;
  border-radius: 8px;
}}
header h1 {{
  font-size: 1.1rem;
  color: #4fc3f7;
}}
.badge {{
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 0.8rem;
  font-weight: 600;
}}
.badge-ok {{ background: #1b5e20; color: #a5d6a7; }}
.badge-warn {{ background: #e65100; color: #ffcc02; }}
.badge-err {{ background: #b71c1c; color: #ef9a9a; }}
.fpv-container {{
  position: relative;
  background: #000;
  border-radius: 8px;
  overflow: hidden;
  min-height: 0;
}}
.fpv-container img {{
  width: 100%;
  height: 100%;
  object-fit: contain;
}}
.osd {{
  position: absolute;
  bottom: 8px;
  left: 8px;
  right: 8px;
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: #0f0;
  text-shadow: 0 0 4px #000;
  pointer-events: none;
}}
.sidebar {{
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
}}
.card {{
  background: #151520;
  border-radius: 8px;
  padding: 10px 12px;
}}
.card h2 {{
  font-size: 0.85rem;
  color: #4fc3f7;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}}
.telem-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  font-size: 0.8rem;
}}
.telem-grid dt {{ color: #888; }}
.telem-grid dd {{ color: #eee; font-weight: 600; }}
.btn-row {{
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}}
button {{
  padding: 6px 14px;
  border: none;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: filter 0.1s;
}}
button:hover {{ filter: brightness(1.2); }}
button:active {{ filter: brightness(0.8); }}
.btn-primary {{ background: #1565c0; color: #fff; }}
.btn-success {{ background: #2e7d32; color: #fff; }}
.btn-warning {{ background: #e65100; color: #fff; }}
.btn-danger {{ background: #c62828; color: #fff; }}
.btn-secondary {{ background: #424242; color: #ddd; }}
.target-list {{
  max-height: 150px;
  overflow-y: auto;
  font-size: 0.75rem;
}}
.target-list table {{ width: 100%; border-collapse: collapse; }}
.target-list th, .target-list td {{
  padding: 3px 6px;
  text-align: left;
  border-bottom: 1px solid #222;
}}
.target-list th {{ color: #888; font-weight: 600; }}
footer {{
  grid-column: 1 / -1;
  padding: 4px 12px;
  background: #151520;
  border-radius: 8px;
  font-size: 0.75rem;
  color: #666;
}}
.key-hint {{
  display: inline-block;
  background: #333;
  border-radius: 4px;
  padding: 1px 6px;
  font-family: monospace;
  font-size: 0.7rem;
  color: #ccc;
  margin: 0 2px;
}}
#status-dot {{
  width: 10px; height: 10px;
  border-radius: 50%;
  display: inline-block;
}}
.connected {{ background: #4caf50; box-shadow: 0 0 6px #4caf50; }}
.disconnected {{ background: #f44336; box-shadow: 0 0 6px #f44336; }}
</style>
</head>
<body>
<div class="grid">
  <header>
    <h1>🤖 {platform.upper()} Operator</h1>
    <span id="status-dot" class="disconnected"></span>
    <span id="conn-label" style="font-size:0.8rem">Connecting…</span>
    <span id="state-badge" class="badge badge-ok">INIT</span>
    <span style="flex:1"></span>
    <span style="font-size:0.75rem;color:#666" id="latency">—</span>
  </header>

  <div class="fpv-container">
    <img id="fpv" src="" alt="FPV stream loading…">
    <div class="osd">
      <span id="osd-left">GPS: —</span>
      <span id="osd-center">HDG: —°</span>
      <span id="osd-right">ALT: —m</span>
    </div>
  </div>

  <div class="sidebar">
    <div class="card">
      <h2>📡 Telemetry</h2>
      <dl class="telem-grid">
        <dt>Latitude</dt>  <dd id="t-lat">—</dd>
        <dt>Longitude</dt> <dd id="t-lon">—</dd>
        <dt>Altitude</dt>  <dd id="t-alt">—</dd>
        <dt>Heading</dt>   <dd id="t-hdg">—</dd>
        <dt>State</dt>     <dd id="t-state">—</dd>
        <dt>Targets</dt>   <dd id="t-targets">0</dd>
      </dl>
    </div>

    <div class="card">
      <h2>🎮 Controls</h2>
      <div class="btn-row">
        <button class="btn-success" onclick="send('start_mission')">▶ Start</button>
        <button class="btn-warning" onclick="send('stop')">⏹ Stop</button>
        <button class="btn-primary" onclick="send('return_home')">🏠 Home</button>
        <button class="btn-danger"  onclick="send('emergency_stop')">🚨 E-Stop</button>
      </div>
    </div>

    <div class="card">
      <h2>{"🦾 Gripper" if is_ugv else "📦 Payload"}</h2>
      <div class="btn-row">
        {mech_buttons}
      </div>
      <div style="font-size:0.75rem;margin-top:4px;color:#888">
        Status: <span id="mech-status">—</span>
      </div>
    </div>

    <div class="card">
      <h2>🎯 Targets</h2>
      <div class="target-list">
        <table>
          <thead><tr><th>#</th><th>Class</th><th>QR</th><th>GPS</th></tr></thead>
          <tbody id="target-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <footer>
    <strong>Keys:</strong> {kb_help}
  </footer>
</div>

<script>
const PLATFORM = "{platform}";
const STREAM_PORT = {stream_port};

// --- FPV stream setup ---
// Use the same host as the page but with the MJPEG port
const fpvImg = document.getElementById('fpv');
const host = location.hostname || '127.0.0.1';
fpvImg.src = 'http://' + host + ':' + STREAM_PORT + '/stream';
fpvImg.onerror = function() {{
  setTimeout(() => {{ fpvImg.src = 'http://' + host + ':' + STREAM_PORT + '/stream?' + Date.now(); }}, 2000);
}};

// --- Command sender ---
function send(cmd, args) {{
  args = args || {{}};
  fetch('/api/command', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{cmd: cmd, args: args}})
  }}).catch(() => {{}});
}}

// --- Keyboard handler ---
const keysDown = new Set();
document.addEventListener('keydown', (e) => {{
  if (keysDown.has(e.key)) return;
  keysDown.add(e.key);
  const k = e.key.toLowerCase();
  const cmds = {{
    'w': 'move_forward', 's': 'move_backward',
    'a': 'turn_left', 'd': 'turn_right',
    ' ': 'stop',
    'arrowup': PLATFORM === 'uav' ? 'altitude_up' : 'move_forward',
    'arrowdown': PLATFORM === 'uav' ? 'altitude_down' : 'move_backward',
    'arrowleft': 'turn_left', 'arrowright': 'turn_right',
    'g': PLATFORM === 'ugv' ? 'gripper_toggle' : 'payload_engage',
    'p': 'payload_toggle',
    'r': PLATFORM === 'ugv' ? 'gripper_open' : 'payload_release',
    't': 'transport',
    'h': 'return_home',
    'e': 'emergency_stop',
  }};
  if (cmds[k]) {{
    send(cmds[k]);
    e.preventDefault();
  }}
}});
document.addEventListener('keyup', (e) => {{
  keysDown.delete(e.key);
  const k = e.key.toLowerCase();
  if (['w','s','a','d','arrowup','arrowdown','arrowleft','arrowright'].includes(k)) {{
    send('stop');
  }}
}});

// --- Telemetry polling ---
async function pollTelemetry() {{
  try {{
    const t0 = Date.now();
    const res = await fetch('/api/telemetry');
    const dt = Date.now() - t0;
    document.getElementById('latency').textContent = dt + 'ms';
    const d = await res.json();
    document.getElementById('status-dot').className = 'connected';
    document.getElementById('conn-label').textContent = 'Connected';
    document.getElementById('t-lat').textContent = d.lat != null ? d.lat.toFixed(6) : '—';
    document.getElementById('t-lon').textContent = d.lon != null ? d.lon.toFixed(6) : '—';
    document.getElementById('t-alt').textContent = d.alt != null ? d.alt.toFixed(1) + 'm' : '—';
    document.getElementById('t-hdg').textContent = d.yaw_deg != null ? d.yaw_deg.toFixed(0) + '°' : '—';
    document.getElementById('t-state').textContent = d.state || '—';
    document.getElementById('t-targets').textContent = d.target_count || '0';
    document.getElementById('state-badge').textContent = d.state || 'INIT';
    // OSD
    document.getElementById('osd-left').textContent = 'GPS: ' + (d.lat != null ? d.lat.toFixed(5) + ',' + d.lon.toFixed(5) : '—');
    document.getElementById('osd-center').textContent = 'HDG: ' + (d.yaw_deg != null ? d.yaw_deg.toFixed(0) + '°' : '—');
    document.getElementById('osd-right').textContent = 'ALT: ' + (d.alt != null ? d.alt.toFixed(1) + 'm' : '—');
    // Mechanism status
    const ms = document.getElementById('mech-status');
    if (PLATFORM === 'ugv') {{
      ms.textContent = d.gripper_open ? '🟢 Open' : '🔴 Closed';
    }} else {{
      ms.textContent = d.payload_engaged ? '🔒 Engaged' : '🔓 Released';
    }}
  }} catch(e) {{
    document.getElementById('status-dot').className = 'disconnected';
    document.getElementById('conn-label').textContent = 'Disconnected';
  }}
}}
setInterval(pollTelemetry, 500);
pollTelemetry();

// --- Target list polling ---
async function pollTargets() {{
  try {{
    const res = await fetch('/api/targets');
    const targets = await res.json();
    const tbody = document.getElementById('target-tbody');
    tbody.innerHTML = targets.map((t, i) =>
      '<tr><td>' + (i+1) + '</td><td>' + (t.class_name||'?') + '</td><td>' +
      (t.qr_value||'—') + '</td><td>' + (t.lat ? t.lat.toFixed(5)+','+t.lon.toFixed(5) : '—') + '</td></tr>'
    ).join('');
  }} catch(e) {{}}
}}
setInterval(pollTargets, 2000);
pollTargets();
</script>
</body>
</html>"""
