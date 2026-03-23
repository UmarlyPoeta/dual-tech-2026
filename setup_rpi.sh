#!/bin/bash
# setup_rpi.sh - Complete environment setup for Dual Tech 2026 on RPi 5 (Bookworm)
# This script is intended to be run on a fresh Raspberry Pi OS Bookworm 64-bit installation.

set -e  # Exit on error

echo "--- Starting Dual Tech 2026 Setup ---"

# 1. Update system
echo "Updating system packages..."
sudo apt update && sudo apt upgrade -y

# 2. Install system dependencies
# libcamera-dev and python3-libcamera are essential for picamera2
# libcap-dev is needed for python-prctl (dependency of picamera2)
# python3-pykms is needed for picamera2 previews
# python3-lgpio and python3-gpiozero are for RPi 5 GPIO
echo "Installing system dependencies..."
sudo apt install -y \
    python3-venv \
    python3-pip \
    python3-libcamera \
    python3-kms++ \
    python3-pykms \
    libcamera-dev \
    libcap-dev \
    libatlas-base-dev \
    libjpeg-dev \
    libtiff5-dev \
    libopenjp2-7-dev \
    libzbar0 \
    ffmpeg \
    v4l-utils \
    python3-lgpio \
    python3-gpiozero \
    python3-serial \
    python3-opencv

# 3. Setup permissions
echo "Setting up user permissions..."
sudo usermod -aG gpio,video,i2c,dialout $USER

# 4. Create Virtual Environment
# We use --system-site-packages to access system-installed libcamera and lgpio
echo "Creating Python virtual environment..."
if [ -d "venv" ]; then
    echo "Existing venv found. Re-creating..."
    rm -rf venv
fi
python3 -m venv venv --system-site-packages
source venv/bin/activate

# 5. Install Python dependencies
echo "Installing Python dependencies from requirements.txt..."
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# 6. Final verification
echo "--- Setup Verification ---"
python3 -c "import cv2; print(f'OpenCV version: {cv2.__version__}')"
python3 -c "import picamera2; print('picamera2: OK')" || echo "picamera2: FAILED (expected if no camera connected)"
python3 -c "import lgpio; print('lgpio: OK')" || echo "lgpio: FAILED"

echo ""
echo "--- Setup Complete ---"
echo "Please REBOOT your Raspberry Pi for group permissions to take effect."
echo "To activate the environment: source venv/bin/activate"
