#!/bin/bash
# =============================================================================
# setup_rpi.sh — Dual Tech 2026 | Raspberry Pi 5 | Bookworm 64-bit
# =============================================================================
# chmod +x setup_rpi.sh && ./setup_rpi.sh
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Kolory i helpery
# ---------------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/setup_rpi.log"
ERRORS=0

log()  { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG_FILE"; }
ok()   { echo -e "${GREEN}  ✔ $*${NC}";  log "[OK] $*"; }
warn() { echo -e "${YELLOW}  ⚠ $*${NC}"; log "[WARN] $*"; }
fail() { echo -e "${RED}  ✘ $*${NC}";   log "[FAIL] $*"; ERRORS=$((ERRORS + 1)); }
step() { echo -e "\n${CYAN}${BOLD}[$1] $2${NC}"; log "--- STEP $1: $2 ---"; }
die()  { echo -e "\n${RED}${BOLD}FATAL: $*${NC}"; log "FATAL: $*"; exit 1; }

echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║        Dual Tech 2026 — Setup Script v2.0               ║"
echo "  ║        Raspberry Pi 5 | Bookworm 64-bit                 ║"
echo "  ╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ---------------------------------------------------------------------------
# Wrapper z retry dla apt i pip
# ---------------------------------------------------------------------------
apt_install() {
    local attempt=1
    while [ $attempt -le 3 ]; do
        if sudo apt-get install -y --no-install-recommends "$@" >> "$LOG_FILE" 2>&1; then
            return 0
        fi
        warn "apt install nieudany (próba $attempt/3), czekam 5s..."
        sleep 5
        attempt=$((attempt + 1))
    done
    fail "apt install nie powiodło się dla: $*"
    return 1
}

pip_install() {
    local attempt=1
    while [ $attempt -le 3 ]; do
        if pip install --quiet "$@" >> "$LOG_FILE" 2>&1; then
            return 0
        fi
        warn "pip install nieudany (próba $attempt/3), czekam 5s..."
        sleep 5
        attempt=$((attempt + 1))
    done
    fail "pip install nie powiodło się dla: $*"
    return 1
}

# ---------------------------------------------------------------------------
# 0. Sprawdzenia wstępne
# ---------------------------------------------------------------------------
step "0/7" "Sprawdzanie wymagań wstępnych"

> "$LOG_FILE"
log "Skrypt uruchomiony: $(date)"
log "User: $USER, PWD: $SCRIPT_DIR"

# Nie uruchamiaj jako root
if [ "$EUID" -eq 0 ]; then
    die "Nie uruchamiaj jako root. Użyj zwykłego użytkownika (np. 'pi') z sudo."
fi

# Sprawdź sudo
if ! sudo -v 2>/dev/null; then
    die "Użytkownik $USER nie ma dostępu do sudo."
fi
ok "sudo: OK"

# Sprawdź OS
if [ -f /etc/os-release ]; then
    source /etc/os-release
    log "OS: ${PRETTY_NAME:-nieznany}"
    if [[ "${VERSION_CODENAME:-}" != "bookworm" ]]; then
        warn "Ten skrypt jest pisany pod Bookworm. Wykryto: ${VERSION_CODENAME:-nieznany}"
        warn "Kontynuowanie może spowodować błędy!"
        read -r -p "  Kontynuować mimo to? [t/N] " REPLY
        [[ "$REPLY" =~ ^[tTyY]$ ]] || die "Przerwano przez użytkownika."
    else
        ok "OS: ${PRETTY_NAME}"
    fi
else
    warn "Nie można odczytać /etc/os-release — kontynuuję bez weryfikacji OS"
fi

# Sprawdź architekturę
ARCH=$(uname -m)
log "Architektura: $ARCH"
if [[ "$ARCH" != "aarch64" ]]; then
    warn "Oczekiwano aarch64 (64-bit), znaleziono: $ARCH"
    warn "RPi 5 wymaga Bookworm 64-bit!"
    read -r -p "  Kontynuować? [t/N] " REPLY
    [[ "$REPLY" =~ ^[tTyY]$ ]] || die "Przerwano."
else
    ok "Architektura: $ARCH (64-bit)"
fi

# Sprawdź wersję Pythona (Bookworm = 3.11)
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
log "Python: $PY_VER"
if [[ "$PY_VER" != "3.11" ]]; then
    warn "Python $PY_VER — oczekiwano 3.11 (domyślny Bookworm). lgpio może nie działać!"
else
    ok "Python: $PY_VER"
fi

# Sprawdź internet
if ! ping -c 1 -W 5 8.8.8.8 > /dev/null 2>&1; then
    die "Brak połączenia z internetem."
fi
ok "Internet: OK"

# Sprawdź wolne miejsce (min 3 GB)
FREE_KB=$(df "$SCRIPT_DIR" | awk 'NR==2 {print $4}')
if [ "$FREE_KB" -lt 3145728 ]; then
    FREE_GB=$(echo "scale=1; $FREE_KB / 1048576" | bc)
    die "Za mało miejsca: ${FREE_GB} GB. Wymagane min. 3 GB."
fi
ok "Miejsce na dysku: OK"

# ---------------------------------------------------------------------------
# 1. Aktualizacja systemu
# ---------------------------------------------------------------------------
step "1/7" "Aktualizacja systemu"

sudo apt-get update >> "$LOG_FILE" 2>&1 \
    || die "apt update nie powiodło się. Sprawdź internet i /etc/apt/sources.list."

sudo DEBIAN_FRONTEND=noninteractive apt-get full-upgrade -y >> "$LOG_FILE" 2>&1 \
    || warn "full-upgrade zakończył się z błędami (kontynuuję)"

ok "System zaktualizowany"

# ---------------------------------------------------------------------------
# 2. Pakiety systemowe
#
# ZASADA: pakiety z natywnymi zależnościami (GPIO, libcamera, OpenCV)
# instalujemy PRZEZ APT. pip dostaje TYLKO pure-Python.
#
# Dlaczego NIE pip dla tych pakietów:
#   lgpio/gpiozero  → skompilowane pod konkretne jądro RPi; pip daje złą wersję
#   picamera2       → wymaga systemowej libcamera której pip nie zainstaluje
#   opencv          → konflikty ABI; python3-opencv z apt jest stabilny
#   numpy           → zależy od BLAS/LAPACK; wersja z apt pasuje do opencv
# ---------------------------------------------------------------------------
step "2/7" "Instalacja pakietów systemowych (apt)"

echo "  → Narzędzia bazowe..."
apt_install \
    python3-venv \
    python3-pip \
    python3-dev \
    build-essential \
    git curl wget bc

echo "  → Biblioteki C wymagane przez pip..."
apt_install \
    libcap-dev \
    libatlas-base-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    libzbar0 \
    libzbar-dev \
    libssl-dev \
    libffi-dev

echo "  → Narzędzia sprzętowe..."
apt_install \
    i2c-tools \
    v4l-utils \
    ffmpeg

echo "  → GPIO i kamera (MUSZĄ być z apt, nie pip)..."
apt_install \
    python3-lgpio \
    python3-gpiozero \
    python3-picamera2 \
    python3-libcamera \
    python3-kms++ \
    python3-pykms

echo "  → OpenCV i NumPy (z apt — unika konfliktów ABI)..."
apt_install \
    python3-opencv \
    python3-numpy \
    python3-pil \
    python3-serial

ok "Wszystkie pakiety systemowe zainstalowane"

# ---------------------------------------------------------------------------
# 3. Interfejsy sprzętowe
# ---------------------------------------------------------------------------
step "3/7" "Konfiguracja interfejsów sprzętowych"

CONFIG_FILE="/boot/firmware/config.txt"
# Fallback dla starszych layoutów
if [ ! -f "$CONFIG_FILE" ]; then
    CONFIG_FILE="/boot/config.txt"
fi

if [ ! -f "$CONFIG_FILE" ]; then
    warn "Nie znaleziono config.txt — pomijam konfigurację interfejsów"
else
    # I2C (PCA9685 sterowanie serwami)
    if ! grep -q "^dtparam=i2c_arm=on" "$CONFIG_FILE"; then
        echo "dtparam=i2c_arm=on" | sudo tee -a "$CONFIG_FILE" >> "$LOG_FILE"
        ok "I2C: włączony"
    else
        ok "I2C: już włączony"
    fi

    # SPI
    if ! grep -q "^dtparam=spi=on" "$CONFIG_FILE"; then
        echo "dtparam=spi=on" | sudo tee -a "$CONFIG_FILE" >> "$LOG_FILE"
        ok "SPI: włączony"
    else
        ok "SPI: już włączony"
    fi

    # UART (GPS)
    if ! grep -q "^enable_uart=1" "$CONFIG_FILE"; then
        echo "enable_uart=1" | sudo tee -a "$CONFIG_FILE" >> "$LOG_FILE"
        ok "UART: włączony"
    else
        ok "UART: już włączony"
    fi
fi

# Załaduj i2c-dev od razu (bez restartu)
sudo modprobe i2c-dev 2>/dev/null \
    && ok "Moduł i2c-dev: załadowany" \
    || warn "Moduł i2c-dev: nie załadowany (normalnie po restarcie)"

# ---------------------------------------------------------------------------
# 4. Uprawnienia użytkownika
# ---------------------------------------------------------------------------
step "4/7" "Uprawnienia użytkownika"

for GROUP in gpio video i2c dialout spi; do
    if getent group "$GROUP" > /dev/null 2>&1; then
        sudo usermod -aG "$GROUP" "$USER" && ok "Dodano $USER → $GROUP"
    else
        warn "Grupa $GROUP nie istnieje — pomijam"
    fi
done

# ---------------------------------------------------------------------------
# 5. Wirtualne środowisko Python
# ---------------------------------------------------------------------------
step "5/7" "Środowisko wirtualne Python"

cd "$SCRIPT_DIR"

if [ -d "venv" ]; then
    warn "Usuwam istniejący venv..."
    rm -rf venv
fi

# --system-site-packages = venv widzi lgpio, gpiozero, picamera2, opencv z apt
# Bez tej flagi te pakiety byłyby niewidoczne i pip próbowałby je zainstalować
python3 -m venv venv --system-site-packages \
    || die "Nie można utworzyć venv. Sprawdź czy python3-venv jest zainstalowany."

source venv/bin/activate

ok "venv aktywny: $(python3 --version) @ $(which python3)"

pip install --quiet --upgrade pip setuptools wheel >> "$LOG_FILE" 2>&1
ok "pip: $(pip --version | cut -d' ' -f1-2)"

# ---------------------------------------------------------------------------
# Zabezpieczenie przed nadpisaniem pakietów systemowych przez pip
#
# Problem: ultralytics/inne pakiety mogą próbować upgrade'ować numpy/opencv
#          co psuje zależności apt. Używamy constraints file żeby to zablokować.
# ---------------------------------------------------------------------------
SYS_NUMPY_VER=$(python3 -c "import numpy; print(numpy.__version__)" 2>/dev/null || echo "1.24")
SYS_CV_VER=$(python3 -c "import cv2; print(cv2.__version__)" 2>/dev/null || echo "4.6")

cat > "$SCRIPT_DIR/.pip_constraints.txt" << EOF
# Auto-generated przez setup_rpi.sh — nie edytuj ręcznie
# Blokuje pip przed nadpisaniem pakietów systemowych
numpy==$SYS_NUMPY_VER
EOF
log "Constraints: numpy==$SYS_NUMPY_VER"

# ---------------------------------------------------------------------------
# 6. Zależności pip
#
# Instalujemy TYLKO to czego nie ma w apt i co jest potrzebne projektowi.
#
# UWAGA na dronekit:
#   - dronekit 2.9.2 NIE jest kompatybilny z pymavlink >2.4.41
#   - pymavlink 2.4.41 to ostatnia działająca wersja z dronekit
#   - używamy --no-deps dla dronekit i ręcznie instalujemy jego zależności
# ---------------------------------------------------------------------------
step "6/7" "Instalacja zależności pip"

echo "  → PyYAML..."
pip_install "pyyaml>=6.0"

echo "  → pynmea2 (parser GPS NMEA)..."
pip_install "pynmea2>=1.19"

echo "  → pyzbar (dekoder QR)..."
pip_install "pyzbar>=0.1.9"

echo "  → pymavlink (pinowana! — dronekit wymaga <=2.4.41)..."
pip_install "pymavlink==2.4.41"

echo "  → dronekit (--no-deps, ręczne zależności)..."
pip_install "dronekit==2.9.2" --no-deps
pip_install "monotonic" "decorator" "future"

echo "  → ultralytics (YOLO)..."
# Instaluj z constraints żeby nie upgrade'ować numpy
pip_install "ultralytics>=8.0" -c "$SCRIPT_DIR/.pip_constraints.txt"

echo "  → pytest..."
pip_install "pytest>=7.0" "pytest-cov>=4.0"

ok "Wszystkie zależności pip zainstalowane"

# ---------------------------------------------------------------------------
# Utwórz plik activate helper (żeby nie zapominać o source venv)
# ---------------------------------------------------------------------------
cat > "$SCRIPT_DIR/activate.sh" << EOF
#!/bin/bash
# Skrót: source activate.sh
source "$SCRIPT_DIR/venv/bin/activate"
echo "venv aktywny: \$(python3 --version)"
EOF
chmod +x "$SCRIPT_DIR/activate.sh"

# ---------------------------------------------------------------------------
# 7. Weryfikacja
# ---------------------------------------------------------------------------
step "7/7" "Weryfikacja instalacji"

echo ""
echo -e "  ${BOLD}Import Python:${NC}"

check_import() {
    local label="$1"
    local code="$2"
    local output
    if output=$(python3 -c "$code" 2>&1); then
        ok "$label  →  $output"
        log "[IMPORT OK] $label: $output"
    else
        fail "$label  →  BŁĄD: ${output:0:120}"
        log "[IMPORT FAIL] $label: $output"
    fi
}

check_import "cv2 (OpenCV)"  "import cv2; print(cv2.__version__)"
check_import "numpy"          "import numpy as np; print(np.__version__)"
check_import "lgpio"          "import lgpio; print('OK')"
check_import "gpiozero"       "import gpiozero; print(gpiozero.__version__)"
check_import "serial"         "import serial; print(serial.__version__)"
check_import "pynmea2"        "import pynmea2; print('OK')"
check_import "pyzbar"         "import pyzbar; print('OK')"
check_import "yaml"           "import yaml; print(yaml.__version__)"
check_import "pymavlink"      "from pymavlink import mavutil; print('2.4.41')"
check_import "dronekit"       "import dronekit; print('OK')"
check_import "ultralytics"    "import ultralytics; print(ultralytics.__version__)"
check_import "pytest"         "import pytest; print(pytest.__version__)"

echo ""
echo -e "  ${BOLD}Opcjonalne (wymaga podłączonego sprzętu):${NC}"
if python3 -c "import picamera2" 2>/dev/null; then
    ok "picamera2  →  OK"
else
    warn "picamera2  →  brak (OK jeśli kamera niepodłączona lub przed restartem)"
fi

echo ""
echo -e "  ${BOLD}Urządzenia sprzętowe:${NC}"
if ls /dev/i2c-* 2>/dev/null | grep -q .; then
    ok "I2C: $(ls /dev/i2c-* | tr '\n' ' ')"
else
    warn "I2C: brak /dev/i2c-* — wymagany restart"
fi

if ls /dev/ttyAMA* 2>/dev/null | grep -q .; then
    ok "UART: $(ls /dev/ttyAMA* | tr '\n' ' ')"
else
    warn "UART: brak /dev/ttyAMA* — wymagany restart"
fi

if ls /dev/video* 2>/dev/null | grep -q .; then
    ok "Kamera V4L: $(ls /dev/video* | head -3 | tr '\n' ' ')"
else
    warn "Kamera: brak /dev/video* — sprawdź połączenie kamery"
fi

echo ""
echo -e "  ${BOLD}Struktura projektu:${NC}"
mkdir -p "$SCRIPT_DIR/models" "$SCRIPT_DIR/logs" "$SCRIPT_DIR/config"
ok "Katalogi models/ logs/ config/ — OK"

if [ ! -f "$SCRIPT_DIR/models/best.pt" ]; then
    warn "Brak models/best.pt — WYMAGANY przed uruchomieniem misji!"
fi

# Utwórz pusty plik waypointów jeśli nie istnieje
WP_FILE="$SCRIPT_DIR/config/ugv_search_waypoints.txt"
if [ ! -f "$WP_FILE" ]; then
    printf "# Waypointy UGV — jeden punkt na linię: lat,lon\n# Przykład:\n# 50.067890,19.912345\n" > "$WP_FILE"
    warn "Stworzono pusty $WP_FILE — uzupełnij przed misją"
fi

# ---------------------------------------------------------------------------
# Podsumowanie
# ---------------------------------------------------------------------------
echo ""
echo -e "${CYAN}${BOLD}════════════════════════════════════════════════════════${NC}"
if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}  ✔  SETUP ZAKOŃCZONY BEZ BŁĘDÓW${NC}"
else
    echo -e "${RED}${BOLD}  ✘  SETUP ZAKOŃCZONY Z $ERRORS BŁĘDAMI${NC}"
    echo -e "     Sprawdź szczegóły: ${BOLD}$LOG_FILE${NC}"
fi
echo -e "${CYAN}${BOLD}════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}NASTĘPNE KROKI:${NC}"
echo ""
echo -e "  ${YELLOW}1. RESTART (obowiązkowy — GPIO i interfejsy):${NC}"
echo -e "       sudo reboot"
echo ""
echo -e "  ${YELLOW}2. Aktywuj środowisko (po restarcie):${NC}"
echo -e "       source $SCRIPT_DIR/activate.sh"
echo ""
echo -e "  ${YELLOW}3. Wgraj wagi YOLO:${NC}"
echo -e "       cp /path/to/best.pt $SCRIPT_DIR/models/best.pt"
echo ""
echo -e "  ${YELLOW}4. Uruchom testy jednostkowe:${NC}"
echo -e "       python -m pytest tests/ -v"
echo ""
echo -e "  ${YELLOW}5. Uruchom misję:${NC}"
echo -e "       python main_ugv.py"
echo -e "       python main_uav.py"
echo ""
echo -e "  Log pełny: ${BOLD}$LOG_FILE${NC}"
echo ""