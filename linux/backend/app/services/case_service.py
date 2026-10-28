from __future__ import annotations

from sqlalchemy.orm import Session

from app.database.session import begin_sqlite_immediate
from app.domain.enums import InterrogationStage, WorkflowState
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.repositories import cases as case_repo
from app.repositories import devices as device_repo
from app.repositories import facts as fact_repo
from app.repositories import persons as person_repo
from app.services.formal_record_policy import assert_formal_record_mutable
from app.services.serializers import audit_dict, case_dict, fact_dict, person_dict
from app.workflow.state import StateMachine


class CaseService:
    def __init__(self, db: Session):
        self.db = db

    def _bind_officers(self, row, payload: dict) -> None:
        from app.services.recording_service import RecordingService
        from app.services.officer_service import OfficerService

        if "fullRecordingEnabled" in payload:
            RecordingService(self.db, None).set_options(row.id, payload["fullRecordingEnabled"])
        if not {"interrogatorBadgeNumber", "recorderBadgeNumber"}.intersection(payload):
            return
        service = OfficerService(self.db)
        existing = service.case_officers(row.id)
        service.bind_case_officers(
            row.id,
            interrogator_badge_number=payload.get("interrogatorBadgeNumber", (existing["interrogator"] or {}).get("badgeNumber")),
            recorder_badge_number=payload.get("recorderBadgeNumber", (existing["recorder"] or {}).get("badgeNumber")),
        )

    def _case_data(self, row) -> dict:
        from app.services.case_management_service import case_management_fields
        from app.services.officer_service import OfficerService
        from app.services.recording_service import RecordingService

        data = case_dict(row)
        data.update(case_management_fields(self.db, row.id))
        data.update(OfficerService(self.db).case_officers(row.id))
        data.update(RecordingService(self.db, None).options(row.id))
        persons = person_repo.list_for_case(self.db, row.id)
        if not persons:
            return data
        identity = persons[-1]
        person = person_dict(identity)
        data.update({
            "suspectName": person["name"] or data["suspectName"],
            "gender": person["gender"] or data["gender"],
            "idNumber": person["idNumber"],
            "nation": person["nation"],
            "birthDate": person["birthDate"],
            "address": person["address"],
            "identitySource": person["source"],
            "identityCapturedAt": identity.created_at.isoformat() if identity.created_at else None,
        })
        return data

    def create(self, payload: dict) -> dict:
        from app.auth.context import current_actor_id

        if current_actor_id():
            payload = {**payload, "operator_id": current_actor_id()}
        row = case_repo.create(self.db, payload)
        fact_repo.seed_defaults(self.db, row.id)
        self._bind_officers(row, payload)
        data = self._case_data(row)
        audit_repo.add(self.db, case_id=row.id, actor_id=row.operator_id, action="CASE_CREATE", target_type="CASE", target_id=row.id, after=data)
        self.db.commit()
        return data

    def intake(self, payload: dict, identity: dict, actor_id: str | None = None) -> dict:
        from app.auth.context import current_actor_id

        if current_actor_id():
            payload = {**payload, "operator_id": current_actor_id()}
        clean_identity = dict(identity)
        clean_identity["name"] = str(clean_identity.get("name") or "").strip()
        clean_identity["idNumber"] = str(clean_identity.get("idNumber") or "").strip()
        clean_identity["source"] = str(clean_identity.get("source") or "MANUAL").strip() or "MANUAL"
        if not clean_identity["name"]:
            raise DomainError("IDENTITY_NAME_REQUIRED", "身份确认必须包含姓名", 400)

        try:
            begin_sqlite_immediate(self.db)
            row = case_repo.create(self.db, payload)
            fact_repo.seed_defaults(self.db, row.id)
            self._bind_officers(row, payload)
            audit_repo.add(
                self.db,
                case_id=row.id,
                actor_id=actor_id or row.operator_id,
                action="CASE_CREATE",
                target_type="CASE",
                target_id=row.id,
                after=case_dict(row),
            )
            person = person_repo.create(self.db, case_id=row.id, data=clean_identity)
            row.workflow_state = StateMachine.transition(
                WorkflowState.IDENTITY_REQUIRED, WorkflowState.IDENTITY_READY
            ).value
            device_repo.add_event(
                self.db,
                case_id=row.id,
                session_id=None,
                device="identity",
                event="IDENTITY_CONFIRMED",
                payload={"person_id": person.id, "source": person.source},
            )
            audit_repo.add(
                self.db,
                case_id=row.id,
                actor_id=actor_id or row.operator_id,
                action="IDENTITY_CONFIRM",
                target_type="PERSON",
                target_id=person.id,
                after={"name": person.name, "id_number": person.id_number, "source": person.source},
            )
            data = self._case_data(row)
            self.db.commit()
            return data
        except Exception:
            self.db.rollback()
            raise

    def get(self, case_id: str) -> dict:
        return self._case_data(case_repo.get(self.db, case_id))

    def list(self, limit: int = 100, query: str | None = None) -> list[dict]:
        return [self._case_data(row) for row in case_repo.list_all(self.db, limit, query)]

    def update(self, case_id: str, patch: dict, actor_id: str | None = None) -> dict:
        from app.auth.context import current_actor_id

        if current_actor_id():
            patch = {key: value for key, value in patch.items() if key not in {"operator_id", "operatorId"}}
        row = assert_formal_record_mutable(self.db, case_id)
        before = self._case_data(row)
        if "stage" in patch:
            try:
                row.stage = InterrogationStage(str(patch["stage"])).value
            except ValueError as exc:
                raise DomainError("INVALID_STAGE", "无效审讯阶段", 400) from exc
        case_repo.update_fields(self.db, row, patch)
        self._bind_officers(row, patch)
        identity_fields = {
            "suspectName": "name",
            "gender": "gender",
            "idNumber": "id_number",
            "nation": "nation",
            "birthDate": "birth_date",
            "address": "address",
        }
        if any(key in patch for key in identity_fields):
            persons = person_repo.list_for_case(self.db, case_id)
            if persons:
                identity = persons[-1]
                for key, attribute in identity_fields.items():
                    if key in patch:
                        setattr(identity, attribute, str(patch[key] or ""))
            else:
                person_repo.create(
                    self.db,
                    case_id=case_id,
                    data={
                        "name": patch.get("suspectName", row.suspect_name),
                        "gender": patch.get("gender", row.gender),
                        "idNumber": patch.get("idNumber", ""),
                        "nation": patch.get("nation", ""),
                        "birthDate": patch.get("birthDate", ""),
                        "address": patch.get("address", ""),
                        "source": "MANUAL",
                    },
                )
            self.db.flush()
        after = self._case_data(row)
        audit_repo.add(self.db, case_id=case_id, actor_id=actor_id, action="CASE_UPDATE", target_type="CASE", target_id=case_id, before=before, after=after, detail=patch)
        self.db.commit()
        return after

    def list_facts(self, case_id: str) -> list[dict]:
        case_repo.get(self.db, case_id)
        return [fact_dict(row) for row in fact_repo.list_for_case(self.db, case_id)]

    def update_fact(self, case_id: str, fact_key: str, patch: dict, actor_id: str | None = None) -> dict:
        assert_formal_record_mutable(self.db, case_id)
        before_item = next((x for x in self.list_facts(case_id) if x["key"] == fact_key), None)
        row = fact_repo.update(self.db, case_id, fact_key, patch)
        after_item = fact_dict(row)
        audit_repo.add(self.db, case_id=case_id, actor_id=actor_id, action="FACT_UPDATE", target_type="FACT", target_id=fact_key, before=before_item or {}, after=after_item)
        self.db.commit()
        return after_item

    def list_audit(self, case_id: str, limit: int = 200) -> list[dict]:
        case_repo.get(self.db, case_id)
        return [audit_dict(row) for row in audit_repo.list_for_case(self.db, case_id, limit)]
