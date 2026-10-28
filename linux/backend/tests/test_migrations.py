import os
import struct
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError


CORE_TABLES = {
    "cases", "persons", "interrogation_sessions", "messages", "message_revisions",
    "facts", "timeline_events", "audit_logs", "device_events", "document_snapshots", "signature_records",
}
VOICEPRINT_TABLES = {
    "suspect_voiceprints", "officer_voiceprints", "session_voice_assignments", "asr_capture_sessions", "asr_fragments",
}
TEMPLATE_TABLES = {
    "standard_questions", "case_questions", "question_rounds", "pending_questions", "processed_speech_fragments",
}
OFFICER_LIBRARY_TABLES = {
    "officer_voice_profiles", "officer_voice_samples", "session_officer_voice_snapshots",
}
CALIBRATION_TABLES = {
    "speaker_device_calibrations", "session_speaker_calibration_snapshots",
}
RECOGNITION_EVIDENCE_TABLES = {
    "asr_recognition_evidence", "asr_recognition_revisions",
    "speaker_backend_comparison_evidence", "asr_speaker_analysis_results",
}
QWEN_ROUTING_TABLES = {
    "qa_units", "qa_unit_fragments",
}
# MOSS 已下线：0020 删除了 0013 建的三张表，head 上不得再有。
RETIRED_MOSS_TABLES = {
    "moss_transcriptions", "moss_transcription_revisions", "moss_speaker_mappings",
}
CASE_DRAFT_TABLES = {"case_voice_role_drafts"}
DURABLE_LIVE_SPEECH_TABLES = {
    "asr_audio_segments", "asr_audio_frames", "live_speech_jobs", "asr_fragment_lineage",
}
REQUIRED_TABLES = (
    CORE_TABLES | VOICEPRINT_TABLES | TEMPLATE_TABLES | OFFICER_LIBRARY_TABLES |
    CALIBRATION_TABLES | RECOGNITION_EVIDENCE_TABLES | QWEN_ROUTING_TABLES |
    CASE_DRAFT_TABLES | DURABLE_LIVE_SPEECH_TABLES
)
ALEMBIC_HEAD = "0027_document_fingerprints"


def _run_alembic(tmp_path, target: str):
    db_file = tmp_path / "alembic.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return db_file, env, result


