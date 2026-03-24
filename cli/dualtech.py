#!/usr/bin/env python3
"""dualtech — CLI for Dual Tech 2026 competition system.

Commands:
    doctor      System health diagnostic
    calibrate   Interactive hardware calibration wizard
    start       Launch the mission (Docker or direct Python)
    stop        Graceful shutdown
    logs        View and manage mission logs
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import click
import yaml

PROJECT_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _pass(msg: str) -> str:
    return click.style(f"  [PASS] {msg}", fg="green")

def _fail(msg: str) -> str:
    return click.style(f"  [FAIL] {msg}", fg="red")

def _warn(msg: str) -> str:
    return click.style(f"  [WARN] {msg}", fg="yellow")

def _info(msg: str) -> str:
    return click.style(f"  [INFO] {msg}", fg="cyan")


@click.group()
@click.version_option(version="1.0.0", prog_name="dualtech")
def cli() -> None:
    """Dual Tech 2026 — Competition System CLI"""
    pass


# ===========================================================================
# dualtech doctor
# ===========================================================================

@cli.command()
@click.option("--json-out", is_flag=True, help="Output results as JSON")
def doctor(json_out: bool) -> None:
    """Run system health diagnostics."""
    results: dict[str, dict] = {}

    def check(name: str, passed: bool, detail: str = "") -> None:
        results[name] = {"status": "pass" if passed else "fail", "detail": detail}
        if not json_out:
            click.echo(_pass(f"{name}: {detail}") if passed else _fail(f"{name}: {detail}"))

    def check_warn(name: str, detail: str) -> None:
        results[name] = {"status": "warn", "detail": detail}
        if not json_out:
            click.echo(_warn(f"{name}: {detail}"))

    if not json_out:
        click.echo(click.style("\n  Dual Tech 2026 — System Doctor\n", fg="cyan", bold=True))

    # I2C
    i2c_devs = glob.glob("/dev/i2c-*")
    check("i2c", len(i2c_devs) > 0, " ".join(i2c_devs) if i2c_devs else "no devices")

    # Serial / UART
    uart_devs = glob.glob("/dev/ttyAMA*") + glob.glob("/dev/ttyUSB*")
    check("serial", len(uart_devs) > 0, " ".join(uart_devs) if uart_devs else "no UART devices")

    # Symlinks from udev
    for symlink in ["/dev/speedybee", "/dev/front_cam", "/dev/gps_uart"]:
        exists = os.path.exists(symlink)
        if exists:
            check(f"udev:{symlink}", True, os.path.realpath(symlink))
        else:
            check_warn(f"udev:{symlink}", "not present (check udev rules)")

    # Camera
    video_devs = glob.glob("/dev/video*")
    check("camera", len(video_devs) > 0, " ".join(video_devs[:4]) if video_devs else "no video devices")

    # GPIO chip
    check("gpiochip", os.path.exists("/dev/gpiochip0"), "/dev/gpiochip0")

    # pigpiod
    pigpio_running = subprocess.run(["pgrep", "-x", "pigpiod"],
                                    capture_output=True).returncode == 0
    check("pigpiod", pigpio_running, "running" if pigpio_running else "not running")

    # Docker
    docker_ok = shutil.which("docker") is not None
    docker_ver = ""
    if docker_ok:
        try:
            docker_ver = subprocess.check_output(
                ["docker", "--version"], text=True, timeout=5
            ).strip()
        except Exception:
            docker_ver = "installed but version check failed"
    check("docker", docker_ok, docker_ver if docker_ok else "not installed")

    # Docker daemon running
    if docker_ok:
        daemon_ok = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=10
        ).returncode == 0
        check("docker_daemon", daemon_ok, "running" if daemon_ok else "not running (try: sudo systemctl start docker)")

    # RAM
    try:
        import resource
        mem_info = Path("/proc/meminfo").read_text()
        total_kb = int([l for l in mem_info.split("\n") if "MemTotal" in l][0].split()[1])
        avail_kb = int([l for l in mem_info.split("\n") if "MemAvailable" in l][0].split()[1])
        total_gb = total_kb / 1048576
        avail_gb = avail_kb / 1048576
        check("ram", avail_gb > 0.5, f"{avail_gb:.1f} GB free / {total_gb:.1f} GB total")
    except Exception:
        check_warn("ram", "cannot read /proc/meminfo")

    # Disk
    try:
        stat = os.statvfs(str(PROJECT_DIR))
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        total_gb = (stat.f_blocks * stat.f_frsize) / (1024 ** 3)
        check("disk", free_gb > 1.0, f"{free_gb:.1f} GB free / {total_gb:.1f} GB total")
    except Exception:
        check_warn("disk", "cannot stat filesystem")

    # Temperature
    thermal_path = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal_path.exists():
        try:
            temp_c = int(thermal_path.read_text().strip()) / 1000
            ok = temp_c < 80
            check("temperature", ok, f"{temp_c:.1f} C")
        except Exception:
            check_warn("temperature", "cannot read thermal zone")
    else:
        check_warn("temperature", "thermal zone not available")

    # YOLO model
    model_path = PROJECT_DIR / "models" / "best.pt"
    check("yolo_model", model_path.exists(), str(model_path) if model_path.exists() else "NOT FOUND")

    # hw_params.yaml
    hw_params = PROJECT_DIR / "configs" / "hw_params.yaml"
    check("hw_params", hw_params.exists(), str(hw_params) if hw_params.exists() else "NOT FOUND — run: dualtech calibrate")

    # Network
    try:
        ret = subprocess.run(["ping", "-c", "1", "-W", "3", "8.8.8.8"],
                             capture_output=True, timeout=5)
        check("network", ret.returncode == 0, "internet reachable" if ret.returncode == 0 else "no internet")
    except Exception:
        check_warn("network", "ping failed")

    # Logs directory size
    logs_dir = PROJECT_DIR / "logs"
    if logs_dir.exists():
        total_size = sum(f.stat().st_size for f in logs_dir.rglob("*") if f.is_file())
        size_mb = total_size / (1024 * 1024)
        check("logs_size", size_mb < 500, f"{size_mb:.0f} MB")
    else:
        check("logs_size", True, "logs/ not yet created")

    if json_out:
        click.echo(json.dumps(results, indent=2))
        return

    # Summary
    passed = sum(1 for r in results.values() if r["status"] == "pass")
    total = len(results)
    click.echo("")
    if passed == total:
        click.echo(click.style(f"  All {total} checks passed.\n", fg="green", bold=True))
    else:
        click.echo(click.style(f"  {passed}/{total} checks passed.\n", fg="yellow", bold=True))


# ===========================================================================
# dualtech calibrate
# ===========================================================================

@cli.command()
@click.option("--servo", is_flag=True, help="Calibrate servo limits")
@click.option("--stepper", is_flag=True, help="Calibrate stepper endstops")
@click.option("--camera", is_flag=True, help="Calibrate camera intrinsics (checkerboard)")
@click.option("--all", "calibrate_all", is_flag=True, help="Run all calibrations")
def calibrate(servo: bool, stepper: bool, camera: bool, calibrate_all: bool) -> None:
    """Interactive hardware calibration wizard."""
    if not any([servo, stepper, camera, calibrate_all]):
        calibrate_all = True

    hw_path = PROJECT_DIR / "configs" / "hw_params.yaml"
    if hw_path.exists():
        with open(hw_path) as f:
            hw_cfg = yaml.safe_load(f) or {}
    else:
        hw_cfg = {"servos": {}, "steppers": {}, "camera_calibration": {}}

    if servo or calibrate_all:
        _calibrate_servos(hw_cfg)
    if stepper or calibrate_all:
        _calibrate_steppers(hw_cfg)
    if camera or calibrate_all:
        _calibrate_camera(hw_cfg)

    hw_path.parent.mkdir(parents=True, exist_ok=True)
    with open(hw_path, "w") as f:
        yaml.safe_dump(hw_cfg, f, default_flow_style=False, sort_keys=False)
    click.echo(_pass(f"Calibration saved to {hw_path}"))


def _calibrate_servos(hw_cfg: dict) -> None:
    """Interactive servo calibration."""
    click.echo(click.style("\n  --- Servo Calibration ---\n", fg="cyan", bold=True))

    servos_cfg = hw_cfg.setdefault("servos", {})
    for servo_name, scfg in servos_cfg.items():
        click.echo(f"\n  Servo: {servo_name} (pin {scfg.get('pin', '?')})")

        try:
            sys.path.insert(0, str(PROJECT_DIR))
            from hal.factory import create_servo
            servo_dev = create_servo({**scfg, "mode": "real"})
            servo_dev.open()
        except Exception as e:
            click.echo(_warn(f"Cannot open servo '{servo_name}': {e} — skipping"))
            continue

        try:
            # Sweep test
            click.echo("  Testing sweep: 0 -> 90 -> 180 -> 90")
            for angle in [0, 90, 180, 90]:
                servo_dev.set_angle(angle)
                time.sleep(0.8)
                click.echo(f"    Angle: {angle} deg — OK? (watch the servo)")

            # Interactive limit setting
            if click.confirm("  Set custom angle limits?", default=False):
                min_a = click.prompt("  Min safe angle (deg)", type=float, default=scfg.get("min_angle_deg", 0.0))
                max_a = click.prompt("  Max safe angle (deg)", type=float, default=scfg.get("max_angle_deg", 180.0))
                scfg["min_angle_deg"] = min_a
                scfg["max_angle_deg"] = max_a
                click.echo(_pass(f"Limits set: {min_a} - {max_a} deg"))

            default_a = click.prompt("  Default angle (deg)",
                                     type=float, default=scfg.get("default_angle_deg", 90.0))
            scfg["default_angle_deg"] = default_a
        finally:
            servo_dev.close()


def _calibrate_steppers(hw_cfg: dict) -> None:
    """Interactive stepper endstop calibration."""
    click.echo(click.style("\n  --- Stepper Calibration ---\n", fg="cyan", bold=True))

    steppers_cfg = hw_cfg.setdefault("steppers", {})
    for stepper_name, scfg in steppers_cfg.items():
        click.echo(f"\n  Stepper: {stepper_name} (step={scfg.get('step_pin')}, dir={scfg.get('dir_pin')})")

        try:
            sys.path.insert(0, str(PROJECT_DIR))
            from hal.factory import create_stepper
            stepper_dev = create_stepper({**scfg, "mode": "real"})
            stepper_dev.open()
        except Exception as e:
            click.echo(_warn(f"Cannot open stepper '{stepper_name}': {e} — skipping"))
            continue

        try:
            click.echo("  Use +/- to jog, 'h' to set as home (0), 'e' to set as endstop, 'q' to finish.")
            jog_steps = click.prompt("  Jog step size", type=int, default=50)

            while True:
                cmd = click.prompt(f"  [pos={stepper_dev.get_position()}] Command (+/-/h/e/q)")
                if cmd == "+":
                    stepper_dev.move_relative(jog_steps)
                    time.sleep(0.5)
                elif cmd == "-":
                    stepper_dev.move_relative(-jog_steps)
                    time.sleep(0.5)
                elif cmd == "h":
                    scfg["min_position"] = stepper_dev.get_position()
                    click.echo(_pass(f"Home (min) set to {stepper_dev.get_position()}"))
                elif cmd == "e":
                    scfg["max_position"] = stepper_dev.get_position()
                    click.echo(_pass(f"Endstop (max) set to {stepper_dev.get_position()}"))
                elif cmd == "q":
                    break
        finally:
            stepper_dev.close()


def _calibrate_camera(hw_cfg: dict) -> None:
    """Camera intrinsic calibration using a checkerboard pattern."""
    click.echo(click.style("\n  --- Camera Calibration ---\n", fg="cyan", bold=True))
    click.echo("  Hold a checkerboard pattern in front of the camera.")
    click.echo("  Press SPACE to capture a frame, 'c' to calibrate, 'q' to quit.\n")

    try:
        import cv2
        import numpy as np
    except ImportError:
        click.echo(_fail("OpenCV not available — cannot calibrate camera"))
        return

    board_w = click.prompt("  Checkerboard inner corners (width)", type=int, default=9)
    board_h = click.prompt("  Checkerboard inner corners (height)", type=int, default=6)
    square_mm = click.prompt("  Square size (mm)", type=float, default=25.0)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        click.echo(_fail("Cannot open camera"))
        return

    objp = np.zeros((board_h * board_w, 3), np.float32)
    objp[:, :2] = np.mgrid[0:board_w, 0:board_h].T.reshape(-1, 2) * square_mm

    obj_points: list = []
    img_points: list = []
    img_size = None

    click.echo("  Camera opened. Press SPACE to capture, 'c' to calibrate, 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if img_size is None:
            img_size = gray.shape[::-1]

        cv2.imshow("Calibration", frame)
        key = cv2.waitKey(30) & 0xFF

        if key == ord(" "):
            found, corners = cv2.findChessboardCorners(gray, (board_w, board_h), None)
            if found:
                refined = cv2.cornerSubPix(
                    gray, corners, (11, 11), (-1, -1),
                    (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001),
                )
                obj_points.append(objp)
                img_points.append(refined)
                cv2.drawChessboardCorners(frame, (board_w, board_h), refined, found)
                cv2.imshow("Calibration", frame)
                cv2.waitKey(500)
                click.echo(_pass(f"Captured frame {len(obj_points)}"))
            else:
                click.echo(_warn("Checkerboard not found — try again"))

        elif key == ord("c"):
            if len(obj_points) < 5:
                click.echo(_warn(f"Need at least 5 captures (have {len(obj_points)})"))
                continue

            click.echo(_info("Calibrating..."))
            ret_val, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(
                obj_points, img_points, img_size, None, None
            )
            click.echo(_pass(f"RMS reprojection error: {ret_val:.4f}"))

            cal = hw_cfg.setdefault("camera_calibration", {})
            cal["calibrated"] = True
            cal["matrix"] = mtx.tolist()
            cal["distortion"] = dist.tolist()
            cal["resolution"] = list(img_size)
            cal["rms_error"] = float(ret_val)
            break

        elif key == ord("q"):
            click.echo("  Calibration cancelled.")
            break

    cap.release()
    cv2.destroyAllWindows()


# ===========================================================================
# dualtech start
# ===========================================================================

@cli.command()
@click.argument("platform", type=click.Choice(["ugv", "uav"]), default="ugv")
@click.option("--docker/--no-docker", default=True, help="Use Docker or run directly")
def start(platform: str, docker: bool) -> None:
    """Launch the competition mission."""
    if docker:
        compose_file = PROJECT_DIR / "docker" / "docker-compose.yml"
        if not compose_file.exists():
            click.echo(_fail(f"docker-compose.yml not found at {compose_file}"))
            raise SystemExit(1)

        click.echo(_info(f"Starting {platform.upper()} via Docker..."))
        env = os.environ.copy()
        env["PLATFORM"] = platform

        compose_cmd = _find_compose_cmd()
        subprocess.run(
            [*compose_cmd, "-f", str(compose_file), "up", "-d", "--remove-orphans"],
            env=env,
            check=True,
        )
        click.echo(_pass(f"{platform.upper()} containers started"))
    else:
        entry = PROJECT_DIR / f"main_{platform}.py"
        if not entry.exists():
            click.echo(_fail(f"Entry point not found: {entry}"))
            raise SystemExit(1)

        click.echo(_info(f"Starting {platform.upper()} directly..."))
        os.execvp(sys.executable, [sys.executable, str(entry)])


# ===========================================================================
# dualtech stop
# ===========================================================================

@cli.command()
def stop() -> None:
    """Gracefully stop all running services."""
    compose_file = PROJECT_DIR / "docker" / "docker-compose.yml"
    compose_cmd = _find_compose_cmd()

    click.echo(_info("Stopping Docker services..."))
    subprocess.run(
        [*compose_cmd, "-f", str(compose_file), "down"],
        capture_output=True,
    )
    click.echo(_pass("Services stopped"))


# ===========================================================================
# dualtech logs
# ===========================================================================

@cli.command()
@click.option("--tail", "-n", default=50, help="Number of lines to show")
@click.option("--follow", "-f", is_flag=True, help="Follow log output")
@click.option("--clean", is_flag=True, help="Delete old logs (keep latest)")
def logs(tail: int, follow: bool, clean: bool) -> None:
    """View and manage mission logs."""
    logs_dir = PROJECT_DIR / "logs"

    if clean:
        if not logs_dir.exists():
            click.echo(_info("No logs directory"))
            return

        total_size = sum(f.stat().st_size for f in logs_dir.rglob("*") if f.is_file())
        size_mb = total_size / (1024 * 1024)
        click.echo(_info(f"Current logs size: {size_mb:.0f} MB"))

        # Keep only the 2 most recent session directories per platform
        for platform_dir in logs_dir.iterdir():
            if not platform_dir.is_dir():
                continue
            sessions = sorted(platform_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in sessions[2:]:
                shutil.rmtree(old, ignore_errors=True)
                click.echo(_info(f"Deleted: {old}"))

        new_size = sum(f.stat().st_size for f in logs_dir.rglob("*") if f.is_file())
        click.echo(_pass(f"Cleaned: {size_mb:.0f} MB -> {new_size / (1024 * 1024):.0f} MB"))
        return

    # Show Docker logs if containers are running
    compose_file = PROJECT_DIR / "docker" / "docker-compose.yml"
    compose_cmd = _find_compose_cmd()

    args = [*compose_cmd, "-f", str(compose_file), "logs"]
    if tail:
        args.extend(["--tail", str(tail)])
    if follow:
        args.append("-f")

    try:
        subprocess.run(args)
    except KeyboardInterrupt:
        pass


# ===========================================================================
# Helpers
# ===========================================================================

def _find_compose_cmd() -> list[str]:
    """Return the docker compose command as a list."""
    try:
        subprocess.run(["docker", "compose", "version"],
                       capture_output=True, check=True, timeout=5)
        return ["docker", "compose"]
    except Exception:
        pass
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    click.echo(_fail("docker compose not found. Install Docker first."))
    raise SystemExit(1)


if __name__ == "__main__":
    cli()
