from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Fact
from app.domain.errors import DomainError

DEFAULT_FACTS = [
    ("time", "时间", "待根据问答核实", "pending", "固定到达、离开和关键行为的具体时间。"),
    ("place", "地点", "待根据问答核实", "pending", "确认具体地点、入口和移动路线。"),
    ("motive", "动机 / 目的", "待核实", "pending", "追问事前联系、约定和准备行为。"),
    ("method", "手段 / 工具", "尚未固定", "missing", "确认工具来源、携带方式和最终去向。"),
    ("process", "行为经过", "尚未形成完整顺序", "missing", "把关键动作拆成连续问题逐项固定。"),
    ("evidence", "证据对应", "待绑定", "pending", "将回答与监控、照片、物证等证据编号关联。"),
    ("after", "事后处置 / 后果", "尚未固定", "missing", "确认离开路线、物品处置以及是否联系他人。"),
    ("current_address", "现住址", "未录入", "missing", None),
    ("case_type", "案件类别", "未录入", "missing", None),
    ("interrogation_round", "询问次数", "1", "confirmed", None),
    ("interrogation_place", "询问地点", "未录入", "missing", None),
    ("officer_unit", "询问人工作单位", "未录入", "missing", None),
    ("recorder_name", "记录人", "未录入", "missing", None),
    ("recorder_unit", "记录人工作单位", "未录入", "missing", None),
    ("id_document_type", "身份证件种类", "身份证", "confirmed", None),
    ("peoples_representative", "人民陪审员", "否", "confirmed", None),
    ("contact", "联系方式", "未录入", "missing", None),
    ("household_registration", "户籍所在地", "未录入", "missing", None),
]


def seed_defaults(db: Session, case_id: str) -> None:
    from app.services.template_catalog_service import get_case_elements

    elements = get_case_elements(db, case_id)
    core_keys = {item[0] for item in DEFAULT_FACTS[:7]}
    selected_keys = None if elements is None else {item["key"] for item in elements}
    existing = set(db.scalars(select(Fact.fact_key).where(Fact.case_id == case_id)))
    for fact_key, label, value, status, suggestion in DEFAULT_FACTS:
        if selected_keys is not None and fact_key in core_keys and fact_key not in selected_keys:
            continue
        if fact_key in existing:
            continue
        db.add(Fact(
            id=str(uuid4()), case_id=case_id, fact_key=fact_key, label=label,
            value=value, status=status, suggestion=suggestion,
        ))
    db.flush()


def list_for_case(db: Session, case_id: str) -> list[Fact]:
    return list(db.scalars(select(Fact).where(Fact.case_id == case_id).order_by(Fact.created_at.asc())))


def update(db: Session, case_id: str, fact_key: str, patch: dict) -> Fact:
    seed_defaults(db, case_id)
    item = db.scalar(select(Fact).where(Fact.case_id == case_id, Fact.fact_key == fact_key))
    if item is None:
        raise DomainError("FACT_NOT_FOUND", "事实项不存在", 404)
    if "status" in patch:
        status = str(patch["status"])
        if status not in {"confirmed", "pending", "conflict", "missing"}:
            raise DomainError("INVALID_FACT_STATUS", "无效事实状态", 400)
        item.status = status
    if "value" in patch:
        item.value = str(patch["value"])
    if "suggestion" in patch:
        item.suggestion = None if patch["suggestion"] is None else str(patch["suggestion"])
    db.flush()
    return item
