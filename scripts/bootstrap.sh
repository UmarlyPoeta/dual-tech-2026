#!/bin/bash
# =============================================================================
# bootstrap.sh — Dual Tech 2026  Zero-Touch Provisioning
# Runs on: Raspberry Pi 5 | Debian Bookworm/Trixie 64-bit, Ubuntu 25.x aarch64
# =============================================================================
# chmod +x bootstrap.sh && ./bootstrap.sh
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Colours and helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_DIR/bootstrap.log"
ERRORS=0

log()  { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG_FILE"; }
ok()   { echo -e "${GREEN}  [OK] $*${NC}";  log "[OK] $*"; }
warn() { echo -e "${YELLOW}  [WARN] $*${NC}"; log "[WARN] $*"; ERRORS=$((ERRORS + 1)); }
fail() { echo -e "${RED}  [FAIL] $*${NC}";   log "[FAIL] $*"; ERRORS=$((ERRORS + 1)); }
step() { echo -e "\n${CYAN}${BOLD}[$1] $2${NC}"; log "=== STEP $1: $2 ==="; }
die()  { echo -e "\n${RED}${BOLD}FATAL: $*${NC}"; log "FATAL: $*"; exit 1; }

echo -e "${CYAN}${BOLD}"
echo "  ================================================================"
echo "    Dual Tech 2026 — Bootstrap Script (Enterprise Edition)"
echo "    RPi 5 | Bookworm / Trixie / Ubuntu 25.x"
echo "  ================================================================${NC}"
echo ""

# ---------------------------------------------------------------------------
# Retry wrappers
# ---------------------------------------------------------------------------
apt_install() {
    local attempt=1
    while [ $attempt -le 3 ]; do
        if sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@" >> "$LOG_FILE" 2>&1; then
            return 0
        fi
        warn "apt install failed (attempt $attempt/3)..."
        sleep 5; attempt=$((attempt + 1))
    done
    fail "apt install failed for: $*"
    return 1
}

pip_install() {
    local attempt=1
    while [ $attempt -le 3 ]; do
        if "$PYTHON_BIN" -m pip install --quiet "$@" >> "$LOG_FILE" 2>&1; then
            return 0
        fi
        warn "pip install failed (attempt $attempt/3)..."
        sleep 5; attempt=$((attempt + 1))
    done
    fail "pip install failed for: $*"
    return 1
}

# ===========================================================================
# STEP 0: Pre-flight checks
# ===========================================================================
step "0/10" "Pre-flight checks"
> "$LOG_FILE"
log "Bootstrap started: $(date), USER=$USER, DIR=$PROJECT_DIR"

[ "$EUID" -eq 0 ] && die "Do not run as root. Use a regular user with sudo."
sudo -v 2>/dev/null || die "No sudo access."
ping -c 1 -W 5 8.8.8.8 > /dev/null 2>&1 || die "No internet connectivity."

source /etc/os-release 2>/dev/null || true
OS_ID="${ID:-unknown}"
OS_CODENAME="${VERSION_CODENAME:-unknown}"
log "OS: ${PRETTY_NAME:-unknown}, ID=$OS_ID, CODENAME=$OS_CODENAME"
ok "OS: ${PRETTY_NAME:-unknown}"

ARCH=$(uname -m)
[[ "$ARCH" == "aarch64" ]] && ok "Architecture: aarch64" || warn "Architecture: $ARCH (expected aarch64)"

# Neutralise pyenv if present
if command -v pyenv > /dev/null 2>&1 || [ -n "${PYENV_ROOT:-}" ]; then
    warn "pyenv detected — removing from PATH for this session"
    export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v "\.pyenv" | tr '\n' ':' | sed 's/:$//')
    unset PYENV_ROOT PYENV_VERSION PYENV_VERSION_FILE PYENV_HOOK_PATH 2>/dev/null || true
fi

if [ -f /usr/bin/python3 ]; then
    SYSTEM_PYTHON="/usr/bin/python3"
elif [ -f /usr/bin/python3.13 ]; then
    SYSTEM_PYTHON="/usr/bin/python3.13"
