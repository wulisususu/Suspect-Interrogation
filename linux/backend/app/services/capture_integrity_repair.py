"""Repair captures that were marked INCOMPLETE while their archive stayed intact.

Two defects used to persist healthy recordings as INCOMPLETE:

* the client closed the audio socket before posting the stop request, so an
  ordinary stop looked like a dropped connection;
* a duplicate window could open a second socket for the same capture, replay
  sequences the archive already held, and get the *real* stream closed as a
  discontinuity.

Both are fixed at the source, but the captures they already produced stay
INCOMPLETE and keep blocking record finalization. This module re-finalizes them
through the same durability checks a live capture goes through: it never forces a
status, it re-finalizes and lets the archive reject anything that is not
internally consistent (missing segment, gap, sample-count mismatch, sha256
mismatch). Repairs are audited per capture.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import ASRCaptureSession, ASRAudioSegment
from app.repositories import audio_archive as archive_repo
from app.repositories import audit as audit_repo
from app.services.durable_audio_archive import DurableAudioArchive

logger = logging.getLogger("suspect.capture_repair")

REPAIR_ACTION = "CAPTURE_INTEGRITY_REPAIR"


@dataclass
class CaptureRepairResult:
    capture_id: str
    case_id: str
    target_question_id: str | None
    recording_status: str
    asr_status: str
    samples: int
    segment_count: int
    repairable: bool
    repaired: bool
    reason: str

    def payload(self) -> dict:
        return {
            "captureId": self.capture_id,
            "caseId": self.case_id,
            "targetQuestionId": self.target_question_id,
            "recordingStatus": self.recording_status,
            "asrStatus": self.asr_status,
            "samples": self.samples,
            "segments": self.segment_count,
            "repairable": self.repairable,
            "repaired": self.repaired,
            "reason": self.reason,
        }


def _preflight(capture: ASRCaptureSession, segments: list[ASRAudioSegment]) -> str | None:
    """Cheap structural check, run before touching anything.

    The authoritative check (per-segment sha256 and byte count against the file on
    disk) only happens inside ``finalize_capture``; this pass exists so a dry run
    can report what would happen without writing.
    """
    if capture.recording_status != "INCOMPLETE":
        return f"录音状态是 {capture.recording_status}，不需要修复"
    if not segments:
        return "没有可校验的音频分段"
    cursor = 0
    for segment in segments:
        if segment.status == "GAP":
            return f"分段 {segment.id} 被标记为缺口（真实丢音），需重录"
        if segment.start_sample != cursor:
            return f"分段 {segment.id} 起始采样 {segment.start_sample}，期望 {cursor}（存在空洞）"
        if segment.status not in {"ACTIVE", "FINALIZED"}:
            return f"分段 {segment.id} 状态异常：{segment.status}"
        if segment.committed_samples <= 0:
            return f"分段 {segment.id} 没有采样数据"
        cursor += segment.committed_samples
    if cursor != capture.audio_sample_count:
        return f"分段合计 {cursor} 个采样，与采集记录 {capture.audio_sample_count} 不一致"
    return None


class CaptureIntegrityRepair:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        archive: DurableAudioArchive,
    ) -> None:
        self.session_factory = session_factory
        self.archive = archive

    def _targets(self, case_id: str | None, capture_id: str | None) -> list[ASRCaptureSession]:
        with self.session_factory() as db:
            statement = select(ASRCaptureSession).where(ASRCaptureSession.recording_status == "INCOMPLETE")
            if capture_id is not None:
                statement = statement.where(ASRCaptureSession.id == capture_id)
            if case_id is not None:
                statement = statement.where(ASRCaptureSession.case_id == case_id)
            return list(db.scalars(statement.order_by(ASRCaptureSession.started_at, ASRCaptureSession.id)))

    def run(
        self,
        *,
        dry_run: bool = True,
        actor_id: str | None = None,
        case_id: str | None = None,
        capture_id: str | None = None,
    ) -> dict:
        results: list[CaptureRepairResult] = []
        for capture in self._targets(case_id, capture_id):
            segments = self.archive.list_segments(capture.id)
            reason = _preflight(capture, segments)
            repairable = reason is None
            repaired = False
            if repairable and not dry_run:
                try:
                    self.archive.finalize_capture(capture.id, allow_incomplete_recovery=True)
                    repaired = True
                    reason = "档案完整，已重新收尾并标记为 COMPLETE"
                except Exception as exc:  # noqa: BLE001 - the reason is reported, not swallowed
                    repairable = False
                    reason = str(exc)
            elif repairable:
                reason = "结构自洽，可在 apply 时重新收尾（届时校验每段 sha256）"

            result = CaptureRepairResult(
                capture_id=capture.id,
                case_id=capture.case_id,
                target_question_id=capture.target_question_id,
                recording_status=capture.recording_status,
                asr_status=capture.asr_status,
                samples=int(capture.audio_sample_count or 0),
                segment_count=len(segments),
                repairable=repairable,
                repaired=repaired,
                reason=reason or "",
            )
            results.append(result)
            if not dry_run:
                self._audit(result, actor_id=actor_id)

        return {
            "dryRun": dry_run,
            "scanned": len(results),
            "repairable": sum(1 for item in results if item.repairable),
            "repaired": sum(1 for item in results if item.repaired),
            "blocked": sum(1 for item in results if not item.repairable),
            "captures": [item.payload() for item in results],
        }

    def _audit(self, result: CaptureRepairResult, *, actor_id: str | None) -> None:
        with self.session_factory() as db:
            audit_repo.add(
                db,
                case_id=result.case_id,
                action=REPAIR_ACTION,
                target_type="ASR_CAPTURE_SESSION",
                target_id=result.capture_id,
                actor_id=actor_id,
                before={"recordingStatus": result.recording_status, "samples": result.samples},
                after={
                    "recordingStatus": "COMPLETE" if result.repaired else result.recording_status,
                    "segments": result.segment_count,
                },
                detail={
                    "repaired": result.repaired,
                    "reason": result.reason,
                    "asrStatus": result.asr_status,
                    "targetQuestionId": result.target_question_id,
                    "source": "capture_integrity_repair",
                },
                result="SUCCESS" if result.repaired else "REJECTED",
            )
            db.commit()
