import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AuditLog
from app.auth.context import current_actor


def add(
    db: Session,
    *,
    case_id: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    actor_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    detail: dict | None = None,
    result: str = "SUCCESS",
    object_summary: str | None = None,
) -> AuditLog:
    actor = current_actor()
    metadata = dict(detail or {})
    metadata.setdefault("result", result)
    if object_summary is not None:
        metadata["objectSummary"] = object_summary
    if actor is not None:
        actor_id = actor.badge_number
        metadata["actorDisplayName"] = f"{actor.name}（{actor.badge_number}）"
    row = AuditLog(
        id=str(uuid4()), case_id=case_id, actor_id=actor_id, action=action,
        target_type=target_type, target_id=target_id,
        before_json=json.dumps(before or {}, ensure_ascii=False, sort_keys=True),
        after_json=json.dumps(after or {}, ensure_ascii=False, sort_keys=True),
        detail_json=json.dumps(metadata, ensure_ascii=False, sort_keys=True),
    )
    db.add(row)
    db.flush()
    return row


def list_for_case(db: Session, case_id: str, limit: int = 200) -> list[AuditLog]:
    return list(db.scalars(
        select(AuditLog).where(AuditLog.case_id == case_id).order_by(AuditLog.created_at.desc()).limit(int(limit))
    ))
