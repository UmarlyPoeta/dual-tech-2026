"""Health monitoring — heartbeat registry, system watchdog, and thermal management."""

from __future__ import annotations

import enum
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

_THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")
_THERMAL_STATE_FILE = Path("logs/.thermal_state")


class ComponentStatus(enum.Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    STALE = "STALE"


class HealthMonitor:
    """Registry for component heartbeats and health status.

    Components (e.g. Camera, GPS, Mission) report their status and a
    timestamped heartbeat to this monitor.

    Also tracks CPU temperature for thermal throttle decisions.
    """

    def __init__(self) -> None:
        self._statuses: Dict[str, ComponentStatus] = {}
        self._last_heartbeats: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._thermal_throttle = False
        self._cpu_temp_c: Optional[float] = None

    def heartbeat(self, name: str, status: ComponentStatus = ComponentStatus.OK) -> None:
        """Report component heartbeat and status."""
        with self._lock:
            self._statuses[name] = status
            self._last_heartbeats[name] = time.monotonic()

    def get_status(self, name: str, timeout_s: float = 5.0) -> ComponentStatus:
        """Get component status, checking for staleness."""
        with self._lock:
            if name not in self._statuses:
                return ComponentStatus.STALE
            
            elapsed = time.monotonic() - self._last_heartbeats[name]
            if elapsed > timeout_s:
                return ComponentStatus.STALE
            
            return self._statuses[name]

    def get_all_statuses(self, timeout_s: float = 5.0) -> Dict[str, ComponentStatus]:
        """Return a snapshot of all component statuses."""
        with self._lock:
            now = time.monotonic()
            results = {}
            for name, status in self._statuses.items():
                elapsed = now - self._last_heartbeats.get(name, 0)
                if elapsed > timeout_s:
                    results[name] = ComponentStatus.STALE
                else:
                    results[name] = status
            return results

    # ------------------------------------------------------------------
    # Thermal management
    # ------------------------------------------------------------------

    @property
    def thermal_throttle(self) -> bool:
        """True if the CPU is too hot and inference should be throttled."""
        return self._thermal_throttle

    @property
    def cpu_temp_c(self) -> Optional[float]:
        return self._cpu_temp_c

    def update_thermal(self) -> None:
        """Read CPU temperature and update throttle state.

        Called periodically by :class:`SystemWatchdog` or the systemd
        thermal timer.
        """
        temp = self._read_cpu_temp()
        if temp is None:
            # Try reading the file written by dualtech-thermal.service
            temp = self._read_thermal_state_file()
            if temp is not None:
                return  # State was set from file

        if temp is None:
            return

        self._cpu_temp_c = temp

        if temp >= 85.0:
            if not self._thermal_throttle:
                logger.critical("CPU temperature %.1f C — CRITICAL, heavy throttling", temp)
            self._thermal_throttle = True
        elif temp >= 80.0:
            if not self._thermal_throttle:
                logger.warning("CPU temperature %.1f C — throttling inference", temp)
            self._thermal_throttle = True
        else:
            if self._thermal_throttle:
                logger.info("CPU temperature %.1f C — resuming normal operation", temp)
            self._thermal_throttle = False

    def _read_cpu_temp(self) -> Optional[float]:
        try:
            return int(_THERMAL_ZONE.read_text().strip()) / 1000.0
        except Exception:
            return None

    def _read_thermal_state_file(self) -> Optional[float]:
        """Read state from the systemd thermal timer output."""
        try:
            state = _THERMAL_STATE_FILE.read_text().strip()
            if state == "CRITICAL":
                self._thermal_throttle = True
                self._cpu_temp_c = 85.0
            elif state == "THROTTLE":
                self._thermal_throttle = True
                self._cpu_temp_c = 80.0
            elif state == "OK":
                self._thermal_throttle = False
            return self._cpu_temp_c
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Disk space
    # ------------------------------------------------------------------

    @staticmethod
    def check_disk_space(path: str = ".") -> Dict[str, float]:
        """Return disk usage stats in GB."""
        stat = os.statvfs(path)
        total = (stat.f_blocks * stat.f_frsize) / (1024 ** 3)
        free = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        return {"total_gb": round(total, 1), "free_gb": round(free, 1), "used_pct": round((1 - free / total) * 100, 1)}


class SystemWatchdog:
    """Background thread that monitors component health and triggers safety actions.

    Parameters
    ----------
    health_monitor:
        The HealthMonitor to check.
    critical_components:
        List of component names that must be OK/WARNING for the system to run.
    timeout_s:
        Seconds without a heartbeat before a component is considered STALE.
    on_failure:
        Callback triggered if a critical component fails or becomes stale.
    """

    def __init__(
        self,
        health_monitor: HealthMonitor,
        critical_components: list[str],
        timeout_s: float = 5.0,
        on_failure: Optional[Callable[[str, ComponentStatus], None]] = None,
    ) -> None:
        self._health = health_monitor
        self._critical = critical_components
        self._timeout_s = timeout_s
        self._on_failure = on_failure
        
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the watchdog thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="system-watchdog")
        self._thread.start()
        logger.info("System watchdog started (critical: %s)", self._critical)

    def stop(self) -> None:
        """Stop the watchdog thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        logger.info("System watchdog stopped.")

    def _run(self) -> None:
        thermal_counter = 0
        disk_counter = 0
        while self._running:
            time.sleep(min(1.0, self._timeout_s / 2.0))
            statuses = self._health.get_all_statuses(self._timeout_s)
            
            for comp in self._critical:
                status = statuses.get(comp, ComponentStatus.STALE)
                if status in (ComponentStatus.ERROR, ComponentStatus.STALE):
                    logger.critical("Watchdog: Critical component '%s' is in state %s!", comp, status.value)
                    if self._on_failure:
                        try:
                            self._on_failure(comp, status)
                        except Exception:
                            logger.exception("Error in watchdog on_failure callback")

            # Thermal check every ~10 seconds
            thermal_counter += 1
            if thermal_counter >= 10:
                thermal_counter = 0
                self._health.update_thermal()

            # Disk space check every ~60 seconds
            disk_counter += 1
            if disk_counter >= 60:
                disk_counter = 0
                try:
                    disk = HealthMonitor.check_disk_space()
                    if disk["free_gb"] < 0.5:
                        logger.critical("Watchdog: Disk almost full! %.1f GB free", disk["free_gb"])
                    elif disk["free_gb"] < 1.0:
                        logger.warning("Watchdog: Low disk space: %.1f GB free", disk["free_gb"])
                except Exception:
                    pass
