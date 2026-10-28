from sqlalchemy.orm import Session

from app.database.base import utc_now
from app.database.session import begin_sqlite_immediate
from app.domain.enums import InterrogationStage, SessionStatus, WorkflowState
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.repositories import cases as case_repo
from app.repositories import sessions as session_repo
from app.repositories import voiceprints as voiceprint_repo
from app.services.serializers import session_dict
from app.workflow.state import StateMachine


class SessionService:
    def __init__(self, db: Session):
        self.db = db

    def get_state(self, case_id: str) -> dict:
        case = case_repo.get(self.db, case_id)
        return session_dict(session_repo.active_for_case(self.db, case_id) or session_repo.latest_for_case(self.db, case_id), case)

    def _advance(self, case, target: WorkflowState) -> None:
        case.workflow_state = StateMachine.transition(WorkflowState(case.workflow_state), target).value

    def start(
        self,
        case_id: str,
        actor_id: str | None = None,
        allow_identity_bypass: bool = False,
        *,
        voiceprint_service=None,
        interrogator_officer_id: str | None = None,
        recorder_officer_id: str | None = None,
    ) -> dict:
        begin_sqlite_immediate(self.db)
        try:
            case = case_repo.get(self.db, case_id)
            active = session_repo.active_for_case(self.db, case_id)
            if active:
                return session_dict(active, case)
            state = WorkflowState(case.workflow_state)
            if state == WorkflowState.IDENTITY_REQUIRED:
                if not allow_identity_bypass:
                    raise DomainError("IDENTITY_REQUIRED", "请先完成身份读取再开始审讯", 409)
                audit_repo.add(self.db, case_id=case_id, actor_id=actor_id, action="IDENTITY_BYPASS_LEGACY_COMPAT", target_type="CASE", target_id=case_id,
                               detail={"reason": "legacy browser compatibility route"})
                self._advance(case, WorkflowState.IDENTITY_READY)
                state = WorkflowState.IDENTITY_READY
            if state == WorkflowState.IDENTITY_READY:
                self._advance(case, WorkflowState.CASE_CREATED)
                state = WorkflowState.CASE_CREATED
            if state != WorkflowState.CASE_CREATED:
                raise DomainError("SESSION_START_NOT_ALLOWED", f"当前状态不可开始审讯：{state.value}", 409)
            # 声纹已从办理流程中移除：开始审讯不再要求嫌疑人声纹。
            # 仍保有声纹的历史案件照旧绑定民警角色，其余案件跳过绑定。
            bind_voiceprint_roles = voiceprint_service is not None and voiceprint_repo.get_suspect(
                self.db, case_id, model_key=voiceprint_service.authoritative_speaker_backend
            ) is not None
            if bind_voiceprint_roles:
                voiceprint_service.validate_role_binding(
                    case_id, interrogator_officer_id, recorder_officer_id
                )
            self._advance(case, WorkflowState.QUESTIONING)
            row = session_repo.create(self.db, case_id, case.stage)
            if bind_voiceprint_roles:
                voiceprint_service.bind_roles(
                    case_id,
                    interrogator_officer_id,
                    recorder_officer_id,
                    actor_id=actor_id,
                    commit=False,
                )
            audit_repo.add(self.db, case_id=case_id, actor_id=actor_id, action="SESSION_START", target_type="SESSION", target_id=row.id)
            self.db.commit()
            return session_dict(row, case)
        except Exception:
            self.db.rollback()
            raise

    def pause(self, case_id: str, actor_id: str | None = None) -> dict:
        case = case_repo.get(self.db, case_id)
        row = session_repo.active_for_case(self.db, case_id)
        if row is None or row.status != SessionStatus.RUNNING.value:
            raise DomainError("SESSION_NOT_RUNNING", "当前没有正在进行的审讯", 409)
        self._advance(case, WorkflowState.PAUSED)
        row.status = SessionStatus.PAUSED.value
        row.paused_at = utc_now()
        audit_repo.add(self.db, case_id=case_id, actor_id=actor_id, action="SESSION_PAUSE", target_type="SESSION", target_id=row.id)
        self.db.commit()
        return session_dict(row, case)

    def resume(self, case_id: str, actor_id: str | None = None) -> dict:
        case = case_repo.get(self.db, case_id)
        row = session_repo.active_for_case(self.db, case_id)
        if row is None or row.status != SessionStatus.PAUSED.value:
            raise DomainError("SESSION_NOT_PAUSED", "当前审讯不是暂停状态", 409)
        self._advance(case, WorkflowState.QUESTIONING)
        row.status = SessionStatus.RUNNING.value
        row.paused_at = None
        audit_repo.add(self.db, case_id=case_id, actor_id=actor_id, action="SESSION_RESUME", target_type="SESSION", target_id=row.id)
        self.db.commit()
        return session_dict(row, case)

    def finish(self, case_id: str, actor_id: str | None = None, *, commit: bool = True) -> dict:
        case = case_repo.get(self.db, case_id)
        row = session_repo.active_for_case(self.db, case_id)
        if row is None:
            raise DomainError("SESSION_NOT_ACTIVE", "当前没有可结束的审讯", 409)
        current = WorkflowState(case.workflow_state)
        if current not in {WorkflowState.QUESTIONING, WorkflowState.PAUSED}:
            raise DomainError("SESSION_FINISH_NOT_ALLOWED", "当前状态不可结束审讯", 409)
        self._advance(case, WorkflowState.SUMMARY)
        row.status = SessionStatus.COMPLETED.value
        row.ended_at = utc_now()
        row.paused_at = None
        audit_repo.add(self.db, case_id=case_id, actor_id=actor_id, action="SESSION_FINISH", target_type="SESSION", target_id=row.id)
        if commit:
            self.db.commit()
        return session_dict(row, case)

    def change_stage(self, case_id: str, stage: str, actor_id: str | None = None) -> dict:
        case = case_repo.get(self.db, case_id)
        row = session_repo.active_for_case(self.db, case_id)
        if row is None:
            raise DomainError("SESSION_NOT_ACTIVE", "请先开始审讯再切换阶段", 409)
        try:
            next_stage = InterrogationStage(stage).value
        except ValueError as exc:
            raise DomainError("INVALID_STAGE", "无效审讯阶段", 400) from exc
        before = row.stage
        row.stage = next_stage
        case.stage = next_stage
        audit_repo.add(self.db, case_id=case_id, actor_id=actor_id, action="SESSION_CHANGE_STAGE", target_type="SESSION", target_id=row.id,
                       before={"stage": before}, after={"stage": next_stage})
        self.db.commit()
        return session_dict(row, case)
