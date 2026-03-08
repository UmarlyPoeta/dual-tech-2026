"""Tests for DataLogger."""

import sys
import os
import tempfile
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from logging_module.logger import DataLogger
from models import TargetRecord


def _make_record(class_name="box", qr_value=None, lat=50.0, lon=20.0):
    return TargetRecord(
        target_id="test-001",
        source_platform="ugv",
        class_name=class_name,
        qr_value=qr_value,
        lat=lat,
        lon=lon,
    )


def test_logger_creates_output_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = {"output_dir": tmpdir, "save_annotated_frames": False,
               "csv_filename": "t.csv", "json_filename": "t.json"}
        with DataLogger(cfg, platform="test") as dl:
            assert dl.output_dir.exists()


def test_logger_writes_csv_row():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = {"output_dir": tmpdir, "save_annotated_frames": False,
               "csv_filename": "t.csv", "json_filename": "t.json"}
        with DataLogger(cfg, platform="test") as dl:
            rec = _make_record(class_name="red_object", qr_value="QR42")
            dl.log_target(rec)

        # CSV should contain the record
        import csv
        from pathlib import Path
        csv_files = list(Path(tmpdir).rglob("t.csv"))
        assert len(csv_files) == 1
        with open(csv_files[0]) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["class_name"] == "red_object"
        assert rows[0]["qr_value"] == "QR42"


def test_logger_writes_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = {"output_dir": tmpdir, "save_annotated_frames": False,
               "csv_filename": "t.csv", "json_filename": "t.json"}
        with DataLogger(cfg, platform="test") as dl:
            dl.log_target(_make_record(class_name="box"))

        from pathlib import Path
        json_files = list(Path(tmpdir).rglob("t.json"))
        assert len(json_files) == 1
        with open(json_files[0]) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["class_name"] == "box"


def test_logger_all_records():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = {"output_dir": tmpdir, "save_annotated_frames": False,
               "csv_filename": "t.csv", "json_filename": "t.json"}
        with DataLogger(cfg, platform="test") as dl:
            dl.log_target(_make_record(lat=50.0))
            dl.log_target(_make_record(lat=51.0))
            assert len(dl.all_records()) == 2
