"""Tests for PoseEstimator helpers."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import pytest
from localization.pose import PoseEstimator
from models import Pose


def test_haversine_zero_distance():
    d = PoseEstimator.haversine_distance(50.0, 20.0, 50.0, 20.0)
    assert d == pytest.approx(0.0)


def test_haversine_known_distance():
    # Kraków (50.0647°N, 19.9450°E) — roughly 1 degree of latitude ≈ 111 km
    d = PoseEstimator.haversine_distance(50.0, 20.0, 51.0, 20.0)
    assert 110_000 < d < 112_000  # ~111 km


def test_pose_estimator_update_gps():
    pe = PoseEstimator()
    pe.update_gps(50.1, 20.2, alt=100.0)
    pose = pe.get_pose()
    assert pose is not None
    assert pose.lat == pytest.approx(50.1)
    assert pose.lon == pytest.approx(20.2)
    assert pose.alt == pytest.approx(100.0)


def test_pose_estimator_no_gps_returns_none():
    pe = PoseEstimator()
    assert pe.get_pose() is None


def test_pose_estimator_update_heading():
    pe = PoseEstimator()
    pe.update_gps(50.0, 20.0)
    pe.update_heading(270.0)
    pose = pe.get_pose()
    assert pose is not None
    assert pose.yaw_deg == pytest.approx(270.0)


def test_pose_estimator_bulk_update():
    pe = PoseEstimator()
    p = Pose(lat=49.9, lon=21.0, alt=50.0, yaw_deg=180.0)
    pe.update_pose(p)
    result = pe.get_pose()
    assert result is not None
    assert result.lat == pytest.approx(49.9)
    assert result.yaw_deg == pytest.approx(180.0)
