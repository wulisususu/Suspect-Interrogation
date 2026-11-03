"""已结案案件的经验提炼与审核入库（Task 02）。

闭环的第二段：积累经验 → 审核经验 → 改进辅助。

- 提炼：只看已冻结 / 已签名 / 已出报告、未作废的案件里，民警在问话中**自己补充**的正文题
  （LIVE 题，排除采纳推荐生成的题），而且确实问过。模板原有的题、知识库里已有的问法不重复提炼。
  只读问题文字，不读当事人的回答；不用模型，规则脱敏（人名、车牌、证件号、电话、日期时刻、金额、
  门牌号等替换成通用说法），脱敏结果仍需人工核对。
- 合并：同一适用范围（模板优先，其次案由）里脱敏后相同或相近的问法合成一条候选，记下来自几个案件。
- 审核：管理员可改写问法、调整要素后通过，或驳回。通过才写进该范围的「办案经验问法」条目的
  「建议问法」小节（新版本、已审核、绑定模板），下一个同类案件即可被推荐；驳回的不再出现。
- 留痕：每次通过 / 驳回写审计；条目每次追加都有版本记录。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.catalog_models import (
    KnowledgeCheckBinding,
    KnowledgeEntry,
    KnowledgeExperienceCandidate,
    KnowledgeExperienceSource,
    KnowledgeSuggestionFeedback,
)
from app.database.models import Case, CaseQuestion, Fact, Person
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.services.knowledge_matching import normalize, similar_question
from app.services.knowledge_suggestions import CORE_FACT_KEYS, UNCONFIRMED, parse_suggestions
from app.services.serializers import iso_utc

COMPLETED_STATES = ('FROZEN', 'SIGNED', 'REPORT_GENERATED')
STATUSES = ('PENDING', 'APPROVED', 'REJECTED')
MIN_CHARS, MAX_CHARS = 4, 120
EXPERIENCE_CATEGORY_ID = 'questioning'
EXPERIENCE_SOURCE_REF = '经验提炼：已结案案件中民警补充的问法，经人工审核发布'
PLACEHOLDER_NAMES = {'待录入', '当前警官', '未知', '无'}

# (说明, 正则, 替换)。顺序有讲究：先长后短，证件号先于电话、电话先于长数字。
MASK_RULES = [
    ('证件号', re.compile(r'(?<![0-9])\d{17}[\dXx](?![0-9])'), '某证件号'),
    ('电话', re.compile(r'(?<![0-9])1[3-9]\d{9}(?![0-9])'), '某号码'),
    ('车牌', re.compile(r'[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Za-z][·\s]?[A-Za-z0-9]{4,6}'), '某车牌'),
    ('日期', re.compile(r'(?:\d{2,4}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*[日号]'), '当天'),
    ('日期', re.compile(r'\d{4}\s*年(?:\s*\d{1,2}\s*月)?'), '当时'),
    ('时刻', re.compile(r'\d{1,2}\s*[点時时:：]\s*(?:\d{1,2}\s*分?|半|一刻|三刻)?'), '那个时间'),
    ('金额', re.compile(r'\d+(?:\.\d+)?\s*(?:万元|万|元|块钱|块)'), '若干元'),
    ('门牌', re.compile(r'[一-龥]{1,8}(?:路|街|巷|大道|弄)\s*\d+\s*号'), lambda m: _street(m.group(0))),
    ('门牌', re.compile(r'\d+\s*(?:号楼|栋|幢|单元|室)'), '某处'),
    ('编号', re.compile(r'\d{5,}'), '某编号'),
]


# 门牌正则会向前多吃字（「停在文三路12号」），这些字之后才算路名。
STREET_LEADERS = '在到去从把的了和与回住往向于是'


def _street(matched: str) -> str:
    cut = max(matched.rfind(char) for char in STREET_LEADERS)
    return matched[:cut + 1] + '某地址'


def _now():
    return datetime.now(timezone.utc)


def mask_question(text: str, names=(), addresses=()) -> tuple[str, list[str]]:
    """规则脱敏：返回 (脱敏后的问法, 用到的规则说明)。只做替换，不改写句意。"""
    value = re.sub(r'\s+', ' ', str(text or '')).strip()
    applied: list[str] = []
    for address in sorted({a.strip() for a in addresses if a and len(a.strip()) >= 4}, key=len, reverse=True):
        if address in value:
            value = value.replace(address, '某地址')
            applied.append('地址')
    for name in sorted({n.strip() for n in names if n and n.strip() not in PLACEHOLDER_NAMES and len(n.strip()) >= 2},
                       key=len, reverse=True):
        if name in value:
            value = value.replace(name, '某某')
            applied.append('人名')
    for label, pattern, replacement in MASK_RULES:
        value, count = pattern.subn(replacement, value)
        if count:
            applied.append(label)
    return value.strip(), list(dict.fromkeys(applied))


def dedupe_key(text: str) -> str:
    return hashlib.sha256(normalize(text).text.encode()).hexdigest()[:32]


def insert_suggestion_line(content: str, line: str) -> str:
    """把一行问法追加到「建议问法」小节末尾；没有这个小节就在正文末尾新建。"""
    lines = (content or '').rstrip('\n').split('\n')
    start = next((i for i, raw in enumerate(lines) if raw.strip().startswith('#') and '建议问法' in raw), None)
    if start is None:
        return '\n'.join(lines + ['', '## 建议问法', '', line]) + '\n'
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith('#')), len(lines))
    last_item = max((i for i in range(start + 1, end) if lines[i].strip().startswith(('-', '*', '·'))), default=None)
    at = last_item + 1 if last_item is not None else start + 1
    insert = [line] if last_item is not None else ['', line]
    return '\n'.join(lines[:at] + insert + lines[at:]) + '\n'


class KnowledgeExperienceService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------ 范围

    def _scope(self, case_id):
        from app.services.template_catalog_service import get_case_snapshot

        snapshot = get_case_snapshot(self.db, case_id)
        if snapshot is None or snapshot.blank:
            return {'scopeKey': '', 'templateKey': None, 'caseType': None, 'title': '通用（未选模板）', 'elements': None}
        data = json.loads(snapshot.snapshot_json)
        catalog = data.get('catalog') or {}
        elements = (data.get('structure') or {}).get('elements') or []
        return {
            'scopeKey': snapshot.template_key or catalog.get('category') or '',
            'templateKey': snapshot.template_key,
            'caseType': catalog.get('category') or None,
            'title': catalog.get('title') or snapshot.template_key or '',
            'elements': [{'key': item['key'], 'label': item.get('label') or item['key']} for item in elements],
        }

    def _completed_cases(self):
        return list(self.db.scalars(
            select(Case).where(Case.workflow_state.in_(COMPLETED_STATES), Case.document_status != 'VOIDED')
            .order_by(Case.created_at, Case.id)))

    def _known_phrases(self, scope):
        """该范围内知识库已有的问法（绑定到本模板 / 案由的有效条目），已有的不再提炼。"""
        values = [value for value in (scope['templateKey'], scope['caseType']) if value]
        if not values:
            return []
        entries = self.db.scalars(
            select(KnowledgeEntry).join(KnowledgeCheckBinding, KnowledgeCheckBinding.entry_id == KnowledgeEntry.id)
            .where(KnowledgeCheckBinding.value.in_(values), KnowledgeEntry.deleted.is_(False)))
        return [text for entry in entries for _element, text in parse_suggestions(entry.content)]

    # ------------------------------------------------------------ 提炼

    def harvest(self):
        """扫描已结案案件，把民警自己补充的问法提炼成待审核候选。可重复执行：每道题只提炼一次。"""
        from app.database.session import begin_sqlite_immediate
        from app.services.knowledge_checks import KnowledgeCheckService

        begin_sqlite_immediate(self.db)  # 两个页面同时打开时不重复提炼同一道题
        KnowledgeCheckService(self.db).ensure_bundled_rules()
        harvested = set(self.db.execute(
            select(KnowledgeExperienceSource.case_id, KnowledgeExperienceSource.question_id)).all())
        adopted = set(self.db.scalars(select(KnowledgeSuggestionFeedback.created_question_id)
                                      .where(KnowledgeSuggestionFeedback.created_question_id.is_not(None))))
        scopes: dict[str, dict] = {}
        added_sources = new_candidates = scanned = 0
        now = _now()
        for case in self._completed_cases():
            questions = list(self.db.scalars(select(CaseQuestion).where(
                CaseQuestion.case_id == case.id, CaseQuestion.active.is_(True))))
            live = [q for q in questions
                    if q.source == 'LIVE' and q.section_type == 'BODY' and q.id not in adopted
                    and (case.id, q.id) not in harvested
                    and (q.first_asked_at is not None or (q.formal_answer_text or '').strip())]
            scanned += 1
            if not live:
                continue
            scope = self._scope(case.id)
            cached = scopes.setdefault(scope['scopeKey'], {
                'known': self._known_phrases(scope),
                'candidates': list(self.db.scalars(select(KnowledgeExperienceCandidate).where(
                    KnowledgeExperienceCandidate.scope_key == scope['scopeKey']))),
            })
            template_texts = [q.text for q in questions if q.source != 'LIVE']
            persons = list(self.db.scalars(select(Person).where(Person.case_id == case.id)))
            names = [case.suspect_name, case.officer_name] + [p.name for p in persons]
            addresses = [p.address for p in persons]
            for question in live:
                masked, rules = mask_question(question.text, names, addresses)
                if not (MIN_CHARS <= len(masked) <= MAX_CHARS):
                    continue
                if any(similar_question(masked, other) or similar_question(question.text, other)
                       for other in template_texts + cached['known']):
                    continue
                key = dedupe_key(masked)
                candidate = next((c for c in cached['candidates'] if c.dedupe_key == key), None) or next(
                    (c for c in cached['candidates'] if similar_question(masked, c.proposed_text)), None)
                if candidate is None:
                    candidate = KnowledgeExperienceCandidate(
                        id=str(uuid4()), scope_key=scope['scopeKey'], scope_title=scope['title'][:128],
                        template_key=scope['templateKey'], case_type=scope['caseType'],
                        element_key=question.element_key, dedupe_key=key, proposed_text=masked[:300],
                        mask_rules_json=json.dumps(rules, ensure_ascii=False), status='PENDING',
                    )
                    self.db.add(candidate)
                    cached['candidates'].append(candidate)
                    new_candidates += 1
                elif candidate.element_key is None and question.element_key:
                    candidate.element_key = question.element_key
                self.db.add(KnowledgeExperienceSource(
                    id=str(uuid4()), candidate_id=candidate.id, case_id=case.id, question_id=question.id,
                    original_text=question.text[:300], created_at=now,
                ))
                added_sources += 1
        self.db.flush()
        if added_sources:
            audit_repo.add(self.db, case_id=None, action='KNOWLEDGE_EXPERIENCE_HARVEST',
                           target_type='KNOWLEDGE_EXPERIENCE', target_id=None,
                           after={'cases': scanned, 'sources': added_sources, 'candidates': new_candidates})
        return {'scannedCases': scanned, 'addedSources': added_sources, 'newCandidates': new_candidates}

    # ------------------------------------------------------------ 查看

    def _gaps(self, cases):
        """各范围的已结案件数，以及结案时仍未确认的要素（容易漏问的地方）。"""
        result: dict[str, dict] = {}
        for case in cases:
            scope = self._scope(case.id)
            facts = {row.fact_key: row for row in self.db.scalars(select(Fact).where(Fact.case_id == case.id))}
            elements = scope['elements']
            if elements is None:
                elements = [{'key': key, 'label': facts[key].label} for key in CORE_FACT_KEYS if key in facts]
            item = result.setdefault(scope['scopeKey'], {
                'scopeKey': scope['scopeKey'], 'title': scope['title'], 'templateKey': scope['templateKey'],
                'caseType': scope['caseType'], 'closedCases': 0, 'elements': {}, 'gaps': {},
            })
            item['closedCases'] += 1
            for element in elements:
                item['elements'].setdefault(element['key'], element['label'])
                fact = facts.get(element['key'])
                if fact is not None and fact.status in UNCONFIRMED:
                    item['gaps'][element['key']] = item['gaps'].get(element['key'], 0) + 1
        return result

    def _candidate_dict(self, row, sources, labels):
        return {
            'id': row.id, 'scopeKey': row.scope_key, 'scopeTitle': row.scope_title,
            'templateKey': row.template_key, 'caseType': row.case_type,
            'elementKey': row.element_key, 'elementLabel': labels.get(row.element_key or '', ''),
            'proposedText': row.proposed_text, 'maskRules': json.loads(row.mask_rules_json or '[]'),
            'status': row.status, 'reviewedBy': row.reviewed_by, 'reviewedAt': iso_utc(row.reviewed_at),
            'reviewNote': row.review_note, 'publishedText': row.published_text,
            'publishedEntryId': row.published_entry_id, 'publishedVersion': row.published_version,
            'caseCount': len({source.case_id for source in sources}),
            'sources': [{'caseId': source.case_id, 'questionId': source.question_id, 'originalText': source.original_text,
                         'harvestedAt': iso_utc(source.created_at)} for source in sources],
            'createdAt': iso_utc(row.created_at),
        }

    def overview(self, *, status=None):
        status = (status or '').upper() or None
        if status is not None and status not in STATUSES:
            raise DomainError('INVALID_EXPERIENCE_STATUS', 'status 只能是 PENDING、APPROVED 或 REJECTED', 400)
        scopes = self._gaps(self._completed_cases())
        statement = select(KnowledgeExperienceCandidate)
        if status:
            statement = statement.where(KnowledgeExperienceCandidate.status == status)
        rows = list(self.db.scalars(statement.order_by(KnowledgeExperienceCandidate.created_at.desc(),
                                                       KnowledgeExperienceCandidate.id)))
        sources: dict[str, list] = {}
        if rows:
            for source in self.db.scalars(select(KnowledgeExperienceSource).where(
                    KnowledgeExperienceSource.candidate_id.in_([row.id for row in rows]))
                    .order_by(KnowledgeExperienceSource.created_at)):
                sources.setdefault(source.candidate_id, []).append(source)
        counts = dict(self.db.execute(select(KnowledgeExperienceCandidate.status, func.count())
                                      .group_by(KnowledgeExperienceCandidate.status)).all())
        candidates = []
        for row in rows:
            labels = scopes.get(row.scope_key, {}).get('elements', {})
            candidates.append(self._candidate_dict(row, sources.get(row.id, []), labels))
        # 多个案件都补问过的排前面：越常见越值得沉淀。
        candidates.sort(key=lambda item: (item['status'] != 'PENDING', -item['caseCount']))
        return {
            'counts': {key: int(counts.get(key, 0)) for key in STATUSES},
            'scopes': [{
                'scopeKey': item['scopeKey'], 'title': item['title'], 'templateKey': item['templateKey'],
                'caseType': item['caseType'], 'closedCases': item['closedCases'],
                'elements': [{'key': key, 'label': label} for key, label in item['elements'].items()],
                'gaps': sorted(({'elementKey': key, 'label': item['elements'].get(key, key), 'cases': count}
                                for key, count in item['gaps'].items()), key=lambda gap: -gap['cases']),
            } for item in sorted(scopes.values(), key=lambda value: -value['closedCases'])],
            'candidates': candidates,
        }

    # ------------------------------------------------------------ 审核

    def _candidate(self, candidate_id):
        row = self.db.get(KnowledgeExperienceCandidate, candidate_id)
        if row is None:
            raise DomainError('EXPERIENCE_CANDIDATE_NOT_FOUND', '候选问法不存在', 404)
        return row

    def _target_entry(self, row):
        """该范围已发布过的「办案经验问法」条目（未删除的最近一条）。"""
        entry_ids = self.db.scalars(
            select(KnowledgeExperienceCandidate.published_entry_id)
            .where(KnowledgeExperienceCandidate.scope_key == row.scope_key,
                   KnowledgeExperienceCandidate.published_entry_id.is_not(None))
            .order_by(KnowledgeExperienceCandidate.reviewed_at.desc()))
        for entry_id in entry_ids:
            entry = self.db.get(KnowledgeEntry, entry_id)
            if entry is not None and not entry.deleted:
                return entry
        return None

    def approve(self, candidate_id, *, text, element_key=None, note=None, actor_id=None):
        from app.database.session import begin_sqlite_immediate
        from app.services.knowledge_service import KnowledgeService

        begin_sqlite_immediate(self.db)
        row = self._candidate(candidate_id)
        if row.status == 'APPROVED':
            raise DomainError('EXPERIENCE_ALREADY_APPROVED', '这条问法已发布；如需修改请到知识条目里编辑', 409)
        phrase = re.sub(r'\s+', ' ', str(text or '')).strip()
        if not (MIN_CHARS <= len(phrase) <= MAX_CHARS):
            raise DomainError('INVALID_EXPERIENCE_TEXT', f'问法需为 {MIN_CHARS}–{MAX_CHARS} 个字', 400)
        element_key = (element_key or '').strip() or None
        if element_key is not None:
            allowed = {item['key'] for item in self._scope_elements(row)}
            if element_key not in allowed:
                raise DomainError('INVALID_EXPERIENCE_ELEMENT', '要素不属于该模板', 400)
        line = f'- [{element_key}] {phrase}' if element_key else f'- {phrase}'
        knowledge = KnowledgeService(self.db)
        entry = self._target_entry(row)
        if entry is None:
            title = f'办案经验问法 · {row.scope_title or "通用"}'
            content = (f'# {title}\n\n从已结案案件中民警补充的问法提炼，经人工审核后发布。'
                       '问法只作提示，由民警决定是否采用。\n\n## 建议问法\n\n' + line + '\n')
            bindings = [value for value in (row.template_key or row.case_type,) if value]
            payload = knowledge.create_entry(
                title=title[:256], category_id=EXPERIENCE_CATEGORY_ID, content=content, keywords=[],
                kind='faq', status='verified', origin='manual', source_ref=EXPERIENCE_SOURCE_REF,
                check_templates=bindings,
            )
        elif any(similar_question(phrase, existing) for _key, existing in parse_suggestions(entry.content)):
            payload = knowledge.detail(entry.id)  # 条目里已有相近问法：不重复追加，直接记为已发布
        else:
            payload = knowledge.update_entry(entry.id, {'content': insert_suggestion_line(entry.content, line)})
        row.status = 'APPROVED'
        row.element_key = element_key
        row.published_text = phrase
        row.published_entry_id = payload['id']
        row.published_version = payload['version']
        row.reviewed_by = actor_id
        row.reviewed_at = _now()
        row.review_note = (note or '').strip()[:300] or None
        self.db.flush()
        audit_repo.add(self.db, case_id=None, action='KNOWLEDGE_EXPERIENCE_APPROVE', actor_id=actor_id,
                       target_type='KNOWLEDGE_EXPERIENCE', target_id=row.id,
                       before={'text': row.proposed_text},
                       after={'text': phrase, 'elementKey': element_key, 'entryId': payload['id'],
                              'entryVersion': payload['version']})
        return {'candidate': self._detail(row), 'entry': payload}

    def reject(self, candidate_id, *, note=None, actor_id=None):
        row = self._candidate(candidate_id)
        if row.status == 'APPROVED':
            raise DomainError('EXPERIENCE_ALREADY_APPROVED', '这条问法已发布；如需撤下请到知识条目里编辑', 409)
        if row.status != 'REJECTED':
            row.status = 'REJECTED'
            row.reviewed_by = actor_id
            row.reviewed_at = _now()
            row.review_note = (note or '').strip()[:300] or None
            self.db.flush()
            audit_repo.add(self.db, case_id=None, action='KNOWLEDGE_EXPERIENCE_REJECT', actor_id=actor_id,
                           target_type='KNOWLEDGE_EXPERIENCE', target_id=row.id,
                           after={'text': row.proposed_text, 'note': row.review_note})
        return self._detail(row)

    def _scope_elements(self, row):
        """候选所在范围的要素（取任一来源案件的模板快照；旧案件为七类核心事实）。"""
        source = self.db.scalar(select(KnowledgeExperienceSource).where(
            KnowledgeExperienceSource.candidate_id == row.id).limit(1))
        if source is None:
            return []
        elements = self._scope(source.case_id)['elements']
        if elements is not None:
            return elements
        facts = {fact.fact_key: fact.label for fact in self.db.scalars(select(Fact).where(Fact.case_id == source.case_id))}
        return [{'key': key, 'label': facts.get(key, key)} for key in CORE_FACT_KEYS]

    def _detail(self, row):
        sources = list(self.db.scalars(select(KnowledgeExperienceSource).where(
            KnowledgeExperienceSource.candidate_id == row.id).order_by(KnowledgeExperienceSource.created_at)))
        labels = {item['key']: item['label'] for item in self._scope_elements(row)}
        return self._candidate_dict(row, sources, labels)
