# Dual Tech 2026 - Setup Guide

This guide describes how to set up the project on your development machine (laptop) and on the final Raspberry Pi 5 competition platform.

## 💻 Development Machine (Laptop/PC)

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
3.  **Run in Simulation**:
    The code detects that it's not on a Pi and will:
    -   Use `OpenCV` (webcam or file) instead of `picamera2`.
    -   Run GPIO (motors/gripper) in **MOCK** mode (no errors, just logs).

---

## 🍓 Raspberry Pi 5 (Competition Platform)

On a fresh **Raspberry Pi OS Bookworm (64-bit)**:

1.  **Clone the Repository**:
    ```bash
    git clone <your-repo-url>
    cd dual-tech-2026
    ```
2.  **Run the Setup Script**:
    This script installs all system drivers, `libcamera`, `picamera2`, and sets up the Python environment correctly.
    ```bash
    ./setup_rpi.sh
    ```
3.  **Reboot**:
    ```bash
    sudo reboot
    ```
4.  **Run the UGV/UAV Application**:
    ```bash
    source venv/bin/activate
    python main_ugv.py
    ```

---

## 🛠 Troubleshooting

If something breaks during the competition (e.g., missing dependencies, permission issues):

1.  **Run the Fix Script**:
    ```bash
    ./fix_shit.sh
    ```
2.  **Check Camera**:
    ```bash
    libcamera-hello --list-cameras
    ```
3.  **Check GPIO**:
    Ensure the user is in the `gpio` group: `groups $USER`.

---

## 📁 Project Structure

- `main_ugv.py`: Main entry point for the ground vehicle.
- `main_uav.py`: Main entry point for the drone.
- `perception/`: Camera, YOLO, and QR logic.
- `controllers/`: Motor and gripper drivers (L298N, Servo).
- `localization/`: GPS and Pose estimation.
- `mission/`: State machine and competition logic.