elif [ -f /usr/bin/python3.11 ]; then
    SYSTEM_PYTHON="/usr/bin/python3.11"
else
    die "System python3 not found. Install via: sudo apt install python3"
fi

PY_VER=$($SYSTEM_PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "System Python: $SYSTEM_PYTHON ($PY_VER)"

FREE_KB=$(df "$PROJECT_DIR" | awk 'NR==2 {print $4}')
[ "$FREE_KB" -lt 3145728 ] && warn "Low disk space: $(echo "scale=1; $FREE_KB/1048576" | bc) GB (min 3 GB recommended)"

# ===========================================================================
# STEP 1: System update
# ===========================================================================
step "1/10" "System update"
sudo apt-get update >> "$LOG_FILE" 2>&1 || die "apt update failed."
sudo DEBIAN_FRONTEND=noninteractive apt-get full-upgrade -y >> "$LOG_FILE" 2>&1 || warn "full-upgrade had warnings"
ok "System updated"

# ===========================================================================
# STEP 2: System packages
# ===========================================================================
step "2/10" "System packages"

echo "  -> Build tools..."
apt_install \
    python3-venv python3-pip python3-dev python3-full \
    build-essential git curl wget bc swig python-is-python3

echo "  -> C libraries for pip wheel builds..."
apt_install \
    libcap-dev libjpeg-dev libopenjp2-7-dev \
    libzbar0 libzbar-dev libssl-dev libffi-dev

if apt-cache show libatlas-base-dev > /dev/null 2>&1; then
    apt_install libatlas-base-dev
else
    apt_install libatlas3-base || true
fi

echo "  -> Hardware tools..."
apt_install i2c-tools v4l-utils ffmpeg usbutils

echo "  -> GPIO (lgpio + gpiozero from apt)..."
apt_install python3-lgpio python3-gpiozero || warn "GPIO apt packages failed"

echo "  -> libgpiod (for stepper motor control)..."
apt_install gpiod libgpiod-dev python3-libgpiod || warn "libgpiod not available"

echo "  -> pigpio daemon (for jitter-free servo PWM)..."
apt_install pigpio python3-pigpio || warn "pigpio not available via apt"

echo "  -> libcamera stack..."
if apt-cache show python3-libcamera > /dev/null 2>&1; then
    apt_install python3-libcamera python3-kms++ libcamera-dev
else
    warn "python3-libcamera not available — camera may not work"
fi

if apt-cache show python3-picamera2 > /dev/null 2>&1; then
    apt_install python3-picamera2
else
    warn "picamera2 not in apt — will install via pip"
    PICAMERA2_FROM_PIP=1
fi

if apt-cache show python3-prctl > /dev/null 2>&1; then
    apt_install python3-prctl
fi

if apt-cache show python3-opencv > /dev/null 2>&1; then
    apt_install python3-opencv
fi

ok "System packages installed"

# ===========================================================================
# STEP 3: Hardware interfaces (I2C, UART, SPI, fan)
# ===========================================================================
step "3/10" "Hardware interfaces"

CONFIG_FILE=""
for cfg in /boot/firmware/config.txt /boot/config.txt; do
    [ -f "$cfg" ] && CONFIG_FILE="$cfg" && break
done

if [ -n "$CONFIG_FILE" ]; then
    for param in "dtparam=i2c_arm=on" "dtparam=spi=on" "enable_uart=1"; do
        grep -q "^${param}" "$CONFIG_FILE" \
            || { echo "$param" | sudo tee -a "$CONFIG_FILE" >> "$LOG_FILE"; ok "$param enabled"; }
    done

    # RPi5 active cooling — fan kicks in at 60C
    if ! grep -q "dtoverlay=gpio-fan" "$CONFIG_FILE" 2>/dev/null; then
        echo "dtoverlay=gpio-fan,gpiopin=14,temp=60000" | sudo tee -a "$CONFIG_FILE" >> "$LOG_FILE"
        ok "Active cooling: fan trigger at 60C"
    fi
else
    warn "config.txt not found — skipping boot config"
fi

sudo modprobe i2c-dev 2>/dev/null && ok "i2c-dev module loaded" || warn "i2c-dev not available until reboot"

# ===========================================================================
# STEP 4: udev rules for fixed device symlinks
# ===========================================================================
step "4/10" "udev rules"

UDEV_RULES="/etc/udev/rules.d/99-dualtech.rules"
sudo tee "$UDEV_RULES" > /dev/null << 'UDEV_EOF'
# Dual Tech 2026 — fixed device symlinks
# Reload: sudo udevadm control --reload-rules && sudo udevadm trigger

# SpeedyBee F4 V4 flight controller (CP210x or STM32 CDC)
# Adjust idVendor/idProduct after running: udevadm info -a /dev/ttyUSBx
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", SYMLINK+="speedybee", MODE="0666"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="5740", SYMLINK+="speedybee", MODE="0666"

# USB camera — first video capture device gets a stable name
SUBSYSTEM=="video4linux", ATTR{index}=="0", ATTRS{idVendor}=="*",  KERNEL=="video[0-9]*", SYMLINK+="front_cam", MODE="0666"

# GPS UART (if USB-UART adapter)
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", SYMLINK+="gps_uart", MODE="0666"
SUBSYSTEM=="tty", ATTRS{idVendor}=="067b", ATTRS{idProduct}=="2303", SYMLINK+="gps_uart", MODE="0666"
UDEV_EOF

sudo udevadm control --reload-rules 2>/dev/null || true
sudo udevadm trigger 2>/dev/null || true
ok "udev rules installed at $UDEV_RULES"

# ===========================================================================
# STEP 5: User groups
# ===========================================================================
step "5/10" "User groups"

for GROUP in gpio video i2c dialout spi tty docker; do
    if getent group "$GROUP" > /dev/null 2>&1; then
        sudo usermod -aG "$GROUP" "$USER" && ok "$USER -> group $GROUP"
    fi
done

# ===========================================================================
# STEP 6: Performance governor
# ===========================================================================
step "6/10" "Performance governor"

if [ -f /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]; then
    for cpu_gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        echo "performance" | sudo tee "$cpu_gov" > /dev/null 2>&1 || true
    done
    ok "CPU governor set to 'performance'"

    # Persist via cron @reboot
    CRON_CMD='@reboot for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > "$g" 2>/dev/null; done'
    ( sudo crontab -l 2>/dev/null | grep -v "scaling_governor"; echo "$CRON_CMD" ) | sudo crontab - 2>/dev/null
    ok "Performance governor persisted via cron"
else
    warn "cpufreq not available — governor not set"
fi

# ===========================================================================
# STEP 7: pigpiod systemd service
# ===========================================================================
step "7/10" "pigpiod daemon"

if command -v pigpiod > /dev/null 2>&1; then
    sudo systemctl enable pigpiod 2>/dev/null || true
    sudo systemctl start pigpiod 2>/dev/null || true
    ok "pigpiod enabled and started"
else
    warn "pigpiod binary not found — servo PWM will fall back to software"
fi

# ===========================================================================
# STEP 8: Docker
# ===========================================================================
step "8/10" "Docker Engine"

if command -v docker > /dev/null 2>&1; then
    ok "Docker already installed: $(docker --version)"
else
    echo "  -> Installing Docker via convenience script..."
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh >> "$LOG_FILE" 2>&1
    sudo sh /tmp/get-docker.sh >> "$LOG_FILE" 2>&1 || fail "Docker install failed"
    rm -f /tmp/get-docker.sh
    if command -v docker > /dev/null 2>&1; then
        ok "Docker installed: $(docker --version)"
    else
        fail "Docker binary not found after install"
    fi
fi

sudo usermod -aG docker "$USER" 2>/dev/null || true
sudo systemctl enable docker 2>/dev/null || true
sudo systemctl start docker 2>/dev/null || true

if ! command -v docker-compose > /dev/null 2>&1 && ! docker compose version > /dev/null 2>&1; then
    echo "  -> Installing docker-compose plugin..."
    sudo apt-get install -y docker-compose-plugin >> "$LOG_FILE" 2>&1 || warn "docker-compose plugin install failed"
fi
ok "Docker ready"

# ===========================================================================
# STEP 9: Python venv + dependencies
# ===========================================================================
step "9/10" "Python virtual environment"

cd "$PROJECT_DIR"

if [ -d "venv" ]; then
    warn "Removing existing venv..."
    rm -rf venv
fi

$SYSTEM_PYTHON -m venv venv --system-site-packages \
    || die "Cannot create venv. Ensure python3-venv is installed."

PYTHON_BIN="$PROJECT_DIR/venv/bin/python3"
PIP_BIN="$PROJECT_DIR/venv/bin/pip"

ok "venv created: $($PYTHON_BIN --version)"

"$PYTHON_BIN" -m pip install --quiet --upgrade pip setuptools wheel >> "$LOG_FILE" 2>&1

# Symlink system-only packages into venv
VENV_SITE="$PROJECT_DIR/venv/lib/python${PY_VER}/site-packages"

symlink_system_pkg() {
    local name="$1" src_glob="$2" linked=0
    for src in /usr/lib/python3/dist-packages/$src_glob; do
        [ -e "$src" ] || continue
        local dst="$VENV_SITE/$(basename "$src")"
        [ -e "$dst" ] || ln -s "$src" "$dst" >> "$LOG_FILE" 2>&1
        linked=1
    done
    [ "$linked" -eq 1 ] && ok "Symlink: $name" || warn "Symlink: $name — not found"
}

symlink_system_pkg "libcamera"   "libcamera"
symlink_system_pkg "libcamera .so" "_libcamera*.so"
symlink_system_pkg "lgpio.py"    "lgpio.py"
symlink_system_pkg "lgpio .so"   "_lgpio*.so"
symlink_system_pkg "kms (pykms)" "kms"
symlink_system_pkg "pykms"       "pykms"
symlink_system_pkg "prctl"       "prctl.py"
symlink_system_pkg "prctl .so"   "_prctl*.so"
symlink_system_pkg "gpiozero"    "gpiozero"
symlink_system_pkg "colorzero"   "colorzero"
symlink_system_pkg "serial"      "serial"
symlink_system_pkg "cv2"         "cv2"
symlink_system_pkg "gpiod"       "gpiod*"
symlink_system_pkg "pigpio"      "pigpio*"

# Install pip requirements
if [ -f "$PROJECT_DIR/requirements.txt" ]; then
    "$PYTHON_BIN" -m pip install --quiet -r "$PROJECT_DIR/requirements.txt" >> "$LOG_FILE" 2>&1 \
        || warn "Some requirements failed — installing critical ones individually"
fi

pip_install "pyyaml>=6.0"
pip_install "pynmea2>=1.19"
pip_install "pyzbar>=0.1.9"
pip_install "pymavlink>=2.4.40"
pip_install "dronekit>=2.9.2"
pip_install "ultralytics>=8.0"
pip_install "click>=8.0"
pip_install "websockets>=12.0"
pip_install "pytest>=7.0" "pytest-cov>=4.0"

if ! "$PYTHON_BIN" -c "import cv2" > /dev/null 2>&1; then
    pip_install "opencv-python>=4.8"
fi
if ! "$PYTHON_BIN" -c "import picamera2" > /dev/null 2>&1; then
    pip_install "picamera2" || warn "picamera2 pip failed — OpenCV fallback in camera.py"
fi

ok "Python dependencies installed"

# ===========================================================================
# STEP 10: Log rotation + verification
# ===========================================================================
step "10/10" "Log rotation and verification"

# System-level log rotation for competition logs
sudo tee /etc/logrotate.d/dualtech > /dev/null << LOGROTATE_EOF
$PROJECT_DIR/logs/*/*.log {
    daily
    rotate 3
    maxsize 50M
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
}
$PROJECT_DIR/logs/*/*.csv {
    weekly
    rotate 2
    maxsize 100M
    missingok
    notifempty
    copytruncate
}
LOGROTATE_EOF
ok "logrotate config installed at /etc/logrotate.d/dualtech"

# Create project directories
mkdir -p "$PROJECT_DIR/models" "$PROJECT_DIR/logs" "$PROJECT_DIR/config/hardware"

# Verification
echo ""
echo -e "  ${BOLD}Python import checks:${NC}"

check() {
    local label="$1" code="$2" out
    if out=$("$PYTHON_BIN" -c "$code" 2>&1); then
        ok "$label -> $out"
    else
        fail "$label -> ${out:0:100}"
    fi
}

check "numpy"        "import numpy as np; print(np.__version__)"
check "cv2"          "import cv2; print(cv2.__version__)"
check "yaml"         "import yaml; print(yaml.__version__)"
check "lgpio"        "import lgpio; print('OK')"
check "gpiozero"     "import gpiozero; print(gpiozero.__version__)"
check "serial"       "import serial; print(serial.__version__)"
check "pynmea2"      "import pynmea2; print('OK')"
check "pyzbar"       "import pyzbar; print('OK')"
check "pymavlink"    "from pymavlink import mavutil; print('OK')"
check "dronekit"     "import dronekit; print('OK')"
check "ultralytics"  "import ultralytics; print(ultralytics.__version__)"
check "click"        "import click; print(click.__version__)"
check "websockets"   "import websockets; print(websockets.__version__)"

echo ""
echo -e "  ${BOLD}Hardware:${NC}"
ls /dev/i2c-* 2>/dev/null | head -1 > /dev/null && ok "I2C: $(ls /dev/i2c-* 2>/dev/null | tr '\n' ' ')" || warn "I2C: not available (reboot required)"
ls /dev/ttyAMA* 2>/dev/null | head -1 > /dev/null && ok "UART: $(ls /dev/ttyAMA* 2>/dev/null | tr '\n' ' ')" || warn "UART: not available"
ls /dev/video* 2>/dev/null | head -1 > /dev/null && ok "Video: $(ls /dev/video* 2>/dev/null | head -3 | tr '\n' ' ')" || warn "Video: no devices"
[ -e /dev/gpiochip0 ] && ok "GPIO: /dev/gpiochip0" || warn "GPIO: /dev/gpiochip0 not found"
pgrep pigpiod > /dev/null 2>&1 && ok "pigpiod: running" || warn "pigpiod: not running"
command -v docker > /dev/null 2>&1 && ok "Docker: $(docker --version 2>/dev/null | head -1)" || warn "Docker: not installed"

[ -f "$PROJECT_DIR/models/best.pt" ] || warn "No models/best.pt — required before mission!"

# Convenience activate script
cat > "$PROJECT_DIR/activate.sh" << ACTIVATE_EOF
#!/bin/bash
export PATH=\$(echo "\$PATH" | tr ':' '\n' | grep -v '\.pyenv' | tr '\n' ':' | sed 's/:\$//')
unset PYENV_ROOT PYENV_VERSION 2>/dev/null || true
source "$PROJECT_DIR/venv/bin/activate"
echo "venv active: \$(python3 --version) @ \$(which python3)"
ACTIVATE_EOF
chmod +x "$PROJECT_DIR/activate.sh"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${CYAN}${BOLD}================================================================${NC}"
if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}  BOOTSTRAP COMPLETE — NO ERRORS${NC}"
else
    echo -e "${YELLOW}${BOLD}  BOOTSTRAP COMPLETE — $ERRORS WARNINGS${NC}"
    echo -e "     Details: ${BOLD}$LOG_FILE${NC}"
fi
echo -e "${CYAN}${BOLD}================================================================${NC}"
echo ""
echo -e "  ${BOLD}NEXT STEPS:${NC}"
echo ""
echo -e "  ${YELLOW}1. REBOOT (GPIO, UART, user groups, fan):${NC}"
echo -e "       sudo reboot"
echo ""
echo -e "  ${YELLOW}2. Activate venv:${NC}"
echo -e "       source $PROJECT_DIR/activate.sh"
echo ""
echo -e "  ${YELLOW}3. Run diagnostics:${NC}"
echo -e "       python cli/dualtech.py doctor"
echo ""
echo -e "  ${YELLOW}4. Start with Docker:${NC}"
echo -e "       python cli/dualtech.py start ugv --docker --with-ros"
echo ""
echo -e "  Log: ${BOLD}$LOG_FILE${NC}"
echo ""
