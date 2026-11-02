"""通道②全程录音：每次「开始/继续询问」到「暂停/结束询问」之间一条连续录音。

与通道①（按次采集、按题切片）完全独立：浏览器在询问进行中一直开着麦克风，
把 16 kHz PCM16 推到本服务；暂停/结束时整段落成一个 WAV 并固化 sha256，
之后不拆分、不修改。

断线、刷新页面造成的缺口不补静音冒充录音，只在 gaps 里如实记录
（发生在文件第几毫秒、估计缺了多久、原因），播放与调阅时一并展示。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import threading
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import utc_now
from app.database.models import InterrogationSession
from app.database.recording_models import CaseRecordingOptions, SessionRecordingSegment
from app.domain.enums import SessionStatus
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.services.serializers import iso_utc

SAMPLE_RATE = 16_000
OPEN_STATUSES = ('RECORDING', 'CLOSING')
# 暂停后浏览器一般几百毫秒内就送完尾音并确认；超过这个时间仍未确认的段由服务端收尾。
CLOSING_GRACE = timedelta(seconds=20)
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')


def _gaps(row: SessionRecordingSegment) -> list[dict]:
    try:
        value = json.loads(row.gaps_json or '[]')
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def _add_gap(row: SessionRecordingSegment, *, missing_ms: int | None, reason: str) -> None:
    gaps = _gaps(row)
    gaps.append({
        'atMs': row.sample_count * 1000 // row.sample_rate,
        'missingMs': missing_ms,
        'reason': reason,
        'at': iso_utc(utc_now()),
    })
    row.gaps_json = json.dumps(gaps, ensure_ascii=False)


def full_recording_enabled(db: Session, case_id: str) -> bool:
    options = db.get(CaseRecordingOptions, case_id)
    return True if options is None else options.full_recording_enabled


def active_segment(db: Session, case_id: str) -> SessionRecordingSegment | None:
    return db.scalar(
        select(SessionRecordingSegment)
        .where(SessionRecordingSegment.case_id == case_id, SessionRecordingSegment.status == 'RECORDING')
        .order_by(SessionRecordingSegment.ordinal.desc())
        .limit(1)
    )


def open_segment(db: Session, case_id: str, session: InterrogationSession, actor_id: str | None = None) -> SessionRecordingSegment | None:
    """在开始/继续询问的同一事务里调用：从这一刻起的声音都属于新的一段。"""
    close_segment(db, case_id, 'SUPERSEDED', actor_id)
    if not full_recording_enabled(db, case_id):
        return None
    ordinal = (db.scalar(select(func.max(SessionRecordingSegment.ordinal)).where(SessionRecordingSegment.case_id == case_id)) or 0) + 1
    row = SessionRecordingSegment(
        id=str(uuid4()), case_id=case_id, interrogation_session_id=session.id, ordinal=ordinal,
        status='RECORDING', started_at=utc_now(), sample_rate=SAMPLE_RATE,
    )
    db.add(row)
    db.flush()
    audit_repo.add(db, case_id=case_id, actor_id=actor_id, action='RECORDING_SEGMENT_START',
                   target_type='RECORDING_SEGMENT', target_id=row.id, detail={'ordinal': ordinal, 'sessionId': session.id})
    return row


def close_segment(db: Session, case_id: str, reason: str, actor_id: str | None = None) -> SessionRecordingSegment | None:
    """在暂停/结束询问的同一事务里调用；文件在浏览器送完尾音后（或宽限期后）落盘。"""
    row = active_segment(db, case_id)
    if row is None:
        return None
    row.status = 'CLOSING'
    row.ended_at = utc_now()
    row.end_reason = reason
    db.flush()
    audit_repo.add(db, case_id=case_id, actor_id=actor_id, action='RECORDING_SEGMENT_STOP',
                   target_type='RECORDING_SEGMENT', target_id=row.id, detail={'ordinal': row.ordinal, 'reason': reason})
    return row


def segment_dict(row: SessionRecordingSegment | None) -> dict | None:
    if row is None:
        return None
    return {'id': row.id, 'ordinal': row.ordinal, 'status': row.status, 'startedAt': iso_utc(row.started_at)}


class SessionRecordingStore:
    """全程录音的文件与帧写入。每段一把锁，帧按浏览器的样本时间线幂等追加。"""

    def __init__(self, data_dir: str | Path, session_factory: sessionmaker[Session]):
        self.data_dir = Path(data_dir).resolve()
        self.session_factory = session_factory
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock(self, segment_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(segment_id, threading.Lock())

    def segment_dir(self, case_id: str, segment_id: str) -> Path:
        if not (_ID.fullmatch(case_id) and _ID.fullmatch(segment_id)):
            raise DomainError('INVALID_RECORDING_PATH', '录音标识无效', 400)
        path = self.data_dir / 'recordings' / case_id / 'session-segments' / segment_id
        if not path.resolve().is_relative_to(self.data_dir):
            raise DomainError('INVALID_RECORDING_PATH', '录音路径无效', 409)
        return path

    def wav_path(self, row: SessionRecordingSegment) -> Path:
        return self.segment_dir(row.case_id, row.id) / 'original.wav'

    def _pcm_path(self, row: SessionRecordingSegment) -> Path:
        return self.segment_dir(row.case_id, row.id) / 'audio.pcm'

    @staticmethod
    def _load(db: Session, case_id: str, segment_id: str) -> SessionRecordingSegment:
        row = db.get(SessionRecordingSegment, segment_id)
        if row is None or row.case_id != case_id:
            raise DomainError('RECORDING_SEGMENT_NOT_FOUND', '全程录音段不存在或不属于本案', 404)
        return row

    def attach(self, case_id: str, segment_id: str, *, fresh: bool) -> dict:
        """浏览器连上（或重连）时调用，告诉它从哪个样本、哪个序号继续。

        fresh=True 表示浏览器是新开的录音器（刷新页面、换了窗口），它内存里没有
        断开期间的音频：按墙钟估算缺口并记入 gaps。同一录音器的重连会把缓存的帧
        补发上来，缺口按样本时间线判断，不在这里记。
        """
        with self._lock(segment_id), self.session_factory() as db:
            row = self._load(db, case_id, segment_id)
            if fresh and row.status == 'RECORDING' and row.last_frame_at is not None:
                last = row.last_frame_at if row.last_frame_at.tzinfo else row.last_frame_at.replace(tzinfo=utc_now().tzinfo)
                missing = max(0, int((utc_now() - last).total_seconds() * 1000))
                _add_gap(row, missing_ms=missing, reason='BROWSER_RESTARTED')
                db.commit()
            return {'status': row.status, 'clientSampleEnd': row.client_sample_end, 'nextSequence': row.next_sequence}

    def ingest(self, case_id: str, segment_id: str, sequence: int, start_sample: int, pcm: bytes) -> dict:
        if not pcm or len(pcm) % 2:
            raise ValueError('pcm16 alignment violation')
        samples = len(pcm) // 2
        end_sample = start_sample + samples
        with self._lock(segment_id), self.session_factory() as db:
            row = self._load(db, case_id, segment_id)
            if row.status not in OPEN_STATUSES:
                raise DomainError('RECORDING_SEGMENT_CLOSED', '这段全程录音已经保存，不再接收音频', 409)
            if end_sample <= row.client_sample_end:
                return {'type': 'ack', 'ackSequence': sequence, 'durableSampleEnd': end_sample}
            if start_sample < row.client_sample_end:
                pcm = pcm[(row.client_sample_end - start_sample) * 2:]
            elif start_sample > row.client_sample_end:
                # 浏览器缓存溢出丢掉的音频：不补静音，只记录。
                _add_gap(row, missing_ms=(start_sample - row.client_sample_end) * 1000 // row.sample_rate, reason='BROWSER_BUFFER_DROPPED')
            path = self._pcm_path(row)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
            with open(path, 'ab') as stream:
                # 文件以数据库记下的样本数为准：上次写入后、提交前崩溃留下的尾巴丢弃。
                if stream.tell() != row.sample_count * 2:
                    stream.truncate(row.sample_count * 2)
                    stream.seek(row.sample_count * 2)
                stream.write(pcm)
                stream.flush()
                os.fsync(stream.fileno())
            row.sample_count += len(pcm) // 2
            row.client_sample_end = end_sample
            row.next_sequence = max(row.next_sequence, sequence + 1)
            row.last_frame_at = utc_now()
            db.commit()
            return {'type': 'ack', 'ackSequence': sequence, 'durableSampleEnd': end_sample}

    def finalize(self, case_id: str, segment_id: str, *, client_confirmed: bool) -> dict:
        """把一段落成 original.wav 并固化 sha256。只处理已暂停/结束（CLOSING）的段。"""
        with self._lock(segment_id), self.session_factory() as db:
            row = self._load(db, case_id, segment_id)
            if row.status == 'CLOSING':
                self._write_original(db, row, client_confirmed=client_confirmed)
                db.commit()
            return {'status': row.status, 'sha256': row.sha256, 'durationMs': row.sample_count * 1000 // row.sample_rate}

    def _write_original(self, db: Session, row: SessionRecordingSegment, *, client_confirmed: bool) -> None:
        row.client_finalized = client_confirmed
        row.finalized_at = utc_now()
        pcm_path = self._pcm_path(row)
        if row.sample_count == 0:
            row.status = 'EMPTY'
            pcm_path.unlink(missing_ok=True)
        else:
            destination = self.wav_path(row)
            temporary = destination.with_name('.original.wav.tmp')
            digest = hashlib.sha256()
            data_bytes = row.sample_count * 2
            header = b'RIFF' + struct.pack('<I', 36 + data_bytes) + b'WAVEfmt ' + struct.pack(
                '<IHHIIHH', 16, 1, 1, row.sample_rate, row.sample_rate * 2, 2, 16) + b'data' + struct.pack('<I', data_bytes)
            try:
                with open(pcm_path, 'rb') as source, open(temporary, 'wb') as target:
                    target.write(header)
                    digest.update(header)
                    remaining = data_bytes
                    while remaining:
                        chunk = source.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise ValueError('session recording is shorter than its committed sample count')
                        target.write(chunk)
                        digest.update(chunk)
                        remaining -= len(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                os.chmod(temporary, 0o640)
                os.replace(temporary, destination)
            except (OSError, ValueError) as exc:
                temporary.unlink(missing_ok=True)
                raise DomainError('RECORDING_INTEGRITY_ERROR', '全程录音落盘失败', 409) from exc
            row.sha256 = digest.hexdigest()
            row.size_bytes = destination.stat().st_size
            row.status = 'COMPLETE'
            pcm_path.unlink(missing_ok=True)
        audit_repo.add(db, case_id=row.case_id, action='RECORDING_SEGMENT_SAVED', target_type='RECORDING_SEGMENT', target_id=row.id,
                       detail={'ordinal': row.ordinal, 'status': row.status, 'sha256': row.sha256,
                               'durationMs': row.sample_count * 1000 // row.sample_rate,
                               'gapCount': len(_gaps(row)), 'clientConfirmed': client_confirmed})

    def sweep(self, case_id: str | None = None, *, force: bool = False) -> int:
        """收尾浏览器没来确认的段：超过宽限期的 CLOSING 段，以及询问已不在进行中却还在 RECORDING 的段。"""
        finalized = 0
        with self.session_factory() as db:
            query = select(SessionRecordingSegment.id, SessionRecordingSegment.case_id).where(SessionRecordingSegment.status.in_(OPEN_STATUSES))
            if case_id is not None:
                query = query.where(SessionRecordingSegment.case_id == case_id)
            candidates = list(db.execute(query))
        for segment_id, owner in candidates:
            with self._lock(segment_id), self.session_factory() as db:
                row = db.get(SessionRecordingSegment, segment_id)
                if row is None or row.status not in OPEN_STATUSES:
                    continue
                if row.status == 'RECORDING':
                    session = db.get(InterrogationSession, row.interrogation_session_id)
                    if session is not None and session.status == SessionStatus.RUNNING.value:
                        continue
                    row.status = 'CLOSING'
                    row.ended_at = row.ended_at or utc_now()
                    row.end_reason = row.end_reason or 'SESSION_NOT_RUNNING'
                quiet_since = max(t if t.tzinfo else t.replace(tzinfo=utc_now().tzinfo)
                                  for t in (row.ended_at, row.last_frame_at) if t is not None)
                if not force and utc_now() - quiet_since < CLOSING_GRACE:
                    db.commit()
                    continue
                try:
                    self._write_original(db, row, client_confirmed=False)
                except DomainError:
                    db.rollback()
                    continue
                db.commit()
                finalized += 1
        return finalized
