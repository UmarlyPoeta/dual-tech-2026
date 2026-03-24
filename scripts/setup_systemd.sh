#!/bin/bash
# =============================================================================
# setup_systemd.sh — Install systemd services for Dual Tech 2026
#
# Creates:
#   - dualtech-core.service    (main mission process via docker compose)
#   - dualtech-foxglove.service (Foxglove WebSocket bridge)
#   - dualtech-thermal.service + timer (thermal throttle monitor)
#
# Usage:
#   chmod +x scripts/setup_systemd.sh && sudo ./scripts/setup_systemd.sh
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  [OK] $*${NC}"; }
fail() { echo -e "${RED}  [FAIL] $*${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/docker/docker-compose.yml"
RUN_USER="${SUDO_USER:-$USER}"

echo -e "${CYAN}${BOLD}"
echo "  ================================================================"
echo "    Dual Tech 2026 — systemd Service Installer"
echo "  ================================================================${NC}"
echo ""

# ---------------------------------------------------------------------------
# Detect docker compose command
# ---------------------------------------------------------------------------
if docker compose version > /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose > /dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    fail "docker compose not found. Run bootstrap.sh first."
    exit 1
fi

# ---------------------------------------------------------------------------
# dualtech-core.service — Main mission (docker compose)
# ---------------------------------------------------------------------------
cat > /etc/systemd/system/dualtech-core.service << SERVICE_EOF
[Unit]
Description=Dual Tech 2026 — Core Mission Service
After=network-online.target docker.service pigpiod.service
Wants=network-online.target docker.service
Requires=docker.service

[Service]
Type=simple
User=$RUN_USER
Group=docker
WorkingDirectory=$PROJECT_DIR
Environment=PLATFORM=ugv
ExecStartPre=$COMPOSE_CMD -f $COMPOSE_FILE pull --ignore-pull-failures
ExecStart=$COMPOSE_CMD -f $COMPOSE_FILE up --remove-orphans core
ExecStop=$COMPOSE_CMD -f $COMPOSE_FILE down
Restart=always
RestartSec=2
TimeoutStartSec=120
TimeoutStopSec=30

# OOM protection — don't kill the mission process
OOMScoreAdjust=-500

[Install]
WantedBy=multi-user.target
SERVICE_EOF
ok "dualtech-core.service created"

# ---------------------------------------------------------------------------
# dualtech-foxglove.service — Foxglove telemetry bridge
# ---------------------------------------------------------------------------
cat > /etc/systemd/system/dualtech-foxglove.service << SERVICE_EOF
[Unit]
Description=Dual Tech 2026 — Foxglove WebSocket Bridge
After=dualtech-core.service
BindsTo=dualtech-core.service

[Service]
Type=simple
User=$RUN_USER
Group=docker
WorkingDirectory=$PROJECT_DIR
ExecStart=$COMPOSE_CMD -f $COMPOSE_FILE up foxglove_bridge
ExecStop=$COMPOSE_CMD -f $COMPOSE_FILE stop foxglove_bridge
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE_EOF
ok "dualtech-foxglove.service created"

# ---------------------------------------------------------------------------
# dualtech-thermal.service + timer — Periodic thermal check
# ---------------------------------------------------------------------------
cat > /etc/systemd/system/dualtech-thermal.service << SERVICE_EOF
[Unit]
Description=Dual Tech 2026 — Thermal Monitor (one-shot)

[Service]
Type=oneshot
ExecStart=/bin/bash -c '
    TEMP_FILE="$PROJECT_DIR/logs/.thermal_state"
    mkdir -p "$(dirname "\$TEMP_FILE")"

    if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
        TEMP_MILLI=\$(cat /sys/class/thermal/thermal_zone0/temp)
        TEMP_C=\$(( TEMP_MILLI / 1000 ))
    else
        TEMP_C=0
    fi

    if [ "\$TEMP_C" -ge 85 ]; then
        echo "CRITICAL" > "\$TEMP_FILE"
        logger -t dualtech-thermal "CRITICAL: CPU temp \${TEMP_C}C"
    elif [ "\$TEMP_C" -ge 80 ]; then
        echo "THROTTLE" > "\$TEMP_FILE"
        logger -t dualtech-thermal "WARNING: CPU temp \${TEMP_C}C — throttling"
    else
        echo "OK" > "\$TEMP_FILE"
    fi
'
SERVICE_EOF

cat > /etc/systemd/system/dualtech-thermal.timer << TIMER_EOF
[Unit]
Description=Dual Tech 2026 — Thermal Monitor Timer

[Timer]
OnBootSec=30
OnUnitActiveSec=10

[Install]
WantedBy=timers.target
TIMER_EOF
ok "dualtech-thermal.service + timer created"

# ---------------------------------------------------------------------------
# Enable services
# ---------------------------------------------------------------------------
systemctl daemon-reload

systemctl enable dualtech-core.service
systemctl enable dualtech-foxglove.service
systemctl enable dualtech-thermal.timer

# Start the thermal timer now
systemctl start dualtech-thermal.timer 2>/dev/null || true

ok "All services enabled"

echo ""
echo -e "${CYAN}${BOLD}================================================================${NC}"
echo -e "${GREEN}${BOLD}  systemd services installed${NC}"
echo -e "${CYAN}${BOLD}================================================================${NC}"
echo ""
echo "  Manage with:"
echo "    sudo systemctl start dualtech-core"
echo "    sudo systemctl stop dualtech-core"
echo "    sudo systemctl status dualtech-core"
echo "    journalctl -u dualtech-core -f"
echo ""
echo "  Change platform (UAV):"
echo "    sudo systemctl edit dualtech-core"
echo "    # Add: Environment=PLATFORM=uav"
echo ""
