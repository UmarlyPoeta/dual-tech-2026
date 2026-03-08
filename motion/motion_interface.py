"""Abstract motion interface — implemented separately by UAV and UGV controllers."""

from __future__ import annotations

import abc
from typing import Optional

import numpy as np

from models import TargetHypothesis


class MotionInterface(abc.ABC):
    """Platform-agnostic motion commands used by :class:`~mission.mission_manager.MissionManager`.

    Both :class:`~controllers.uav.uav_controller.UAVController` and
    :class:`~controllers.ugv.ugv_controller.UGVController` implement this interface.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def precheck(self) -> None:
        """Verify that the platform is ready to operate.

        Should raise :class:`RuntimeError` if a critical component is unavailable.
        """

    @abc.abstractmethod
    def start_search(self) -> None:
        """Begin the search pattern (AUTO flight / patrol drive)."""

    @abc.abstractmethod
    def return_home(self) -> None:
        """Navigate back to the home / start position and land / stop."""

    @abc.abstractmethod
    def emergency_stop(self) -> None:
        """Immediately stop all motion (RTL / hard-stop)."""

    # ------------------------------------------------------------------
    # Target interaction
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def inspect_target(self, hypothesis: TargetHypothesis) -> None:
        """Move to an inspection position relative to the target and hold."""

    @abc.abstractmethod
    def resume_search(self) -> None:
        """Return to the search pattern after inspecting a target."""

    @abc.abstractmethod
    def transport_target(self, hypothesis: TargetHypothesis) -> None:
        """Pick up (or hook onto) the target and carry it to the drop zone."""

    # ------------------------------------------------------------------
    # Sensor access
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def get_inspect_frame(self) -> Optional[np.ndarray]:
        """Return a fresh frame captured during the inspect phase, or ``None``."""

    # ------------------------------------------------------------------
    # Mission lifecycle callback
    # ------------------------------------------------------------------

    def check_mission_complete(self, state_machine) -> None:
        """Called each iteration to let the platform signal mission end.

        Default implementation does nothing.  Override to e.g. detect
        that the search waypoints have been exhausted.
        """
