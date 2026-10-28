from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import json

from app.database.models import ASRCaptureSession, ASRFragment, QAUnit, QuestionRound, ProcessedSpeechFragment
from app.database.session import begin_sqlite_immediate
from app.domain.enums import WorkflowState
from app.domain.errors import DomainError
from app.repositories import cases as case_repo
from app.repositories import sessions as session_repo
from app.services.document_service import DocumentService
from app.services.session_service import SessionService


_UNRESOLVED_QA_STATUSES = {"OPEN", "CLOSED", "ROUTING", "NEEDS_REVIEW"}


class DocumentFinalizationService:
    """Finish one interrogation only after its final speech routing is durable."""

    def __init__(
        self,
        db: Session,
        *,
        capture_service: Any,
        routing_coordinator: Any | None,
        speech_coordinator: Any | None = None,
        drain_timeout: float = 60.0,
    ) -> None:
        self.db = db
        self.capture_service = capture_service
        self.routing_coordinator = routing_coordinator
        self.speech_coordinator = speech_coordinator
        self.drain_timeout = max(1.0, float(drain_timeout))

    def finalize(self, case_id: str, actor_id: str | None = None) -> dict:
        case_id = str(case_id).strip()
        if not case_id:
            raise DomainError("CASE_ID_REQUIRED", "案件编号不能为空", 400)

        from app.services.case_management_service import assert_case_not_void

        case = assert_case_not_void(self.db, case_id)
        if WorkflowState(case.workflow_state) in {
            WorkflowState.FROZEN,
            WorkflowState.SIGNED,
            WorkflowState.REPORT_GENERATED,
        }:
            result = DocumentService(self.db).signing_state(case_id)
            self.db.rollback()
            if result is None:
                raise DomainError("DOCUMENT_SNAPSHOT_NOT_FOUND", "冻结笔录快照不存在", 409)
            return result
        session = session_repo.active_for_case(self.db, case_id) or session_repo.latest_for_case(self.db, case_id)
        session_id = None if session is None else session.id
        self.db.rollback()

        deadline = time.monotonic() + self.drain_timeout
        status = self.capture_service.status(case_id)
        if status.get("active"):
            self.capture_service.stop(case_id)

        if self.speech_coordinator is not None and session_id is not None:
            try:
                self.speech_coordinator.wait_for_session_processing(
                    session_id,
                    timeout=max(0.01, deadline - time.monotonic()),
                )
            except TimeoutError as exc:
                raise DomainError(
                    "SPEECH_PROCESSING_TIMEOUT",
                    "最终转写或说话人识别仍在处理，笔录尚未冻结；请稍后重试",
                    504,
                ) from exc
            except RuntimeError as exc:
                raise DomainError(
                    "SPEECH_PROCESSING_FAILED",
                    "最终转写未完成，笔录尚未冻结；请处理语音服务问题后重试",
                    503,
                ) from exc

        if self.routing_coordinator is not None and session_id is not None:
            try:
                self.routing_coordinator.drain_capture(
                    case_id,
                    session_id,
                    timeout=max(0.01, deadline - time.monotonic()),
                )
            except TimeoutError as exc:
                raise DomainError(
                    "QA_ROUTING_DRAIN_TIMEOUT",
                    "正式问答仍在整理，请稍后再次结束并冻结",
                    504,
                ) from exc
            except RuntimeError as exc:
                raise DomainError(
                    "QA_ROUTING_UNAVAILABLE",
                    "正式问答整理服务不可用，不能冻结笔录",
                    503,
                ) from exc

        begin_sqlite_immediate(self.db)
        try:
            case = case_repo.get(self.db, case_id)
            state = WorkflowState(case.workflow_state)
            active = session_repo.active_for_case(self.db, case_id)
            latest = session_repo.latest_for_case(self.db, case_id)
            target_session = active or latest
            if target_session is None:
                raise DomainError("SESSION_NOT_ACTIVE", "当前没有可结束的审讯", 409)

            captures = list(self.db.scalars(
                select(ASRCaptureSession).where(
                    ASRCaptureSession.interrogation_session_id == target_session.id,
                )
            ))
            incomplete_captures = [row for row in captures if row.recording_status != "COMPLETE"]
            if incomplete_captures:
                raise DomainError(
                    "AUDIO_ARCHIVE_INCOMPLETE",
                    "原始录音尚未完整归档，不能冻结笔录；请先恢复或处理未完成录音",
                    409,
                    data={"capture_session_ids": [row.id for row in incomplete_captures]},
                )

            capture_ids = [row.id for row in captures]
            if capture_ids:
                # 逐题录音挂到某道题回答上的片段已经有了去处，视为已处理。
                attached_ids: set[str] = set()
                attached_ids.update(self.db.scalars(select(ProcessedSpeechFragment.fragment_id).where(
                    ProcessedSpeechFragment.case_id == case_id,
                    ProcessedSpeechFragment.action == "LIVE_QUESTION",
                )))
                for raw in self.db.scalars(
                    select(QuestionRound.answer_fragment_ids_json).where(
                        QuestionRound.case_id == case_id,
                        QuestionRound.status != "DETACHED",
                    )
                ):
                    attached_ids.update(str(value) for value in json.loads(raw or "[]"))
                unresolved_fragments = [
                    row for row in self.db.scalars(
                        select(ASRFragment).where(
                            ASRFragment.capture_session_id.in_(capture_ids),
                            ASRFragment.state.not_in(("DISCARDED", "SUPERSEDED")),
                            (ASRFragment.state != "CONFIRMED") | ASRFragment.confirmed_message_id.is_(None),
                        )
                    )
                    if row.id not in attached_ids
                ]
                if unresolved_fragments:
                    raise DomainError(
                        "ASR_FRAGMENT_REVIEW_REQUIRED",
                        "仍有未处理的转写片段，请确认并正式入库，或明确丢弃后再冻结笔录",
                        409,
                        data={"fragment_ids": [row.id for row in unresolved_fragments]},
                    )

            unresolved = list(self.db.scalars(
                select(QAUnit).where(
                    QAUnit.case_id == case_id,
                    QAUnit.session_id == target_session.id,
                    QAUnit.status.in_(_UNRESOLVED_QA_STATUSES),
                )
            ))
            if unresolved:
                raise DomainError(
                    "FORMAL_RECORD_REVIEW_REQUIRED",
                    "仍有待处理的问答，完成处置后才能冻结笔录",
                    409,
                    data={"qa_unit_ids": [row.id for row in unresolved]},
                )

            if state in {WorkflowState.QUESTIONING, WorkflowState.PAUSED}:
                SessionService(self.db).finish(case_id, actor_id, commit=False)
            elif state != WorkflowState.SUMMARY:
                raise DomainError("DOCUMENT_FINALIZE_NOT_ALLOWED", "当前状态不可结束并冻结笔录", 409)

            result = DocumentService(self.db).freeze(case_id, actor_id, commit=False)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise
