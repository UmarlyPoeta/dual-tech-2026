"""Central mission manager — orchestrates perception, navigation, and logging."""

from __future__ import annotations

import logging
import time
from typing import List, Optional

import numpy as np

from localization.pose import PoseEstimator
from mission.state_machine import MissionState, StateMachine
from mission.target_registry import TargetRegistry
from models import Pose, TargetHypothesis
from perception.detector import ObjectDetector
from perception.fusion import PerceptionFusion
from perception.qr_reader import QrReader

logger = logging.getLogger(__name__)


class MissionManager:
    """Ties together all subsystems and drives the competition mission loop.

    The manager is *platform-agnostic*: it delegates physical movement to a
    platform-specific **motion interface** (see :mod:`motion.motion_interface`).

    Parameters
    ----------
    config:
        Parsed mission configuration dict (from ``config/common.yaml``).
    detector:
        Loaded :class:`~perception.detector.ObjectDetector`.
    qr_reader:
        Initialised :class:`~perception.qr_reader.QrReader`.
    fusion:
        :class:`~perception.fusion.PerceptionFusion` instance.
    pose_estimator:
        :class:`~localization.pose.PoseEstimator` that is already receiving updates.
    registry:
        :class:`~mission.target_registry.TargetRegistry` shared across the session.
    motion:
        Platform motion interface implementing :class:`~motion.motion_interface.MotionInterface`.
    data_logger:
        :class:`~logging_module.logger.DataLogger` for persisting results.
    target_classes:
        List of class labels that should be acted upon.
    transport_classes:
        List of class labels for which a transport action should be attempted.
    enable_transport:
        Whether to attempt target transport at all.
    """

    def __init__(
        self,
        config: dict,
        detector: ObjectDetector,
        qr_reader: QrReader,
        fusion: PerceptionFusion,
        pose_estimator: PoseEstimator,
        registry: TargetRegistry,
        motion,
        data_logger,
        target_classes: Optional[List[str]] = None,
        transport_classes: Optional[List[str]] = None,
        enable_transport: bool = False,
    ) -> None:
        self._config = config
        self._detector = detector
        self._qr_reader = qr_reader
        self._fusion = fusion
        self._pose_estimator = pose_estimator
        self._registry = registry
        self._motion = motion
        self._data_logger = data_logger
        self._target_classes = target_classes or []
        self._transport_classes = transport_classes or []
        self._enable_transport = enable_transport

        self._sm = StateMachine()
        self._confirm_frames: int = config.get("confirm_frames", 5)
        self._classify_confidence: float = config.get("classify_confidence", 0.6)
        self._qr_retry_count: int = config.get("qr_retry_count", 5)

        # Candidate tracking
        self._candidate_frames: int = 0
        self._current_hypothesis: Optional[TargetHypothesis] = None

    @property
    def state_name(self) -> str:
        """Return the current mission state name."""
        return self._sm.state.name

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, get_frame) -> None:
        """Run the mission loop until finished or aborted.

        Parameters
        ----------
        get_frame:
            Callable that returns the latest BGR frame (``np.ndarray``) or
            ``None`` on error.
        """
        try:
            self._phase_init()
            self._phase_precheck()
            self._phase_search_loop(get_frame)
        except KeyboardInterrupt:
            logger.info("Mission interrupted by operator.")
            self._safe_abort()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Unhandled exception in mission: %s", exc)
            self._safe_abort()
        finally:
            self._phase_return_home()

    # ------------------------------------------------------------------
    # Mission phases
    # ------------------------------------------------------------------

    def _phase_init(self) -> None:
        logger.info("=== INIT ===")
        self._sm.transition_to(MissionState.PRECHECK)

    def _phase_precheck(self) -> None:
        logger.info("=== PRECHECK ===")
        self._motion.precheck()
        self._sm.transition_to(MissionState.SEARCH)

    def _phase_search_loop(self, get_frame) -> None:
        logger.info("=== SEARCH LOOP ===")
        self._motion.start_search()

        while not self._sm.is_terminal():
            frame: Optional[np.ndarray] = get_frame()
            if frame is None:
                time.sleep(0.05)
                continue

            pose = self._pose_estimator.get_pose()
            hypotheses = self._perceive(frame)

            if self._sm.state == MissionState.SEARCH:
                self._handle_search(hypotheses)

            elif self._sm.state == MissionState.DETECT_CANDIDATE:
                self._handle_detect_candidate(hypotheses, frame, pose)

            elif self._sm.state in (
                MissionState.INSPECT,
                MissionState.READ_QR,
                MissionState.CLASSIFY,
                MissionState.REGISTER,
                MissionState.TRANSPORT,
                MissionState.RESUME,
            ):
                # These are handled synchronously inside _handle_detect_candidate
                pass

            elif self._sm.state == MissionState.RETURN_HOME:
                break

            self._motion.check_mission_complete(self._sm)

    def _phase_return_home(self) -> None:
        if not self._sm.is_terminal():
            try:
                self._sm.transition_to(MissionState.RETURN_HOME)
            except ValueError:
                pass
        self._motion.return_home()
        logger.info("=== MISSION SUMMARY: %d targets logged ===", self._registry.count())
        try:
            self._sm.transition_to(MissionState.FINISHED)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Per-frame helpers
    # ------------------------------------------------------------------

    def _perceive(self, frame: np.ndarray) -> List[TargetHypothesis]:
        """Run full perception pipeline on *frame*."""
        all_detections = self._detector.detect(frame)
        box_dets = [d for d in all_detections if d.label == "box"]
        obj_dets = [d for d in all_detections if d.label != "box"]
        qr_dets = self._qr_reader.decode(frame)
        return self._fusion.fuse(
            box_dets, obj_dets, qr_dets, target_classes=self._target_classes or None
        )

    def _handle_search(self, hypotheses: List[TargetHypothesis]) -> None:
        confident = [
            h for h in hypotheses if h.confidence >= self._classify_confidence
        ]
        if confident:
            self._current_hypothesis = confident[0]
            self._candidate_frames = 1
            self._sm.transition_to(MissionState.DETECT_CANDIDATE)
        else:
            self._candidate_frames = 0

    def _handle_detect_candidate(
        self,
        hypotheses: List[TargetHypothesis],
        frame: np.ndarray,
        pose: Optional[Pose],
    ) -> None:
        # Check if the same candidate is still visible
        still_visible = any(
            h.class_name == (self._current_hypothesis.class_name if self._current_hypothesis else None)
            and h.confidence >= self._classify_confidence
            for h in hypotheses
        )

        if still_visible:
            self._candidate_frames += 1
        else:
            # Lost sight — go back to searching
            logger.debug("Candidate lost, returning to SEARCH")
            self._candidate_frames = 0
            self._sm.transition_to(MissionState.SEARCH)
            return

        if self._candidate_frames >= self._confirm_frames:
            self._execute_inspect_sequence(frame, pose)

    def _execute_inspect_sequence(self, frame: np.ndarray, pose: Optional[Pose]) -> None:
        """Drive through INSPECT → READ_QR → CLASSIFY → REGISTER → (TRANSPORT) → RESUME."""
        try:
            # INSPECT
            self._sm.transition_to(MissionState.INSPECT)
            self._motion.inspect_target(self._current_hypothesis)

            # READ_QR
            self._sm.transition_to(MissionState.READ_QR)
            latest_frame = self._motion.get_inspect_frame()
            qr_results = []
            for _ in range(self._qr_retry_count):
                if latest_frame is not None:
                    qr_results = self._qr_reader.decode(latest_frame)
                if qr_results:
                    break
                time.sleep(0.2)
                latest_frame = self._motion.get_inspect_frame()

            if qr_results and self._current_hypothesis is not None:
                self._current_hypothesis.qr_detection = qr_results[0]

            # CLASSIFY
            self._sm.transition_to(MissionState.CLASSIFY)
            # Classification already done by YOLO; just log it

            # REGISTER
            self._sm.transition_to(MissionState.REGISTER)
            current_pose = self._pose_estimator.get_pose()
            if current_pose and self._current_hypothesis is not None:
                record = self._registry.register(self._current_hypothesis, current_pose)
                if record is not None:
                    self._data_logger.log_target(record, frame)

            # TRANSPORT (optional)
            should_transport = (
                self._enable_transport
                and self._current_hypothesis is not None
                and self._current_hypothesis.class_name in self._transport_classes
            )
            if should_transport:
                self._sm.transition_to(MissionState.TRANSPORT)
                self._motion.transport_target(self._current_hypothesis)
                if self._current_hypothesis is not None:
                    self._registry.mark_transported(self._current_hypothesis.id)

            # RESUME
            self._sm.transition_to(MissionState.RESUME)
            self._motion.resume_search()
            self._sm.transition_to(MissionState.SEARCH)
            self._current_hypothesis = None
            self._candidate_frames = 0

        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Error during inspect sequence: %s", exc)
            self._safe_abort()

    def _safe_abort(self) -> None:
        try:
            self._sm.transition_to(MissionState.ABORT)
        except ValueError:
            pass
        self._motion.emergency_stop()
