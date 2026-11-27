from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import ASRAudioFrame, ASRAudioSegment, ASRCaptureSession, Case
from app.database.session import begin_sqlite_immediate, sqlite_write_lock


@contextmanager
def archive_transaction(factory: sessionmaker[Session], *, immediate: bool = True) -> Iterator[Session]:
    bind = getattr(factory, "kw", {}).get("bind") or getattr(factory, "bind", None)
    lock = sqlite_write_lock(bind) if immediate else None
    if lock is not None:
        lock.acquire()
    db = factory()
    try:
        if immediate:
            begin_sqlite_immediate(db)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        if lock is not None:
            lock.release()


def get_capture(db: Session, capture_id: str) -> ASRCaptureSession | None:
    return db.get(ASRCaptureSession, capture_id)


def create_capture(db: Session, *, capture_id: str, case_id: str) -> ASRCaptureSession:
    if db.get(Case, case_id) is None:
        raise ValueError(f"case does not exist: {case_id}")
    item = ASRCaptureSession(
        id=capture_id,
        case_id=case_id,
        status="CAPTURING",
        sample_rate=16_000,
        audio_sample_count=0,
        asr_cursor_sample=0,
        voiced_ms=0,
        recording_status="CAPTURING",
        asr_status="PENDING",
        speaker_status="PENDING",
    )
    db.add(item)
    db.flush()
    return item


def list_capture_segments(db: Session, capture_id: str) -> list[ASRAudioSegment]:
    stmt = (
        select(ASRAudioSegment)
        .where(ASRAudioSegment.capture_session_id == capture_id)
        .order_by(ASRAudioSegment.sequence.asc())
    )
    return list(db.scalars(stmt))


def get_frame(db: Session, capture_id: str, source_sequence: int) -> ASRAudioFrame | None:
    stmt = select(ASRAudioFrame).where(
        ASRAudioFrame.capture_session_id == capture_id,
        ASRAudioFrame.source_sequence == source_sequence,
    )
    return db.scalar(stmt)


def record_frame(
    db: Session,
    *,
    capture_id: str,
    source_sequence: int,
    start_sample: int,
    end_sample: int,
    payload_sha256: str,
    durable_sample_end: int,
) -> ASRAudioFrame:
    item = ASRAudioFrame(
        id=str(uuid4()),
        capture_session_id=capture_id,
        source_sequence=source_sequence,
        start_sample=start_sample,
        end_sample=end_sample,
        payload_sha256=payload_sha256,
        durable_sample_end=durable_sample_end,
    )
    db.add(item)
    db.flush()
    return item


def create_segment(
    db: Session,
    *,
    capture_id: str,
    sequence: int,
    relative_path: str,
    start_sample: int,
    sha256: str,
) -> ASRAudioSegment:
    item = ASRAudioSegment(
        id=str(uuid4()),
        capture_session_id=capture_id,
        sequence=sequence,
        relative_path=relative_path,
        start_sample=start_sample,
        committed_samples=0,
        finalized_samples=0,
        sha256=sha256,
        status="ACTIVE",
    )
    db.add(item)
    db.flush()
    return item


def update_segment(
    segment: ASRAudioSegment,
    *,
    committed_samples: int | None = None,
    finalized_samples: int | None = None,
    sha256: str | None = None,
    status: str | None = None,
) -> None:
    if committed_samples is not None:
        segment.committed_samples = committed_samples
    if finalized_samples is not None:
        segment.finalized_samples = finalized_samples
    if sha256 is not None:
        segment.sha256 = sha256
    if status is not None:
        segment.status = status


def update_capture_count(capture: ASRCaptureSession, sample_count: int) -> None:
    capture.audio_sample_count = sample_count


def mark_capture_incomplete(db: Session, capture_id: str) -> None:
    capture = db.get(ASRCaptureSession, capture_id)
    if capture is not None:
        capture.recording_status = "INCOMPLETE"
        capture.status = "FAILED"
        capture.ended_at = datetime.now(timezone.utc)


def complete_capture(capture: ASRCaptureSession) -> None:
    capture.recording_status = "COMPLETE"
    capture.status = "STOPPED"
    capture.ended_at = datetime.now(timezone.utc)


def active_captures(db: Session) -> list[ASRCaptureSession]:
    stmt = select(ASRCaptureSession).where(ASRCaptureSession.recording_status.in_(("CAPTURING", "INCOMPLETE")))
    return list(db.scalars(stmt))
