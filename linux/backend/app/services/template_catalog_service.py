from __future__ import annotations

import json
import re
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database.catalog_models import CaseTemplateSnapshot, RecordTemplate, RecordTemplateVersion
from app.database.models import ASRCaptureSession, ASRFragment, CaseQuestion, Fact, QuestionRound
from app.database.session import begin_sqlite_immediate
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.repositories.facts import DEFAULT_FACTS
from app.repositories import template_questions as question_repo
from app.services.formal_record_policy import assert_formal_record_mutable
from app.services.serializers import iso_utc
from app.services.template_catalog_seed import SEED_TEMPLATES


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def get_case_snapshot(db: Session, case_id: str) -> CaseTemplateSnapshot | None:
    return db.get(CaseTemplateSnapshot, case_id)


def get_case_elements(db: Session, case_id: str) -> list[dict] | None:
    """None means a legacy case; [] is an explicitly selected blank template."""
    snapshot = get_case_snapshot(db, case_id)
    if snapshot is None:
        return None
    return json.loads(snapshot.snapshot_json)['structure']['elements']


def _validate_structure(structure: dict) -> dict:
    if not isinstance(structure, dict) or not isinstance(structure.get('elements'), list) or not isinstance(structure.get('questions'), list):
        raise DomainError('INVALID_TEMPLATE_STRUCTURE', '模板结构需要elements与questions列表', 400)
    if len(structure['elements']) > 100 or len(structure['questions']) > 500:
        raise DomainError('INVALID_TEMPLATE_STRUCTURE', '模板结构超出支持的题目或要素数量', 400)
    keys = set()
    reserved = {item[0] for item in DEFAULT_FACTS} - {'time', 'place', 'motive', 'method', 'process', 'evidence', 'after'}
    for item in structure['elements']:
        if not isinstance(item, dict) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', str(item.get('key', ''))) or not isinstance(item.get('label'), str) or not item['label'].strip() or len(item['label']) > 128 or item['key'] in keys or item['key'] in reserved:
            raise DomainError('INVALID_TEMPLATE_STRUCTURE', '要素key须唯一且包含有效名称', 400)
        keys.add(item['key'])
    question_keys = set()
    for question in structure['questions']:
        if not isinstance(question, dict) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', str(question.get('key', ''))) or not isinstance(question.get('text'), str) or not question['text'].strip() or len(question['text']) > 10000 or question['key'] in question_keys:
            raise DomainError('INVALID_TEMPLATE_STRUCTURE', '题目key须唯一且包含问题文字', 400)
        if question.get('elementKey') is not None and (not isinstance(question['elementKey'], str) or question['elementKey'] not in keys):
            raise DomainError('INVALID_TEMPLATE_STRUCTURE', '问题关联的要素不属于本模板', 400)
        question_keys.add(question['key'])
        for field in ('regexPatterns', 'aliases'):
            values = question.get(field, [])
            if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, str) or len(v) > 1000 for v in values):
                raise DomainError('INVALID_TEMPLATE_STRUCTURE', '题目匹配规则与别名必须是文字列表', 400)
    # Optional theme/field trees are stored with the same immutable structure snapshot.
    if 'topics' in structure and not isinstance(structure['topics'], list):
        raise DomainError('INVALID_TEMPLATE_STRUCTURE', 'topics必须是主题列表', 400)
    if len(_json(structure)) > 1_000_000:
        raise DomainError('INVALID_TEMPLATE_STRUCTURE', '模板结构过大', 400)
    return json.loads(_json(structure))


class TemplateCatalogService:
    def __init__(self, db: Session):
        self.db = db

    def seed(self) -> None:
        begin_sqlite_immediate(self.db)
        for catalog, structure in SEED_TEMPLATES:
            if self.db.get(RecordTemplate, catalog['id']) is not None:
                continue
            row = RecordTemplate(id=catalog['id'], backend_key=catalog['backendKey'], catalog_json=_json(catalog), current_version=1, active=True)
            self.db.add(row)
            self.db.flush()
            self.db.add(RecordTemplateVersion(id=str(uuid4()), template_id=row.id, version=1, structure_json=_json(structure), catalog_json=row.catalog_json))
        self.db.flush()

    def _template(self, template_id: str) -> RecordTemplate:
        self.seed()
        row = self.db.scalar(select(RecordTemplate).where((RecordTemplate.id == template_id) | (RecordTemplate.backend_key == template_id)))
        if row is None:
            raise DomainError('TEMPLATE_NOT_FOUND', '笔录模板不存在', 404)
        return row

    def _version(self, row: RecordTemplate) -> RecordTemplateVersion:
        return self.db.scalar(select(RecordTemplateVersion).where(RecordTemplateVersion.template_id == row.id, RecordTemplateVersion.version == row.current_version))

    def catalog(self, *, include_disabled: bool = False) -> list[dict]:
        self.seed()
        query = select(RecordTemplate).order_by(RecordTemplate.created_at, RecordTemplate.id)
        if not include_disabled:
            query = query.where(RecordTemplate.active.is_(True))
        return [self._payload(row) for row in self.db.scalars(query)]

    def _payload(self, row: RecordTemplate) -> dict:
        version = self._version(row)
        structure = json.loads(version.structure_json)
        catalog = json.loads(row.catalog_json)
        count = catalog.get('learnedCount', 0)
        return {**catalog, 'active': row.active, 'version': row.current_version,
                'elements': [x['label'] for x in structure['elements']],
                'elementDefinitions': structure['elements'],
                'presetQuestions': [x['text'] for x in structure['questions']],
                'learning': f'已学习 {count} 份' if count else '未学习 · 基础模板',
                'structure': structure, 'updatedAt': iso_utc(row.updated_at)}

    def detail(self, template_id: str) -> dict:
        return self._payload(self._template(template_id))

    def create(self, *, template_id: str, backend_key: str, catalog: dict, structure: dict) -> dict:
        self.seed()
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', template_id) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', backend_key):
            raise DomainError('INVALID_TEMPLATE_KEY', '模板编号格式无效', 400)
        if self.db.scalar(select(RecordTemplate.id).where((RecordTemplate.id == template_id) | (RecordTemplate.backend_key == backend_key))):
            raise DomainError('TEMPLATE_EXISTS', '模板编号已存在', 409)
        structure = _validate_structure(structure)
        data = self._validate_catalog(catalog)
        data.update(id=template_id, backendKey=backend_key)
        row = RecordTemplate(id=template_id, backend_key=backend_key, catalog_json=_json(data), current_version=1, active=True)
        self.db.add(row)
        self.db.flush()
        self.db.add(RecordTemplateVersion(id=str(uuid4()), template_id=row.id, version=1, catalog_json=row.catalog_json, structure_json=_json(structure)))
        self.db.flush()
        audit_repo.add(self.db, case_id=None, action='TEMPLATE_CREATE', target_type='TEMPLATE', target_id=row.id, after={'version': 1})
        return self._payload(row)

    @staticmethod
    def _validate_catalog(catalog: dict) -> dict:
        if not isinstance(catalog.get('title'), str) or not catalog['title'].strip() or len(catalog['title']) > 256 or not isinstance(catalog.get('category'), str) or catalog['category'] not in {'theft', 'injury', 'traffic', 'other'}:
            raise DomainError('INVALID_TEMPLATE_CATALOG', '模板名称与分类无效', 400)
        for key in ('minutes', 'learnedCount'):
            value = catalog.get(key, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise DomainError('INVALID_TEMPLATE_CATALOG', '模板时长与学习份数必须为非负整数', 400)
        result = {key: catalog.get(key, default) for key, default in [('title', ''), ('category', 'other'), ('tag', '其他'), ('tagTone', 'neutral'), ('summary', ''), ('minutes', 0), ('scene', ''), ('learnedCount', 0)]}
        if not isinstance(result['tagTone'], str) or result['tagTone'] not in {'primary', 'danger', 'warning', 'neutral'} or any(not isinstance(result[k], str) for k in ('tag', 'summary', 'scene')):
            raise DomainError('INVALID_TEMPLATE_CATALOG', '模板标签、说明与适用场景格式无效', 400)
        if catalog.get('badge') is not None:
            badge = catalog['badge']
            if not isinstance(badge, dict) or not isinstance(badge.get('tone'), str) or badge['tone'] not in {'danger', 'success', 'warning'} or not isinstance(badge.get('label'), str) or not badge['label'].strip():
                raise DomainError('INVALID_TEMPLATE_CATALOG', '模板标签无效', 400)
            result['badge'] = {'label': badge['label'], 'tone': badge['tone']}
        return result

    def save_version(self, template_id: str, *, structure: dict, catalog: dict | None = None) -> dict:
        row = self._template(template_id)
        structure = _validate_structure(structure)
        data = self._validate_catalog({**json.loads(row.catalog_json), **(catalog or {})})
        data.update(id=row.id, backendKey=row.backend_key)
        row.current_version += 1
        row.catalog_json = _json(data)
        self.db.add(RecordTemplateVersion(id=str(uuid4()), template_id=row.id, version=row.current_version, structure_json=_json(structure), catalog_json=row.catalog_json))
        self.db.flush()
        audit_repo.add(self.db, case_id=None, action='TEMPLATE_VERSION_SAVE', target_type='TEMPLATE', target_id=row.id, after={'version': row.current_version})
        return self._payload(row)

    def set_active(self, template_id: str, active: bool) -> dict:
        row = self._template(template_id)
        row.active = active
        self.db.flush()
        audit_repo.add(self.db, case_id=None, action='TEMPLATE_ENABLE' if active else 'TEMPLATE_DISABLE', target_type='TEMPLATE', target_id=row.id)
        return self._payload(row)

    def versions(self, template_id: str) -> list[dict]:
        row = self._template(template_id)
        versions = self.db.scalars(select(RecordTemplateVersion).where(RecordTemplateVersion.template_id == row.id).order_by(RecordTemplateVersion.version.desc()))
        return [dict(id=v.id, version=v.version, structure=json.loads(v.structure_json), catalog=json.loads(v.catalog_json), createdAt=iso_utc(v.created_at)) for v in versions]

    def select(self, case_id: str, *, template_id: str | None = None, blank: bool = False) -> dict:
        from app.services.template_workspace_service import TemplateWorkspaceService

        begin_sqlite_immediate(self.db)
        assert_formal_record_mutable(self.db, case_id)
        if blank == (template_id is not None):
            raise DomainError('TEMPLATE_SELECTION_REQUIRED', '请选择一个模板或空白笔录', 400)
        current = get_case_snapshot(self.db, case_id)
        if current is not None and ((blank and current.blank) or (template_id in {current.template_id, current.template_key} and not current.blank)):
            return {**TemplateWorkspaceService(self.db).workspace(case_id), 'blank': current.blank, 'templateKey': current.template_key}
        row = None if blank else self._template(template_id)
        if row is not None and not row.active:
            raise DomainError('TEMPLATE_DISABLED', '模板已停用，不可用于新笔录', 409)
        questions = question_repo.list_case(self.db, case_id)
        has_work = any(q.formal_answer_text.strip() or q.first_asked_at for q in questions)
        has_round = self.db.scalar(select(QuestionRound.id).where(QuestionRound.case_id == case_id).limit(1))
        has_capture = self.db.scalar(select(ASRCaptureSession.id).where(ASRCaptureSession.case_id == case_id).limit(1))
        has_fragment = self.db.scalar(select(ASRFragment.id).where(ASRFragment.case_id == case_id).limit(1))
        if has_work or has_round or has_capture or has_fragment:
            raise DomainError('TEMPLATE_SELECTION_HAS_WORK', '本案已有回答或录音，不可更换模板以免丢失归属', 409)
        old_elements = get_case_elements(self.db, case_id)
        if current is not None:
            self.db.delete(current)
            self.db.flush()
        # Preserve legacy fixed wording; ensure is called only while no selection snapshot exists.
        if not any(q.section_type in {'OPENING', 'CLOSING'} for q in questions):
            TemplateWorkspaceService(self.db).ensure_formal_record(case_id)
        questions = question_repo.list_case(self.db, case_id)
        for question in questions:
            if question.section_type == 'BODY':
                question.active = False
        self.db.flush()
        fixed = [q for q in questions if q.section_type != 'BODY']
        version = None if blank else self._version(row)
        structure = {'elements': [], 'questions': []} if blank else json.loads(version.structure_json)
        key = 'BLANK_V1' if blank else row.backend_key
        body = []
        for item in structure['questions']:
            q = CaseQuestion(id=str(uuid4()), case_id=case_id, source='CASE', text=item['text'].strip(), section_type='BODY', template_key=key, template_item_key=item['key'], element_key=item.get('elementKey'), locked=False,
                             regex_patterns_json=_json(item.get('regexPatterns', [])), aliases_json=_json(item.get('aliases', [])), sort_order=question_repo.next_case_sort_order(self.db, case_id), active=True)
            self.db.add(q)
            self.db.flush()
            body.append(q)
        ordered = [q for q in fixed if q.section_type == 'OPENING'] + body + [q for q in fixed if q.section_type == 'CLOSING']
        # Inactive rows retain their historical sort positions; allocate new positions after every row.
        start = question_repo.next_case_sort_order(self.db, case_id)
        for index, question in enumerate(ordered):
            question.template_key = key
            question.sort_order = start + index * 10
            if question.section_type != 'BODY':
                question.element_key = None
        self.db.flush()
        core_keys = {'time', 'place', 'motive', 'method', 'process', 'evidence', 'after'} | {x['key'] for x in (old_elements or [])}
        self.db.execute(delete(Fact).where(Fact.case_id == case_id, Fact.fact_key.in_(core_keys)))
        for element in structure['elements']:
            self.db.add(Fact(id=str(uuid4()), case_id=case_id, fact_key=element['key'], label=element['label'], value='', status='pending'))
        snapshot_data = {'structure': structure, 'catalog': None if blank else json.loads(version.catalog_json)}
        self.db.add(CaseTemplateSnapshot(case_id=case_id, template_id=None if blank else row.id, version_id=None if blank else version.id, template_key=key, blank=blank, snapshot_json=_json(snapshot_data)))
        self.db.flush()
        audit_repo.add(self.db, case_id=case_id, action='CASE_TEMPLATE_SELECT', target_type='TEMPLATE', target_id=None if blank else row.id, after={'templateKey': key, 'version': None if blank else version.version, 'blank': blank})
        return {**TemplateWorkspaceService(self.db).workspace(case_id), 'blank': blank, 'templateKey': key}
