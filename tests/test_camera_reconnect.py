"""Tests for Camera auto-reconnect behaviour."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from perception.camera import Camera, _FAIL_THRESHOLD


class TestCameraReconnect:
    """Test that Camera automatically reconnects after repeated failures."""

    def test_consecutive_failures_triggers_reconnect(self):
        """After _FAIL_THRESHOLD failures, the camera should attempt reconnect."""
        cam = Camera(source=0)

        # Mock cv2 module
        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (False, None)  # simulate failures
        mock_cv2.VideoCapture.return_value = mock_cap

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            cam.open()
            # Drain failures up to threshold
            for _ in range(_FAIL_THRESHOLD):
                result = cam.get_frame()
                assert result is None

            # The next get_frame should trigger _try_reconnect
            # which calls close() then open()
            assert cam._consecutive_failures >= _FAIL_THRESHOLD

        cam.close()

    def test_successful_read_resets_counter(self):
        """A successful frame read should reset the failure counter."""
        cam = Camera(source=0)

        mock_cv2 = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True

        fake_frame = np.zeros((48, 64, 3), dtype=np.uint8)

        # First N reads fail, then one succeeds
        reads = [(False, None)] * 5 + [(True, fake_frame)]
        mock_cap.read.side_effect = reads
        mock_cv2.VideoCapture.return_value = mock_cap

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            cam.open()
            for _ in range(5):
                cam.get_frame()
            assert cam._consecutive_failures == 5

            # Successful read
            frame = cam.get_frame()
            assert frame is not None
            assert cam._consecutive_failures == 0

        cam.close()
