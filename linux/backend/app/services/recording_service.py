from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import wave
from datetime import timedelta
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.context import current_actor
from app.database.models import ASRCaptureSession, ASRFragment, CaseQuestion, QuestionRound
from app.database.recording_models import CaptureRecording, CaseRecordingOptions
from app.database.session import begin_sqlite_immediate
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo, cases as case_repo
from app.services.formal_record_policy import assert_formal_record_mutable
from app.services.serializers import iso_utc


def snapshot_capture_options(db: Session, capture_id: str) -> CaptureRecording:
    """Call in the capture-start transaction, before accepting any audio."""
    row = db.get(CaptureRecording, capture_id)
    if row is not None:
        return row
    capture = db.get(ASRCaptureSession, capture_id)
    if capture is None:
        raise DomainError('CAPTURE_NOT_FOUND', '录音采集不存在', 404)
    options = db.get(CaseRecordingOptions, capture.case_id)
    row = CaptureRecording(capture_id=capture.id, full_recording_enabled=True if options is None else options.full_recording_enabled)
    db.add(row)
    db.flush()
    return row


def require_recording_actor(*, admin=False):
    actor = current_actor()
    if actor is None:
        raise DomainError('AUTH_REQUIRED', '调阅录音需要民警认证', 401)
    if admin and not actor.is_admin:
        raise DomainError('ADMIN_REQUIRED', '调阅全程原始录音需要管理员授权', 403)
    return actor