def _sqlite_engine_with_foreign_keys(db_file):
    engine = create_engine(f"sqlite:///{db_file}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def test_alembic_honors_runtime_suspect_db_path(tmp_path):
    db_file = tmp_path / "production-runtime.db"
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("DB_PATH", None)
    env["SUSPECT_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert db_file.is_file()
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == ALEMBIC_HEAD
    finally:
        engine.dispose()


def test_alembic_revision_0001_remains_core_only(tmp_path):
    db_file, _env, result = _run_alembic(tmp_path, "0001_linux_core_schema")
    assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        tables = set(inspect(engine).get_table_names())
        assert CORE_TABLES <= tables
        assert VOICEPRINT_TABLES.isdisjoint(tables)
        assert TEMPLATE_TABLES.isdisjoint(tables)
        assert OFFICER_LIBRARY_TABLES.isdisjoint(tables)
        assert CALIBRATION_TABLES.isdisjoint(tables)
        assert RECOGNITION_EVIDENCE_TABLES.isdisjoint(tables)
    finally:
        engine.dispose()


def test_alembic_revision_0002_remains_voiceprint_only(tmp_path):
    db_file, _env, result = _run_alembic(tmp_path, "0002_voiceprint_speech_pipeline")
    assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        tables = set(inspect(engine).get_table_names())
        assert CORE_TABLES | VOICEPRINT_TABLES <= tables
        assert TEMPLATE_TABLES.isdisjoint(tables)
        assert OFFICER_LIBRARY_TABLES.isdisjoint(tables)
        assert CALIBRATION_TABLES.isdisjoint(tables)
        assert RECOGNITION_EVIDENCE_TABLES.isdisjoint(tables)
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "0002_voiceprint_speech_pipeline"
    finally:
        engine.dispose()


def test_alembic_upgrade_head_builds_required_schema(tmp_path):
    db_file, _env, result = _run_alembic(tmp_path, "head")
    assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        inspector = inspect(engine)
        assert REQUIRED_TABLES <= set(inspector.get_table_names())
        signature_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("signature_records")
        }
        assert ("snapshot_id", "signer_role") in signature_uniques
        evidence_columns = {item["name"] for item in inspector.get_columns("asr_recognition_evidence")}
        assert {
            "fragment_id", "ai_speaker", "score", "threshold", "margin", "threshold_source",
            "asr_model_version", "speaker_model_version", "speaker_model_fingerprint",
            "microphone_fingerprint", "calibration_id", "calibration_status",
        } <= evidence_columns
        revision_columns = {item["name"] for item in inspector.get_columns("asr_recognition_revisions")}
        assert {
            "fragment_id", "revision_no", "before_speaker", "after_speaker", "before_text",
            "after_text", "actor_id", "reason",
        } <= revision_columns
        compare_columns = {item["name"] for item in inspector.get_columns("speaker_backend_comparison_evidence")}
        assert {
            "fragment_id", "capture_session_id", "case_id", "backend_key", "authoritative",
            "available", "role", "speaker_source", "voiceprint_verified", "score",
            "second_best_score", "threshold", "margin", "calibration_id", "calibration_status",
            "model_id", "model_version", "model_fingerprint", "latency_ms", "error_code",
            "candidate_scores_json",
        } <= compare_columns
        assert {"embedding", "pcm", "audio"}.isdisjoint(compare_columns)
        calibration_columns = {item["name"] for item in inspector.get_columns("speaker_device_calibrations")}
        snapshot_columns = {item["name"] for item in inspector.get_columns("session_speaker_calibration_snapshots")}
        assert "speaker_backend_key" in calibration_columns
        assert "speaker_backend_key" in snapshot_columns
        formal_columns = {item["name"] for item in inspector.get_columns("case_questions")}
        assert {"section_type", "template_key", "template_item_key", "locked", "formal_answer_text", "first_asked_at"} <= formal_columns
        assert RETIRED_MOSS_TABLES.isdisjoint(inspector.get_table_names())
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == ALEMBIC_HEAD

        capture_columns = {item["name"] for item in inspector.get_columns("asr_capture_sessions")}
        assert {
            "audio_sample_count", "asr_cursor_sample", "voiced_ms",
            "recording_status", "asr_status", "speaker_status", "asr_unfinished_start_sample",
            "asr_finalize_checkpoint_sample",
        } <= capture_columns
        unfinished_start = next(
            item for item in inspector.get_columns("asr_capture_sessions")
            if item["name"] == "asr_unfinished_start_sample"
        )
        assert unfinished_start["nullable"] is True
        finalize_checkpoint = next(
            item for item in inspector.get_columns("asr_capture_sessions")
            if item["name"] == "asr_finalize_checkpoint_sample"
        )
        assert finalize_checkpoint["nullable"] is True
        fragment_columns = {item["name"] for item in inspector.get_columns("asr_fragments")}
        assert "asr_idempotency_key" in fragment_columns
        segment_columns = {item["name"] for item in inspector.get_columns("asr_audio_segments")}
        assert {
            "capture_session_id", "sequence", "relative_path", "start_sample",
            "committed_samples", "finalized_samples", "sha256", "status",
        } <= segment_columns
        frame_columns = {item["name"] for item in inspector.get_columns("asr_audio_frames")}
        assert {
            "capture_session_id", "source_sequence", "start_sample", "end_sample",
            "payload_sha256", "durable_sample_end",
        } <= frame_columns
        job_columns = {item["name"] for item in inspector.get_columns("live_speech_jobs")}
        assert {
            "idempotency_key", "kind", "capture_session_id", "fragment_id",
            "start_sample", "end_sample", "state", "attempts", "model_version", "last_error_code",
        } <= job_columns
        lineage_columns = {item["name"] for item in inspector.get_columns("asr_fragment_lineage")}
        assert {
            "analysis_job_id", "parent_fragment_id", "child_fragment_id", "relation",
        } <= lineage_columns
        for table in DURABLE_LIVE_SPEECH_TABLES:
            column_names = {item["name"].lower() for item in inspector.get_columns(table)}
            assert not any("pcm" in name or name == "audio" for name in column_names)

        segment_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("asr_audio_segments")
        }
        frame_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("asr_audio_frames")
        }
        job_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("live_speech_jobs")
        }
        lineage_uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints("asr_fragment_lineage")
        }
        assert ("capture_session_id", "sequence") in segment_uniques
        assert ("capture_session_id", "source_sequence") in frame_uniques
        assert ("idempotency_key",) in job_uniques
        assert ("parent_fragment_id", "child_fragment_id") in lineage_uniques
        fragment_unique_indexes = {
            tuple(item["column_names"])
            for item in inspector.get_indexes("asr_fragments")
            if item["unique"]
        }
        assert ("asr_idempotency_key",) in fragment_unique_indexes

        foreign_keys = {
            table: {
                (tuple(item["constrained_columns"]), item["referred_table"])
                for item in inspector.get_foreign_keys(table)
            }
            for table in DURABLE_LIVE_SPEECH_TABLES
        }
        assert (("capture_session_id",), "asr_capture_sessions") in foreign_keys["asr_audio_segments"]
        assert (("capture_session_id",), "asr_capture_sessions") in foreign_keys["asr_audio_frames"]
        assert (("capture_session_id",), "asr_capture_sessions") in foreign_keys["live_speech_jobs"]
        assert (("fragment_id",), "asr_fragments") in foreign_keys["live_speech_jobs"]
        assert (("analysis_job_id",), "live_speech_jobs") in foreign_keys["asr_fragment_lineage"]
        assert (("parent_fragment_id",), "asr_fragments") in foreign_keys["asr_fragment_lineage"]
        assert (("child_fragment_id",), "asr_fragments") in foreign_keys["asr_fragment_lineage"]
    finally:
        engine.dispose()


