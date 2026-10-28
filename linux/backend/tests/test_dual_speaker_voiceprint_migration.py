from __future__ import annotations

import os
import struct
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


EXPECTED_HEAD = "0027_document_fingerprints"
XVECTOR = "xvector"


def _run_alembic(tmp_path: Path, target: str):
    db_file = tmp_path / "dual-speaker-migration.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return db_file, env, result


def _upgrade_existing(db_file: Path, env: dict[str, str], target: str):
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_0009_head_exposes_model_aware_voiceprint_columns_and_uniqueness(tmp_path):
    db_file, _env, result = _run_alembic(tmp_path, "head")
    assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        inspector = inspect(engine)
        for table in (
            "suspect_voiceprints",
            "officer_voiceprints",
            "officer_voice_profiles",
            "officer_voice_samples",
            "session_officer_voice_snapshots",
        ):
            assert "model_key" in {column["name"] for column in inspector.get_columns(table)}

        suspect_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("suspect_voiceprints")
        }
        officer_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("officer_voiceprints")
        }
        profile_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("officer_voice_profiles")
        }
        assert ("case_id", "model_key") in suspect_uniques
        assert ("officer_id", "model_key") in officer_uniques
        assert ("officer_id", "model_key") in profile_uniques

        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == EXPECTED_HEAD
    finally:
        engine.dispose()


