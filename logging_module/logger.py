"""Data logger — persists target records, annotated frames, CSV, and JSON."""

from __future__ import annotations

import csv
import json
import logging
import os
import time
from pathlib import Path
from typing import List, Optional

import numpy as np

from models import TargetRecord

logger = logging.getLogger(__name__)


class DataLogger:
    """Logs confirmed target records to CSV, JSON, and (optionally) images.

    Parameters
    ----------
    config:
        Parsed logging configuration dict (from ``config/common.yaml``
        under the ``logging`` key).
    platform:
        ``"uav"`` or ``"ugv"`` — used to prefix log filenames.
    """

    def __init__(self, config: dict, platform: str = "unknown") -> None:
        self._platform = platform
        output_dir = config.get("output_dir", "logs")
        self._output_dir = Path(output_dir) / platform / time.strftime("%Y%m%d_%H%M%S")
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self._save_frames: bool = config.get("save_annotated_frames", True)
        self._csv_path = self._output_dir / config.get("csv_filename", "targets.csv")
        self._json_path = self._output_dir / config.get("json_filename", "targets.json")

        self._records: List[TargetRecord] = []
        self._csv_writer: Optional[csv.DictWriter] = None
        self._csv_file = None
        self._open_csv()

        logger.info("DataLogger ready (output=%s)", self._output_dir)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _open_csv(self) -> None:
        self._csv_file = open(self._csv_path, "w", newline="", encoding="utf-8")
        fieldnames = [
            "target_id", "source_platform", "class_name", "qr_value",
            "lat", "lon", "alt", "timestamp", "transported",
        ]
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=fieldnames)
        self._csv_writer.writeheader()

    def close(self) -> None:
        """Flush and close all open file handles."""
        if self._csv_file is not None:
            self._csv_file.flush()
            self._csv_file.close()
            self._csv_file = None
        self._flush_json()
        logger.info("DataLogger closed (%d records written).", len(self._records))

    def __enter__(self) -> "DataLogger":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Logging methods
    # ------------------------------------------------------------------

    def log_target(self, record: TargetRecord, frame: Optional[np.ndarray] = None) -> None:
        """Persist a confirmed target record.

        Parameters
        ----------
        record:
            Confirmed :class:`~models.TargetRecord` from the registry.
        frame:
            Optional BGR image to save alongside the record.
        """
        self._records.append(record)

        # CSV row
        if self._csv_writer is not None:
            self._csv_writer.writerow(
                {
                    "target_id": record.target_id,
                    "source_platform": record.source_platform,
                    "class_name": record.class_name or "",
                    "qr_value": record.qr_value or "",
                    "lat": record.lat,
                    "lon": record.lon,
                    "alt": record.alt if record.alt is not None else "",
                    "timestamp": record.timestamp,
                    "transported": record.transported,
                }
            )
            if self._csv_file is not None:
                self._csv_file.flush()

        # Image
        if self._save_frames and frame is not None:
            self._save_frame(record, frame)

        logger.info(
            "Logged target #%d — class=%s qr=%s lat=%.6f lon=%.6f",
            len(self._records),
            record.class_name,
            record.qr_value,
            record.lat,
            record.lon,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save_frame(self, record: TargetRecord, frame: np.ndarray) -> None:
        try:
            import cv2  # type: ignore

            fname = self._output_dir / f"{record.target_id[:8]}.jpg"
            cv2.imwrite(str(fname), frame)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Could not save frame: %s", exc)

    def _flush_json(self) -> None:
        data = [
            {
                "target_id": r.target_id,
                "source_platform": r.source_platform,
                "class_name": r.class_name,
                "qr_value": r.qr_value,
                "lat": r.lat,
                "lon": r.lon,
                "alt": r.alt,
                "timestamp": r.timestamp,
                "transported": r.transported,
            }
            for r in self._records
        ]
        with open(self._json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    def all_records(self) -> List[TargetRecord]:
        return list(self._records)