def test_0016_preserves_existing_fragments_and_speaker_roles(tmp_path):
    db_file, env, result = _run_alembic(tmp_path, "0015_case_voice_role_draft")
    assert result.returncode == 0, result.stdout + result.stderr
    engine = _sqlite_engine_with_foreign_keys(db_file)
    try:
        now = "2026-09-01 00:00:00"
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO cases (id, operator_id, case_type, suspect_name, gender, age, officer_name, workflow_state, stage, document_status, report_status, created_at, updated_at) "
                "VALUES ('CASE-DURABLE', NULL, 'suspect_interrogation', '嫌疑人', NULL, NULL, '测试警官', 'QUESTIONING', 'QUESTIONS', 'DRAFT', 'PENDING', :now, :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO asr_capture_sessions (id, case_id, interrogation_session_id, status, sample_rate, started_at, ended_at, created_at) "
                "VALUES ('CAPTURE-DURABLE', 'CASE-DURABLE', NULL, 'COMPLETE', 16000, :now, :now, :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO messages (id, case_id, session_id, seq, speaker, text, mark, confirmed, current_version, created_at, updated_at) "
                "VALUES ('MESSAGE-DURABLE', 'CASE-DURABLE', NULL, 1, 'SUSPECT', '已确认文本', '', 1, 1, :now, :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO asr_fragments (id, capture_session_id, case_id, ordinal, started_at_ms, ended_at_ms, raw_text, edited_text, asr_confidence, speaker, speaker_id, speaker_name, speaker_score, second_best_score, speaker_threshold, speaker_margin, speaker_source, voiceprint_verified, low_confidence, state, model_id, model_version, confirmed_message_id, created_at, updated_at) "
                "VALUES ('FRAGMENT-DURABLE', 'CAPTURE-DURABLE', 'CASE-DURABLE', 1, 100, 800, '原始文本', '原始文本', 0.91, 'SUSPECT', 'speaker-1', '嫌疑人', 0.91, 0.08, 0.7, 0.1, 'VOICEPRINT', 1, 0, 'PENDING', 'paraformer', 'v1', NULL, :now, :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO asr_fragments (id, capture_session_id, case_id, ordinal, started_at_ms, ended_at_ms, raw_text, edited_text, asr_confidence, speaker, speaker_id, speaker_name, speaker_score, second_best_score, speaker_threshold, speaker_margin, speaker_source, voiceprint_verified, low_confidence, state, model_id, model_version, confirmed_message_id, created_at, updated_at) "
                "VALUES ('FRAGMENT-CONFIRMED', 'CAPTURE-DURABLE', 'CASE-DURABLE', 2, 800, 1500, '已确认文本', '已确认文本', 0.89, 'SUSPECT', 'speaker-1', '嫌疑人', 0.89, 0.08, 0.7, 0.1, 'VOICEPRINT', 1, 0, 'CONFIRMED', 'paraformer', 'v1', 'MESSAGE-DURABLE', :now, :now)"
            ), {"now": now})
    finally:
        engine.dispose()

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    engine = _sqlite_engine_with_foreign_keys(db_file)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        with pytest.raises(IntegrityError, match="confirmed fragments cannot be superseded"):
            with engine.begin() as connection:
                connection.execute(text(
                    "UPDATE asr_fragments SET state='SUPERSEDED' WHERE id='FRAGMENT-CONFIRMED'"
                ))
        with engine.connect() as connection:
            linked_fragment = connection.execute(text(
                "SELECT state, confirmed_message_id FROM asr_fragments WHERE id='FRAGMENT-CONFIRMED'"
            )).mappings().one()
        assert linked_fragment["state"] == "CONFIRMED"
        assert linked_fragment["confirmed_message_id"] == "MESSAGE-DURABLE"

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM messages WHERE id='MESSAGE-DURABLE'"))
        with engine.connect() as connection:
            fragment = connection.execute(text(
                "SELECT id, speaker, speaker_id, state, raw_text, asr_idempotency_key "
                "FROM asr_fragments WHERE id='FRAGMENT-DURABLE'"
            )).mappings().one()
            capture = connection.execute(text(
                "SELECT audio_sample_count, asr_cursor_sample, asr_unfinished_start_sample, asr_finalize_checkpoint_sample, voiced_ms, recording_status, asr_status, speaker_status "
                "FROM asr_capture_sessions WHERE id='CAPTURE-DURABLE'"
            )).mappings().one()
            confirmed_fragment = connection.execute(text(
                "SELECT state, confirmed_message_id FROM asr_fragments WHERE id='FRAGMENT-CONFIRMED'"
            )).mappings().one()
        assert fragment["speaker"] == "SUSPECT"
        assert fragment["speaker_id"] == "speaker-1"
        assert fragment["state"] == "PENDING"
        assert fragment["raw_text"] == "原始文本"
        assert fragment["asr_idempotency_key"] is None
        assert capture["audio_sample_count"] == 0
        assert capture["asr_cursor_sample"] == 0
        assert capture["asr_unfinished_start_sample"] is None
        assert capture["asr_finalize_checkpoint_sample"] is None
        assert capture["voiced_ms"] == 0
        assert confirmed_fragment["state"] == "CONFIRMED"
        assert confirmed_fragment["confirmed_message_id"] is None

        with pytest.raises(IntegrityError, match="confirmed fragments cannot be superseded"):
            with engine.begin() as connection:
                connection.execute(text(
                    "UPDATE asr_fragments SET state='SUPERSEDED' WHERE id='FRAGMENT-CONFIRMED'"
                ))

        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE asr_fragments SET state='SUPERSEDED' WHERE id='FRAGMENT-DURABLE'"
            ))
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT state FROM asr_fragments WHERE id='FRAGMENT-DURABLE'"
            )).scalar_one() == "SUPERSEDED"
    finally:
        engine.dispose()


