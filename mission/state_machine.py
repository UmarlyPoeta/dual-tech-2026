"""Competition mission state machine."""

from __future__ import annotations

import logging
from enum import Enum, auto

logger = logging.getLogger(__name__)


class MissionState(Enum):
    """All states of the competition mission finite-state machine."""

    INIT = auto()
    PRECHECK = auto()
    SEARCH = auto()
    DETECT_CANDIDATE = auto()
    INSPECT = auto()
    READ_QR = auto()
    CLASSIFY = auto()
    REGISTER = auto()
    TRANSPORT = auto()
    RESUME = auto()
    RETURN_HOME = auto()
    ABORT = auto()
    FINISHED = auto()


# Valid transitions: maps a state → set of states it may transition to
_VALID_TRANSITIONS: dict[MissionState, set[MissionState]] = {
    MissionState.INIT: {MissionState.PRECHECK, MissionState.ABORT},
    MissionState.PRECHECK: {MissionState.SEARCH, MissionState.ABORT},
    MissionState.SEARCH: {MissionState.DETECT_CANDIDATE, MissionState.RETURN_HOME, MissionState.ABORT},
    MissionState.DETECT_CANDIDATE: {MissionState.INSPECT, MissionState.SEARCH, MissionState.ABORT},
    MissionState.INSPECT: {MissionState.READ_QR, MissionState.CLASSIFY, MissionState.ABORT},
    MissionState.READ_QR: {MissionState.CLASSIFY, MissionState.REGISTER, MissionState.INSPECT, MissionState.ABORT},
    MissionState.CLASSIFY: {MissionState.REGISTER, MissionState.ABORT},
    MissionState.REGISTER: {MissionState.TRANSPORT, MissionState.RESUME, MissionState.ABORT},
    MissionState.TRANSPORT: {MissionState.RESUME, MissionState.ABORT},
    MissionState.RESUME: {MissionState.SEARCH, MissionState.RETURN_HOME, MissionState.ABORT},
    MissionState.RETURN_HOME: {MissionState.FINISHED, MissionState.ABORT},
    MissionState.ABORT: {MissionState.FINISHED},
    MissionState.FINISHED: set(),
}


class StateMachine:
    """Lightweight finite-state machine for the competition mission.

    Usage
    -----
    ::

        sm = StateMachine()
        sm.transition_to(MissionState.PRECHECK)
    """

    def __init__(self) -> None:
        self._state = MissionState.INIT
        self._history: list[MissionState] = [MissionState.INIT]

    @property
    def state(self) -> MissionState:
        return self._state

    def transition_to(self, new_state: MissionState) -> None:
        """Transition to *new_state*.

        Raises
        ------
        ValueError
            If the transition is not valid from the current state.
        """
        allowed = _VALID_TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            raise ValueError(
                f"Invalid transition: {self._state.name} → {new_state.name}. "
                f"Allowed: {[s.name for s in allowed]}"
            )
        logger.info("State: %s → %s", self._state.name, new_state.name)
        self._state = new_state
        self._history.append(new_state)

    def is_terminal(self) -> bool:
        return self._state in (MissionState.FINISHED, MissionState.ABORT)

    @property
    def history(self) -> list[MissionState]:
        return list(self._history)
