"""Shared data models used by both UAV and UGV platforms."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class Detection:
    """Single object detection result from YOLO."""

    label: str
    confidence: float
    # (x_min, y_min, x_max, y_max) in pixel coordinates
    bbox: Tuple[float, float, float, float]
    frame_id: int = 0
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)


@dataclass
class QrDetection:
    """Decoded QR code detection result."""

    payload: str
    confidence: float
    bbox: Tuple[float, float, float, float]
    timestamp: float = field(default_factory=time.time)


@dataclass
class Pose:
    """Position and orientation of the robot."""

    lat: float
    lon: float
    alt: Optional[float] = None       # metres above sea level (UAV)
    yaw_deg: Optional[float] = None   # heading in degrees (0 = North)
    pitch_deg: Optional[float] = None  # camera/vehicle pitch


@dataclass
class TargetHypothesis:
    """Fused hypothesis about a single physical target in the field."""

    box_detection: Optional[Detection] = None
    object_detection: Optional[Detection] = None
    qr_detection: Optional[QrDetection] = None
    confidence: float = 0.0
    pose: Optional[Pose] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)

    @property
    def class_name(self) -> Optional[str]:
        if self.object_detection is not None:
            return self.object_detection.label
        if self.box_detection is not None:
            return self.box_detection.label
        return None

    @property
    def qr_value(self) -> Optional[str]:
        if self.qr_detection is not None:
            return self.qr_detection.payload
        return None


@dataclass
class TargetRecord:
    """Confirmed and logged target entry."""

    target_id: str
    source_platform: str          # "uav" or "ugv"
    class_name: Optional[str]
    qr_value: Optional[str]
    lat: float
    lon: float
    alt: Optional[float] = None
    timestamp: float = field(default_factory=time.time)
    transported: bool = False
