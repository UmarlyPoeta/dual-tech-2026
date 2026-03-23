#!/bin/bash
# =============================================================================
# setup_rpi.sh — Dual Tech 2026 na Raspberry Pi 5 (Bookworm 64-bit)
# =============================================================================
# Uruchom na świeżym Raspberry Pi OS Bookworm 64-bit:
#   chmod +x setup_rpi.sh && ./setup_rpi.sh
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }

echo "============================================================"
echo "  Dual Tech 2026 — Setup (Bookworm, Python 3.11, RPi 5)"
echo "============================================================"

# ---------------------------------------------------------------------------
# 1. System update
# ---------------------------------------------------------------------------
echo ""
echo "[1/6] Aktualizacja systemu..."
sudo apt update && sudo apt full-upgrade -y

# ---------------------------------------------------------------------------
# 2. Pakiety systemowe
#
# DLACZEGO APT a nie pip dla tych pakietów:
#   - python3-lgpio / python3-gpiozero   → wymagają binarnego lgpio skompilowanego
#                                          pod konkretne jądro RPi; pip daje inną wersję
#   - python3-picamera2 / python3-libcamera → zależą od systemowej libcamera
#                                             której pip nie zainstaluje
#   - python3-opencv                      → unikamy konfliktu abi; wersja 4.6
#                                           z Bookworm wystarczy do projektu
# ---------------------------------------------------------------------------
echo ""
echo "[2/6] Instalacja pakietów systemowych..."
sudo apt install -y \
    python3-venv \
    python3-pip \
    python3-picamera2 \
    python3-libcamera \
    python3-kms++ \
    python3-pykms \
    python3-lgpio \
    python3-gpiozero \
    python3-opencv \
    python3-numpy \
    python3-serial \
    python3-pil \
    libcap-dev \
    libatlas-base-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    libzbar0 \
    libzbar-dev \
    ffmpeg \
    v4l-utils \
    i2c-tools \
    git \
    curl

# ---------------------------------------------------------------------------
# 3. Uprawnienia użytkownika
# ---------------------------------------------------------------------------
echo ""
echo "[3/6] Konfiguracja uprawnień użytkownika ($USER)..."
sudo usermod -aG gpio,video,i2c,dialout,spi "$USER"
ok "Dodano $USER do grup: gpio, video, i2c, dialout, spi"
warn "Uprawnienia zadziałają po restarcie!"

# ---------------------------------------------------------------------------
# 4. Wirtualne środowisko z --system-site-packages
#
# --system-site-packages = venv widzi python3-lgpio, python3-gpiozero,
# python3-picamera2, python3-opencv zainstalowane przez apt.
# Bez tej flagi te pakiety byłyby niewidoczne.
# ---------------------------------------------------------------------------
echo ""
echo "[4/6] Tworzenie środowiska wirtualnego (venv)..."
cd "$SCRIPT_DIR"

if [ -d "venv" ]; then
    warn "Istniejący venv znaleziony — usuwam i tworzę od nowa..."
    rm -rf venv
fi

python3 -m venv venv --system-site-packages
source venv/bin/activate
ok "venv aktywny: $(which python3)"
ok "Python: $(python3 --version)"

# ---------------------------------------------------------------------------
# 5. Instalacja pip — TYLKO pakiety niedostępne przez apt
#
# Celowo pomijamy przez pip:
#   - opencv-python     → używamy python3-opencv z apt (brak konfliktu abi)
#   - lgpio             → z apt (wersja skompilowana pod jądro RPi)
#   - gpiozero          → z apt
#   - picamera2         → z apt (wymaga systemowej libcamera)
#   - numpy             → z apt (unikamy problemu z BLAS/LAPACK)
# ---------------------------------------------------------------------------
echo ""
echo "[5/6] Instalacja zależności pip..."
pip install --upgrade pip setuptools wheel

pip install \
    "pyyaml>=6.0" \
    "ultralytics>=8.0" \
    "pyzbar>=0.1.9" \
    "pynmea2>=1.19" \
    "pymavlink>=2.4.40" \
    "dronekit>=2.9.2" \
    "pytest>=7.0" \
    "pytest-cov>=4.0"

# dronekit wymaga starszego MAVProxy — jeśli zassie zbyt nową wersję mavlink:
# pip install "MAVProxy==1.8.71" --no-deps  # odkomentuj jeśli dronekit pada

# ---------------------------------------------------------------------------
# 6. Weryfikacja
# ---------------------------------------------------------------------------
echo ""
echo "[6/6] Weryfikacja instalacji..."
echo ""

check_import() {
    local label=$1; local expr=$2
    if python3 -c "$expr" 2>/dev/null; then
        ok "$label"
    else
        fail "$label"
    fi
}

check_import "opencv (cv2)"   "import cv2; print(f'  opencv {cv2.__version__}')"
check_import "numpy"          "import numpy as np; print(f'  numpy {np.__version__}')"
check_import "lgpio"          "import lgpio; print('  lgpio OK')"
check_import "gpiozero"       "import gpiozero; print(f'  gpiozero {gpiozero.__version__}')"
check_import "pyserial"       "import serial; print(f'  pyserial {serial.__version__}')"
check_import "pynmea2"        "import pynmea2; print('  pynmea2 OK')"
check_import "pyyaml"         "import yaml; print(f'  pyyaml {yaml.__version__}')"
check_import "ultralytics"    "import ultralytics; print(f'  ultralytics {ultralytics.__version__}')"
check_import "pymavlink"      "import pymavlink; print('  pymavlink OK')"
check_import "dronekit"       "import dronekit; print('  dronekit OK')"
check_import "pyzbar"         "import pyzbar; print('  pyzbar OK')"
check_import "picamera2"      "import picamera2; print('  picamera2 OK')" || warn "picamera2 — OK jeśli nie masz podłączonej kamery"

# Sprawdź I2C i SPI
echo ""
if ls /dev/i2c-* 2>/dev/null | head -1 | grep -q i2c; then
    ok "I2C: $(ls /dev/i2c-*)"
else
    warn "I2C: brak urządzeń /dev/i2c-* (może wymagać włączenia w raspi-config)"
fi

# Katalog na wagi YOLO
mkdir -p "$SCRIPT_DIR/models"
if [ ! -f "$SCRIPT_DIR/models/best.pt" ]; then
    warn "Brak models/best.pt — wgraj wagi YOLO przed uruchomieniem misji"
fi

echo ""
echo "============================================================"
echo "  Setup zakończony pomyślnie!"
echo "============================================================"
echo ""
echo "  Następne kroki:"
echo "  1. ZRESTARTUJ RPi (wymagane dla uprawnień GPIO):"
echo "       sudo reboot"
echo ""
echo "  2. Po restarcie aktywuj środowisko:"
echo "       cd $SCRIPT_DIR && source venv/bin/activate"
echo ""
echo "  3. Wgraj wagi modelu YOLO:"
echo "       cp /path/to/best.pt models/best.pt"
echo ""
echo "  4. Uruchom testy:"
echo "       python -m pytest tests/ -v"
echo ""
echo "  5. Uruchom misję UGV / UAV:"
echo "       python main_ugv.py"
echo "       python main_uav.py"
echo "============================================================"