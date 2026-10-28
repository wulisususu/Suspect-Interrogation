from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.catalog_models import KnowledgeCategory, KnowledgeEntry, KnowledgeEntryVersion
from app.database.session import begin_sqlite_immediate
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.services.serializers import iso_utc


def _text(value, label, limit=None):
    if not isinstance(value, str):
        raise DomainError('INVALID_KNOWLEDGE_ENTRY', f'{label}必须是文字', 400)
    value = value.strip()
    if not value or (limit is not None and len(value) > limit):
        raise DomainError('INVALID_KNOWLEDGE_ENTRY', f'{label}不能为空或超出长度限制', 400)
    return value


class KnowledgeService:
    def __init__(self, db: Session):
        self.db = db

    def _seed(self):
        begin_sqlite_immediate(self.db)
        for key, name in [('questioning', '问话要点'), ('law', '法规条文'), ('evidence', '取证规范'), ('safety', '安全提示')]:
            if self.db.get(KnowledgeCategory, key) is None:
                self.db.add(KnowledgeCategory(id=key, name=name, active=True))
        self.db.flush()

    def categories(self):
        self._seed()
        return [dict(id=r.id, name=r.name, active=r.active) for r in self.db.scalars(select(KnowledgeCategory).where(KnowledgeCategory.active.is_(True)).order_by(KnowledgeCategory.created_at, KnowledgeCategory.id))]

    def _category(self, category_id):
        row = self.db.get(KnowledgeCategory, category_id)
        if row is None or not row.active:
            raise DomainError('KNOWLEDGE_CATEGORY_NOT_FOUND', '知识分类不存在或已停用', 404)
        return row

    def _check_category_name(self, name, excluding=None):
        name = _text(name, '分类名称', 128)
        row = self.db.scalar(select(KnowledgeCategory).where(KnowledgeCategory.name == name))
        if row is not None and row.id != excluding:
            raise DomainError('KNOWLEDGE_CATEGORY_EXISTS', '知识分类名称已存在', 409)
        return name

    def create_category(self, name):
        self._seed()
        row = KnowledgeCategory(id=str(uuid4()), name=self._check_category_name(name), active=True)
        self.db.add(row)
        self.db.flush()
        audit_repo.add(self.db, case_id=None, action='KNOWLEDGE_CATEGORY_CREATE', target_type='KNOWLEDGE_CATEGORY', target_id=row.id, after={'name': row.name})
        return dict(id=row.id, name=row.name, active=row.active)

    def update_category(self, category_id, name):
        begin_sqlite_immediate(self.db)
        row = self._category(category_id)
        row.name = self._check_category_name(name, excluding=category_id)
        self.db.flush()
        audit_repo.add(self.db, case_id=None, action='KNOWLEDGE_CATEGORY_UPDATE', target_type='KNOWLEDGE_CATEGORY', target_id=row.id, after={'name': row.name})
        return dict(id=row.id, name=row.name, active=row.active)

    def delete_category(self, category_id):
        begin_sqlite_immediate(self.db)
        row = self._category(category_id)
        if self.db.scalar(select(KnowledgeEntry.id).where(KnowledgeEntry.category_id == category_id, KnowledgeEntry.deleted.is_(False)).limit(1)):
            raise DomainError('KNOWLEDGE_CATEGORY_IN_USE', '分类仍有知识条目，请先移动或删除条目', 409)
        row.active = False
        self.db.flush()
        audit_repo.add(self.db, case_id=None, action='KNOWLEDGE_CATEGORY_DELETE', target_type='KNOWLEDGE_CATEGORY', target_id=row.id)
        return {'id': row.id, 'active': False}

    def _entry(self, entry_id, *, include_deleted=False):
        row = self.db.get(KnowledgeEntry, entry_id)
        if row is None or (row.deleted and not include_deleted):
            raise DomainError('KNOWLEDGE_ENTRY_NOT_FOUND', '知识条目不存在', 404)
        return row

    def _payload(self, row):
        category = self.db.get(KnowledgeCategory, row.category_id)
        return dict(id=row.id, title=row.title, categoryId=row.category_id, categoryName=category.name if category else '', content=row.content, keywords=json.loads(row.keywords_json), active=row.active, deleted=row.deleted, version=row.current_version, createdAt=iso_utc(row.created_at), updatedAt=iso_utc(row.updated_at))

    def entries(self, *, category_id=None, active=None, query=None, guidance=False):
        self._seed()
        statement = select(KnowledgeEntry).join(KnowledgeCategory).where(KnowledgeEntry.deleted.is_(False))
        if category_id is not None:
            statement = statement.where(KnowledgeEntry.category_id == category_id)
        if guidance:
            statement = statement.where(KnowledgeEntry.active.is_(True), KnowledgeCategory.active.is_(True))
        elif active is not None:
            statement = statement.where(KnowledgeEntry.active.is_(active))
        rows = list(self.db.scalars(statement.order_by(KnowledgeEntry.created_at.desc(), KnowledgeEntry.id)))
        if query:
            needle = query.casefold()
            rows = [r for r in rows if needle in (r.title + '\n' + r.content + '\n' + r.keywords_json).casefold()]
        return [self._payload(row) for row in rows]

    def detail(self, entry_id):
        return self._payload(self._entry(entry_id))

    def _version(self, row, action):
        data = self._payload(row)
        self.db.add(KnowledgeEntryVersion(id=str(uuid4()), entry_id=row.id, version=row.current_version, action=action, data_json=json.dumps(data, ensure_ascii=False, sort_keys=True)))
        self.db.flush()
        audit_repo.add(self.db, case_id=None, action=f'KNOWLEDGE_{action}', target_type='KNOWLEDGE_ENTRY', target_id=row.id, after={'version': row.current_version, 'title': row.title})
        return data

    @staticmethod
    def _keywords(values):
        if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, str) or len(v) > 128 for v in values):
            raise DomainError('INVALID_KNOWLEDGE_ENTRY', '关键词必须是最多100个词的列表', 400)
        return json.dumps(list(dict.fromkeys(v.strip() for v in values if v.strip())), ensure_ascii=False)

    def create_entry(self, *, title, category_id, content, keywords=None, active=True):
        self._seed()
        self._category(category_id)
        row = KnowledgeEntry(id=str(uuid4()), title=_text(title, '条目名称', 256), category_id=category_id, content=_text(content, '条目内容', 100000), keywords_json=self._keywords(keywords or []), active=bool(active), deleted=False, current_version=1)
        self.db.add(row)
        self.db.flush()
        return self._version(row, 'CREATE')

    def update_entry(self, entry_id, patch):
        begin_sqlite_immediate(self.db)
        row = self._entry(entry_id)
        if not patch or ('active' in patch and not isinstance(patch['active'], bool)):
            raise DomainError('INVALID_KNOWLEDGE_ENTRY', '请提供有效的条目更新字段', 400)
        if 'categoryId' in patch:
            row.category_id = self._category(patch['categoryId']).id
        if 'title' in patch:
            row.title = _text(patch['title'], '条目名称', 256)
        if 'content' in patch:
            row.content = _text(patch['content'], '条目内容', 100000)
        if 'keywords' in patch:
            row.keywords_json = self._keywords(patch['keywords'])
        if 'active' in patch:
            row.active = bool(patch['active'])
        row.current_version += 1
        self.db.flush()
        return self._version(row, 'UPDATE')

    def delete_entry(self, entry_id):
        begin_sqlite_immediate(self.db)
        row = self._entry(entry_id)
        row.deleted = True
        row.active = False
        row.current_version += 1
        self.db.flush()
        return self._version(row, 'DELETE')

    def versions(self, entry_id):
        self._entry(entry_id, include_deleted=True)
        rows = self.db.scalars(select(KnowledgeEntryVersion).where(KnowledgeEntryVersion.entry_id == entry_id).order_by(KnowledgeEntryVersion.version.desc()))
        return [dict(id=r.id, version=r.version, action=r.action, data=json.loads(r.data_json), createdAt=iso_utc(r.created_at)) for r in rows]
