# Dual Tech 2026 - Setup Guide

This guide describes how to set up the project on your development machine (laptop) and on the final Raspberry Pi 5 competition platform.

## Development Machine (Laptop/PC)

To work on the code without the Raspberry Pi hardware:

1.  **Create a Virtual Environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
    *Note: `picamera2` and `lgpio` may fail to install or run on Windows/macOS. This is fine; the code handles fallbacks automatically.*
3.  **Run consistency checks and tests**:
    ```bash
    python scripts/check_config_consistency.py
    python -m pytest tests/ -v
    ```
4.  **Run in Simulation**:
    The code detects that it's not on a Pi and will:
    -   Use `OpenCV` (webcam or file) instead of `picamera2`.
    -   Run GPIO (motors/gripper) in **MOCK** mode (no errors, just logs).

---

## Raspberry Pi 5 (Competition Platform)

On a fresh **Raspberry Pi OS Bookworm (64-bit)**:

1.  **Clone the Repository**:
    ```bash
    git clone <your-repo-url>
    cd dual-tech-2026
    ```
2.  **Run the Setup Script**:
    This script installs all system drivers, `libcamera`, `picamera2`, and sets up the Python environment correctly.
    ```bash
    ./scripts/bootstrap.sh
    ```
3.  **Reboot**:
    ```bash
    sudo reboot
    ```
4.  **Start with one command (recommended)**:
    ```bash
    source activate.sh
    python cli/dualtech.py start ugv --docker --with-ros
    ```
    For UAV:
    ```bash
    python cli/dualtech.py start uav --docker --with-ros
    ```
5.  **Control and status**:
    - WebGUI (primary): `http://<rpi-ip>:8080`
    - CLI fallback:
      ```bash
      python cli/dualtech.py status
      python cli/dualtech.py logs -f
      python cli/dualtech.py stop
      ```

---

## Dependency Model (Docker-first on RPi5)

- `requirements.txt` and `requirements-base.txt` are host-safe (CLI, calibration, GPIO, camera checks).
- `requirements-ml.txt` contains ML dependencies (`ultralytics`/torch chain) intended for Docker runtime.
- On RPi5 with armhf userspace, host install of `ultralytics` is intentionally not required for mission startup.

## Troubleshooting

If something breaks during the competition (e.g., missing dependencies, permission issues):

1.  **Run diagnostics first**:
    ```bash
    python cli/dualtech.py doctor
    ```
2.  **Check Camera**:
    ```bash
    libcamera-hello --list-cameras
    ```
3.  **Check GPIO**:
    Ensure the user is in the `gpio` group: `groups $USER`.
4.  **If `numpy/cv2` import fails with `libopenblas.so.0`**:
    ```bash
    sudo apt install -y libopenblas0-pthread
    sudo ldconfig
    ```

---

## Project Structure

- `main_ugv.py`: Main entry point for the ground vehicle.
- `main_uav.py`: Main entry point for the drone.
- `perception/`: Camera, YOLO, and QR logic.
- `controllers/`: Motor and gripper drivers (L298N, Servo).
- `localization/`: GPS and Pose estimation.
- `mission/`: State machine and competition logic.