def test_0004_migrates_legacy_officer_reference_and_freezes_existing_assignment(tmp_path):
    db_file, env, result = _run_alembic(tmp_path, "0003_template_interrogation_workspace")
    assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        now = "2026-08-31 00:00:00"
        embedding = struct.pack("<3f", 1.0, 0.0, 0.0)
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO cases (id, operator_id, case_type, suspect_name, gender, age, officer_name, workflow_state, stage, document_status, report_status, created_at, updated_at) "
                "VALUES ('CASE-M', NULL, 'suspect_interrogation', '嫌疑人', NULL, NULL, '测试警官', 'IDENTITY_REQUIRED', 'IDENTITY', 'DRAFT', 'PENDING', :now, :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO interrogation_sessions (id, case_id, status, stage, started_at, paused_at, ended_at, created_at, updated_at) "
                "VALUES ('SESSION-M', 'CASE-M', 'READY', 'IDENTITY', NULL, NULL, NULL, :now, :now)"
            ), {"now": now})
            connection.execute(text(
                "INSERT INTO suspect_voiceprints (id, case_id, embedding, embedding_dim, model_id, model_version, enrollment_quality, usable_duration_ms, active, created_at, updated_at) "
                "VALUES ('SUS-M', 'CASE-M', :embedding, 3, 'xvector', 'v1', 'GOOD', 20000, 1, :now, :now)"
            ), {"embedding": embedding, "now": now})
            connection.execute(text(
                "INSERT INTO officer_voiceprints (id, officer_id, officer_name, embedding, embedding_dim, model_id, model_version, enrollment_quality, usable_duration_ms, active, revoked_at, created_at, updated_at) "
                "VALUES ('OFF-M', 'P-001', '张警官', :embedding, 3, 'xvector', 'v1', 'GOOD', 24000, 1, NULL, :now, :now)"
            ), {"embedding": embedding, "now": now})
            connection.execute(text(
                "INSERT INTO session_voice_assignments (id, session_id, suspect_voiceprint_id, interrogator_officer_id, interrogator_voiceprint_id, recorder_officer_id, recorder_voiceprint_id, recognition_mode, created_at, updated_at) "
                "VALUES (:id, 'SESSION-M', 'SUS-M', 'P-001', 'OFF-M', NULL, NULL, 'SUSPECT_PLUS_INTERROGATOR', :now, :now)"
            ), {"id": str(uuid4()), "now": now})
    finally:
        engine.dispose()

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as connection:
            profile = connection.execute(text(
                "SELECT id, officer_id, officer_name, sample_count, aggregate_version FROM officer_voice_profiles WHERE officer_id='P-001'"
            )).mappings().one()
            sample = connection.execute(text(
                "SELECT audio_source, active FROM officer_voice_samples WHERE profile_id=:profile_id"
            ), {"profile_id": profile["id"]}).mappings().one()
            snapshot = connection.execute(text(
                "SELECT officer_id, aggregate_version FROM session_officer_voice_snapshots WHERE session_id='SESSION-M' AND role='INTERROGATOR'"
            )).mappings().one()
        assert profile["officer_name"] == "张警官"
        assert profile["sample_count"] == 1
        assert profile["aggregate_version"] == 1
        assert sample["audio_source"] == "LEGACY_MIGRATED"
        assert bool(sample["active"]) is True
        assert snapshot["officer_id"] == "P-001"
        assert snapshot["aggregate_version"] == 1
    finally:
        engine.dispose()


def test_moss_tables_are_dropped_at_head_and_restored_on_downgrade(tmp_path):
    db_file, env, result = _run_alembic(tmp_path, "0019_deferred_speaker_analysis")
    assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        assert RETIRED_MOSS_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    cwd = os.path.dirname(os.path.dirname(__file__))
    for target, present in (("head", False), ("0019_deferred_speaker_analysis", True)):
        command = "upgrade" if target == "head" else "downgrade"
        step = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", command, target],
            cwd=cwd, env=env, text=True, capture_output=True, check=False,
        )
        assert step.returncode == 0, step.stdout + step.stderr
        engine = create_engine(f"sqlite:///{db_file}")
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
        assert (RETIRED_MOSS_TABLES <= tables) is present
        assert RETIRED_MOSS_TABLES.isdisjoint(tables) is (not present)
