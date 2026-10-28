from __future__ import annotations

import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text


def test_alembic_head_contains_device_calibration_history_and_sample_fingerprints(tmp_path):
    db_file = tmp_path / "calibration-migration.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file}"
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "speaker_device_calibrations" in tables
        assert "session_speaker_calibration_snapshots" in tables
        assert "asr_recognition_evidence" in tables
        assert "asr_recognition_revisions" in tables
        assert "speaker_backend_comparison_evidence" in tables

        calibration_columns = {item["name"] for item in inspector.get_columns("speaker_device_calibrations")}
        assert {
            "threshold", "margin", "far", "frr", "eer", "eer_threshold", "eer_far", "eer_frr",
            "speaker_backend_key", "speaker_model_fingerprint", "microphone_fingerprint", "corpus_digest",
        } <= calibration_columns

        sample_columns = {item["name"] for item in inspector.get_columns("officer_voice_samples")}
        assert {"model_fingerprint", "microphone_fingerprint", "microphone_fingerprint_certainty"} <= sample_columns

        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "0027_document_fingerprints"
    finally:
        engine.dispose()
