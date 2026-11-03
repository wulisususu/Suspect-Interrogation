"""智能追问推荐与采纳反馈（Task 01）。

闭环的第一段：办案 → 积累使用经验。

- 推荐：按本案模板要素里**尚未确认**的事实，从已审核、在有效期内、绑定到本案模板 / 案由的知识条目
  「建议问法」小节里取带要素标记的问法（``- [lock] 停车时你用的是什么锁？``）；当前题和刚才的回答
  匹配到的通用条目问法作为补充。
- 反馈：每个案件每条问法一行（``knowledge_suggestion_feedback``），记录展示、采纳 / 不适用、操作人。
  采纳时在同一事务里建一张 LIVE 草稿题（不写正式答案）；重复点击不重复建题、不重复计数。
- 复用：同一要素下的候选按历史采纳情况微调先后，但只在已审核的问法之间排序，不自动改规则、
  不把采纳的问题发布进知识库，也不读取其他案件的问答内容。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.database.catalog_models import (
    KnowledgeCategory,
    KnowledgeCheckBinding,
    KnowledgeEntry,
    KnowledgeSuggestionFeedback,
)
from app.database.models import CaseQuestion, Fact
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.repositories import cases as case_repo
from app.services.knowledge_matching import normalize, similar_question

ELEMENT_TAG = re.compile(r'^\s*[\[【]([a-z][a-z0-9_-]{0,63})[\]】]\s*')
UNCONFIRMED = {'pending': '尚未确认', 'missing': '尚未获取', 'conflict': '存在冲突'}
DEFAULT_HINT = '建议先检查已有问答中是否已记录相关内容；若确实未获取，再补充提问。'
DECISIONS = {'ADOPTED', 'NOT_APPLICABLE'}
CORE_FACT_KEYS = ('time', 'place', 'motive', 'method', 'process', 'evidence', 'after')


def parse_suggestions(content: str) -> list[tuple[str | None, str]]:
    """条目正文「建议问法」小节 → [(要素 key 或 None, 问法)]。"""
    collected: list[tuple[str | None, str]] = []
    in_section = False
    for line in (content or '').splitlines():
        stripped = line.strip()
        if stripped.startswith('#'):
            if in_section:
                break
            in_section = '建议问法' in stripped
            continue
        if not in_section or not stripped.startswith(('-', '*', '·')):
            continue
        value = stripped.lstrip('-*· ').strip()
        match = ELEMENT_TAG.match(value)
        element_key = match.group(1) if match else None
        value = ELEMENT_TAG.sub('', value).strip()
        if value:
            collected.append((element_key, value[:300]))
    return collected


def suggestion_key(entry_id: str | None, text: str) -> str:
    """同一条目里同一问法的稳定标识（标点、口语差异归一后相同即同一条）。"""
    digest = hashlib.sha256(f'{entry_id or "-"}|{normalize(text).text}'.encode()).hexdigest()
    return digest[:32]


def _now():
    return datetime.now(timezone.utc)


class KnowledgeSuggestionService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------ 推荐

    def _case_scope(self, case_id):
        from app.services.template_catalog_service import get_case_elements, get_case_snapshot

        snapshot = get_case_snapshot(self.db, case_id)
        catalog = json.loads(snapshot.snapshot_json).get('catalog') or {} if snapshot and not snapshot.blank else {}
        facts = {row.fact_key: row for row in self.db.scalars(select(Fact).where(Fact.case_id == case_id))}
        elements = get_case_elements(self.db, case_id)
        if elements is None:  # 旧案件：用七类核心事实
            elements = [{'key': key, 'label': facts[key].label} for key in CORE_FACT_KEYS if key in facts]
        return {
            'templateKey': snapshot.template_key if snapshot and not snapshot.blank else None,
            'caseType': catalog.get('category') or None,
            'templateTitle': catalog.get('title') or '',
            'elements': [dict(key=item['key'], label=item.get('label') or item['key']) for item in elements],
            'facts': facts,
        }

    def _bound_entries(self, template_key, case_type):
        from app.services.knowledge_service import KnowledgeService, in_force

        targets = []
        if template_key:
            targets.append((KnowledgeCheckBinding.scope == 'TEMPLATE') & (KnowledgeCheckBinding.value == template_key))
        if case_type:
            targets.append((KnowledgeCheckBinding.scope == 'CASE_TYPE') & (KnowledgeCheckBinding.value == case_type))
        if not targets:
            return []
        rows = self.db.execute(
            select(KnowledgeCheckBinding.scope, KnowledgeEntry)
            .join(KnowledgeEntry, KnowledgeEntry.id == KnowledgeCheckBinding.entry_id)
            .join(KnowledgeCategory, KnowledgeCategory.id == KnowledgeEntry.category_id)
            .where(or_(*targets), KnowledgeEntry.deleted.is_(False), KnowledgeEntry.active.is_(True),
                   KnowledgeEntry.status == 'verified', KnowledgeCategory.active.is_(True),
                   in_force(KnowledgeService(self.db).today()))
        ).all()
        # 模板专属条目排在案由通用条目前，同一条目只取一次。
        rows.sort(key=lambda item: (item[0] != 'TEMPLATE', item[1].title, item[1].id))
        seen, entries = set(), []
        for _scope, entry in rows:
            if entry.id not in seen:
                seen.add(entry.id)
                entries.append(entry)
        return entries

    def _stats(self, keys):
        """每条问法：在多少个案件里展示过、被采纳、被标不适用。"""
        if not keys:
            return {}
        rows = self.db.execute(
            select(KnowledgeSuggestionFeedback.suggestion_key, func.count(),
                   func.sum(case((KnowledgeSuggestionFeedback.decision == 'ADOPTED', 1), else_=0)),
                   func.sum(case((KnowledgeSuggestionFeedback.decision == 'NOT_APPLICABLE', 1), else_=0)))
            .where(KnowledgeSuggestionFeedback.suggestion_key.in_(keys))
            .group_by(KnowledgeSuggestionFeedback.suggestion_key)
        ).all()
        return {key: (int(shown), int(adopted or 0), int(dismissed or 0)) for key, shown, adopted, dismissed in rows}

    def _anchor(self, case_id, element_key, question):
        """采纳后的题插在哪：本要素最后一道正文题之后；否则当前题（正文）之后；否则交给后端落到正文末尾。"""
        if element_key:
            row = self.db.scalar(
                select(CaseQuestion.id).where(
                    CaseQuestion.case_id == case_id, CaseQuestion.element_key == element_key,
                    CaseQuestion.active.is_(True), CaseQuestion.section_type == 'BODY',
                ).order_by(CaseQuestion.sort_order.desc()).limit(1))
            if row:
                return row
        if question is not None and question.section_type == 'BODY' and question.active:
            return question.id
        return None

    def recommend(self, case_id, *, question_id=None, text=None, limit=3, actor_id=None):
        from app.services.knowledge_checks import KnowledgeCheckService
        from app.services.knowledge_service import KnowledgeService

        case_repo.get(self.db, case_id)
        KnowledgeCheckService(self.db).ensure_bundled_rules()
        scope = self._case_scope(case_id)
        question = self.db.get(CaseQuestion, question_id) if question_id else None
        if question is not None and question.case_id != case_id:
            question = None
        labels = {item['key']: item['label'] for item in scope['elements']}
        unconfirmed = [item['key'] for item in scope['elements']
                       if (fact := scope['facts'].get(item['key'])) is not None and fact.status in UNCONFIRMED]
        current = question.element_key if question is not None else None
        order = ([current] if current in unconfirmed else []) + [key for key in unconfirmed if key != current]

        candidates: list[dict] = []
        for entry in self._bound_entries(scope['templateKey'], scope['caseType']):
            for element_key, phrase in parse_suggestions(entry.content):
                if element_key in labels:
                    candidates.append(dict(entry=entry, elementKey=element_key, text=phrase, reason='ELEMENT'))
        # 当前题与刚才的回答匹配到的通用条目：问法不带要素标记的，归到当前题的要素。
        if question is not None or (text or '').strip():
            knowledge = KnowledgeService(self.db)
            for match in knowledge.guidance_for(case_id=case_id, question_id=question.id if question else None,
                                                text=text, limit=3):
                entry = self.db.get(KnowledgeEntry, match['id'])
                for element_key, phrase in parse_suggestions(entry.content):
                    if element_key is None:
                        candidates.append(dict(entry=entry, elementKey=current, text=phrase, reason='CONTEXT'))

        decided = dict(self.db.execute(
            select(KnowledgeSuggestionFeedback.suggestion_key, KnowledgeSuggestionFeedback.decision)
            .where(KnowledgeSuggestionFeedback.case_id == case_id,
                   KnowledgeSuggestionFeedback.decision.is_not(None))
        ).all())
        asked = list(self.db.scalars(select(CaseQuestion.text).where(
            CaseQuestion.case_id == case_id, CaseQuestion.active.is_(True))))
        for item in candidates:
            item['key'] = suggestion_key(item['entry'].id, item['text'])
        stats = self._stats(list({item['key'] for item in candidates}))

        def usable(item, chosen):
            return (item['key'] not in decided
                    and not any(similar_question(item['text'], other) for other in asked)
                    and all(item['key'] != other['key'] and not similar_question(item['text'], other['text'])
                            for other in chosen))

        def rank(item):
            # 只看民警做过决定的次数：平滑后的采纳率。没有决定时保持规则原顺序，
            # 仅仅展示过不扣分，否则每次刷新都会换一批。
            _shown, adopted, dismissed = stats.get(item['key'], (0, 0, 0))
            return -(adopted + 1) / (adopted + dismissed + 2)

        chosen: list[dict] = []
        for element_key in order + ([current] if current not in order else []):
            group = sorted((item for item in candidates if item['elementKey'] == element_key), key=rank)
            for item in group:
                if len(chosen) >= limit:
                    break
                if usable(item, chosen):
                    chosen.append(item)
        focus_key = order[0] if order else None

        now = _now()
        results = []
        for item in chosen:
            entry = item['entry']
            anchor = self._anchor(case_id, item['elementKey'], question)
            row = self.db.scalar(select(KnowledgeSuggestionFeedback).where(
                KnowledgeSuggestionFeedback.case_id == case_id,
                KnowledgeSuggestionFeedback.suggestion_key == item['key']))
            if row is None:
                self.db.add(KnowledgeSuggestionFeedback(
                    id=str(uuid4()), case_id=case_id, suggestion_key=item['key'], entry_id=entry.id,
                    entry_version=entry.current_version, element_key=item['elementKey'], suggestion_text=item['text'],
                    anchor_question_id=anchor, shown_at=now, shown_by=actor_id,
                ))
            elif row.decision is None:
                row.anchor_question_id = anchor
                row.entry_version = entry.current_version
            shown, adopted, dismissed = stats.get(item['key'], (0, 0, 0))
            results.append({
                'key': item['key'], 'text': item['text'], 'elementKey': item['elementKey'],
                'elementLabel': labels.get(item['elementKey'] or '', ''), 'reason': item['reason'],
                'entryId': entry.id, 'entryTitle': entry.title, 'entryVersion': entry.current_version,
                'sourceRef': entry.source_ref,
                'usage': {'shown': shown, 'adopted': adopted, 'notApplicable': dismissed},
            })
        self.db.flush()

        focus = None
        if focus_key:
            fact = scope['facts'][focus_key]
            focus = {
                'elementKey': focus_key, 'label': labels.get(focus_key, focus_key), 'status': fact.status,
                'statusText': UNCONFIRMED.get(fact.status, ''), 'hint': fact.suggestion or DEFAULT_HINT,
            }
        return {
            'caseId': case_id, 'templateTitle': scope['templateTitle'], 'focus': focus,
            'pendingElements': [{'elementKey': key, 'label': labels.get(key, key)} for key in order],
            'suggestions': results,
        }

    # ------------------------------------------------------------ 反馈

    def feedback(self, case_id, key, action, *, actor_id=None):
        from app.services.template_workspace_service import TemplateWorkspaceService

        action = str(action or '').upper()
        if action not in DECISIONS:
            raise DomainError('INVALID_SUGGESTION_ACTION', 'action 只能是 ADOPTED 或 NOT_APPLICABLE', 400)
        case_repo.get(self.db, case_id)
        row = self.db.scalar(select(KnowledgeSuggestionFeedback).where(
            KnowledgeSuggestionFeedback.case_id == case_id, KnowledgeSuggestionFeedback.suggestion_key == key))
        if row is None:
            raise DomainError('SUGGESTION_NOT_FOUND', '本案没有这条推荐追问', 404)
        if row.decision == action:
            return self._row_dict(row)
        if row.decision == 'ADOPTED':
            raise DomainError('SUGGESTION_ALREADY_ADOPTED', '这条追问已采纳成题，如不需要请删除该题', 409)
        if action == 'ADOPTED':
            from app.services.template_catalog_service import get_case_elements

            anchor = self.db.get(CaseQuestion, row.anchor_question_id) if row.anchor_question_id else None
            after = anchor.id if anchor is not None and anchor.active and anchor.section_type != 'CLOSING' else None
            elements = get_case_elements(self.db, case_id)
            allowed = {item['key'] for item in elements} if elements is not None else set(CORE_FACT_KEYS)
            created = TemplateWorkspaceService(self.db).add_case_question(
                case_id, text=row.suggestion_text, source='LIVE', after_question_id=after,
                element_key=row.element_key if row.element_key in allowed else None,
            )
            row.created_question_id = created['id']
        row.decision = action
        row.decided_at = _now()
        row.decided_by = actor_id
        self.db.flush()
        audit_repo.add(
            self.db, case_id=case_id,
            action='KNOWLEDGE_SUGGESTION_ADOPT' if action == 'ADOPTED' else 'KNOWLEDGE_SUGGESTION_DISMISS',
            target_type='KNOWLEDGE_SUGGESTION', target_id=row.id,
            after={'entryId': row.entry_id, 'entryVersion': row.entry_version, 'elementKey': row.element_key,
                   'questionId': row.created_question_id},
        )
        return self._row_dict(row)

    @staticmethod
    def _row_dict(row):
        return {
            'key': row.suggestion_key, 'decision': row.decision, 'entryId': row.entry_id,
            'entryVersion': row.entry_version, 'elementKey': row.element_key, 'createdQuestionId': row.created_question_id,
        }

    # ------------------------------------------------------------ 统计

    def usage_by_entry(self):
        """每个条目：在多少个案件里展示过、被采纳、被标不适用（按案件计，不按点击次数）。"""
        rows = self.db.execute(
            select(KnowledgeSuggestionFeedback.entry_id, func.count(),
                   func.sum(case((KnowledgeSuggestionFeedback.decision == 'ADOPTED', 1), else_=0)),
                   func.sum(case((KnowledgeSuggestionFeedback.decision == 'NOT_APPLICABLE', 1), else_=0)))
            .where(KnowledgeSuggestionFeedback.entry_id.is_not(None))
            .group_by(KnowledgeSuggestionFeedback.entry_id)
        ).all()
        return {entry_id: {'shown': int(shown), 'adopted': int(adopted or 0), 'notApplicable': int(dismissed or 0)}
                for entry_id, shown, adopted, dismissed in rows}

    def entry_usage(self, entry_id):
        """一个条目下每条问法的使用情况，供管理员判断哪些问法该保留或优化。"""
        rows = self.db.execute(
            select(KnowledgeSuggestionFeedback.suggestion_text, KnowledgeSuggestionFeedback.element_key, func.count(),
                   func.sum(case((KnowledgeSuggestionFeedback.decision == 'ADOPTED', 1), else_=0)),
                   func.sum(case((KnowledgeSuggestionFeedback.decision == 'NOT_APPLICABLE', 1), else_=0)))
            .where(KnowledgeSuggestionFeedback.entry_id == entry_id)
            .group_by(KnowledgeSuggestionFeedback.suggestion_key)
            .order_by(func.count().desc())
        ).all()
        return [{'text': text, 'elementKey': element_key, 'shown': int(shown), 'adopted': int(adopted or 0),
                 'notApplicable': int(dismissed or 0)}
                for text, element_key, shown, adopted, dismissed in rows]
