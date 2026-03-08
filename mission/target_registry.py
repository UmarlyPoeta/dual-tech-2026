"""Target registry — tracks confirmed targets and prevents duplicate logging."""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

from localization.pose import PoseEstimator
from models import Pose, TargetHypothesis, TargetRecord

logger = logging.getLogger(__name__)


class TargetRegistry:
    """Keeps a deduplicated list of all confirmed targets encountered.

    A new hypothesis is considered a *duplicate* of an existing record if:
    * It is within *revisit_radius_m* metres of the existing record's GPS position, **and**
    * Its class matches (or both are unclassified).

    Parameters
    ----------
    revisit_radius_m:
        Spatial threshold for duplicate detection (metres).
    platform:
        ``"uav"`` or ``"ugv"`` — stored in each :class:`~models.TargetRecord`.
    """

    def __init__(self, revisit_radius_m: float = 3.0, platform: str = "unknown") -> None:
        self._radius = revisit_radius_m
        self._platform = platform
        self._records: List[TargetRecord] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, hypothesis: TargetHypothesis, pose: Pose) -> Optional[TargetRecord]:
        """Attempt to register a confirmed hypothesis.

        Returns the new :class:`~models.TargetRecord` if it was added,
        or ``None`` if it was a duplicate.
        """
        with self._lock:
            for existing in self._records:
                dist = PoseEstimator.haversine_distance(
                    existing.lat, existing.lon, pose.lat, pose.lon
                )
                same_class = (existing.class_name == hypothesis.class_name) or (
                    existing.class_name is None and hypothesis.class_name is None
                )
                if dist <= self._radius and same_class:
                    logger.debug(
                        "Duplicate target suppressed (dist=%.1f m, class=%s)",
                        dist,
                        hypothesis.class_name,
                    )
                    return None

            record = TargetRecord(
                target_id=hypothesis.id,
                source_platform=self._platform,
                class_name=hypothesis.class_name,
                qr_value=hypothesis.qr_value,
                lat=pose.lat,
                lon=pose.lon,
                alt=pose.alt,
            )
            self._records.append(record)
            logger.info(
                "Target registered [#%d] class=%s qr=%s lat=%.6f lon=%.6f",
                len(self._records),
                record.class_name,
                record.qr_value,
                record.lat,
                record.lon,
            )
            return record

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def all_records(self) -> List[TargetRecord]:
        with self._lock:
            return list(self._records)

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def mark_transported(self, target_id: str) -> bool:
        """Mark a target as transported.  Returns ``True`` if found."""
        with self._lock:
            for record in self._records:
                if record.target_id == target_id:
                    record.transported = True
                    return True
        return False
