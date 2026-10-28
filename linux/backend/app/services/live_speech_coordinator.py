from __future__ import annotations

import logging
import hashlib
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.legacy_voiceprint import legacy_voiceprint_enabled
from app.ai.speech.types import SpeechEvent, SpeechEventType
from app.database.models import ASRAudioFrame, ASRCaptureSession, ASRFragment, Case, LiveSpeechJob
from app.repositories import audio_archive as archive_repo
from app.repositories import asr_fragments as asr_repo
from app.domain.errors import DomainError
from app.services.durable_audio_archive import (
    AudioStorageReserveError,
    BrowserAudioDiscontinuityError,
    DurableAudioArchive,
)
from speech_worker.session import SpeechSession
from speech_worker.speaker_turn_splitter import SpeakerTurnSplitter


logger = logging.getLogger(__name__)
_MAX_INFERENCE_SAMPLES = 16_000
_SPEAKER_MIN_VOICED_MS = 10_000
_SPEAKER_MIN_FINAL_FRAGMENTS = 3
# The worker caps a VAD segment at 5 seconds and SpeechSession retains
# 1.2 seconds of pre-roll, so a 6.2-second tail covers finalization output.
_FINALIZE_REPLAY_WINDOW_MS = 6_200


@dataclass(frozen=True)
class _AudioRange:
    runtime: Any
    start_sample: int
    end_sample: int


@dataclass(frozen=True)
class _FinishCapture:
    runtime: Any


@dataclass(frozen=True)
class _ProcessedAudioRange:
    fragment_ids: list[str]


@dataclass(frozen=True)
class _SpeakerJob:
    job_id: str
    capture_session_id: str


