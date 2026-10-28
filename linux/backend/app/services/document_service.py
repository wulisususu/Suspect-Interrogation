import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.session import begin_sqlite_immediate
from app.domain.enums import WorkflowState
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.repositories import cases as case_repo
from app.repositories import documents as document_repo
from app.repositories import facts as fact_repo
from app.repositories import messages as message_repo
from app.repositories import question_rounds as round_repo
from app.repositories import sessions as session_repo
from app.repositories import template_questions as question_repo
from app.services.serializers import (
    case_question_dict,
    fact_dict,
    message_dict,
    question_round_dict,
    signature_dict,
    session_dict,
    snapshot_dict,
)
from app.workflow.state import StateMachine
from app.services.case_management_service import assert_case_not_void


_REQUIRED_SIGNER_ROLES = {"SUSPECT", "OFFICER"}


def _epoch_ms(value: datetime | None) -> int:
    if value is None:
        return 0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


class DocumentService:
    def __init__(self, db: Session):
        self.db = db

    def status(self, case_id: str) -> dict:
        case = case_repo.get(self.db, case_id)
        snapshot = document_repo.latest_snapshot(self.db, case_id)
        signatures = document_repo.list_signatures(self.db, case_id)
        return {
            "caseId": case_id, "workflowState": case.workflow_state, "documentStatus": case.document_status,
            "reportStatus": case.report_status, "snapshot": snapshot_dict(snapshot) if snapshot else None,
            "signatures": [signature_dict(row) for row in signatures],
        }

    def signing_state(self, case_id: str) -> dict | None:
        case_repo.get(self.db, case_id)
        snapshot = document_repo.latest_snapshot(self.db, case_id)
        if snapshot is None:
            return None

        signatures = [
            row for row in document_repo.list_signatures(self.db, case_id)
            if row.snapshot_id == snapshot.id
        ]
        roles = {str(row.signer_role or "").strip().upper() for row in signatures}
        integrity_hash = hashlib.sha256(snapshot.content_json.encode("utf-8")).hexdigest()

        signature_states = []
        for row in signatures:
            signer_role = str(row.signer_role or "").strip().upper()
            signature_payload = json.dumps(
                {
                    "snapshotId": snapshot.id,
                    "signerRole": signer_role,
                    "signerName": row.signer_name,
                    "imageData": row.image_data,
                    "strokesJson": row.strokes_json or "[]",
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            signature_states.append(
                {
                    "signerRole": signer_role,
                    "signerName": row.signer_name,
                    "signedAt": _epoch_ms(row.created_at),
                    "signatureHash": hashlib.sha256(signature_payload.encode("utf-8")).hexdigest(),
                    "imageDataUrl": row.image_data,
                    "strokesJson": row.strokes_json or "[]",
                    "deviceId": "LINUX_LOCAL",
                }
            )

        return {
            "id": snapshot.id,
            "caseId": case_id,
            "version": snapshot.version,
            "documentId": snapshot.id,
            "documentHash": snapshot.content_hash,
            "status": "LOCKED" if _REQUIRED_SIGNER_ROLES.issubset(roles) else "FROZEN",
            "createdAt": _epoch_ms(snapshot.created_at),
            "integrityValid": integrity_hash == snapshot.content_hash,
            "signatures": signature_states,
        }

    def _transcript(self, case_id: str) -> dict:
        case_questions = question_repo.list_case(self.db, case_id)
        if not case_questions:
            return {
                "source": "LEGACY_MESSAGES",
                "messages": [message_dict(row) for row in message_repo.list_for_case(self.db, case_id)],
            }

        rounds = round_repo.list_for_case(self.db, case_id)
        questions_by_id = {row.id: row for row in case_questions}
        rounds_by_question: dict[str, list] = {row.id: [] for row in case_questions}
        for round_row in rounds:
            if round_row.case_question_id in rounds_by_question:
                rounds_by_question[round_row.case_question_id].append(round_row)

        def entry_for(question, round_row) -> dict:
            serialized = question_round_dict(round_row)
            return {
                "roundId": round_row.id,
                "questionId": round_row.case_question_id,
                "questionText": question.text,
                "sectionType": question.section_type or "BODY",
                "templateKey": question.template_key,
                "templateItemKey": question.template_item_key,
                "caseQuestionId": round_row.case_question_id,
                "roundNo": round_row.round_no,
                "formalQuestionText": question.text,
                "actualQuestionText": round_row.actual_question_text,
                "answerText": round_row.answer_text,
                "officerFragmentId": round_row.officer_fragment_id,
                "answerFragmentIds": serialized["answerFragmentIds"],
                "status": round_row.status,
                "startedAt": serialized["startedAt"],
                "endedAt": serialized["endedAt"],
            }

        # Versioned formal records freeze in paper/editor order. Pre-existing
        # template workspaces have no template_key and retain their historical
        # real-time chronology contract for backward compatibility.
        is_formal_record = any(row.template_key for row in case_questions)
        entries = []
        if is_formal_record:
            for question in case_questions:
                for round_row in rounds_by_question.get(question.id, []):
                    entries.append(entry_for(question, round_row))
        else:
            for round_row in rounds:
                question = questions_by_id.get(round_row.case_question_id)
                if question is not None:
                    entries.append(entry_for(question, round_row))

        return {
            "source": "TEMPLATE_ROUNDS",
            "templateKey": next((row.template_key for row in case_questions if row.template_key), None),
            "questions": [
                case_question_dict(row, rounds=rounds_by_question[row.id])
                for row in case_questions
            ],
            "entries": entries,
        }

    def freeze(self, case_id: str, actor_id: str | None = None, *, commit: bool = True) -> dict:
        begin_sqlite_immediate(self.db)
        case = assert_case_not_void(self.db, case_id)
        if WorkflowState(case.workflow_state) != WorkflowState.SUMMARY:
            raise DomainError("DOCUMENT_FREEZE_NOT_ALLOWED", "仅复核阶段可以冻结笔录", 409)
        from app.services.case_service import CaseService

        latest_session = session_repo.latest_for_case(self.db, case_id)
        payload = {
            "case": CaseService(self.db).get(case_id),
            "session": session_dict(latest_session, case),
            "transcript": self._transcript(case_id),
            "facts": [fact_dict(row) for row in fact_repo.list_for_case(self.db, case_id)],
        }
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        snapshot = document_repo.create_snapshot(
            self.db,
            case_id=case_id,
            session_id=latest_session.id if latest_session else None,
            content_json=content,
            content_hash=digest,
        )
        case.workflow_state = StateMachine.transition(WorkflowState.SUMMARY, WorkflowState.FROZEN).value
        case.document_status = "FROZEN"
        audit_repo.add(
            self.db,
            case_id=case_id,
            actor_id=actor_id,
            action="DOCUMENT_FREEZE",
            target_type="DOCUMENT",
            target_id=snapshot.id,
            after={"version": snapshot.version, "content_hash": snapshot.content_hash},
        )
        if commit:
            self.db.commit()
        state = self.signing_state(case_id)
        assert state is not None
        return state

    def sign(
        self,
        case_id: str,
        *,
        signer_role: str,
        signer_name: str,
        image_data: str,
        strokes_json: str = "[]",
        actor_id: str | None = None,
        commit: bool = True,
    ) -> dict:
        begin_sqlite_immediate(self.db)
        case = assert_case_not_void(self.db, case_id)
        workflow_state = WorkflowState(case.workflow_state)
        if workflow_state not in {WorkflowState.FROZEN, WorkflowState.SIGNED}:
            raise DomainError("SIGNATURE_NOT_ALLOWED", "笔录冻结后才能签名", 409)

        role = str(signer_role or "").strip().upper()
        if role not in _REQUIRED_SIGNER_ROLES:
            raise DomainError("INVALID_SIGNER_ROLE", "签名角色仅支持被讯问人或民警", 400)
        name = str(signer_name or "").strip()
        from app.auth.context import current_actor

        actor = current_actor()
        if role == "OFFICER" and actor is not None:
            from app.database.officer_models import CaseOfficerBinding

            binding = self.db.get(CaseOfficerBinding, case_id)
            if binding is None or actor.badge_number not in {binding.interrogator_badge_number, binding.recorder_badge_number}:
                raise DomainError("OFFICER_SIGNATURE_FORBIDDEN", "签名民警必须是本案询问人或记录员", 403)
            name = actor.name
        if not name:
            raise DomainError("SIGNER_NAME_REQUIRED", "签名人姓名不能为空", 400)

        snapshot = document_repo.latest_snapshot(self.db, case_id)
        if snapshot is None:
            raise DomainError("DOCUMENT_NOT_FROZEN", "未找到冻结笔录快照", 409)

        snapshot_signatures = [
            row for row in document_repo.list_signatures(self.db, case_id)
            if row.snapshot_id == snapshot.id
        ]
        if any(str(row.signer_role or "").strip().upper() == role for row in snapshot_signatures):
            raise DomainError("SIGNATURE_ALREADY_EXISTS", "该签名角色已完成签名", 409)

        from app.services.officer_service import validate_signature_image

        image_data = validate_signature_image(image_data)
        session = session_repo.latest_for_case(self.db, case_id)
        try:
            signature = document_repo.create_signature(
                self.db,
                case_id=case_id,
                session_id=session.id if session else None,
                snapshot_id=snapshot.id,
                signer_role=role,
                signer_name=name,
                image_data=image_data,
                strokes_json=strokes_json,
            )
        except IntegrityError as exc:
            self.db.rollback()
            if "signature_records.snapshot_id, signature_records.signer_role" in str(exc.orig):
                raise DomainError("SIGNATURE_ALREADY_EXISTS", "该签名角色已完成签名", 409) from exc
            raise

        signed_roles = {
            str(row.signer_role or "").strip().upper()
            for row in snapshot_signatures
        } | {role}
        if _REQUIRED_SIGNER_ROLES.issubset(signed_roles):
            if workflow_state == WorkflowState.FROZEN:
                case.workflow_state = StateMachine.transition(WorkflowState.FROZEN, WorkflowState.SIGNED).value
            case.document_status = "SIGNED"
        else:
            case.document_status = "FROZEN"

        audit_repo.add(
            self.db,
            case_id=case_id,
            actor_id=actor_id,
            action="SIGNATURE_SAVE",
            target_type="SIGNATURE",
            target_id=signature.id,
            after={"signer_role": role, "signer_name": name, "snapshot_id": snapshot.id},
        )
        if commit:
            self.db.commit()
        state = self.signing_state(case_id)
        assert state is not None
        return state

    def list_signatures(self, case_id: str) -> list[dict]:
        case_repo.get(self.db, case_id)
        return [signature_dict(row) for row in document_repo.list_signatures(self.db, case_id)]

    def mark_report_generated(self, case_id: str, actor_id: str | None = None) -> dict:
        case = assert_case_not_void(self.db, case_id)
        if WorkflowState(case.workflow_state) != WorkflowState.SIGNED:
            raise DomainError("REPORT_NOT_ALLOWED", "完成签名后才能生成报告", 409)
        case.workflow_state = StateMachine.transition(WorkflowState.SIGNED, WorkflowState.REPORT_GENERATED).value
        case.report_status = "GENERATED"
        audit_repo.add(
            self.db,
            case_id=case_id,
            actor_id=actor_id,
            action="REPORT_GENERATED",
            target_type="CASE",
            target_id=case_id,
            after={"reportStatus": "GENERATED"},
        )
        self.db.commit()
        return self.status(case_id)
