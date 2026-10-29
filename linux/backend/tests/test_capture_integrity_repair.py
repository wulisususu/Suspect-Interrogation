from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.database.models import ASRCaptureSession, AuditLog, Case
from app.database.session import init_database, make_engine, make_session_factory
from app.repositories import audio_archive as archive_repo
from app.services.capture_integrity_repair import REPAIR_ACTION, CaptureIntegrityRepair
from app.services.durable_audio_archive import DurableAudioArchive

CAPTURE = "capture-1"
CASE = "case-1"


@pytest.fixture
def repair_env(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'repair.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        db.add(Case(id=CASE))
        db.commit()
    archive = DurableAudioArchive(tmp_path / "data", factory)
    return CaptureIntegrityRepair(factory, archive), archive, factory


def _record_complete_capture(archive: DurableAudioArchive) -> None:
    archive.open_capture(CAPTURE, case_id=CASE)
    archive.append(CAPTURE, b"\x01\x00" * 800, source_sequence=1, expected_start_sample=0)
    archive.append(CAPTURE, b"\x02\x00" * 800, source_sequence=2, expected_start_sample=800)
    archive.finalize_capture(CAPTURE)


def _mark_incomplete(factory) -> None:
    with factory() as db:
        archive_repo.mark_capture_incomplete(db, CAPTURE)
        db.commit()


def test_dry_run_reports_an_intact_capture_without_writing(repair_env):
    repair, archive, factory = repair_env
    _record_complete_capture(archive)
    _mark_incomplete(factory)

    report = repair.run(dry_run=True)

    assert report["scanned"] == 1
    assert report["repairable"] == 1
    assert report["repaired"] == 0
    assert report["captures"][0]["samples"] == 1600
    assert report["captures"][0]["segments"] == 1
    with factory() as db:
        assert db.get(ASRCaptureSession, CAPTURE).recording_status == "INCOMPLETE"
        assert db.scalar(select(AuditLog).where(AuditLog.action == REPAIR_ACTION)) is None


def test_apply_re_finalizes_the_capture_and_audits_it(repair_env):
    repair, archive, factory = repair_env
    _record_complete_capture(archive)
    _mark_incomplete(factory)

    report = repair.run(dry_run=False, actor_id="001")

    assert report["repaired"] == 1
    with factory() as db:
        capture = db.get(ASRCaptureSession, CAPTURE)
        assert capture.recording_status == "COMPLETE"
        assert capture.status == "STOPPED"
        audit = db.scalar(select(AuditLog).where(AuditLog.action == REPAIR_ACTION))
        assert audit is not None
        assert audit.actor_id == "001"
        assert audit.target_id == CAPTURE
        assert capture.recording_status == "COMPLETE"

    # 修复后不再出现在待修列表里
    assert repair.run(dry_run=True)["scanned"] == 0


def test_a_capture_with_a_sample_count_mismatch_stays_incomplete(repair_env):
    repair, archive, factory = repair_env
    _record_complete_capture(archive)
    with factory() as db:
        archive_repo.mark_capture_incomplete(db, CAPTURE)
        db.get(ASRCaptureSession, CAPTURE).audio_sample_count = 4096
        db.commit()

    report = repair.run(dry_run=False)

    assert report["blocked"] == 1
    assert report["repaired"] == 0
    assert "不一致" in report["captures"][0]["reason"]
    with factory() as db:
        assert db.get(ASRCaptureSession, CAPTURE).recording_status == "INCOMPLETE"
        audit = db.scalar(select(AuditLog).where(AuditLog.action == REPAIR_ACTION))
        assert audit is not None


def test_a_capture_with_an_audio_gap_is_never_repaired(repair_env):
    repair, archive, factory = repair_env
    _record_complete_capture(archive)
    with factory() as db:
        archive_repo.mark_capture_incomplete(db, CAPTURE)
        db.commit()
    with factory() as db:
        segments = archive_repo.list_capture_segments(db, CAPTURE)
        segments[0].status = "GAP"
        db.commit()

    report = repair.run(dry_run=False)

    assert report["blocked"] == 1
    assert "缺口" in report["captures"][0]["reason"]
    with factory() as db:
        assert db.get(ASRCaptureSession, CAPTURE).recording_status == "INCOMPLETE"


def test_repair_can_be_scoped_to_one_case(repair_env):
    repair, archive, factory = repair_env
    _record_complete_capture(archive)
    _mark_incomplete(factory)

    assert repair.run(dry_run=True, case_id="other-case")["scanned"] == 0
    assert repair.run(dry_run=True, case_id=CASE)["scanned"] == 1