class RecordingService:
    def __init__(self, db: Session, archive):
        self.db = db
        self.archive = archive

    def options(self, case_id: str) -> dict:
        case_repo.get(self.db, case_id)
        row = self.db.get(CaseRecordingOptions, case_id)
        return {'caseId': case_id, 'fullRecordingEnabled': True if row is None else row.full_recording_enabled}

    def set_options(self, case_id: str, enabled: bool) -> dict:
        begin_sqlite_immediate(self.db)
        assert_formal_record_mutable(self.db, case_id)
        if not isinstance(enabled, bool):
            raise DomainError('INVALID_RECORDING_OPTION', '全程录音开关必须为布尔值', 400)
        active = self.db.scalar(select(ASRCaptureSession.id).where(ASRCaptureSession.case_id == case_id, or_(ASRCaptureSession.recording_status == 'CAPTURING', ASRCaptureSession.status.in_(['CAPTURING', 'RECORDING', 'RUNNING', 'STOPPING']))).limit(1))
        if active:
            raise DomainError('RECORDING_IN_PROGRESS', '采集过程中不能修改全程录音开关', 409)
        before = self.options(case_id)
        row = self.db.get(CaseRecordingOptions, case_id)
        if row is None:
            row = CaseRecordingOptions(case_id=case_id, full_recording_enabled=enabled)
            self.db.add(row)
        else:
            row.full_recording_enabled = enabled
        self.db.flush()
        after = self.options(case_id)
        audit_repo.add(self.db, case_id=case_id, action='RECORDING_OPTIONS_UPDATE', target_type='CASE', target_id=case_id, before=before, after=after)
        return after

    def _capture(self, case_id: str, capture_id: str):
        capture = self.db.get(ASRCaptureSession, capture_id)
        if capture is None or capture.case_id != case_id:
            raise DomainError('RECORDING_NOT_FOUND', '录音不存在或不属于本案', 404)
        return capture

    def _ranges(self, case_id: str) -> list[dict]:
        questions = {q.id: q for q in self.db.scalars(select(CaseQuestion).where(CaseQuestion.case_id == case_id).order_by(CaseQuestion.sort_order))}
        numbers = {q.id: number for number, q in enumerate((q for q in questions.values() if q.active), 1)}
        captures = {c.id: c for c in self.db.scalars(select(ASRCaptureSession).where(ASRCaptureSession.case_id == case_id))}
        rows = []
        for capture in captures.values():
            if capture.target_question_id in questions and capture.audio_sample_count > 0:
                rows.append(self._range(questions[capture.target_question_id], capture, 0, capture.audio_sample_count))
        seen = set()
        for round_ in self.db.scalars(select(QuestionRound).where(QuestionRound.case_id == case_id)):
            if round_.case_question_id not in questions:
                continue
            fragment_ids = json.loads(round_.answer_fragment_ids_json or '[]')
            if round_.officer_fragment_id:
                fragment_ids.append(round_.officer_fragment_id)
            for fragment_id in fragment_ids:
                key = (round_.case_question_id, fragment_id)
                if key in seen:
                    continue
                seen.add(key)
                fragment = self.db.get(ASRFragment, fragment_id)
                capture = captures.get(fragment.capture_session_id) if fragment is not None and fragment.case_id == case_id else None
                if capture is None or capture.target_question_id == round_.case_question_id:
                    continue
                start = fragment.started_at_ms * capture.sample_rate // 1000
                end = fragment.ended_at_ms * capture.sample_rate // 1000
                if 0 <= start < end <= capture.audio_sample_count:
                    rows.append(self._range(questions[round_.case_question_id], capture, start, end, fragment_id))
        for row in rows:
            row['questionNumber'] = numbers.get(row['questionId'])
            row['questionActive'] = questions[row['questionId']].active
        return sorted(rows, key=lambda r: (r['questionNumber'] is None, r['questionNumber'] or 0, r['startedAt'], r['startMs']))

    @staticmethod
    def _range(question, capture, start, end, fragment_id=None):
        start_ms = start * 1000 // capture.sample_rate
        return {'questionId': question.id, 'question': question.text, 'captureSessionId': capture.id, 'fragmentId': fragment_id, 'startSample': start, 'endSample': end, 'startMs': start_ms, 'durationMs': (end - start) * 1000 // capture.sample_rate, 'startedAt': iso_utc(capture.started_at + timedelta(milliseconds=start_ms)), 'status': capture.recording_status, 'available': capture.recording_status == 'COMPLETE'}

    def list_recordings(self, case_id: str) -> dict:
        require_recording_actor()
        options = self.options(case_id)
        rows = self._ranges(case_id)
        for row in rows:
            suffix = f"/fragments/{row['fragmentId']}" if row['fragmentId'] else ''
            row['audioUrl'] = f"/api/v1/cases/{case_id}/recordings/questions/{row['questionId']}/captures/{row['captureSessionId']}{suffix}/audio" if row['available'] else None
        originals = []
        for capture in self.db.scalars(select(ASRCaptureSession).where(ASRCaptureSession.case_id == case_id).order_by(ASRCaptureSession.started_at)):
            recording = self.db.get(CaptureRecording, capture.id)
            if recording is not None and recording.original_sha256:
                originals.append(self._original_metadata(capture, recording))
        return {**options, 'questions': rows, 'originals': originals, 'originalAccessRequiresAdmin': True}

    def _path(self, case_id: str, capture_id: str, filename: str) -> Path:
        if self.archive is None:
            raise DomainError('RECORDING_ARCHIVE_UNAVAILABLE', '录音存档服务尚未就绪', 503)
        if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value) for value in (case_id, capture_id)):
            raise DomainError('INVALID_RECORDING_PATH', '录音标识无效', 400)
        root = self.archive.data_dir.resolve()
        path = root
        for part in ('recordings', case_id, capture_id, filename):
            path = path / part
            if path.resolve() != path:
                raise DomainError('INVALID_RECORDING_PATH', '录音路径无效', 409)
        return path

    def _write_range(self, capture, start: int, end: int, destination: Path):
        if capture.recording_status != 'COMPLETE' or end <= start:
            raise DomainError('RECORDING_NOT_READY', '录音尚未完整保存', 409)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        # Recheck after directory creation so a configured archive alias cannot escape data_dir.
        self._path(capture.case_id, capture.id, destination.name)
        fd, temporary = tempfile.mkstemp(prefix='.recording-', suffix='.wav', dir=destination.parent)
        try:
            with os.fdopen(fd, 'w+b') as stream:
                with wave.open(stream, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(capture.sample_rate)
                    for offset in range(start, end, capture.sample_rate * 60):
                        stop = min(end, offset + capture.sample_rate * 60)
                        pcm = self.archive.read_samples(capture.id, offset, stop)
                        if len(pcm) != (stop - offset) * 2:
                            raise ValueError('archive sample count mismatch')
                        wav.writeframesraw(pcm)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o640)
            os.replace(temporary, destination)
        except (OSError, ValueError, RuntimeError) as exc:
            raise DomainError('RECORDING_INTEGRITY_ERROR', '录音文件缺失或完整性校验失败', 409) from exc
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def question_audio(self, case_id: str, question_id: str, capture_id: str, *, fragment_id=None) -> Path:
        require_recording_actor()
        self._capture(case_id, capture_id)
        row = next((r for r in self._ranges(case_id) if r['questionId'] == question_id and r['captureSessionId'] == capture_id and r['fragmentId'] == fragment_id), None)
        if row is None:
            raise DomainError('RECORDING_NOT_FOUND', '题目录音不存在或不属于本案', 404)
        capture = self._capture(case_id, capture_id)
        filename = f"question-{row['startSample']}-{row['endSample']}.wav"
        path = self._path(case_id, capture_id, filename)
        self._write_range(capture, row['startSample'], row['endSample'], path)
        audit_repo.add(self.db, case_id=case_id, action='RECORDING_QUESTION_ACCESS', target_type='CASE_QUESTION', target_id=question_id, detail={'captureSessionId': capture_id, 'fragmentId': fragment_id, 'startMs': row['startMs'], 'durationMs': row['durationMs']})
        return path

    @staticmethod
    def _digest(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    def finalize_original(self, capture_id: str) -> dict | None:
        capture = self.db.get(ASRCaptureSession, capture_id)
        if capture is None:
            raise DomainError('CAPTURE_NOT_FOUND', '录音采集不存在', 404)
        recording = self.db.get(CaptureRecording, capture_id)
        # Captures predating the option migration are preserved by its backfill.
        # Missing snapshots on new captures must not create an unauthorized full copy.
        if recording is None or not recording.full_recording_enabled or not capture.audio_sample_count:
            return None
        if recording.original_sha256:
            return self._original_metadata(capture, recording)
        path = self._path(capture.case_id, capture.id, 'original.wav')
        self._write_range(capture, 0, capture.audio_sample_count, path)
        recording.original_sha256 = self._digest(path)
        recording.original_sample_count = capture.audio_sample_count
        recording.original_size_bytes = path.stat().st_size
        self.db.flush()
        return self._original_metadata(capture, recording)

    @staticmethod
    def _original_metadata(capture, recording):
        return {'captureSessionId': capture.id, 'filename': f'{capture.id}-original.wav', 'durationMs': recording.original_sample_count * 1000 // capture.sample_rate, 'sizeBytes': recording.original_size_bytes, 'sha256': recording.original_sha256, 'startedAt': iso_utc(capture.started_at), 'accessRequiresAdmin': True}

    def original_audio(self, case_id: str, capture_id: str, *, reason: str) -> Path:
        require_recording_actor(admin=True)
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 1000:
            raise DomainError('RECORDING_ACCESS_REASON_REQUIRED', '调阅全程原始录音需要填写原因', 400)
        capture = self._capture(case_id, capture_id)
        recording = self.db.get(CaptureRecording, capture_id)
        if recording is None or not recording.full_recording_enabled or not recording.original_sha256:
            raise DomainError('RECORDING_NOT_FOUND', '本次采集未生成全程原始录音', 404)
        path = self._path(case_id, capture_id, 'original.wav')
        try:
            valid = path.stat().st_size == recording.original_size_bytes and self._digest(path) == recording.original_sha256
        except OSError:
            valid = False
        if not valid:
            raise DomainError('RECORDING_INTEGRITY_ERROR', '原始录音文件缺失或完整性校验失败', 409)
        audit_repo.add(self.db, case_id=case_id, action='RECORDING_ORIGINAL_ACCESS', target_type='ASR_CAPTURE', target_id=capture.id, detail={'reason': reason.strip(), 'sha256': recording.original_sha256, 'durationMs': recording.original_sample_count * 1000 // capture.sample_rate})
        return path
