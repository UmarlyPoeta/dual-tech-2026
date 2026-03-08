"""Tests for the mission state machine."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from mission.state_machine import MissionState, StateMachine


def test_initial_state():
    sm = StateMachine()
    assert sm.state == MissionState.INIT


def test_valid_transition():
    sm = StateMachine()
    sm.transition_to(MissionState.PRECHECK)
    assert sm.state == MissionState.PRECHECK


def test_invalid_transition_raises():
    sm = StateMachine()
    with pytest.raises(ValueError, match="Invalid transition"):
        sm.transition_to(MissionState.SEARCH)  # must go through PRECHECK first


def test_full_happy_path():
    sm = StateMachine()
    path = [
        MissionState.PRECHECK,
        MissionState.SEARCH,
        MissionState.DETECT_CANDIDATE,
        MissionState.INSPECT,
        MissionState.READ_QR,
        MissionState.CLASSIFY,
        MissionState.REGISTER,
        MissionState.RESUME,
        MissionState.RETURN_HOME,
        MissionState.FINISHED,
    ]
    for state in path:
        sm.transition_to(state)
    assert sm.state == MissionState.FINISHED


def test_abort_from_search():
    sm = StateMachine()
    sm.transition_to(MissionState.PRECHECK)
    sm.transition_to(MissionState.SEARCH)
    sm.transition_to(MissionState.ABORT)
    assert sm.state == MissionState.ABORT
    assert sm.is_terminal()


def test_history_is_tracked():
    sm = StateMachine()
    sm.transition_to(MissionState.PRECHECK)
    sm.transition_to(MissionState.SEARCH)
    assert MissionState.INIT in sm.history
    assert MissionState.PRECHECK in sm.history
    assert MissionState.SEARCH in sm.history


def test_transport_path():
    sm = StateMachine()
    sm.transition_to(MissionState.PRECHECK)
    sm.transition_to(MissionState.SEARCH)
    sm.transition_to(MissionState.DETECT_CANDIDATE)
    sm.transition_to(MissionState.INSPECT)
    sm.transition_to(MissionState.CLASSIFY)
    sm.transition_to(MissionState.REGISTER)
    sm.transition_to(MissionState.TRANSPORT)
    sm.transition_to(MissionState.RESUME)
    sm.transition_to(MissionState.SEARCH)
    assert sm.state == MissionState.SEARCH
