#!/bin/bash
# =============================================================================
# setup_rpi.sh — Dual Tech 2026
# Działa na: Raspberry Pi OS Bookworm/Trixie 64-bit, Ubuntu 25.x aarch64
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
step() { echo -e "\n${CYAN}${BOLD}[$1] $2${NC}"; log "=== STEP $1: $2 ==="; }
die()  { echo -e "\n${RED}${BOLD}FATAL: $*${NC}"; log "FATAL: $*"; exit 1; }

echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║        Dual Tech 2026 — Setup Script v3.0               ║"
echo "  ║        RPi 5 | Bookworm / Trixie / Ubuntu 25.x          ║"
echo "  ╚══════════════════════════════════════════════════════════╝${NC}"
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
        warn "apt install nieudany (próba $attempt/3)..."
        sleep 5; attempt=$((attempt + 1))
    done
    fail "apt install nie powiodło się dla: $*"
    return 1
}

pip_install() {
    local attempt=1
    while [ $attempt -le 3 ]; do
        if "$PYTHON_BIN" -m pip install --quiet "$@" >> "$LOG_FILE" 2>&1; then
            return 0
        fi
        warn "pip install nieudany (próba $attempt/3)..."
        sleep 5; attempt=$((attempt + 1))
    done
    fail "pip install nie powiodło się dla: $*"
    return 1
}

# ---------------------------------------------------------------------------
# 0. Sprawdzenia wstępne
# ---------------------------------------------------------------------------
step "0/7" "Sprawdzanie wymagań wstępnych"
> "$LOG_FILE"
log "Skrypt uruchomiony: $(date), USER=$USER, DIR=$SCRIPT_DIR"

[ "$EUID" -eq 0 ] && die "Nie uruchamiaj jako root."
sudo -v 2>/dev/null || die "Brak dostępu do sudo."
ping -c 1 -W 5 8.8.8.8 > /dev/null 2>&1 || die "Brak internetu."

# Wykryj OS
source /etc/os-release 2>/dev/null || true
OS_ID="${ID:-unknown}"
OS_CODENAME="${VERSION_CODENAME:-unknown}"
log "OS: ${PRETTY_NAME:-unknown}, ID=$OS_ID, CODENAME=$OS_CODENAME"
ok "OS: ${PRETTY_NAME:-unknown}"

ARCH=$(uname -m)
[[ "$ARCH" == "aarch64" ]] && ok "Architektura: aarch64" || warn "Architektura: $ARCH (oczekiwano aarch64)"

# ---------------------------------------------------------------------------
# KRYTYCZNE: Neutralizuj pyenv
#
# pyenv przechwytuje 'python3' i daje wersję bez dostępu do /usr/lib/python3/
# Musimy użyć /usr/bin/python3 (systemowy Python od apt) do tworzenia venv.
# Bez tego --system-site-packages nie działa i lgpio/libcamera są niewidoczne.
# ---------------------------------------------------------------------------
if command -v pyenv > /dev/null 2>&1 || [ -n "${PYENV_ROOT:-}" ]; then
    warn "Wykryto pyenv! Neutralizuję na czas setupu..."
    log "pyenv detected, removing from PATH"
    # Usuń pyenv z PATH na czas tego skryptu
    export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v "\.pyenv" | tr '\n' ':' | sed 's/:$//')
    unset PYENV_ROOT PYENV_VERSION PYENV_VERSION_FILE PYENV_HOOK_PATH 2>/dev/null || true
    warn "pyenv wyłączony na czas instalacji (zmiany dotyczą tylko tego procesu)"
fi

# Znajdź systemowy Python 3
if [ -f /usr/bin/python3 ]; then
    SYSTEM_PYTHON="/usr/bin/python3"
elif [ -f /usr/bin/python3.13 ]; then
    SYSTEM_PYTHON="/usr/bin/python3.13"
elif [ -f /usr/bin/python3.11 ]; then
    SYSTEM_PYTHON="/usr/bin/python3.11"