def test_0009_migrates_preexisting_rows_to_xvector_without_changing_embedding_bytes(tmp_path):
    db_file, env, result = _run_alembic(tmp_path, "0008_qwen_formal_record_routing")
    assert result.returncode == 0, result.stdout + result.stderr
    suspect_embedding = struct.pack("<3f", 0.25, 0.5, 0.75)
    officer_embedding = struct.pack("<2f", 0.6, 0.8)
    now = "2026-09-01 00:00:00"

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO cases "
                    "(id, operator_id, case_type, suspect_name, gender, age, officer_name, workflow_state, stage, "
                    "document_status, report_status, created_at, updated_at) "
                    "VALUES ('CASE-DUAL-M', NULL, 'suspect_interrogation', '嫌疑人', NULL, NULL, '测试警官', "
                    "'IDENTITY_REQUIRED', 'IDENTITY', 'DRAFT', 'PENDING', :now, :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO interrogation_sessions "
                    "(id, case_id, status, stage, started_at, paused_at, ended_at, created_at, updated_at) "
                    "VALUES ('SESSION-DUAL-M', 'CASE-DUAL-M', 'READY', 'IDENTITY', NULL, NULL, NULL, :now, :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO suspect_voiceprints "
                    "(id, case_id, embedding, embedding_dim, model_id, model_version, enrollment_quality, "
                    "usable_duration_ms, active, created_at, updated_at) "
                    "VALUES ('SUS-DUAL-M', 'CASE-DUAL-M', :embedding, 3, 'xvector', 'legacy-v1', 'GOOD', 22000, 1, :now, :now)"
                ),
                {"embedding": suspect_embedding, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO officer_voiceprints "
                    "(id, officer_id, officer_name, embedding, embedding_dim, model_id, model_version, enrollment_quality, "
                    "usable_duration_ms, active, revoked_at, created_at, updated_at) "
                    "VALUES ('OFF-DUAL-M', 'P-DUAL', '张警官', :embedding, 2, 'xvector', 'legacy-v1', 'GOOD', 24000, 1, NULL, :now, :now)"
                ),
                {"embedding": officer_embedding, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO officer_voice_profiles "
                    "(id, officer_id, officer_name, aggregate_embedding, embedding_dim, model_id, model_version, "
                    "aggregate_version, sample_count, active, revoked_at, created_at, updated_at) "
                    "VALUES ('PROF-DUAL-M', 'P-DUAL', '张警官', :embedding, 2, 'xvector', 'legacy-v1', 1, 1, 1, NULL, :now, :now)"
                ),
                {"embedding": officer_embedding, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO officer_voice_samples "
                    "(id, profile_id, embedding, embedding_dim, model_id, model_version, model_fingerprint, quality, "
                    "usable_duration_ms, segment_count, audio_source, device_id, device_name, microphone_fingerprint, "
                    "microphone_fingerprint_certainty, captured_at, active, disabled_at, disabled_reason, created_by, "
                    "created_at, updated_at) "
                    "VALUES ('SAMPLE-DUAL-M', 'PROF-DUAL-M', :embedding, 2, 'xvector', 'legacy-v1', :fingerprint, 'GOOD', "
                    "24000, 3, 'ALSA', 'default', 'Linux ALSA Microphone', NULL, NULL, :now, 1, NULL, NULL, NULL, :now, :now)"
                ),
                {"embedding": officer_embedding, "fingerprint": "a" * 64, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO session_voice_assignments "
                    "(id, session_id, suspect_voiceprint_id, interrogator_officer_id, interrogator_voiceprint_id, "
                    "recorder_officer_id, recorder_voiceprint_id, recognition_mode, created_at, updated_at) "
                    "VALUES ('ASSIGN-DUAL-M', 'SESSION-DUAL-M', 'SUS-DUAL-M', 'P-DUAL', 'OFF-DUAL-M', "
                    "NULL, NULL, 'SUSPECT_PLUS_INTERROGATOR', :now, :now)"
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO session_officer_voice_snapshots "
                    "(id, session_id, role, officer_id, profile_id, aggregate_version, voiceprint_snapshot_id, "
                    "model_id, model_version, created_at) "
                    "VALUES ('SNAP-DUAL-M', 'SESSION-DUAL-M', 'INTERROGATOR', 'P-DUAL', 'PROF-DUAL-M', 1, "
                    "'OFF-DUAL-M', 'xvector', 'legacy-v1', :now)"
                ),
                {"now": now},
            )
    finally:
        engine.dispose()

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.begin() as connection:
            for table in (
                "officer_voice_samples",
                "session_officer_voice_snapshots",
                "session_voice_assignments",
                ):
                    backup = f"__0009_backup_{table}"
                    connection.execute(text(f'CREATE TABLE "{backup}" AS SELECT * FROM "{table}"'))
                    if table != "session_voice_assignments":
                        connection.execute(text(f'DELETE FROM "{table}"'))
    finally:
        engine.dispose()

    result = _upgrade_existing(db_file, env, "head")
    assert result.returncode == 0, result.stdout + result.stderr

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as connection:
            suspect = connection.execute(
                text("SELECT model_key, embedding FROM suspect_voiceprints WHERE id='SUS-DUAL-M'")
            ).mappings().one()
            officer = connection.execute(
                text("SELECT model_key, embedding FROM officer_voiceprints WHERE id='OFF-DUAL-M'")
            ).mappings().one()
            profile = connection.execute(
                text("SELECT model_key, aggregate_embedding FROM officer_voice_profiles WHERE id='PROF-DUAL-M'")
            ).mappings().one()
            sample = connection.execute(
                text("SELECT model_key, embedding, model_fingerprint, profile_id FROM officer_voice_samples WHERE id='SAMPLE-DUAL-M'")
            ).mappings().one()
            assignment = connection.execute(
                text(
                    "SELECT suspect_voiceprint_id, interrogator_officer_id, interrogator_voiceprint_id "
                    "FROM session_voice_assignments WHERE id='ASSIGN-DUAL-M'"
                )
            ).mappings().one()
            snapshot = connection.execute(
                text(
                    "SELECT model_key, profile_id, voiceprint_snapshot_id, model_id, model_version "
                    "FROM session_officer_voice_snapshots WHERE id='SNAP-DUAL-M'"
                )
            ).mappings().one()
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

        assert revision == EXPECTED_HEAD
        assert suspect["model_key"] == XVECTOR
        assert officer["model_key"] == XVECTOR
        assert profile["model_key"] == XVECTOR
        assert sample["model_key"] == XVECTOR
        assert snapshot["model_key"] == XVECTOR
        assert bytes(suspect["embedding"]) == suspect_embedding
        assert bytes(officer["embedding"]) == officer_embedding
        assert bytes(profile["aggregate_embedding"]) == officer_embedding
        assert bytes(sample["embedding"]) == officer_embedding
        assert sample["model_fingerprint"] == "a" * 64
        assert sample["profile_id"] == "PROF-DUAL-M"
        assert assignment == {
            "suspect_voiceprint_id": "SUS-DUAL-M",
            "interrogator_officer_id": "P-DUAL",
            "interrogator_voiceprint_id": "OFF-DUAL-M",
        }
        assert snapshot == {
            "model_key": XVECTOR,
            "profile_id": "PROF-DUAL-M",
            "voiceprint_snapshot_id": "OFF-DUAL-M",
            "model_id": "xvector",
            "model_version": "legacy-v1",
        }
        tables = set(inspect(engine).get_table_names())
        assert not {"__0009_backup_officer_voice_samples", "__0009_backup_session_officer_voice_snapshots", "__0009_backup_session_voice_assignments"} & tables
    finally:
        engine.dispose()
