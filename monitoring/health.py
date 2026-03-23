"""Health monitoring — heartbeat registry and system watchdog."""

from __future__ import annotations

import enum
import logging
import threading
import time
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class ComponentStatus(enum.Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    STALE = "STALE"


class HealthMonitor:
    """Registry for component heartbeats and health status.

    Components (e.g. Camera, GPS, Mission) report their status and a
    timestamped heartbeat to this monitor.
    """

    def __init__(self) -> None:
        self._statuses: Dict[str, ComponentStatus] = {}
        self._last_heartbeats: Dict[str, float] = {}
        self._lock = threading.Lock()

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
        while self._running:
            # Check more frequently than the timeout
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
                    
                    # Prevent multiple callbacks for the same failure
                    # self.stop() 
                    # Usually we want it to keep monitoring or we exit the program
