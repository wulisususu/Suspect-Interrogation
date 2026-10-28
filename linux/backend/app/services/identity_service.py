from sqlalchemy.orm import Session

from app.domain.enums import WorkflowState
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.repositories import cases as case_repo
from app.repositories import devices as device_repo
from app.repositories import persons as person_repo
from app.services.serializers import person_dict
from app.workflow.state import StateMachine


class IdentityService:
    def __init__(self, db: Session, hardware_gateway):
        self.db = db
        self.hardware = hardware_gateway

    def status(self) -> dict:
        return self.hardware.status()["devices"]["identity"] | {"device": "idcard_reader"}

    @staticmethod
    def _response(row, data: dict) -> dict:
        result = person_dict(row)
        for key in ("portrait", "issuer", "valid_from", "valid_to", "device_id", "read_at"):
            value = data.get(key)
            if value not in (None, ""):
                result[key] = value
        return result

    def _persist(
        self,
        *,
        case_id: str,
        actor_id: str | None,
        data: dict,
        device_event: str,
        audit_action: str,
    ) -> dict:
        from app.services.formal_record_policy import assert_formal_record_mutable

        case = assert_formal_record_mutable(self.db, case_id)
        current = WorkflowState(case.workflow_state)
        if current == WorkflowState.IDENTITY_REQUIRED:
            next_state = StateMachine.transition(current, WorkflowState.IDENTITY_READY)
        elif current in {
            WorkflowState.IDENTITY_READY,
            WorkflowState.CASE_CREATED,
            WorkflowState.QUESTIONING,
            WorkflowState.PAUSED,
        }:
            next_state = current
        else:
            raise DomainError("IDENTITY_NOT_ALLOWED", f"当前状态不允许读取身份：{current.value}", 409)

        row = person_repo.create(self.db, case_id=case_id, data=data)
        case.workflow_state = next_state.value
        device_repo.add_event(
            self.db,
            case_id=case_id,
            session_id=None,
            device="identity",
            event=device_event,
            payload={"person_id": row.id, "source": row.source},
        )
        audit_repo.add(
            self.db,
            case_id=case_id,
            actor_id=actor_id,
            action=audit_action,
            target_type="PERSON",
            target_id=row.id,
            after={"name": row.name, "id_number": row.id_number, "source": row.source},
        )
        self.db.commit()
        return self._response(row, data)

    def read(self, case_id: str | None = None, actor_id: str | None = None) -> dict:
        if case_id:
            from app.services.formal_record_policy import assert_formal_record_mutable

            assert_formal_record_mutable(self.db, case_id)
        data = self.hardware.read_identity()
        # The intake UI reads the physical card before a case exists. Treat that
        # as a preview only: do not create an orphan Person. Return the legacy
        # preview envelope expected by the existing Vue intake component.
        if case_id is None:
            preview = dict(data)
            if not preview.get("sex") and preview.get("gender") is not None:
                preview["sex"] = preview.get("gender")
            return {"identity": preview}
        return self._persist(
            case_id=case_id,
            actor_id=actor_id,
            data=data,
            device_event="IDENTITY_SUCCESS",
            audit_action="IDENTITY_READ",
        )

    def confirm(self, case_id: str, data: dict, actor_id: str | None = None) -> dict:
        clean = dict(data)
        clean["name"] = str(clean.get("name") or "").strip()
        clean["id_number"] = str(clean.get("id_number") or "").strip()
        clean["source"] = str(clean.get("source") or "MANUAL").strip() or "MANUAL"
        if not clean["name"]:
            raise DomainError("IDENTITY_NAME_REQUIRED", "身份确认必须包含姓名", 400)
        return self._persist(
            case_id=case_id,
            actor_id=actor_id,
            data=clean,
            device_event="IDENTITY_CONFIRMED",
            audit_action="IDENTITY_CONFIRM",
        )