else
    die "Nie znaleziono /usr/bin/python3. Zainstaluj python3 przez apt."
fi

PY_VER=$($SYSTEM_PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
ok "Systemowy Python: $SYSTEM_PYTHON ($PY_VER)"

# Sprawdź miejsce
FREE_KB=$(df "$SCRIPT_DIR" | awk 'NR==2 {print $4}')
[ "$FREE_KB" -lt 3145728 ] && warn "Mało miejsca: $(echo "scale=1; $FREE_KB/1048576" | bc) GB (min. 3 GB zalecane)"

# ---------------------------------------------------------------------------
# 1. Aktualizacja systemu
# ---------------------------------------------------------------------------
step "1/7" "Aktualizacja systemu"
sudo apt-get update >> "$LOG_FILE" 2>&1 || die "apt update nieudany."
sudo DEBIAN_FRONTEND=noninteractive apt-get full-upgrade -y >> "$LOG_FILE" 2>&1 || warn "full-upgrade z błędami (kontynuuję)"
ok "System zaktualizowany"

# ---------------------------------------------------------------------------
# 2. Pakiety systemowe
# ---------------------------------------------------------------------------
step "2/7" "Instalacja pakietów systemowych"

echo "  → Narzędzia bazowe..."
apt_install \
    python3-venv \
    python3-pip \
    python3-dev \
    python3-full \
    build-essential \
    git curl wget bc swig \
    python-is-python3

echo "  → Biblioteki C (wymagane do budowania kółek pip)..."
apt_install \
    libcap-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    libzbar0 \
    libzbar-dev \
    libssl-dev \
    libffi-dev

# libatlas — nazwa różni się między distro
if apt-cache show libatlas-base-dev > /dev/null 2>&1; then
    apt_install libatlas-base-dev && ok "libatlas-base-dev: zainstalowany"
else
    apt_install libatlas3-base && ok "libatlas3-base: zainstalowany (fallback)"
fi

echo "  → Narzędzia sprzętowe..."
apt_install i2c-tools v4l-utils ffmpeg

echo "  → GPIO — MUSZĄ być z apt (lgpio, gpiozero)..."
apt_install python3-lgpio python3-gpiozero || warn "GPIO apt paczki nieudane — spróbujemy symlinki"

echo "  → libcamera — MUSI być z apt..."
# Próbujemy różnych nazw między distro
if apt-cache show python3-libcamera > /dev/null 2>&1; then
    apt_install python3-libcamera python3-kms++ libcamera-dev \
        && ok "libcamera apt: OK"
else
    warn "python3-libcamera niedostępny w tym repo — kamera może nie działać"
fi

# picamera2 z apt (jeśli dostępna) lub z pip
if apt-cache show python3-picamera2 > /dev/null 2>&1; then
    apt_install python3-picamera2 && ok "picamera2 z apt: OK"
else
    ok "picamera2 z apt niedostępna — zainstalujemy z pip"
    PICAMERA2_FROM_PIP=1
fi

# python3-kms++ dostarcza moduł 'kms' potrzebny picamera2
if apt-cache show python3-kms++ > /dev/null 2>&1; then
    apt_install python3-kms++ && ok "python3-kms++: OK"
elif apt-cache show python3-pykms > /dev/null 2>&1; then
    apt_install python3-pykms && ok "python3-pykms: OK"
else
    warn "python3-kms++ niedostępny — picamera2 może wymagać OpenCV fallback"
fi

# python3-prctl (wymagane przez picamera2)
if apt-cache show python3-prctl > /dev/null 2>&1; then
    apt_install python3-prctl && ok "python3-prctl z apt: OK"
fi

# OpenCV z apt jeśli dostępny (unikamy konfliktu ABI)
if apt-cache show python3-opencv > /dev/null 2>&1; then
    apt_install python3-opencv && ok "python3-opencv z apt: OK"
fi

# python-venv dla konkretnej wersji
VENV_PKG="python${PY_VER}-venv"
if apt-cache show "$VENV_PKG" > /dev/null 2>&1; then
    apt_install "$VENV_PKG" && ok "$VENV_PKG: OK"
fi

ok "Pakiety systemowe zainstalowane"

# ---------------------------------------------------------------------------
# 3. Interfejsy sprzętowe (I2C, UART, SPI)
# ---------------------------------------------------------------------------
step "3/7" "Konfiguracja sprzętu"

CONFIG_FILE=""
for cfg in /boot/firmware/config.txt /boot/config.txt; do
    [ -f "$cfg" ] && CONFIG_FILE="$cfg" && break
done

if [ -n "$CONFIG_FILE" ]; then
    grep -q "^dtparam=i2c_arm=on" "$CONFIG_FILE" \
        || { echo "dtparam=i2c_arm=on" | sudo tee -a "$CONFIG_FILE" >> "$LOG_FILE"; ok "I2C: włączony"; } \
        || ok "I2C: już włączony"
    grep -q "^dtparam=spi=on" "$CONFIG_FILE" \
        || { echo "dtparam=spi=on" | sudo tee -a "$CONFIG_FILE" >> "$LOG_FILE"; ok "SPI: włączony"; } \
        || ok "SPI: już włączony"
    grep -q "^enable_uart=1" "$CONFIG_FILE" \
        || { echo "enable_uart=1" | sudo tee -a "$CONFIG_FILE" >> "$LOG_FILE"; ok "UART: włączony"; } \
        || ok "UART: już włączony"
else
    warn "Nie znaleziono config.txt — pomiń konfigurację boot"
fi

sudo modprobe i2c-dev 2>/dev/null && ok "Moduł i2c-dev: załadowany" || warn "i2c-dev: brak (OK po restarcie)"

# ---------------------------------------------------------------------------
# 4. Uprawnienia użytkownika
# ---------------------------------------------------------------------------
step "4/7" "Uprawnienia użytkownika ($USER)"

for GROUP in gpio video i2c dialout spi tty; do
    if getent group "$GROUP" > /dev/null 2>&1; then
        sudo usermod -aG "$GROUP" "$USER" && ok "$USER → grupa $GROUP"
    else
        log "Grupa $GROUP nie istnieje — pomijam"
    fi
done

# ---------------------------------------------------------------------------
# 5. Środowisko wirtualne Python
#
# KRYTYCZNE: Używamy $SYSTEM_PYTHON (= /usr/bin/python3), NIE pyenv!
# --system-site-packages musi widzieć /usr/lib/python3/dist-packages
# ---------------------------------------------------------------------------
step "5/7" "Środowisko wirtualne Python"

cd "$SCRIPT_DIR"

if [ -d "venv" ]; then
    warn "Usuwam istniejący venv..."
    rm -rf venv
fi

$SYSTEM_PYTHON -m venv venv --system-site-packages \
    || die "Nie można utworzyć venv. Sprawdź czy python3-venv jest zainstalowany."

# Ścieżka do Python w venv
PYTHON_BIN="$SCRIPT_DIR/venv/bin/python3"
PIP_BIN="$SCRIPT_DIR/venv/bin/pip"

ok "venv: $($PYTHON_BIN --version) @ $PYTHON_BIN"

# Upgrade pip/setuptools w venv
"$PYTHON_BIN" -m pip install --quiet --upgrade pip setuptools wheel >> "$LOG_FILE" 2>&1
ok "pip: $($PIP_BIN --version | cut -d' ' -f1-2)"

# ---------------------------------------------------------------------------
# KRYTYCZNE: Symlinki dla pakietów które NIE są na PyPI
#
# Problem: picamera2 z pip importuje 'libcamera', 'kms' (pykms), 'prctl' i 'lgpio'
# Te moduły są w /usr/lib/python3/dist-packages/ ale venv z pip-instalowanym
# picamera2 ich nie widzi bo pip nie wie że są systemowe.
#
# Rozwiązanie: tworzymy symlinki do site-packages u venv.
# -------m---------m=-----------------------------,--------------------------
VENV_SITE="$SCRIPT_DIR/ven6/lib/pyp`on${PYVER}/site-packages"

symliNk_sxstem_pkg,) {    local name="$1"    local sRa_glob="$2"
    local linked=0

    for src in /usr/lib/p}uhon3/dist-packages/$2rc_clob; do
        [ -m "$src" ]$|| continue
    "   local dst="$VENVOSITE/$(basename "$src")
    "�  if [ ! -e "$dst" ]; 4hen
           "ln -s "$src" "$dst" >> " LOG_FILE" 2>&1 && minkeD=1
        else
  (         |inked=1
       "fi
    done

    if [ "$,inked"!-eq 1 M; then
        ok "SYmlink2 $na}e → 6eNv"
  0 else
        warn "S9mlink: $name ℔ nie znaleziono pliku ($(ls /usr/mib/pyt(on3/dist-packaggs/$src_�lob 2>/dev/n�ll || echo 'brak'9-"
    fi
}

eaho "  → Tworzԛ symlinki pakietów systamowych do V�nv..."
# l)bcamera (k`tadog + ewdntualnie .so)
symlink_system_pkg "libcamera" "libcamera"
syllink_sy�tem_pkg "libcamera .so" "_libcamera..so"

# lgpio
Symlink_system_pkg "lgpio.py" "lgpio.py"
symlink_system_pke "lgpio .so" "_lgpio*.so"
symlink_system_pkg "lgpio egg-info" "lgpio-*.egg-info"

# kms / pykms (potrzebne przez picamera2 do drm preview)
symlink_system_pkg "kms (pykms)" "kms"
symlink_system_pkg "pykms" "pykms"

# prctl (potrzebne przez picamera2)
symlink_system_pkg "prctl.py" "prctl.py"
symlink_system_pkg "prctl .so" "_prctl*.so"
symlink_system_pkg "prctl egg-info" "python_prctl-*.egg-info"

# gpiozero + colorzero
symlink_system_pkg "gpiozero" "gpiozero"
symlink_system_pkg "colorzero" "colorzero"

# pyserial (zwykle już dostępny przez --system-site-packages)
symlink_system_pkg "serial (pyserial)" "serial"

# OpenCV jeśli zainstalowany z apt
symlink_system_pkg "cv2 (opencv)" "cv2"

# ---------------------------------------------------------------------------
# Symlink liblgpio.so — potrzebny jeśli ktoś próbuje budować lgpio z pip
# ---------------------------------------------------------------------------
if [ ! -f /usr/lib/liblgpio.so ] && [ ! -f /usr/local/lib/liblgpio.so ]; then
    LIB_LGPIO=$(find /usr/lib -name "liblgpio.so*" 2>/dev/null | head -1)
    if [ -n "$LIB_LGPIO" ]; then
        sudo ln -sf "$LIB_LGPIO" /usr/lib/liblgpio.so 2>/dev/null \
            && ok "liblgpio.so symlink: OK ($LIB_LGPIO)" \
            || warn "liblgpio.so symlink: nieudany (może być potrzebny do budowania lgpio)"
    fi
fi

# ---------------------------------------------------------------------------
# 6. Instalacja pip — TYLKO pakiety niedostępne przez apt / symlinki
# ---------------------------------------------------------------------------
step "6/7" "Instalacja pip"

# Zaktualizuj requirements.txt — usuń lgpio (to systemowy pakiet)
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    # Backup
    cp "$SCRIPT_DIR/requirements.txt" "$SCRIPT_DIR/requirements.txt.bak"
    # Usuń linie z lgpio i picamera2 (zainstalujemy osobno)
    grep -v "^lgpio" "$SCRIPT_DIR/requirements.txt" > /tmp/req_clean.txt || true
    mv /tmp/req_clean.txt "$SCRIPT_DIR/requirements.txt"
    ok "requirements.txt: usunięto 'lgpio' (systemowy)"
fi

echo "  → Instaluję z requirements.txt..."
# Ignoruj błędy pojedynczych pakietów — będziemy je instalować osobno
"$PYTHON_BIN" -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt" >> "$LOG_FILE" 2>&1 \
    || warn "requirements.txt: niektóre paczki nieudane, instaluję ręcznie"

# Ręczna instalacja krytycznych pakietów (z retry)
echo "  → Kluczowe pakiety pip..."
pip_install "pyyaml>=6.0"
pip_install "pynmea2>=1.19"
pip_install "pyzbar>=0.1.9"
pip_install "pymavlink>=2.4.40"
pip_install "dronekit>=2.9.2"
pip_install "ultralytics>=8.0"
pip_install "pytest>=7.0" "pytest-cov>=4.0"

# opencv-python z pip jeśli nie ma z apt
if ! "$PYTHON_BIN" -c "import cv2" > /dev/null 2>&1; then
    echo "  → opencv-python z pip (apt nie ma)..."
    pip_install "opencv-python>=4.8"
fi

# picamera2 z pip jeśli nie z apt
if ! "$PYTHON_BIN" -c "import picamera2" > /dev/null 2>&1; then
    echo "  → picamera2 z pip..."
    pip_install "picamera2" || warn "picamera2 pip nieudany — fallback do OpenCV w camera.py"
fi

ok "Zależności pip zainstalowane"

# ---------------------------------------------------------------------------
# Przywróć requirements.txt (opcjonalnie)
# ---------------------------------------------------------------------------
if [ -f "$SCRIPT_DIR/requirements.txt.bak" ]; then
    mv "$SCRIPT_DIR/requirements.txt.bak" "$SCRIPT_DIR/requirements.txt"
fi

# ---------------------------------------------------------------------------
# 7. Weryfikacja
# ---------------------------------------------------------------------------
step "7/7" "Weryfikacja"

echo ""
echo -e "  ${BOLD}Import Python:${NC}"

check() {
    local label="$1"; local code="$2"
    local out
    if out=$("$PYTHON_BIN" -c "$code" 2>&1); then
        ok "$label  →  $out"
    else
        fail "$label  →  ${out:0:100}"
    fi
}

check "numpy"          "import numpy as np; print(np.__version__)"
check "cv2 (OpenCV)"   "import cv2; print(cv2.__version__)"
check "yaml (PyYAML)"  "import yaml; print(yaml.__version__)"
check "lgpio"          "import lgpio; print('OK')"
check "gpiozero"       "import gpiozero; print(gpiozero.__version__)"
check "serial"         "import serial; print(serial.__version__)"
check "pynmea2"        "import pynmea2; print('OK')"
check "pyzbar"         "import pyzbar; print('OK')"
check "pymavlink"      "from pymavlink import mavutil; print('OK')"
check "dronekit"       "import dronekit; print('OK')"
check "ultralytics"    "import ultralytics; print(ultralytics.__version__)"
check "pytest"         "import pytest; print(pytest.__version__)"

echo ""
echo -e "  ${BOLD}Kamera i libcamera:${NC}"
if "$PYTHON_BIN" -c "import libcamera; print('libcamera OK')" 2>/dev/null; then
    ok "libcamera  →  OK"
else
    warn "libcamera  →  niedostępna w venv (kamera może działać przez OpenCV)"
fi

if "$PYTHON_BIN" -c "from picamera2 import Picamera2" 2>/dev/null; then
    ok "picamera2  →  OK"
else
    warn "picamera2  →  nie importuje (kamera.py używa OpenCV fallback — to OK)"
fi

echo ""
echo -e "  ${BOLD}Urządzenia sprzętowe:${NC}"
ls /dev/i2c-* 2>/dev/null | grep -q . && ok "I2C: $(ls /dev/i2c-* | tr '\n' ' ')" || warn "I2C: brak (wymagany restart)"
ls /dev/ttyAMA* 2>/dev/null | grep -q . && ok "UART: $(ls /dev/ttyAMA* | tr '\n' ' ')" || warn "UART: brak (wymagany restart lub enable_uart=1)"
ls /dev/video* 2>/dev/null | grep -q . && ok "Video: $(ls /dev/video* | head -3 | tr '\n' ' ')..." || warn "Video: brak urządzeń"
ls /dev/gpiochip0 2>/dev/null && ok "GPIO: /dev/gpiochip0 dostępny" || warn "GPIO: /dev/gpiochip0 brak (wymagany restart)"

echo ""
echo -e "  ${BOLD}Projekt:${NC}"
mkdir -p "$SCRIPT_DIR/models" "$SCRIPT_DIR/logs" "$SCRIPT_DIR/config"
ok "Katalogi: models/ logs/ config/ OK"
[ -f "$SCRIPT_DIR/models/best.pt" ] || warn "Brak models/best.pt — wymagany przed misją!"
[ -f "$SCRIPT_DIR/config/ugv_search_waypoints.txt" ] \
    || { printf "# lat,lon\n" > "$SCRIPT_DIR/config/ugv_search_waypoints.txt"; warn "Stworzono pusty ugv_search_waypoints.txt"; }

# Skrót activate
cat > "$SCRIPT_DIR/activate.sh" << EOF
#!/bin/bash
# Użycie: source activate.sh
# Neutralizuje pyenv i aktywuje venv
export PATH=\$(echo "\$PATH" | tr ':' '\n' | grep -v '\.pyenv' | tr '\n' ':' | sed 's/:\$//')
unset PYENV_ROOT PYENV_VERSION 2>/dev/null || true
source "$SCRIPT_DIR/venv/bin/activate"
echo "venv aktywny: \$(python3 --version) @ \$(which python3)"
EOF
chmod +x "$SCRIPT_DIR/activate.sh"
ok "Stworzono activate.sh (neutralizuje pyenv)"

# ---------------------------------------------------------------------------
# Podsumowanie
# ---------------------------------------------------------------------------
echo ""
echo -e "${CYAN}${BOLD}════════════════════════════════════════════════════════${NC}"
if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}  ✔  SETUP ZAKOŃCZONY BEZ BŁĘDÓW${NC}"
else
    echo -e "${YELLOW}${BOLD}  ⚠  SETUP ZAKOŃCZONY Z $ERRORS OSTRZEŻENIAMI${NC}"
    echo -e "     Sprawdź: ${BOLD}$LOG_FILE${NC}"
