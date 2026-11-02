from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_hardware
from app.api.responses import envelope
from app.api.schemas import (
    LegacyActorRequest, LegacyCaseCreateRequest, LegacyCaseUpdateRequest, LegacyDeviceActionRequest,
    LegacyFactUpdateRequest, LegacyMessageMarkRequest, LegacyMessageUpdateRequest, LegacyStageRequest,
    LegacyWorkMessageRequest,
)
from app.services.case_service import CaseService
from app.services.device_service import DeviceService
from app.services.message_service import MessageService
from app.services.session_service import SessionService

router = APIRouter(tags=["legacy-compat"])


@router.get("/api/health")
def legacy_health():
    return envelope({"service": "suspect-interrogation-backend", "status": "ready"})


@router.post("/api/cases/create")
def legacy_create_case(body: LegacyCaseCreateRequest, db: Session = Depends(get_db)):
    return envelope(CaseService(db).create(body.model_dump(exclude_none=True)), "案件已创建")


@router.get("/api/cases")
def legacy_list_cases(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    return envelope(CaseService(db).list(limit))


@router.get("/api/cases/{case_id}")
def legacy_get_case(case_id: str, db: Session = Depends(get_db)):
    return envelope(CaseService(db).get(case_id))


@router.put("/api/cases/{case_id}")
def legacy_update_case(case_id: str, body: LegacyCaseUpdateRequest, db: Session = Depends(get_db)):
    patch = body.model_dump(exclude_none=True)
    actor_id = patch.pop("actor_id", None)
    return envelope(CaseService(db).update(case_id, patch, actor_id), "案件信息已保存")


@router.get("/work/case/{case_id}")
def legacy_work_case(case_id: str, db: Session = Depends(get_db)):
    return envelope(CaseService(db).get(case_id))


@router.get("/work/case/{case_id}/message")
def legacy_work_messages(case_id: str, limit: int = 1000, db: Session = Depends(get_db)):
    return envelope(MessageService(db).list(case_id, limit))


@router.post("/work/case/{case_id}/message")
def legacy_add_message(case_id: str, body: LegacyWorkMessageRequest, db: Session = Depends(get_db)):
    if body.profile:
        text, speaker = body.profile.text, body.profile.from_
    else:
        text, speaker = body.text or "", body.from_ or ""
    return envelope(MessageService(db).create(case_id, text=text, speaker=speaker), "问答已保存")


@router.get("/api/cases/{case_id}/messages")
def legacy_list_messages(case_id: str, limit: int = 1000, db: Session = Depends(get_db)):
    return envelope(MessageService(db).list(case_id, limit))


@router.put("/api/cases/{case_id}/messages/{message_id}")
def legacy_revise_message(case_id: str, message_id: str, body: LegacyMessageUpdateRequest, db: Session = Depends(get_db)):
    return envelope(MessageService(db).revise(case_id, message_id, text=body.text, reason=body.reason, actor_id=body.actor_id), "笔录已修订并生成版本")


@router.post("/api/cases/{case_id}/messages/{message_id}/mark")
def legacy_mark_message(case_id: str, message_id: str, body: LegacyMessageMarkRequest, db: Session = Depends(get_db)):
    return envelope(MessageService(db).mark(case_id, message_id, body.mark, body.actor_id), "标记已保存")


@router.get("/api/cases/{case_id}/messages/{message_id}/revisions")
def legacy_message_revisions(case_id: str, message_id: str, db: Session = Depends(get_db)):
    return envelope(MessageService(db).revisions(case_id, message_id))


@router.get("/api/cases/{case_id}/revisions")
def legacy_case_revisions(case_id: str, db: Session = Depends(get_db)):
    return envelope(MessageService(db).revisions(case_id))


@router.get("/api/cases/{case_id}/facts")
def legacy_facts(case_id: str, db: Session = Depends(get_db)):
    return envelope(CaseService(db).list_facts(case_id))


@router.put("/api/cases/{case_id}/facts/{fact_key}")
def legacy_update_fact(case_id: str, fact_key: str, body: LegacyFactUpdateRequest, db: Session = Depends(get_db)):
    patch = body.model_dump(exclude_none=True)
    actor_id = patch.pop("actor_id", None)
    return envelope(CaseService(db).update_fact(case_id, fact_key, patch, actor_id), "事实项已更新")


@router.get("/api/cases/{case_id}/session")
def legacy_get_session(case_id: str, db: Session = Depends(get_db)):
    return envelope(SessionService(db).get_state(case_id))


@router.post("/api/cases/{case_id}/session/start")
def legacy_start(case_id: str, body: LegacyActorRequest | None = None, db: Session = Depends(get_db)):
    return envelope(SessionService(db).start(case_id, body.actor_id if body else None), "审讯已开始")


@router.post("/api/cases/{case_id}/session/pause")
def legacy_pause(case_id: str, body: LegacyActorRequest | None = None, db: Session = Depends(get_db)):
    return envelope(SessionService(db).pause(case_id, body.actor_id if body else None), "审讯已暂停")


@router.post("/api/cases/{case_id}/session/resume")
def legacy_resume(case_id: str, body: LegacyActorRequest | None = None, db: Session = Depends(get_db)):
    return envelope(SessionService(db).resume(case_id, body.actor_id if body else None), "审讯已恢复")


@router.post("/api/cases/{case_id}/session/finish")
def legacy_finish(case_id: str, body: LegacyActorRequest | None = None, db: Session = Depends(get_db)):
    return envelope(SessionService(db).finish(case_id, body.actor_id if body else None), "审讯已结束，进入复核")


@router.post("/api/cases/{case_id}/session/stage")
def legacy_stage(case_id: str, body: LegacyStageRequest, db: Session = Depends(get_db)):
    return envelope(SessionService(db).change_stage(case_id, body.stage, body.actor_id), "审讯阶段已切换")


@router.get("/api/cases/{case_id}/audit")
def legacy_audit(case_id: str, db: Session = Depends(get_db)):
    return envelope(CaseService(db).list_audit(case_id))


@router.get("/api/device/status")
def legacy_device_status(hardware=Depends(get_hardware)):
    return envelope(DeviceService(hardware).status())


@router.post("/api/device/action")
def legacy_device_action(body: LegacyDeviceActionRequest, hardware=Depends(get_hardware)):
    return envelope(DeviceService(hardware).action(body.type), "设备操作完成")