class LiveSpeechCoordinator:
    """Keep microphone reads independent from the slower speech worker."""

    def __init__(
        self,
        *,
        data_dir: str | Path,
        session_factory: sessionmaker[Session],
        capture_service: Any,
        ai_supervisor: Any,
        min_free_bytes: int = 0,
    ) -> None:
        self.legacy_voiceprint_enabled = legacy_voiceprint_enabled()
        self.session_factory = session_factory
        self.capture_service = capture_service
        self.ai_supervisor = ai_supervisor
        self.archive = DurableAudioArchive(
            data_dir,
            session_factory,
            min_free_bytes=min_free_bytes,
        )
        self.asr_queue: queue.Queue[_AudioRange | _FinishCapture | None] = queue.Queue()
        self.speaker_queue: queue.Queue[_SpeakerJob | Callable[[], None] | None] = queue.Queue()
        self._lock = threading.RLock()
        self._speaker_work_condition = threading.Condition(self._lock)
        self._started = False
        self._stopping = threading.Event()
        self._asr_thread: threading.Thread | None = None
        self._speaker_thread: threading.Thread | None = None
        self._durable_cursors: dict[str, int] = {}
        self._append_locks: dict[str, threading.Lock] = {}
        self._asr_cursors: dict[str, int] = {}
        self._asr_blocked: set[str] = set()
        self._runtimes: dict[str, Any] = {}
        self._open_asr_sessions: set[str] = set()
        self._process_lock = threading.RLock()
        self._asr_busy = threading.Event()
        self._speaker_queued_ids: set[str] = set()
        self._speaker_pending_counts: dict[str, int] = {}
        self._capture_finish_events: dict[str, threading.Event] = {}
        self._browser_recoveries_started: set[str] = set()
        self.capture_service.set_live_speech_coordinator(self)

    def assert_storage_available_for_capture(self) -> None:
        try:
            self.archive.check_storage_reserve()
        except AudioStorageReserveError as exc:
            reserve_mb = self.archive.min_free_bytes // (1024 * 1024)
            raise DomainError(
                "ASR_AUDIO_STORAGE_RESERVE",
                f"可用存储空间已达到 {reserve_mb} MB 预留线，无法开始正式录音",
                507,
                {"reason": str(exc)},
            ) from exc

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            with self.session_factory() as db:
                interrupted_ids = list(db.scalars(select(ASRCaptureSession.id).where(
                    ASRCaptureSession.recording_status == "CAPTURING")))
            recovered = self.archive.recover_incomplete()
            for capture_id in interrupted_ids:
                self._record_capture_interruption(capture_id, "POWER_RECOVERY", "capture recovered after service restart")
            with self.session_factory() as db:
                browser_capture_ids = set(
                    db.scalars(select(ASRAudioFrame.capture_session_id).distinct())
                )
            with self.session_factory() as db:
                completed_with_backlog = list(
                    db.scalars(
                        select(ASRCaptureSession.id)
                        .where(
                            ASRCaptureSession.recording_status.in_(("COMPLETE", "INCOMPLETE")),
                            ASRCaptureSession.interrogation_session_id.is_not(None),
                            or_(
                                ASRCaptureSession.asr_status.in_(("PENDING", "FINALIZING")),
                                ASRCaptureSession.asr_cursor_sample < ASRCaptureSession.audio_sample_count,
                                ASRCaptureSession.asr_unfinished_start_sample.is_not(None),
                                ASRCaptureSession.asr_finalize_checkpoint_sample.is_not(None),
                            ),
                        )
                        .order_by(ASRCaptureSession.started_at, ASRCaptureSession.id)
                    )
                )
            recovered = list(dict.fromkeys([*recovered, *completed_with_backlog]))
            recovery_jobs: list[_AudioRange | _FinishCapture] = []
            resumable_browser_runtimes: list[Any] = []
            for capture_id in recovered:
                finalization_error: Exception | None = None
                with self.session_factory() as db:
                    capture = db.get(ASRCaptureSession, capture_id)
                    if capture is None:
                        continue
                    resumable_browser = (
                        capture.recording_status == "CAPTURING"
                        and capture_id in browser_capture_ids
                        and capture.interrogation_session_id is not None
                    )
                    should_finalize = capture.recording_status == "CAPTURING" and not resumable_browser
                    has_interrogation_session = capture.interrogation_session_id is not None
                    sample_rate = int(capture.sample_rate)
                    needs_asr = (
                        has_interrogation_session
                        and (
                            resumable_browser
                            or should_finalize
                            or capture.asr_status in ("PENDING", "FINALIZING")
                            or int(capture.asr_cursor_sample or 0)
                            < int(capture.audio_sample_count or 0)
                            or capture.asr_unfinished_start_sample is not None
                            or capture.asr_finalize_checkpoint_sample is not None
                        )
                    )
                if not has_interrogation_session:
                    if should_finalize:
                        try:
                            self._finalize_archive(capture_id)
                        except Exception:
                            logger.exception(
                                "failed to finalize orphan audio capture %s",
                                capture_id,
                            )
                    continue
                if not needs_asr:
                    continue
                try:
                    if not resumable_browser:
                        self._begin_asr_finalization(capture_id, sample_rate)
                except Exception as exc:
                    finalization_error = exc
                if should_finalize:
                    if finalization_error is None:
                        try:
                            self._finalize_archive(capture_id)
                        except Exception as exc:
                            finalization_error = exc

                browser_runtime = None
                if resumable_browser:
                    with self.session_factory() as db:
                        capture = db.get(ASRCaptureSession, capture_id)
                        runtime_builder = getattr(
                            self.capture_service,
                            "build_browser_recovery_runtime",
                            None,
                        )
                        if capture is not None and callable(runtime_builder):
                            try:
                                browser_runtime = runtime_builder(capture)
                            except Exception:
                                logger.exception(
                                    "failed to rebuild browser capture runtime %s",
                                    capture_id,
                                )
                    if browser_runtime is None:
                        with archive_repo.archive_transaction(self.session_factory) as db:
                            capture = db.get(ASRCaptureSession, capture_id)
                            if capture is not None and capture.recording_status == "CAPTURING":
                                archive_repo.mark_capture_incomplete(db, capture_id)
                        resumable_browser = False
                        try:
                            self._begin_asr_finalization(capture_id, sample_rate)
                        except Exception as exc:
                            finalization_error = exc

                with self.session_factory() as db:
                    capture = db.get(ASRCaptureSession, capture_id)
                    if capture is None or capture.interrogation_session_id is None:
                        continue
                    runtime = browser_runtime if resumable_browser else self.capture_service.build_recovery_runtime(capture)
                    unfinished_start = capture.asr_unfinished_start_sample
                    cursor = max(0, int(capture.asr_cursor_sample or 0))
                    checkpoint = capture.asr_finalize_checkpoint_sample
                    if checkpoint is not None:
                        cursor = min(cursor, max(0, int(checkpoint)))
                    if unfinished_start is not None:
                        cursor = min(cursor, max(0, int(unfinished_start)))
                    end = max(cursor, int(capture.audio_sample_count or 0))
                if runtime is None:
                    continue
                self._runtimes[capture_id] = runtime
                self._asr_cursors[capture_id] = cursor
                self._durable_cursors[capture_id] = int(capture.audio_sample_count or 0)
                if finalization_error is not None:
                    self._mark_storage_error(runtime, finalization_error)
                    self._asr_blocked.add(capture_id)
                while cursor < end:
                    next_cursor = min(end, cursor + _MAX_INFERENCE_SAMPLES)
                    recovery_jobs.append(_AudioRange(runtime, cursor, next_cursor))
                    cursor = next_cursor
                if resumable_browser:
                    resumable_browser_runtimes.append(runtime)
                else:
                    recovery_jobs.append(_FinishCapture(runtime))

            for job in recovery_jobs:
                if isinstance(job, _FinishCapture):
                    self._capture_finish_event(job.runtime.capture_session_id)
                self.asr_queue.put(job)
            resume_browser_capture = getattr(self.capture_service, "resume_browser_capture", None)
            for runtime in resumable_browser_runtimes:
                try:
                    if not callable(resume_browser_capture):
                        raise RuntimeError("capture service cannot resume browser audio")
                    resume_browser_capture(runtime)
                except Exception as exc:
                    logger.exception(
                        "failed to resume browser capture %s; preserving archived audio for ASR",
                        runtime.capture_session_id,
                    )
                    try:
                        self.mark_browser_capture_incomplete(
                            runtime.case_id,
                            runtime.capture_session_id,
                            str(exc),
                        )
                    except Exception:
                        logger.exception(
                            "failed to mark browser capture %s incomplete after resume failure",
                            runtime.capture_session_id,
                        )
                    try:
                        self._begin_asr_finalization(
                            runtime.capture_session_id,
                            runtime.sample_rate,
                        )
                    except Exception:
                        logger.exception(
                            "failed to begin ASR finalization for browser capture %s",
                            runtime.capture_session_id,
                        )
                    self._enqueue_finish_capture(runtime)

            from app.database.recording_models import CaptureRecording
            with self.session_factory() as db:
                unfinished_originals = list(db.scalars(
                    select(ASRCaptureSession.id).join(CaptureRecording,
                        CaptureRecording.capture_id == ASRCaptureSession.id).where(
                        ASRCaptureSession.recording_status == "COMPLETE",
                        ASRCaptureSession.audio_sample_count > 0,
                        CaptureRecording.full_recording_enabled.is_(True),
                        CaptureRecording.original_sha256.is_(None),
                    )))
            for capture_id in unfinished_originals:
                self._finalize_original(capture_id)

            self._asr_thread = threading.Thread(
                target=self._asr_loop,
                daemon=True,
                name="live-speech-asr",
            )
            self._asr_thread.start()

            if self.legacy_voiceprint_enabled:
                with self.session_factory() as db:
                    speaker_candidates = list(
                        db.scalars(
                            select(ASRCaptureSession.id).where(
                                ASRCaptureSession.recording_status.in_(("COMPLETE", "INCOMPLETE")),
                                ASRCaptureSession.id.in_(
                                    select(ASRFragment.capture_session_id).where(
                                        ASRFragment.state == "PENDING",
                                        ASRFragment.speaker_source == "PENDING_ANALYSIS",
                                    )
                                ),
                            )
                        )
                    )
                for capture_id in speaker_candidates:
                    self.schedule_speaker_jobs(capture_id, force=True)
                self._recover_speaker_jobs()

                self._speaker_thread = threading.Thread(
                    target=self._speaker_loop,
                    daemon=True,
                    name="live-speech-speaker",
                )
                self._speaker_thread.start()
            self._started = True

    def _finalize_archive(self, capture_id: str, **options) -> None:
        self.archive.finalize_capture(capture_id, **options)
        self._finalize_original(capture_id)

    def _finalize_original(self, capture_id: str) -> None:
        from app.services.recording_service import RecordingService
        try:
            with self.session_factory() as db:
                RecordingService(db, self.archive).finalize_original(capture_id)
                db.commit()
        except Exception:
            # Durable archive and ASR can finish; a missing hash is retried on restart.
            logger.exception("full recording could not be assembled for capture %s", capture_id)

    def open_capture(self, runtime: Any) -> None:
        try:
            self.archive.open_capture(runtime.capture_session_id, case_id=runtime.case_id)
        except Exception as exc:
            self._mark_storage_error(runtime, exc)
            raise
        runtime.durable_sample_cursor = 0
        with self._lock:
            self._durable_cursors[runtime.capture_session_id] = 0
            self._asr_cursors[runtime.capture_session_id] = 0
            self._runtimes[runtime.capture_session_id] = runtime

    def register_browser_capture(self, capture_id: str) -> None:
        """Persist a source marker so a just-started browser capture can resume."""
        with archive_repo.archive_transaction(self.session_factory) as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if capture is None or capture.recording_status != "CAPTURING":
                raise RuntimeError("browser capture is not accepting audio")
            marker = archive_repo.get_frame(db, capture_id, 0)
            if marker is None:
                digest = hashlib.sha256(b"").hexdigest()
                archive_repo.record_frame(
                    db,
                    capture_id=capture_id,
                    source_sequence=0,
                    start_sample=0,
                    end_sample=0,
                    payload_sha256=digest,
                    durable_sample_end=0,
                )

    def append_audio(
        self,
        runtime: Any,
        pcm: bytes,
        *,
        source_sequence: int | None = None,
        expected_start_sample: int | None = None,
    ) -> int:
        """Commit audio first, then queue only its durable sample range."""
        capture_id = str(runtime.capture_session_id)
        with self._lock:
            append_lock = self._append_locks.setdefault(capture_id, threading.Lock())
        with append_lock:
            with self._lock:
                durable_cursor = self._durable_cursors.get(capture_id, 0)
            start_sample = durable_cursor if expected_start_sample is None else expected_start_sample
            try:
                end_sample = self.archive.append(
                    capture_id,
                    pcm,
                    source_sequence=source_sequence,
                    expected_start_sample=expected_start_sample,
                )
            except BrowserAudioDiscontinuityError:
                raise
            except Exception as exc:
                self._mark_storage_error(runtime, exc)
                raise
            if source_sequence is not None and end_sample <= durable_cursor:
                return end_sample
            if end_sample != start_sample + len(pcm) // 2:
                exc = RuntimeError("audio archive returned a non-contiguous durable cursor")
                self._mark_storage_error(runtime, exc)
                raise exc
            with self._lock:
                self._durable_cursors[capture_id] = max(durable_cursor, end_sample)
                runtime.durable_sample_cursor = max(
                    int(getattr(runtime, "durable_sample_cursor", 0) or 0),
                    end_sample,
                )
            self.asr_queue.put(_AudioRange(runtime, start_sample, end_sample))
            return end_sample

    def replay_browser_frame(
        self,
        *,
        case_id: str,
        capture_id: str,
        source_sequence: int,
        start_sample: int,
        pcm: bytes,
    ) -> dict[str, int]:
        """Replay an exact frame or append a missing frame to an incomplete capture."""
        with archive_repo.archive_transaction(self.session_factory, immediate=False) as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if capture is None or capture.case_id != str(case_id):
                raise ValueError("browser frame does not match a stored capture")
            recovering = capture.recording_status == "INCOMPLETE"
            prior = archive_repo.get_frame(db, capture_id, source_sequence)
        first_recovery_frame = False
        if recovering and prior is None:
            with self._lock:
                first_recovery_frame = capture_id not in self._browser_recoveries_started
                self._browser_recoveries_started.add(capture_id)
            if first_recovery_frame:
                if self._started:
                    self.asr_queue.join()
                with self.session_factory() as db:
                    capture = db.get(ASRCaptureSession, capture_id)
                    if capture is None:
                        raise ValueError(f"unknown capture session: {capture_id}")
                    runtime = self.capture_service.build_recovery_runtime(capture)
                    cursor = max(0, int(capture.asr_cursor_sample or 0))
                if runtime is None:
                    raise RuntimeError("capture session cannot be recovered for ASR")
                runtime.durable_sample_cursor = int(start_sample)
                self._runtimes[capture_id] = runtime
                self._durable_cursors[capture_id] = int(start_sample)
                self._asr_cursors[capture_id] = cursor
                self._asr_blocked.discard(capture_id)
                while cursor < int(start_sample):
                    next_cursor = min(int(start_sample), cursor + _MAX_INFERENCE_SAMPLES)
                    self.asr_queue.put(_AudioRange(runtime, cursor, next_cursor))
                    cursor = next_cursor
        durable_end = self.archive.append(
            capture_id,
            bytes(pcm),
            source_sequence=source_sequence,
            expected_start_sample=start_sample,
            allow_incomplete_recovery=recovering,
        )
        if recovering and prior is None:
            runtime = self._runtimes.get(capture_id)
            if runtime is None:
                with self.session_factory() as db:
                    capture = db.get(ASRCaptureSession, capture_id)
                    if capture is None:
                        raise ValueError(f"unknown capture session: {capture_id}")
                    runtime = self.capture_service.build_recovery_runtime(capture)
                    asr_cursor = max(0, int(capture.asr_cursor_sample or 0))
                if runtime is None:
                    raise RuntimeError("capture session cannot be recovered for ASR")
                self._runtimes[capture_id] = runtime
                self._asr_cursors.setdefault(capture_id, asr_cursor)
                self._asr_blocked.discard(capture_id)
            runtime.durable_sample_cursor = durable_end
            self._durable_cursors[capture_id] = durable_end
            self.asr_queue.put(_AudioRange(runtime, int(start_sample), durable_end))
        return {"ackSequence": source_sequence, "durableSampleEnd": durable_end}

    def complete_browser_capture_recovery(
        self,
        *,
        case_id: str,
        capture_id: str,
        next_sequence: int,
        next_sample: int,
    ) -> dict[str, int | str]:
        if not isinstance(next_sequence, int) or isinstance(next_sequence, bool) or next_sequence < 1:
            raise ValueError("browser recovery sequence cursor is invalid")
        if not isinstance(next_sample, int) or isinstance(next_sample, bool) or next_sample < 0:
            raise ValueError("browser recovery sample cursor is invalid")
        with archive_repo.archive_transaction(self.session_factory, immediate=False) as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if capture is None or capture.case_id != str(case_id):
                raise ValueError("browser recovery does not match a stored capture")
            already_complete = capture.recording_status == "COMPLETE"
            if capture.recording_status not in {"INCOMPLETE", "COMPLETE"}:
                raise ValueError("browser capture is not awaiting recovery")
            last_sequence = db.scalar(
                select(func.max(ASRAudioFrame.source_sequence)).where(
                    ASRAudioFrame.capture_session_id == capture_id
                )
            )
            if int(last_sequence or 0) + 1 != next_sequence or int(capture.audio_sample_count or 0) != next_sample:
                raise ValueError("browser recovery cursors do not match the durable archive")
            if already_complete:
                return {
                    "captureId": capture_id,
                    "recordingStatus": "COMPLETE",
                    "nextSequence": next_sequence,
                    "nextSample": next_sample,
                }
            sample_rate = int(capture.sample_rate)
            asr_cursor = max(0, int(capture.asr_cursor_sample or 0))
            runtime = self.capture_service.build_recovery_runtime(capture)
        if runtime is None:
            raise RuntimeError("capture session cannot be recovered for ASR")
        if self._started:
            self.asr_queue.join()
        runtime.durable_sample_cursor = next_sample
        self._runtimes[capture_id] = runtime
        self._durable_cursors[capture_id] = next_sample
        self._asr_cursors.setdefault(capture_id, asr_cursor)
        self._asr_blocked.discard(capture_id)
        self._begin_asr_finalization(capture_id, sample_rate)
        self._finalize_archive(capture_id, allow_incomplete_recovery=True)
        self._enqueue_finish_capture(runtime)
        self._browser_recoveries_started.discard(capture_id)
        return {
            "captureId": capture_id,
            "recordingStatus": "COMPLETE",
            "nextSequence": next_sequence,
            "nextSample": next_sample,
        }

    def has_browser_frame_receipt(self, case_id: str, capture_id: str) -> bool:
        with self.session_factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if (
                capture is None
                or capture.case_id != str(case_id)
                or capture.recording_status not in {"CAPTURING", "INCOMPLETE", "COMPLETE"}
            ):
                return False
            return db.scalar(
                select(ASRAudioFrame.id)
                .where(ASRAudioFrame.capture_session_id == capture_id)
                .where(ASRAudioFrame.source_sequence == 0)
                .limit(1)
            ) is not None

    def mark_browser_capture_incomplete(self, case_id: str, capture_id: str, reason: str) -> bool:
        changed = False
        with archive_repo.archive_transaction(self.session_factory) as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if capture is None or capture.case_id != str(case_id):
                raise ValueError("browser audio capture does not match the requested case")
            if capture.recording_status == "COMPLETE":
                return False
            if capture.recording_status != "INCOMPLETE":
                archive_repo.mark_capture_incomplete(db, capture_id)
                changed = True
        if changed:
            self._record_capture_interruption(capture_id, "NETWORK_INTERRUPTED", reason)
        return True

    def _record_capture_interruption(self, capture_id: str, reason: str, detail: str) -> None:
        from app.services.case_management_service import CaseManagementService
        with self.session_factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if capture is None:
                return
            try:
                CaseManagementService(db).interrupt(
                    capture.case_id, reason=reason,
                    question_id=getattr(capture, "target_question_id", None),
                    detail=str(detail)[:1000],
                )
                db.commit()
            except DomainError as exc:
                db.rollback()
                # Recovery must preserve audio even when the record was sealed or voided.
                if exc.code not in {"FORMAL_RECORD_FROZEN", "CASE_VOIDED", "CASE_QUESTION_NOT_FOUND"}:
                    raise

    def speaker_jobs_ready(
        self,
        capture_id: str,
        *,
        voiced_ms: int | None = None,
        final_count: int | None = None,
    ) -> bool:
        if voiced_ms is None or final_count is None:
            with self.session_factory() as db:
                capture = db.get(ASRCaptureSession, capture_id)
                if capture is None:
                    return False
                if voiced_ms is None:
                    voiced_ms = int(capture.voiced_ms or 0)
                if final_count is None:
                    final_count = int(
                        db.scalar(
                            select(func.count(ASRFragment.id)).where(
                                ASRFragment.capture_session_id == capture_id,
                                ASRFragment.asr_idempotency_key.is_not(None),
                            )
                        )
                        or 0
                    )
        return (
            int(voiced_ms) >= _SPEAKER_MIN_VOICED_MS
            and int(final_count) >= _SPEAKER_MIN_FINAL_FRAGMENTS
        )

    def schedule_speaker_jobs(self, capture_id: str, *, force: bool = False) -> list[str]:
        """Persist one deferred analysis job for each unresolved Stage 1 fragment."""
        if not self.legacy_voiceprint_enabled:
            return []
        queued: list[str] = []
        with archive_repo.archive_transaction(self.session_factory) as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if capture is None:
                return []
            final_count = int(
                db.scalar(
                    select(func.count(ASRFragment.id)).where(
                        ASRFragment.capture_session_id == capture_id,
                        ASRFragment.asr_idempotency_key.is_not(None),
                    )
                )
                or 0
            )
            if not force and not self.speaker_jobs_ready(
                capture_id,
                voiced_ms=int(capture.voiced_ms or 0),
                final_count=final_count,
            ):
                return []

            fragments = list(
                db.scalars(
                    select(ASRFragment)
                    .where(
                        ASRFragment.capture_session_id == capture_id,
                        ASRFragment.state == "PENDING",
                        ASRFragment.speaker_source == "PENDING_ANALYSIS",
                        ASRFragment.confirmed_message_id.is_(None),
                        ASRFragment.edited_text == ASRFragment.raw_text,
                    )
                    .order_by(ASRFragment.ordinal, ASRFragment.id)
                )
            )
            for fragment in fragments:
                start_sample = int(round(fragment.started_at_ms * capture.sample_rate / 1000))
                end_sample = int(round(fragment.ended_at_ms * capture.sample_rate / 1000))
                if end_sample <= start_sample:
                    continue
                key = f"speaker:{fragment.id}"
                job = db.scalar(
                    select(LiveSpeechJob).where(LiveSpeechJob.idempotency_key == key)
                )
                if job is None:
                    job = LiveSpeechJob(
                        id=str(uuid4()),
                        idempotency_key=key,
                        kind="SPEAKER",
                        capture_session_id=capture_id,
                        fragment_id=fragment.id,
                        start_sample=start_sample,
                        end_sample=end_sample,
                        state="PENDING",
                    )
                    db.add(job)
                    db.flush()
                if job.state == "PENDING":
                    queued.append(job.id)
            if queued:
                capture.speaker_status = "QUEUED"
        for job_id in queued:
            self._queue_speaker_job(job_id)
        return queued

    def _queue_speaker_job(self, job_id: str) -> None:
        with self.session_factory() as db:
            job = db.get(LiveSpeechJob, job_id)
            if job is None:
                return
            capture_id = job.capture_session_id
        with self._lock:
            if job_id in self._speaker_queued_ids:
                return
            self._speaker_queued_ids.add(job_id)
            self._speaker_pending_counts[capture_id] = self._speaker_pending_counts.get(capture_id, 0) + 1
        self.speaker_queue.put(_SpeakerJob(job_id, capture_id))

    def _recover_speaker_jobs(self) -> list[str]:
        """Requeue durable work after start has queued all ASR recovery ranges."""
        if not self.legacy_voiceprint_enabled:
            return []
        with archive_repo.archive_transaction(self.session_factory) as db:
            interrupted = list(
                db.scalars(
                    select(LiveSpeechJob).where(
                        LiveSpeechJob.kind == "SPEAKER",
                        LiveSpeechJob.state == "RUNNING",
                    )
                )
            )
            for job in interrupted:
                job.state = "PENDING"
            db.flush()
            pending_ids = list(
                db.scalars(
                    select(LiveSpeechJob.id)
                    .where(
                        LiveSpeechJob.kind == "SPEAKER",
                        LiveSpeechJob.state == "PENDING",
                    )
                    .order_by(LiveSpeechJob.created_at, LiveSpeechJob.id)
                )
            )
        for job_id in pending_ids:
            self._queue_speaker_job(job_id)
        return pending_ids

    def finish_capture(self, runtime: Any) -> None:
        if runtime.storage_error is None:
            try:
                self._begin_asr_finalization(
                    runtime.capture_session_id,
                    runtime.sample_rate,
                )
                with self.session_factory() as db:
                    capture = db.get(ASRCaptureSession, runtime.capture_session_id)
                    recording_status = None if capture is None else capture.recording_status
                if recording_status == "CAPTURING":
                    self._finalize_archive(runtime.capture_session_id)
                elif recording_status not in {"INCOMPLETE", "COMPLETE"}:
                    raise RuntimeError("capture cannot be finalized from its current state")
            except Exception as exc:
                self._mark_storage_error(runtime, exc)
                self._asr_blocked.add(runtime.capture_session_id)
        else:
            self._asr_blocked.add(runtime.capture_session_id)
        self._enqueue_finish_capture(runtime)

    def wait_for_session_processing(self, session_id: str, *, timeout: float) -> None:
        """Wait until final ASR and queued speaker analysis for a session have settled."""
        wait_seconds = max(0.01, float(timeout))
        deadline = time.monotonic() + wait_seconds
        target_session_id = str(session_id)

        while True:
            with self.session_factory() as db:
                captures = list(
                    db.scalars(
                        select(ASRCaptureSession)
                        .where(ASRCaptureSession.interrogation_session_id == target_session_id)
                        .order_by(ASRCaptureSession.started_at, ASRCaptureSession.id)
                    )
                )
                capture_ids = [capture.id for capture in captures]
                failed = [
                    capture.id
                    for capture in captures
                    if str(capture.asr_status or "").upper() in {"ERROR", "FAILED"}
                ]
                pending_asr = [
                    capture.id
                    for capture in captures
                    if str(capture.asr_status or "").upper() != "COMPLETE"
                ]
                pending_speaker_jobs = (
                    int(
                        db.scalar(
                            select(func.count(LiveSpeechJob.id)).where(
                                LiveSpeechJob.kind == "SPEAKER",
                                LiveSpeechJob.capture_session_id.in_(capture_ids),
                                LiveSpeechJob.state.in_(("PENDING", "RUNNING")),
                            )
                        )
                        or 0
                    )
                    if capture_ids and self.legacy_voiceprint_enabled
                    else 0
                )

            if failed:
                raise RuntimeError(f"ASR finalization failed for capture {failed[0]}")

            if pending_asr:
                capture_id = pending_asr[0]
                event = self._capture_finish_event(capture_id)
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not event.wait(remaining):
                    raise TimeoutError("ASR finalization did not finish before the deadline")
                with self.session_factory() as db:
                    capture = db.get(ASRCaptureSession, capture_id)
                    status = "MISSING" if capture is None else str(capture.asr_status or "").upper()
                if status != "COMPLETE":
                    raise RuntimeError(f"ASR finalization ended in {status} for capture {capture_id}")
                continue

            with self._lock:
                pending_finish_events = [
                    self._capture_finish_events[capture_id]
                    for capture_id in capture_ids
                    if capture_id in self._capture_finish_events
                    and not self._capture_finish_events[capture_id].is_set()
                ]
                pending_speaker_count = sum(
                    self._speaker_pending_counts.get(capture_id, 0)
                    for capture_id in capture_ids
                )

            if pending_finish_events:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("ASR finalization callbacks did not finish before the deadline")
                pending_finish_events[0].wait(min(0.05, remaining))
                continue

            if self.legacy_voiceprint_enabled and (pending_speaker_jobs or pending_speaker_count):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("speaker analysis did not finish before the deadline")
                with self._speaker_work_condition:
                    self._speaker_work_condition.wait(min(0.05, remaining))
                continue

            return

    def _capture_finish_event(self, capture_id: str) -> threading.Event:
        normalized_id = str(capture_id)
        with self._lock:
            return self._capture_finish_events.setdefault(normalized_id, threading.Event())

    def _signal_capture_finished(self, capture_id: str) -> None:
        with self._lock:
            event = self._capture_finish_events.pop(str(capture_id), None)
        if event is not None:
            event.set()

    def _enqueue_finish_capture(self, runtime: Any) -> None:
        self._capture_finish_event(runtime.capture_session_id)
        self.asr_queue.put(_FinishCapture(runtime))

    def _mark_storage_error(self, runtime: Any, exc: Exception) -> None:
        runtime.storage_error = str(exc)
        try:
            with archive_repo.archive_transaction(self.session_factory) as db:
                archive_repo.mark_capture_incomplete(db, runtime.capture_session_id)
        except Exception:
            logger.exception("failed to mark audio capture %s incomplete", runtime.capture_session_id)
        try:
            runtime.capture_error_sink(exc)
        except Exception:
            logger.exception("failed to publish storage failure for capture %s", runtime.capture_session_id)
        try:
            self.capture_service.publish_event(
                runtime.interrogation_session_id,
                "ASR_STORAGE_ERROR",
                {
                    "caseId": runtime.case_id,
                    "captureSessionId": runtime.capture_session_id,
                    "code": "AUDIO_STORAGE_ERROR",
                    "message": str(exc),
                },
            )
        except Exception:
            logger.exception("failed to publish audio storage error for capture %s", runtime.capture_session_id)

    def _asr_loop(self) -> None:
        while True:
            task = self.asr_queue.get()
            if task is None:
                self.asr_queue.task_done()
                return
            runtime = task.runtime
            session_id = runtime.speech_session_id
            if isinstance(task, _AudioRange):
                self._asr_busy.set()
            else:
                try:
                    if runtime.storage_error is None and runtime.capture_session_id not in self._asr_blocked:
                        with self.session_factory() as db:
                            capture = db.get(ASRCaptureSession, runtime.capture_session_id)
                            should_finalize = (
                                capture is not None
                                and capture.interrogation_session_id is not None
                                and capture.asr_status != "FINALIZING"
                            )
                        if should_finalize:
                            try:
                                self._begin_asr_finalization(
                                    runtime.capture_session_id,
                                    runtime.sample_rate,
                                )
                            except Exception:
                                self._asr_blocked.add(runtime.capture_session_id)
                                raise
                        if session_id not in self._open_asr_sessions:
                            with self.session_factory() as db:
                                capture = db.get(ASRCaptureSession, runtime.capture_session_id)
                                base_sample = 0 if capture is None else max(
                                    0,
                                    int(capture.asr_cursor_sample or 0),
                                )
                                if capture is not None and capture.asr_unfinished_start_sample is not None:
                                    base_sample = min(
                                        base_sample,
                                        max(0, int(capture.asr_unfinished_start_sample)),
                                    )
                            open_options = {
                                "sample_rate": runtime.sample_rate,
                                "speaker_backend": runtime.speaker_backend,
                            }
                            if base_sample:
                                open_options["base_sample"] = base_sample
                            self.ai_supervisor.open_speech_session(session_id, **open_options)
                            self._open_asr_sessions.add(session_id)
                        end_sample = self._capture_audio_sample_count(runtime.capture_session_id)
                        events = self.ai_supervisor.finalize_speech_session(session_id)
                        self._consume_event_batch(
                            runtime,
                            events,
                            end_sample=end_sample,
                            complete_asr=True,
                        )
                except Exception as exc:
                    try:
                        runtime.inference_error_sink(exc)
                    except Exception:
                        logger.exception(
                            "failed to report ASR finalization failure for capture %s",
                            runtime.capture_session_id,
                        )
                finally:
                    try:
                        if session_id in self._open_asr_sessions:
                            try:
                                self.ai_supervisor.close_speech_session(session_id)
                            except Exception as exc:
                                logger.exception(
                                    "failed to close speech session %s",
                                    session_id,
                                )
                                try:
                                    runtime.inference_error_sink(exc)
                                except Exception:
                                    logger.exception(
                                        "failed to report speech-session close failure for capture %s",
                                        runtime.capture_session_id,
                                    )
                    finally:
                        self._open_asr_sessions.discard(session_id)
                        try:
                            self.schedule_speaker_jobs(runtime.capture_session_id, force=True)
                        except Exception:
                            logger.exception(
                                "failed to queue deferred speaker analysis for capture %s",
                                runtime.capture_session_id,
                            )
                        try:
                            runtime.capture_finished_sink()
                        except Exception:
                            logger.exception(
                                "capture finished callback failed for %s",
                                runtime.capture_session_id,
                            )
                        finally:
                            self._signal_capture_finished(runtime.capture_session_id)
                            self.asr_queue.task_done()
                continue
            try:
                if runtime.capture_session_id in self._asr_blocked:
                    continue
                expected_start = self._asr_cursors.setdefault(
                    runtime.capture_session_id,
                    task.start_sample,
                )
                if expected_start != task.start_sample:
                    raise RuntimeError("ASR queue received a non-contiguous durable audio range")
                self.process_asr_range(
                    runtime.capture_session_id,
                    task.start_sample,
                    task.end_sample,
                )
            except Exception as exc:
                if isinstance(task, _AudioRange):
                    self._asr_blocked.add(runtime.capture_session_id)
                try:
                    runtime.inference_error_sink(exc)
                except Exception:
                    logger.exception("failed to report inference error for capture %s", runtime.capture_session_id)
            finally:
                self._asr_busy.clear()
                self.asr_queue.task_done()

    def process_asr_range(
        self,
        capture_id: str,
        start_sample: int,
        end_sample: int,
    ) -> _ProcessedAudioRange:
        """Replay a durable capture range and return committed ASR fragment ids."""
        start = int(start_sample)
        end = int(end_sample)
        if start < 0 or end <= start:
            raise ValueError("ASR sample range must be non-empty and non-negative")
        with self._process_lock:
            runtime = self._runtimes.get(capture_id)
            if runtime is None:
                with self.session_factory() as db:
                    capture = db.get(ASRCaptureSession, capture_id)
                    if capture is None:
                        raise ValueError(f"unknown capture session: {capture_id}")
                    runtime = self.capture_service.build_recovery_runtime(capture)
                if runtime is None:
                    raise ValueError(f"capture session cannot be recovered: {capture_id}")
                self._runtimes[capture_id] = runtime

            session_id = runtime.speech_session_id
            if session_id not in self._open_asr_sessions:
                open_options = {
                    "sample_rate": runtime.sample_rate,
                    "speaker_backend": runtime.speaker_backend,
                }
                if start:
                    open_options["base_sample"] = start
                self.ai_supervisor.open_speech_session(
                    session_id,
                    **open_options,
                )
                self._open_asr_sessions.add(session_id)
            pcm = self.archive.read_samples(capture_id, start, end)
            self._rewind_asr_cursor(capture_id, start)
            events = self.ai_supervisor.push_speech_pcm(session_id, pcm)
            fragment_ids = self._consume_event_batch(runtime, events, end_sample=end)
            self.schedule_speaker_jobs(capture_id)
            return _ProcessedAudioRange(fragment_ids)

    def _consume_event_batch(
        self,
        runtime: Any,
        events: list[Any] | None,
        *,
        end_sample: int | None,
        complete_asr: bool = False,
    ) -> list[str]:
        events = list(events or [])
        replay_start = self._get_unfinished_asr_start(runtime.capture_session_id)
        vad_open = replay_start is not None
        for event in events:
            event_type = getattr(event, "type", None)
            if event_type is SpeechEventType.VAD_END:
                vad_open = False
                replay_start = None
                continue
            if event_type is not SpeechEventType.VAD_START:
                continue
            details = getattr(event, "details", {}) or {}
            if details.get("replay_start_sample") is not None:
                replay_start = int(details["replay_start_sample"])
            elif event.start_ms is not None:
                boundary = int(round(int(event.start_ms) * runtime.sample_rate / 1000))
                replay_start = max(0, boundary - int(round(1200 * runtime.sample_rate / 1000)))
            else:
                replay_start = 0
            vad_open = True
        if vad_open:
            if replay_start is None:
                replay_start = 0

        fragment_ids = runtime.consume_events(events) or []
        if end_sample is not None:
            self._advance_asr_cursor(
                runtime.capture_session_id,
                end_sample,
                unfinished_start=replay_start if vad_open else None,
                complete_asr=complete_asr,
            )
        else:
            self._replace_unfinished_asr_start(
                runtime.capture_session_id,
                replay_start if vad_open else None,
            )
        return list(fragment_ids)

    def _get_unfinished_asr_start(self, capture_id: str) -> int | None:
        with self.session_factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            return None if capture is None else capture.asr_unfinished_start_sample

    def _capture_audio_sample_count(self, capture_id: str) -> int:
        with self.session_factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if capture is None:
                raise ValueError(f"unknown capture session: {capture_id}")
            return max(0, int(capture.audio_sample_count or 0))

    def _begin_asr_finalization(
        self,
        capture_id: str,
        sample_rate: int,
    ) -> None:
        with archive_repo.archive_transaction(self.session_factory) as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if capture is None:
                raise ValueError(f"unknown capture session: {capture_id}")
            end_sample = max(0, int(capture.audio_sample_count or 0))
            marker = capture.asr_unfinished_start_sample
            checkpoint = marker
            if checkpoint is None:
                checkpoint_samples = int(round(_FINALIZE_REPLAY_WINDOW_MS * sample_rate / 1000))
                checkpoint = max(0, end_sample - checkpoint_samples)
            if capture.asr_finalize_checkpoint_sample is not None:
                checkpoint = min(
                    max(0, int(capture.asr_finalize_checkpoint_sample)),
                    max(0, int(checkpoint)),
                )
            capture.asr_finalize_checkpoint_sample = max(0, int(checkpoint))
            capture.asr_status = "FINALIZING"

    def _rewind_asr_cursor(self, capture_id: str, start_sample: int) -> None:
        with self.session_factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if capture is not None:
                capture.asr_cursor_sample = min(
                    max(0, int(capture.asr_cursor_sample or 0)),
                    max(0, int(start_sample)),
                )
                db.commit()
        with self._lock:
            if capture_id in self._asr_cursors:
                self._asr_cursors[capture_id] = min(
                    self._asr_cursors[capture_id],
                    max(0, int(start_sample)),
                )

    def _replace_unfinished_asr_start(self, capture_id: str, start_sample: int | None) -> None:
        with self.session_factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if capture is not None:
                capture.asr_unfinished_start_sample = (
                    None if start_sample is None else max(0, int(start_sample))
                )
                db.commit()

    def _advance_asr_cursor(
        self,
        capture_id: str,
        end_sample: int,
        *,
        unfinished_start: int | None,
        complete_asr: bool = False,
    ) -> None:
        with self.session_factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if capture is not None:
                if complete_asr:
                    capture.asr_cursor_sample = int(end_sample)
                    capture.asr_status = "COMPLETE"
                    capture.asr_finalize_checkpoint_sample = None
                else:
                    capture.asr_cursor_sample = max(
                        int(capture.asr_cursor_sample or 0),
                        int(end_sample),
                    )
                capture.asr_unfinished_start_sample = (
                    None if unfinished_start is None else max(0, int(unfinished_start))
                )
                db.commit()
        with self._lock:
            self._asr_cursors[capture_id] = max(self._asr_cursors.get(capture_id, 0), int(end_sample))

    def enqueue_speaker_work(self, work: Callable[[], None]) -> None:
        self.speaker_queue.put(work)

    def _speaker_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                work = self.speaker_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if work is None:
                self.speaker_queue.task_done()
                return
            try:
                while (
                    not self._stopping.is_set()
                    and (not self.asr_queue.empty() or self._asr_busy.is_set())
                ):
                    self._stopping.wait(0.02)
                if not self._stopping.is_set():
                    if isinstance(work, _SpeakerJob):
                        self.process_speaker_job(work.job_id)
                    else:
                        work()
            except Exception:
                logger.exception("deferred speaker work failed")
            finally:
                if isinstance(work, _SpeakerJob):
                    with self._speaker_work_condition:
                        self._speaker_queued_ids.discard(work.job_id)
                        pending = self._speaker_pending_counts.get(work.capture_session_id, 0)
                        if pending <= 1:
                            self._speaker_pending_counts.pop(work.capture_session_id, None)
                        else:
                            self._speaker_pending_counts[work.capture_session_id] = pending - 1
                        self._speaker_work_condition.notify_all()
                self.speaker_queue.task_done()

    def process_speaker_job(self, job_id: str) -> None:
        """Analyze one pending Stage 1 utterance; commit replacements atomically."""
        try:
            with self.session_factory() as db:
                job = db.get(LiveSpeechJob, job_id)
                if job is None or job.kind != "SPEAKER" or job.state != "PENDING":
                    return
                parent = db.get(ASRFragment, job.fragment_id) if job.fragment_id else None
                if not self._parent_is_unedited_pending(parent):
                    job.state = "COMPLETE"
                    self._refresh_speaker_status(db, job.capture_session_id)
                    db.commit()
                    return
                capture = db.get(ASRCaptureSession, job.capture_session_id)
                if capture is None:
                    job.state = "NEEDS_REVIEW"
                    job.last_error_code = "CAPTURE_MISSING"
                    db.commit()
                    return
                job.state = "RUNNING"
                job.attempts = int(job.attempts or 0) + 1
                db.commit()
                capture_id = capture.id
                sample_rate = int(capture.sample_rate)
                interrogation_session_id = capture.interrogation_session_id
                start_sample = int(job.start_sample)
                end_sample = int(job.end_sample)
                parent_start_ms = int(parent.started_at_ms)
                parent_end_ms = int(parent.ended_at_ms)
                parent_confidence = parent.asr_confidence
                parent_model_id = parent.model_id
                parent_model_version = parent.model_version

            if interrogation_session_id is None:
                self._set_speaker_job_state(job_id, "NEEDS_REVIEW", "SESSION_MISSING")
                return
            runtime = self._runtimes.get(capture_id)
            if runtime is None:
                with self.session_factory() as db:
                    capture = db.get(ASRCaptureSession, capture_id)
                    runtime = None if capture is None else self.capture_service.build_recovery_runtime(capture)
                if runtime is None:
                    self._set_speaker_job_state(job_id, "NEEDS_REVIEW", "RUNTIME_UNAVAILABLE")
                    return
                self._runtimes[capture_id] = runtime

            pcm = self.archive.read_samples(capture_id, start_sample, end_sample)
            total_ms = int(round((end_sample - start_sample) * 1000 / sample_rate))
            spans = SpeechSession.split_speaker_turns(
                pcm,
                sample_rate,
                lambda chunk: self._extract_embedding_with_priority(chunk, sample_rate)["embedding"],
                splitter=SpeakerTurnSplitter(),
            )
            if not self._valid_turn_spans(spans, total_ms):
                self._set_speaker_job_state(job_id, "NEEDS_REVIEW", "AMBIGUOUS_BOUNDARY")
                return

            if len(spans) == 1:
                span = spans[0]
                if span.ambiguous:
                    self._persist_ambiguous_speaker_result(
                        job_id,
                        runtime,
                        self._extract_embedding_with_priority(pcm, sample_rate),
                        duration_ms=total_ms,
                    )
                    return
                embedding = self._extract_embedding_with_priority(pcm, sample_rate)
                decision = self._decide_deferred_speaker(
                    runtime,
                    embedding=embedding["embedding"],
                    start_ms=parent_start_ms,
                    end_ms=parent_end_ms,
                    duration_ms=total_ms,
                    overlap=False,
                )
                self._commit_single_speaker_decision(
                    job_id,
                    runtime,
                    decision,
                    model=embedding,
                    duration_ms=total_ms,
                )
                return

            child_results: list[dict[str, Any]] = []
            for index, span in enumerate(spans):
                if span.ambiguous:
                    self._persist_ambiguous_speaker_result(
                        job_id,
                        runtime,
                        self._extract_embedding_with_priority(pcm, sample_rate),
                        duration_ms=total_ms,
                    )
                    return
                child_start = start_sample + int(round(span.start_ms * sample_rate / 1000))
                child_end = start_sample + int(round(span.end_ms * sample_rate / 1000))
                relative_start = child_start - start_sample
                relative_end = child_end - start_sample
                child_pcm = pcm[relative_start * 2 : relative_end * 2]
                if not child_pcm or child_end <= child_start:
                    self._set_speaker_job_state(job_id, "NEEDS_REVIEW", "AMBIGUOUS_BOUNDARY")
                    return
                embedding = self._extract_embedding_with_priority(child_pcm, sample_rate)
                duration_ms = int(round((child_end - child_start) * 1000 / sample_rate))
                decision = self._decide_deferred_speaker(
                    runtime,
                    embedding=embedding["embedding"],
                    start_ms=int(round(child_start * 1000 / sample_rate)),
                    end_ms=int(round(child_end * 1000 / sample_rate)),
                    duration_ms=duration_ms,
                    overlap=False,
                )
                self._wait_for_asr_priority()
                transcript = self._transcribe_child(child_pcm, job_id, index)
                child_results.append(
                    {
                        "start_sample": child_start,
                        "end_sample": child_end,
                        "started_at_ms": int(round(child_start * 1000 / sample_rate)),
                        "ended_at_ms": int(round(child_end * 1000 / sample_rate)),
                        "text": transcript["text"],
                        "confidence": transcript["confidence"],
                        "model_id": transcript["model_id"] or parent_model_id or "paraformer",
                        "model_version": transcript["model_version"] or parent_model_version,
                        "decision": decision,
                        "speaker_model": embedding,
                        "duration_ms": duration_ms,
                    }
                )
            self._commit_split_speaker_decisions(
                job_id,
                runtime,
                child_results,
                parent_confidence=parent_confidence,
            )
        except Exception as exc:
            logger.exception("deferred speaker analysis failed for job %s", job_id)
            self._set_speaker_job_state(job_id, "NEEDS_REVIEW", self._speaker_error_code(exc))

    @staticmethod
    def _parent_is_unedited_pending(parent: ASRFragment | None) -> bool:
        return bool(
            parent is not None
            and parent.state == "PENDING"
            and parent.speaker_source == "PENDING_ANALYSIS"
            and parent.confirmed_message_id is None
            and parent.edited_text == parent.raw_text
        )

    @staticmethod
    def _valid_turn_spans(spans: list[Any], total_ms: int) -> bool:
        if not spans or total_ms <= 0 or spans[0].start_ms != 0 or spans[-1].end_ms != total_ms:
            return False
        cursor = 0
        for span in spans:
            if span.start_ms != cursor or span.end_ms <= span.start_ms:
                return False
            cursor = span.end_ms
        return cursor == total_ms

    def _extract_embedding(self, pcm: bytes, sample_rate: int) -> dict[str, Any]:
        result = self.ai_supervisor.extract_speaker_embedding(pcm, sample_rate=sample_rate)
        embedding_value = result.get("embedding") if isinstance(result, dict) else getattr(result, "embedding", None)
        owner = self._capture_service_owner()
        embedding = owner._normalize_vector(embedding_value)
        if embedding is None:
            raise ValueError("speaker worker returned an invalid embedding")
        return {
            "embedding": embedding,
            "model_id": self._optional_text(
                result.get("model_id") if isinstance(result, dict) else getattr(result, "model_id", None)
            ),
            "model_version": self._optional_text(
                result.get("model_version") if isinstance(result, dict) else getattr(result, "model_version", None)
            ),
            "model_fingerprint": self._optional_text(
                (result.get("model_fingerprint") or result.get("fingerprint"))
                if isinstance(result, dict)
                else getattr(result, "model_fingerprint", None)
            ),
        }

    def _extract_embedding_with_priority(self, pcm: bytes, sample_rate: int) -> dict[str, Any]:
        self._wait_for_asr_priority()
        return self._extract_embedding(pcm, sample_rate)

    def _capture_service_owner(self):
        return getattr(self.capture_service, "_default_service", self.capture_service)

    def _decide_deferred_speaker(
        self,
        runtime: Any,
        *,
        embedding: list[float],
        start_ms: int,
        end_ms: int,
        duration_ms: int,
        overlap: bool,
    ):
        owner = self._capture_service_owner()
        speaker_event = SpeechEvent(
            type=SpeechEventType.SPEAKER_RESULT,
            session_id=runtime.speech_session_id,
            start_ms=start_ms,
            end_ms=end_ms,
            embedding=embedding,
            model_id="eres2net_large",
        )
        with self.session_factory() as db:
            case = db.get(Case, runtime.case_id)
            if case is None:
                raise ValueError("speaker analysis case no longer exists")
            candidates, enabled_roles = owner._speaker_candidates(
                db,
                case=case,
                interrogation_session_id=runtime.interrogation_session_id,
                speaker_event=speaker_event,
                backend_key=runtime.authoritative_speaker_backend or owner.authoritative_speaker_backend,
            )
            return owner._decide_with_operating_point(
                candidates=candidates,
                enabled_roles=enabled_roles,
                threshold=runtime.speaker_threshold,
                margin=runtime.speaker_margin,
                usable_duration_ms=duration_ms,
                overlap=overlap,
            )

    def _transcribe_child(self, pcm: bytes, job_id: str, index: int) -> dict[str, Any]:
        result = self.ai_supervisor.transcribe(
            pcm,
            session_id=f"speaker-{job_id[:40]}-{index}",
        )
        value = lambda name: result.get(name) if isinstance(result, dict) else getattr(result, name, None)
        text = str(value("text") or "").strip()
        if not text:
            raise ValueError("child ASR returned an empty transcript")
        confidence = value("confidence")
        return {
            "text": text,
            "confidence": None if confidence is None else float(confidence),
            "model_id": self._optional_text(value("model_id")),
            "model_version": self._optional_text(value("model_version")),
        }

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _speaker_error_code(exc: Exception) -> str:
        code = getattr(exc, "code", None)
        return str(code or type(exc).__name__).upper()[:64]

    def _wait_for_asr_priority(self) -> None:
        while not self._stopping.is_set() and (
            not self.asr_queue.empty() or self._asr_busy.is_set()
        ):
            self._stopping.wait(0.02)

    def _commit_single_speaker_decision(
        self,
        job_id: str,
        runtime: Any,
        decision,
        *,
        model: dict[str, Any],
        duration_ms: int,
    ) -> None:
        owner = self._capture_service_owner()
        payload = None
        with archive_repo.archive_transaction(self.session_factory) as db:
            job = db.get(LiveSpeechJob, job_id)
            parent = None if job is None or job.fragment_id is None else db.get(ASRFragment, job.fragment_id)
            if job is None or job.state != "RUNNING":
                return
            if not self._parent_is_unedited_pending(parent):
                job.state = "COMPLETE"
                self._refresh_speaker_status(db, job.capture_session_id)
                return

            parent.speaker = decision.role.value
            parent.speaker_id = decision.speaker_id
            parent.speaker_name = decision.speaker_name
            parent.speaker_score = decision.score
            parent.second_best_score = decision.second_best_score
            parent.speaker_threshold = decision.threshold
            parent.speaker_margin = runtime.speaker_margin
            parent.speaker_source = decision.source.value
            parent.voiceprint_verified = decision.voiceprint_verified
            parent.low_confidence = decision.low_confidence
            asr_repo.create_speaker_analysis_result(
                db,
                analysis_job_id=job_id,
                fragment_id=parent.id,
                decision=decision,
                threshold_source=runtime.threshold_source,
                calibration_id=runtime.calibration_id,
                calibration_status=runtime.calibration_status,
                overlap=False,
                usable_duration_ms=duration_ms,
                model_id=model["model_id"],
                model_version=model["model_version"],
                model_fingerprint=model["model_fingerprint"] or runtime.speaker_model_fingerprint,
                microphone_fingerprint=runtime.microphone_fingerprint,
            )
            job.state = "COMPLETE"
            job.last_error_code = None
            job.model_version = model["model_version"]
            self._refresh_speaker_status(db, job.capture_session_id)
            payload = owner._fragment_payload(parent)
            payload["captureStartedAt"] = runtime.capture_started_at
            payload["thresholdSource"] = runtime.threshold_source
            payload["calibrationId"] = runtime.calibration_id
            payload["calibrationStatus"] = runtime.calibration_status
        if payload is not None:
            try:
                self.capture_service.publish_event(
                    runtime.interrogation_session_id,
                    "ASR_FRAGMENT",
                    payload,
                )
            finally:
                if decision.role.value != "UNKNOWN":
                    self._route_resolved_fragments(runtime.case_id, [payload["fragmentId"]])

    def _commit_split_speaker_decisions(
        self,
        job_id: str,
        runtime: Any,
        children: list[dict[str, Any]],
        *,
        parent_confidence: float | None,
    ) -> None:
        if len(children) < 2:
            raise ValueError("speaker split requires at least two stable turns")
        owner = self._capture_service_owner()
        replacement_payload: dict[str, Any] | None = None
        with archive_repo.archive_transaction(self.session_factory) as db:
            job = db.get(LiveSpeechJob, job_id)
            parent = None if job is None or job.fragment_id is None else db.get(ASRFragment, job.fragment_id)
            if job is None or job.state != "RUNNING":
                return
            if not self._parent_is_unedited_pending(parent):
                job.state = "COMPLETE"
                self._refresh_speaker_status(db, job.capture_session_id)
                return
            if children[0]["started_at_ms"] != parent.started_at_ms or children[-1]["ended_at_ms"] != parent.ended_at_ms:
                raise ValueError("speaker split boundaries do not cover the source fragment")
            for previous, current in zip(children, children[1:]):
                if previous["ended_at_ms"] != current["started_at_ms"]:
                    raise ValueError("speaker split boundaries overlap or leave a gap")

            max_ordinal = db.scalar(
                select(func.max(ASRFragment.ordinal)).where(
                    ASRFragment.capture_session_id == parent.capture_session_id
                )
            )
            next_ordinal = int(max_ordinal) + 1 if max_ordinal is not None else 0
            payloads: list[dict[str, Any]] = []
            first_model_version = None
            for child in children:
                decision = child["decision"]
                speaker_model = child["speaker_model"]
                if first_model_version is None:
                    first_model_version = speaker_model["model_version"]
                fragment = asr_repo.create_fragment(
                    db,
                    capture_session_id=parent.capture_session_id,
                    case_id=parent.case_id,
                    ordinal=next_ordinal,
                    started_at_ms=child["started_at_ms"],
                    ended_at_ms=child["ended_at_ms"],
                    raw_text=child["text"],
                    asr_confidence=child["confidence"] if child["confidence"] is not None else parent_confidence,
                    speaker=decision.role.value,
                    speaker_id=decision.speaker_id,
                    speaker_name=decision.speaker_name,
                    speaker_score=decision.score,
                    second_best_score=decision.second_best_score,
                    speaker_threshold=decision.threshold,
                    speaker_margin=runtime.speaker_margin,
                    speaker_source=decision.source.value,
                    voiceprint_verified=decision.voiceprint_verified,
                    low_confidence=decision.low_confidence,
                    model_id=child["model_id"],
                    model_version=child["model_version"],
                    speaker_threshold_source=runtime.threshold_source,
                    speaker_model_id=speaker_model["model_id"],
                    speaker_model_version=speaker_model["model_version"],
                    speaker_model_fingerprint=(
                        speaker_model["model_fingerprint"] or runtime.speaker_model_fingerprint
                    ),
                    microphone_fingerprint=runtime.microphone_fingerprint,
                )
                asr_repo.create_speaker_analysis_result(
                    db,
                    analysis_job_id=job_id,
                    fragment_id=fragment.id,
                    decision=decision,
                    threshold_source=runtime.threshold_source,
                    calibration_id=runtime.calibration_id,
                    calibration_status=runtime.calibration_status,
                    overlap=False,
                    usable_duration_ms=child["duration_ms"],
                    model_id=speaker_model["model_id"],
                    model_version=speaker_model["model_version"],
                    model_fingerprint=(
                        speaker_model["model_fingerprint"] or runtime.speaker_model_fingerprint
                    ),
                    microphone_fingerprint=runtime.microphone_fingerprint,
                )
                asr_repo.add_fragment_lineage(
                    db,
                    analysis_job_id=job_id,
                    parent_fragment_id=parent.id,
                    child_fragment_id=fragment.id,
                )
                item = owner._fragment_payload(fragment)
                item["captureStartedAt"] = runtime.capture_started_at
                item["thresholdSource"] = runtime.threshold_source
                item["calibrationId"] = runtime.calibration_id
                item["calibrationStatus"] = runtime.calibration_status
                payloads.append(item)
                next_ordinal += 1

            parent.state = "SUPERSEDED"
            job.state = "COMPLETE"
            job.last_error_code = None
            job.model_version = first_model_version
            self._refresh_speaker_status(db, job.capture_session_id)
            replacement_payload = {
                "parentFragmentId": parent.id,
                "fragments": payloads,
                "jobId": job.id,
            }
        if replacement_payload is not None:
            try:
                self.capture_service.publish_event(
                    runtime.interrogation_session_id,
                    "ASR_FRAGMENT_REPLACED",
                    replacement_payload,
                )
            finally:
                self._route_resolved_fragments(
                    runtime.case_id,
                    [
                        item["fragmentId"]
                        for item in replacement_payload["fragments"]
                        if item.get("speaker") != "UNKNOWN"
                    ],
                )

    def _route_resolved_fragments(self, case_id: str, fragment_ids: list[str]) -> None:
        unique_ids = list(dict.fromkeys(fragment_ids))
        if not unique_ids:
            return
        with self.session_factory() as db:
            eligible_ids = [
                fragment.id
                for fragment in db.scalars(
                    select(ASRFragment)
                    .where(
                        ASRFragment.id.in_(unique_ids),
                        ASRFragment.case_id == case_id,
                        ASRFragment.speaker.in_(
                            ("INTERROGATOR", "RECORDER", "OFFICER_FALLBACK", "SUSPECT")
                        ),
                        ASRFragment.state.in_(("PENDING", "EDITED")),
                    )
                    .order_by(
                        ASRFragment.started_at_ms.asc(),
                        ASRFragment.ended_at_ms.asc(),
                        ASRFragment.ordinal.asc(),
                        ASRFragment.id.asc(),
                    )
                )
            ]
        fragment_sink = getattr(self.capture_service, "fragment_sink", None)
        if fragment_sink is not None:
            for fragment_id in eligible_ids:
                fragment_sink(case_id, fragment_id)
            return

        if eligible_ids:
            from app.services.interrogation_projection_service import InterrogationProjectionService

            with self.session_factory() as db:
                projection = InterrogationProjectionService(db)
                for fragment_id in eligible_ids:
                    projection.process_fragment(case_id, fragment_id)
                db.commit()

    def _set_speaker_job_state(self, job_id: str, state: str, error_code: str | None) -> None:
        with archive_repo.archive_transaction(self.session_factory) as db:
            job = db.get(LiveSpeechJob, job_id)
            if job is None or job.state == "COMPLETE":
                return
            job.state = state
            job.last_error_code = error_code
            self._refresh_speaker_status(db, job.capture_session_id)

    def _persist_ambiguous_speaker_result(
        self,
        job_id: str,
        runtime: Any,
        model: dict[str, Any],
        *,
        duration_ms: int,
    ) -> None:
        decision = self._decide_deferred_speaker(
            runtime,
            embedding=model["embedding"],
            start_ms=0,
            end_ms=duration_ms,
            duration_ms=duration_ms,
            overlap=True,
        )
        with archive_repo.archive_transaction(self.session_factory) as db:
            job = db.get(LiveSpeechJob, job_id)
            parent = None if job is None or job.fragment_id is None else db.get(ASRFragment, job.fragment_id)
            if job is None or job.state != "RUNNING":
                return
            if self._parent_is_unedited_pending(parent):
                asr_repo.create_speaker_analysis_result(
                    db,
                    analysis_job_id=job_id,
                    fragment_id=parent.id,
                    decision=decision,
                    threshold_source=runtime.threshold_source,
                    calibration_id=runtime.calibration_id,
                    calibration_status=runtime.calibration_status,
                    overlap=True,
                    usable_duration_ms=duration_ms,
                    model_id=model["model_id"],
                    model_version=model["model_version"],
                    model_fingerprint=model["model_fingerprint"] or runtime.speaker_model_fingerprint,
                    microphone_fingerprint=runtime.microphone_fingerprint,
                )
            job.state = "NEEDS_REVIEW"
            job.last_error_code = "AMBIGUOUS_BOUNDARY"
            self._refresh_speaker_status(db, job.capture_session_id)

    @staticmethod
    def _refresh_speaker_status(db: Session, capture_id: str) -> None:
        capture = db.get(ASRCaptureSession, capture_id)
        if capture is None:
            return
        db.flush()
        states = list(
            db.scalars(
                select(LiveSpeechJob.state).where(
                    LiveSpeechJob.kind == "SPEAKER",
                    LiveSpeechJob.capture_session_id == capture_id,
                )
            )
        )
        if "RUNNING" in states:
            capture.speaker_status = "RUNNING"
        elif "PENDING" in states:
            capture.speaker_status = "QUEUED"
        elif "NEEDS_REVIEW" in states:
            capture.speaker_status = "NEEDS_REVIEW"
        elif states:
            capture.speaker_status = "COMPLETE"

    def shutdown(self) -> None:
        with self._lock:
            if not self._started:
                return
            self._stopping.set()
            self.asr_queue.put(None)
            self.speaker_queue.put(None)
            asr_thread = self._asr_thread
            speaker_thread = self._speaker_thread
            self._started = False
        if asr_thread is not None:
            asr_thread.join(timeout=5)
        if speaker_thread is not None:
            speaker_thread.join(timeout=2)
