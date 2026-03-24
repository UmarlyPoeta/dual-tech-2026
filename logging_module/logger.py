"""Data logger — persists target records, annotated frames, CSV, and JSON.

Includes automatic log rotation and disk space management to prevent
"disk full" errors during competition.
"""

from __future__ import annotations

import csv
import json
import logging
import logging.handlers
import os
import shutil
import time
from pathlib import Path
from typing import List, Optional

import numpy as np

from models import TargetRecord

logger = logging.getLogger(__name__)

MAX_LOGS_DIR_MB = 500
MAX_LOG_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per file
LOG_BACKUP_COUNT = 3
MAX_SESSIONS_KEPT = 5


class DataLogger:
    """Logs confirmed target records to CSV, JSON, and (optionally) images.

    Automatically manages disk usage:
    - Rotating file handler for Python log output
    - Startup cleanup of old session directories
    - Periodic disk space warnings

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
        self._base_dir = Path(output_dir) / platform
        self._output_dir = self._base_dir / time.strftime("%Y%m%d_%H%M%S")
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self._save_frames: bool = config.get("save_annotated_frames", True)
        self._csv_path = self._output_dir / config.get("csv_filename", "targets.csv")
        self._json_path = self._output_dir / config.get("json_filename", "targets.json")

        self._records: List[TargetRecord] = []
        self._csv_writer: Optional[csv.DictWriter] = None
        self._csv_file = None

        # Set up rotating file handler for this session
        self._setup_rotating_log()

        # Clean up old sessions on startup
        self._cleanup_old_sessions(config.get("max_sessions", MAX_SESSIONS_KEPT))

        self._open_csv()

        logger.info("DataLogger ready (output=%s)", self._output_dir)

    # ------------------------------------------------------------------
    # Log rotation and disk management
    # ------------------------------------------------------------------

    def _setup_rotating_log(self) -> None:
        """Add a rotating file handler for structured logging output."""
        log_file = self._output_dir / "mission.log"
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=MAX_LOG_FILE_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        logging.getLogger().addHandler(handler)

    def _cleanup_old_sessions(self, max_sessions: int = MAX_SESSIONS_KEPT) -> None:
        """Delete old session directories to keep disk usage in check."""
        if not self._base_dir.exists():
            return

        sessions = sorted(
            [d for d in self._base_dir.iterdir() if d.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        # Keep only the N most recent sessions
        for old_session in sessions[max_sessions:]:
            try:
                shutil.rmtree(old_session)
                logger.info("Cleaned up old log session: %s", old_session.name)
            except Exception as e:
                logger.warning("Failed to clean up %s: %s", old_session, e)

        # If total size still exceeds limit, remove more
        total_mb = self._dir_size_mb(self._base_dir.parent)
        if total_mb > MAX_LOGS_DIR_MB:
            logger.warning("Logs directory %.0f MB exceeds %d MB limit — cleaning aggressively",
                           total_mb, MAX_LOGS_DIR_MB)
            for old_session in sessions[2:]:  # Keep only 2 most recent
                if not old_session.exists():
                    continue
                try:
                    shutil.rmtree(old_session)
                except Exception:
                    pass

    @staticmethod
    def _dir_size_mb(path: Path) -> float:
        """Calculate directory size in megabytes."""
        total = 0
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        except Exception:
            pass
        return total / (1024 * 1024)

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