fi
echo -e "${CYAN}${BOLD}════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}NASTĘPNE KROKI:${NC}"
echo ""
echo -e "  ${YELLOW}1. RESTART (GPIO, UART, grupy użytkownika):${NC}"
echo -e "       sudo reboot"
echo ""
echo -e "  ${YELLOW}2. Po restarcie — aktywuj venv (BEZ pyenv):${NC}"
echo -e "       source $SCRIPT_DIR/activate.sh"
echo ""
echo -e "  ${YELLOW}3. Wgraj wagi YOLO:${NC}"
echo -e "       cp /path/to/best.pt $SCRIPT_DIR/models/best.pt"
echo ""
echo -e "  ${YELLOW}4. Uruchom testy:${NC}"
echo -e "       python -m pytest tests/ -v"
echo ""
echo -e "  ${YELLOW}5. Uruchom misję:${NC}"
echo -e "       python main_ugv.py   # lub python main_uav.py"
echo ""
echo -e "  ${RED}${BOLD}  UWAGA: Po restarcie zawsze używaj:${NC}"
echo -e "  ${BOLD}  source activate.sh${NC}  (nie: source venv/bin/activate)"
echo -e "  ${BOLD}  bo to neutralizuje pyenv który psuje system-site-packages${NC}"
echo ""
echo -e "  Log: ${BOLD}$LOG_FILE${NC}"
echo ""