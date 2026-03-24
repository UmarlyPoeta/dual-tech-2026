"""Stepper motor HAL — gpiod-based step/dir driver for A4988 / DRV8825.

Generates step pulses with trapezoidal acceleration ramping to prevent
step loss at high speeds.  Tracks absolute position in steps and
enforces software endstops.

Implements :class:`~hal.base.Actuator` with state type
``dict`` containing ``{"target_position": int}`` or ``{"steps": int, "direction": int}``.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, Optional

from hal.base import Actuator
from monitoring.health import ComponentStatus, HealthMonitor

logger = logging.getLogger(__name__)

_PULSE_WIDTH_US = 5  # Minimum pulse width for A4988 (2.5 us per datasheet, use 5 for margin)


class StepperInterface(Actuator[Dict[str, Any]]):
    """Abstract stepper motor interface."""

    def get_position(self) -> int:
        """Return current absolute position in steps."""
        raise NotImplementedError

    def move_to(self, target: int) -> None:
        """Move to an absolute position (blocking)."""
        self.set_state({"target_position": target})

    def move_relative(self, steps: int) -> None:
        """Move by a relative number of steps (positive = forward)."""
        self.set_state({"target_position": self.get_position() + steps})

    def is_moving(self) -> bool:
        """Return True if the motor is currently in motion."""
        return False

    def stop_motor(self) -> None:
        """Immediately stop any motion."""
        pass


class GpiodStepper(StepperInterface):
    """Stepper driver using libgpiod for step/dir/enable signals.

    Parameters
    ----------
    step_pin, dir_pin, enable_pin:
        BCM GPIO pin numbers for A4988/DRV8825 STEP, DIR, and ENABLE.
    steps_per_rev:
        Full steps per revolution (200 for 1.8-degree motors).
    max_speed_sps:
        Maximum speed in steps per second.
    acceleration_sps2:
        Acceleration in steps/sec^2 for trapezoidal ramp.
    min_position, max_position:
        Software endstop limits (in steps).
    gpiochip:
        GPIO chip device (default "gpiochip4" for RPi5 user GPIO).
    """

    def __init__(
        self,
        step_pin: int,
        dir_pin: int,
        enable_pin: int = -1,
        steps_per_rev: int = 200,
        max_speed_sps: int = 800,
        acceleration_sps2: int = 2000,
        min_position: int = 0,
        max_position: int = 10000,
        gpiochip: str = "gpiochip4",
        name: str = "stepper",
        health_monitor: Optional[HealthMonitor] = None,
    ) -> None:
        self._step_pin = step_pin
        self._dir_pin = dir_pin
        self._enable_pin = enable_pin
        self._steps_per_rev = steps_per_rev
        self._max_speed = max_speed_sps
        self._accel = acceleration_sps2
        self._min_pos = min_position
        self._max_pos = max_position
        self._gpiochip_name = gpiochip
        self._name = name
        self._health = health_monitor

        self._position: int = 0
        self._moving = False
        self._stop_flag = threading.Event()
        self._move_lock = threading.Lock()
        self._chip = None
        self._lines: Dict[str, Any] = {}

    def open(self) -> None:
        try:
            import gpiod  # type: ignore

            self._chip = gpiod.Chip(self._gpiochip_name)

            config = gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=gpiod.line.Value.INACTIVE)
            pins = {self._step_pin: config, self._dir_pin: config}
            if self._enable_pin >= 0:
                pins[self._enable_pin] = config

            request = self._chip.request_lines(
                consumer=f"dualtech-{self._name}",
                config=pins,
            )
            self._lines["request"] = request
            self._stop_flag.clear()

            # Enable the driver (A4988 ENABLE is active-low)
            if self._enable_pin >= 0:
                request.set_value(self._enable_pin, gpiod.line.Value.INACTIVE)

            logger.info("GpiodStepper '%s' opened (step=%d dir=%d en=%d chip=%s)",
                        self._name, self._step_pin, self._dir_pin, self._enable_pin,
                        self._gpiochip_name)
        except Exception as e:
            logger.error("GpiodStepper '%s' init failed: %s", self._name, e)
            if self._health:
                self._health.heartbeat(self._name, ComponentStatus.ERROR)
            raise

    def close(self) -> None:
        self.stop_motor()
        if "request" in self._lines:
            try:
                # Disable driver before releasing
                if self._enable_pin >= 0:
                    import gpiod
                    self._lines["request"].set_value(self._enable_pin, gpiod.line.Value.ACTIVE)
                self._lines["request"].release()
            except Exception:
                pass
            self._lines.clear()
        if self._chip is not None:
            try:
                self._chip.close()
            except Exception:
                pass
            self._chip = None
        logger.info("GpiodStepper '%s' closed.", self._name)

    def set_state(self, state: Dict[str, Any]) -> None:
        target = state.get("target_position")
        if target is None:
            return

        target = int(target)
        target = max(self._min_pos, min(self._max_pos, target))

        # Run motion in background thread to avoid blocking
        thread = threading.Thread(
            target=self._execute_move,
            args=(target,),
            daemon=True,
            name=f"{self._name}-move",
        )
        thread.start()

    def get_position(self) -> int:
        return self._position

    def is_moving(self) -> bool:
        return self._moving

    def stop_motor(self) -> None:
        self._stop_flag.set()
        # Wait briefly for motion to halt
        for _ in range(50):
            if not self._moving:
                break
            time.sleep(0.01)

    def _execute_move(self, target: int) -> None:
        """Trapezoidal acceleration move to target position."""
        with self._move_lock:
            self._stop_flag.clear()
            self._moving = True
            try:
                self._trapezoidal_move(target)
                if self._health:
                    self._health.heartbeat(self._name, ComponentStatus.OK)
            except Exception as e:
                logger.error("GpiodStepper '%s' move failed: %s — disabling", self._name, e)
                self._emergency_disable()
                if self._health:
                    self._health.heartbeat(self._name, ComponentStatus.ERROR)
            finally:
                self._moving = False

    def _trapezoidal_move(self, target: int) -> None:
        """Generate step pulses with trapezoidal velocity profile."""
        import gpiod

        request = self._lines.get("request")
        if request is None:
            raise RuntimeError("Stepper not opened")

        total_steps = target - self._position
        if total_steps == 0:
            return

        direction = 1 if total_steps > 0 else -1
        abs_steps = abs(total_steps)

        # Set direction pin
        dir_val = gpiod.line.Value.ACTIVE if direction > 0 else gpiod.line.Value.INACTIVE
        request.set_value(self._dir_pin, dir_val)
        time.sleep(0.000005)  # DIR setup time

        # Trapezoidal profile parameters
        max_speed = float(self._max_speed)
        accel = float(self._accel)

        # Steps needed to accelerate from 0 to max_speed
        accel_steps = int(max_speed * max_speed / (2.0 * accel))
        if accel_steps == 0:
            accel_steps = 1

        # If we can't reach max speed, use triangular profile
        if 2 * accel_steps > abs_steps:
            accel_steps = abs_steps // 2

        decel_start = abs_steps - accel_steps
        current_speed = 0.0
        min_delay = 1.0 / max_speed if max_speed > 0 else 0.001

        for step_num in range(abs_steps):
            if self._stop_flag.is_set():
                logger.warning("GpiodStepper '%s': move interrupted at step %d/%d",
                               self._name, step_num, abs_steps)
                break

            # Compute current speed based on profile phase
            if step_num < accel_steps:
                # Accelerating
                current_speed = math.sqrt(2.0 * accel * (step_num + 1))
            elif step_num >= decel_start:
                # Decelerating
                steps_remaining = abs_steps - step_num
                current_speed = math.sqrt(2.0 * accel * steps_remaining)
            else:
                # Cruising at max speed
                current_speed = max_speed

            current_speed = max(current_speed, accel * 0.01)  # Floor to prevent div-by-zero
            current_speed = min(current_speed, max_speed)
            delay = 1.0 / current_speed

            # Generate step pulse
            request.set_value(self._step_pin, gpiod.line.Value.ACTIVE)
            time.sleep(0.000005)  # Pulse width
            request.set_value(self._step_pin, gpiod.line.Value.INACTIVE)

            self._position += direction

            # Inter-step delay (subtract pulse width)
            remaining_delay = delay - 0.000005
            if remaining_delay > 0:
                time.sleep(remaining_delay)

    def _emergency_disable(self) -> None:
        """Disable the stepper driver on error (cut current to coils)."""
        try:
            if self._enable_pin >= 0 and "request" in self._lines:
                import gpiod
                self._lines["request"].set_value(self._enable_pin, gpiod.line.Value.ACTIVE)
                logger.warning("GpiodStepper '%s': driver disabled (emergency)", self._name)
        except Exception:
            pass


class MockStepper(StepperInterface):
    """Mock stepper for testing without hardware."""

    def __init__(
        self,
        name: str = "stepper",
        health_monitor: Optional[HealthMonitor] = None,
        **kwargs: Any,
    ) -> None:
        self._name = name
        self._health = health_monitor
        self._position: int = 0
        self._min_pos = kwargs.get("min_position", 0)
        self._max_pos = kwargs.get("max_position", 10000)

    def open(self) -> None:
        logger.info("MockStepper '%s' opened.", self._name)

    def close(self) -> None:
        logger.info("MockStepper '%s' closed.", self._name)

    def set_state(self, state: Dict[str, Any]) -> None:
        target = state.get("target_position")
        if target is not None:
            self._position = max(self._min_pos, min(self._max_pos, int(target)))
        if self._health:
            self._health.heartbeat(self._name, ComponentStatus.OK)

    def get_position(self) -> int:
        return self._position
