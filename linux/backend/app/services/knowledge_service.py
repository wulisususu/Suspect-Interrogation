from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.database.catalog_models import (
    AsrTermCorrection,
    KnowledgeCategory,
    KnowledgeEntry,
    KnowledgeEntryLink,
    KnowledgeEntryVersion,
    KnowledgeSyncRun,
)
from app.database.models import CaseQuestion
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
        return dict(
            id=row.id, title=row.title, categoryId=row.category_id,
            categoryName=category.name if category else '', content=row.content,
            keywords=json.loads(row.keywords_json), active=row.active, deleted=row.deleted,
            version=row.current_version, kind=row.kind, status=row.status, origin=row.origin,
            vaultUid=row.vault_uid, sourcePath=row.source_path, sourceRef=row.source_ref,
            sourceSha256=row.source_sha256,
            createdAt=iso_utc(row.created_at), updatedAt=iso_utc(row.updated_at),
        )

    def _search_ids(self, query):
        """FTS5 trigram 优先，LIKE 兜底（覆盖 2 字短词与 FTS 不可用的情况）。"""
        needle = (query or '').strip()
        if not needle:
            return None
        ids: set[str] = set()
        if len(needle) >= 3:
            try:
                rows = self.db.execute(
                    text('SELECT entry_id FROM knowledge_entries_fts WHERE knowledge_entries_fts MATCH :q'),
                    {'q': '"' + needle.replace('"', '""') + '"'},
                )
                ids |= {str(row[0]) for row in rows}
            except Exception:  # noqa: BLE001 - 索引缺失时退回 LIKE
                pass
        pattern = f'%{needle}%'
        ids |= set(self.db.scalars(select(KnowledgeEntry.id).where(or_(
            KnowledgeEntry.title.like(pattern),
            KnowledgeEntry.content.like(pattern),
            KnowledgeEntry.keywords_json.like(pattern),
        ))))
        return ids

    def entries(self, *, category_id=None, active=None, query=None, guidance=False, status=None):
        self._seed()
        statement = select(KnowledgeEntry).join(KnowledgeCategory).where(KnowledgeEntry.deleted.is_(False))
        if category_id is not None:
            statement = statement.where(KnowledgeEntry.category_id == category_id)
        if guidance:
            statement = statement.where(KnowledgeEntry.active.is_(True), KnowledgeCategory.active.is_(True))
        elif active is not None:
            statement = statement.where(KnowledgeEntry.active.is_(active))
        if status:
            statement = statement.where(KnowledgeEntry.status == status)
        if query:
            ids = self._search_ids(query)
            if not ids:
                return []
            statement = statement.where(KnowledgeEntry.id.in_(ids))
        rows = list(self.db.scalars(statement.order_by(KnowledgeEntry.created_at.desc(), KnowledgeEntry.id)))
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

    @staticmethod
    def _status(value):
        normalized = str(value or '').strip().lower()
        if normalized not in {'verified', 'pending'}:
            raise DomainError('INVALID_KNOWLEDGE_ENTRY', 'status 只能是 verified 或 pending', 400)
        return normalized

    @staticmethod
    def _kind(value):
        normalized = str(value or '').strip().lower()
        if normalized not in {'faq', 'wiki'}:
            raise DomainError('INVALID_KNOWLEDGE_ENTRY', 'kind 只能是 faq 或 wiki', 400)
        return normalized

    def create_entry(self, *, title, category_id, content, keywords=None, active=True,
                     kind='faq', status='pending', origin='manual', source_ref=None,
                     vault_uid=None, source_path=None, source_sha256=None):
        self._seed()
        self._category(category_id)
        row = KnowledgeEntry(
            id=str(uuid4()), title=_text(title, '条目名称', 256), category_id=category_id,
            content=_text(content, '条目内容', 100000), keywords_json=self._keywords(keywords or []),
            active=bool(active), deleted=False, current_version=1,
            kind=self._kind(kind), status=self._status(status), origin=str(origin or 'manual'),
            source_ref=(str(source_ref)[:512] if source_ref else None),
            vault_uid=(str(vault_uid)[:64] if vault_uid else None),
            source_path=(str(source_path)[:512] if source_path else None),
            source_sha256=(str(source_sha256)[:64] if source_sha256 else None),
        )
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
        if 'status' in patch:
            row.status = self._status(patch['status'])
        if 'kind' in patch:
            row.kind = self._kind(patch['kind'])
        if 'sourceRef' in patch:
            value = patch['sourceRef']
            row.source_ref = None if value in (None, '') else str(value)[:512]
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

    # ------------------------------------------------------------------ 关联

    def links(self, entry_id):
        self._entry(entry_id, include_deleted=True)
        outgoing = list(self.db.scalars(select(KnowledgeEntryLink).where(KnowledgeEntryLink.from_entry_id == entry_id)))
        incoming = list(self.db.scalars(select(KnowledgeEntryLink).where(KnowledgeEntryLink.to_entry_id == entry_id)))
        return {
            'outgoing': [
                dict(targetTitle=r.target_title, entryId=r.to_entry_id, relation=r.relation,
                     resolved=r.to_entry_id is not None)
                for r in outgoing
            ],
            'incoming': [
                dict(entryId=r.from_entry_id, title=(self.db.get(KnowledgeEntry, r.from_entry_id).title
                                                     if self.db.get(KnowledgeEntry, r.from_entry_id) else ''))
                for r in incoming
            ],
        }

    # -------------------------------------------------------------- 办案提示

    def _element_label(self, case_id, element_key):
        if not case_id or not element_key:
            return None
        try:
            from app.services.template_catalog_service import get_case_elements

            for element in get_case_elements(self.db, case_id) or []:
                if element.get('key') == element_key:
                    return element.get('label')
        except Exception:  # noqa: BLE001 - 要素缺失不影响提示
            return None
        return element_key

    def _guidance_terms(self, case_id, question_id, element_key, extra_text):
        label = self._element_label(case_id, element_key)
        terms: list[str] = []
        question_text = ''
        if question_id:
            question = self.db.get(CaseQuestion, question_id)
            if question is not None:
                question_text = question.text or ''
                if not element_key and question.element_key:
                    label = self._element_label(case_id, question.element_key)
                try:
                    aliases = json.loads(question.aliases_json or '[]')
                except Exception:  # noqa: BLE001
                    aliases = []
                terms.extend(str(item) for item in aliases if str(item).strip())
        for value in (label, question_text, extra_text):
            if value and str(value).strip():
                terms.append(str(value).strip())
        deduped: list[str] = []
        for term in terms:
            if term and term not in deduped:
                deduped.append(term)
        return deduped

    def guidance_for(self, *, case_id=None, question_id=None, element_key=None, text=None,
                     limit=5, verified_only=True):
        """按要素标签/题目文本匹配知识，返回带来源与版本的可展示条目。"""
        self._seed()
        terms = self._guidance_terms(case_id, question_id, element_key, text)
        statement = (
            select(KnowledgeEntry)
            .join(KnowledgeCategory)
            .where(KnowledgeEntry.deleted.is_(False), KnowledgeEntry.active.is_(True),
                   KnowledgeCategory.active.is_(True))
        )
        if verified_only:
            statement = statement.where(KnowledgeEntry.status == 'verified')
        candidates = list(self.db.scalars(statement))
        if terms:
            ids: set[str] = set()
            for term in terms:
                ids |= self._search_ids(term) or set()
            if ids:
                candidates = [row for row in candidates if row.id in ids] or candidates
        scored = []
        for row in candidates:
            keywords = json.loads(row.keywords_json or '[]')
            score = 2 if row.status == 'verified' else 0
            score += 1 if row.kind == 'faq' else 0
            reasons: list[str] = []
            for keyword in keywords:
                if any(keyword in term for term in terms):
                    score += 4
                    reasons.append(f'关键词命中：{keyword}')
            for term in terms:
                if len(term) >= 2 and term in row.title:
                    score += 3
                    reasons.append(f'标题命中：{term}')
                elif len(term) >= 3 and term in row.content:
                    score += 1
                    reasons.append(f'正文命中：{term}')
            if not reasons and terms:
                continue
            scored.append((score, row, reasons))
        scored.sort(key=lambda item: (-item[0], item[1].created_at, item[1].id))
        results = []
        for score, row, reasons in scored[:limit]:
            payload = self._payload(row)
            payload['score'] = score
            payload['matchReasons'] = list(dict.fromkeys(reasons))[:5]
            payload['snippet'] = row.content.strip().splitlines()[0][:120] if row.content.strip() else ''
            results.append(payload)
        return results

    @staticmethod
    def _suggestion_lines(content):
        lines = content.splitlines()
        collected: list[str] = []
        in_section = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('#'):
                if '建议问法' in stripped:
                    in_section = True
                    continue
                if in_section:
                    break
                continue
            if in_section and stripped.startswith(('-', '*', '·')):
                value = stripped.lstrip('-*· ').strip()
                if value:
                    collected.append(value)
        return collected

    def draft_questions(self, *, case_id=None, question_id=None, element_key=None, text=None, limit=3):
        """给出可采纳的建议问法。只返回候选，不写笔录、不建题。"""
        entries = self.guidance_for(case_id=case_id, question_id=question_id, element_key=element_key,
                                    text=text, limit=max(limit, 3), verified_only=True)
        suggestions = []
        for entry in entries:
            for phrase in self._suggestion_lines(entry['content'])[:2]:
                suggestions.append({
                    'text': phrase[:300],
                    'entryId': entry['id'],
                    'entryTitle': entry['title'],
                    'entryVersion': entry['version'],
                    'sourceRef': entry['sourceRef'],
                    'status': entry['status'],
                    'categoryName': entry['categoryName'],
                })
                if len(suggestions) >= limit:
                    return suggestions
        if suggestions:
            return suggestions
        label = self._element_label(case_id, element_key)
        if label:
            return [{
                'text': f'关于{label}，请你具体说明当时的情况。',
                'entryId': None, 'entryTitle': '通用问法', 'entryVersion': None,
                'sourceRef': None, 'status': 'pending', 'categoryName': '',
            }]
        return []

    # ---------------------------------------------------------- Vault 导入

    def import_vault(self, root, *, dry_run=True, actor_id=None):
        from pathlib import Path

        from app.services.knowledge_vault import KnowledgeVaultImporter

        return KnowledgeVaultImporter(self.db, self).run(Path(root), dry_run=dry_run, actor_id=actor_id)

    def sync_runs(self, limit=10):
        rows = self.db.scalars(select(KnowledgeSyncRun).order_by(KnowledgeSyncRun.started_at.desc()).limit(limit))
        return [
            dict(id=r.id, startedAt=iso_utc(r.started_at), finishedAt=iso_utc(r.finished_at) if r.finished_at else None,
                 dryRun=r.dry_run, actorId=r.actor_id, sourceRoot=r.source_root, added=r.added, updated=r.updated,
                 disabled=r.disabled, conflicts=r.conflicts, rejected=r.rejected,
                 report=json.loads(r.report_json or '{}'))
            for r in rows
        ]

    # -------------------------------------------------------------- 热词表

    def term_corrections(self, *, active=None):
        statement = select(AsrTermCorrection).order_by(AsrTermCorrection.wrong_text)
        if active is not None:
            statement = statement.where(AsrTermCorrection.active.is_(active))
        rows = list(self.db.scalars(statement))
        return [
            dict(id=r.id, wrong=r.wrong_text, right=r.right_text, category=r.category,
                 active=r.active, entryId=r.entry_id)
            for r in rows
        ]

    def upsert_term_correction(self, *, wrong, right, category='TERM', active=True, replace=False):
        wrong = _text(wrong, '误写文本', 128)
        right = _text(right, '更正文本', 128)
        if wrong == right:
            raise DomainError('INVALID_TERM_CORRECTION', '误写与更正不能相同', 400)
        row = self.db.scalar(select(AsrTermCorrection).where(AsrTermCorrection.wrong_text == wrong))
        if row is None:
            row = AsrTermCorrection(id=str(uuid4()), wrong_text=wrong, right_text=right,
                                    category=category, active=bool(active), entry_id=None)
            self.db.add(row)
            self.db.flush()
            audit_repo.add(self.db, case_id=None, action='TERM_CORRECTION_CREATE', target_type='ASR_TERM',
                           target_id=row.id, after={'wrong': wrong, 'right': right})
        else:
            if row.right_text != right and not replace:
                raise DomainError('TERM_CORRECTION_EXISTS', '该误写已有不同更正，需显式替换', 409)
            row.right_text = right
            row.category = category
            row.active = bool(active)
            self.db.flush()
            audit_repo.add(self.db, case_id=None, action='TERM_CORRECTION_UPDATE', target_type='ASR_TERM',
                           target_id=row.id, after={'wrong': wrong, 'right': right})
        return dict(id=row.id, wrong=row.wrong_text, right=row.right_text, category=row.category, active=row.active)

    def set_term_correction_active(self, correction_id, active):
        row = self.db.get(AsrTermCorrection, correction_id)
        if row is None:
            raise DomainError('TERM_CORRECTION_NOT_FOUND', '热词条目不存在', 404)
        row.active = bool(active)
        self.db.flush()
        audit_repo.add(self.db, case_id=None, action='TERM_CORRECTION_DISABLE', target_type='ASR_TERM',
                       target_id=row.id, after={'active': row.active})
        return dict(id=row.id, wrong=row.wrong_text, right=row.right_text, active=row.active)

    def lookup_corrections(self, text):
        """对一段文本做确定性短语匹配，返回命中的纠错项（不修改原文）。"""
        if not text:
            return []
        hits = []
        for row in self.db.scalars(select(AsrTermCorrection).where(AsrTermCorrection.active.is_(True))):
            if row.wrong_text and row.wrong_text in text:
                hits.append(dict(wrong=row.wrong_text, right=row.right_text, entryId=row.entry_id))
        return hits

    def export_corrections(self):
        """导出为 asr-stack 认的 corrections.json 结构，并附热词列表。"""
        rows = list(self.db.scalars(select(AsrTermCorrection).where(AsrTermCorrection.active.is_(True))))
        rules = []
        for row in rows:
            entry = self.db.get(KnowledgeEntry, row.entry_id) if row.entry_id else None
            rules.append({
                'wrong': row.wrong_text,
                'right': row.right_text,
                'note': f'知识库：{entry.title}' if entry else '知识库热词表',
                'enabled': True,
            })
        return {
            'corrections': {'_comment': '由知识库导出，确定性短语替换；每条须人工确认后上线', 'rules': rules},
            'hotwords': sorted({row.right_text for row in rows}),
        }

