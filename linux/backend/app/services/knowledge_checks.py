"""按模板 / 案由加载的定稿校验规则（知识库驱动）。

规则就是知识条目：校验项写在正文的「校验项」小节，随条目一起版本化、溯源；
`knowledge_check_bindings` 只记录条目适用于哪个模板（backendKey）或哪类案由（模板 category）。

校验项写法（每行一项，冒号后是笔录里应能找到的说法，可选 [要素key] 关联模板要素）：

    ## 校验项
    - 锁具情况 [lock]：锁、U型锁、遥控锁
    - 购买凭证：发票、收据、购买凭证

规则只用于 ④ 定稿校验的提示，不阻断定稿、不改笔录。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database.catalog_models import KnowledgeCategory, KnowledgeCheckBinding, KnowledgeEntry
from app.database.session import begin_sqlite_immediate
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.repositories import cases as case_repo

# 仓库自带的 Vault 里的规则笔记；发布目录整体拷贝仓库，生产上同样存在。
BUNDLED_VAULT_ROOT = Path(__file__).resolve().parents[4] / 'obsidian-vault'
BUNDLED_RULES_DIR = 'rules'

TEMPLATE_KEY = re.compile(r'^[A-Z][A-Z0-9_]{0,63}$')
CASE_TYPE = re.compile(r'^[a-z][a-z0-9_-]{0,63}$')
ELEMENT_KEY = re.compile(r'\s*[\[【]([a-z][a-z0-9_-]{0,63})[\]】]\s*')
TERM_SPLIT = re.compile(r'[、，,／/；;|]+')
MAX_ITEMS = 20
MAX_TERMS = 20


def binding_scope(value: str) -> str | None:
    """大写 backendKey → TEMPLATE；小写模板分类 → CASE_TYPE；其余不认。"""
    if TEMPLATE_KEY.match(value):
        return 'TEMPLATE'
    if CASE_TYPE.match(value):
        return 'CASE_TYPE'
    return None


def normalize_bindings(values) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > 50:
        raise DomainError('INVALID_KNOWLEDGE_ENTRY', '适用模板必须是最多 50 项的列表', 400)
    result: list[str] = []
    for raw in values:
        value = str(raw or '').strip()
        if not value:
            continue
        if binding_scope(value) is None:
            raise DomainError('INVALID_KNOWLEDGE_ENTRY', f'适用模板 {value[:64]} 不是模板 backendKey 或案由分类', 400)
        if value not in result:
            result.append(value)
    return result


def parse_check_items(content: str) -> list[dict]:
    """从条目正文的「校验项」小节解析出校验项；没有该小节的条目不产生校验。"""
    items: list[dict] = []
    in_section = False
    for line in (content or '').splitlines():
        stripped = line.strip()
        if stripped.startswith('#'):
            if in_section:
                break
            in_section = '校验项' in stripped
            continue
        if not in_section or not stripped.startswith(('-', '*', '·')):
            continue
        text = stripped.lstrip('-*· ').strip()
        if not text:
            continue
        colon = re.search(r'[：:]', text)
        label, rest = (text[:colon.start()], text[colon.end():]) if colon else (text, '')
        element_key = None
        match = ELEMENT_KEY.search(label)
        if match:
            element_key = match.group(1)
            label = ELEMENT_KEY.sub(' ', label)
        label = label.strip()[:64]
        if not label:
            continue
        terms = [term.strip()[:32] for term in TERM_SPLIT.split(rest) if term.strip()][:MAX_TERMS] or [label]
        items.append({'label': label, 'terms': list(dict.fromkeys(terms)), 'elementKey': element_key})
        if len(items) >= MAX_ITEMS:
            break
    return items


class KnowledgeCheckService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------- 绑定

    def bindings(self, entry_id: str) -> list[str]:
        rows = self.db.scalars(
            select(KnowledgeCheckBinding)
            .where(KnowledgeCheckBinding.entry_id == entry_id)
            .order_by(KnowledgeCheckBinding.scope.desc(), KnowledgeCheckBinding.value)
        )
        return [row.value for row in rows]

    def set_bindings(self, entry_id: str, values, *, audit: bool = True) -> list[str]:
        wanted = normalize_bindings(values)
        current = list(self.db.scalars(select(KnowledgeCheckBinding).where(KnowledgeCheckBinding.entry_id == entry_id)))
        if sorted(row.value for row in current) == sorted(wanted):
            return self.bindings(entry_id)
        for row in current:
            self.db.delete(row)
        self.db.flush()
        now = datetime.now(timezone.utc)
        for value in wanted:
            self.db.add(KnowledgeCheckBinding(id=str(uuid4()), entry_id=entry_id, scope=binding_scope(value),
                                              value=value, created_at=now))
        self.db.flush()
        if audit:
            audit_repo.add(self.db, case_id=None, action='KNOWLEDGE_CHECK_BIND', target_type='KNOWLEDGE_ENTRY',
                           target_id=entry_id, before={'templates': sorted(row.value for row in current)},
                           after={'templates': wanted})
        return self.bindings(entry_id)

    # --------------------------------------------------------- 内置规则

    def _missing_bundled(self, notes):
        known = set(self.db.scalars(select(KnowledgeEntry.vault_uid).where(
            KnowledgeEntry.vault_uid.in_([note.uid for note in notes]))))
        known_paths = set(self.db.scalars(select(KnowledgeEntry.source_path).where(
            KnowledgeEntry.source_path.in_([note.relative_path for note in notes]))))
        return [note for note in notes if note.uid not in known and note.relative_path not in known_paths]

    def ensure_bundled_rules(self, root: Path | None = None) -> list[str]:
        """把仓库 Vault 里的规则笔记补进库（只补从未入库的 uid，删掉/停用过的不复活）。

        入库后 origin=vault、带 source_path 与 sha256，后续由正常的 Vault 导入接管更新与停用。
        """
        from app.services.knowledge_service import KnowledgeService
        from app.services.knowledge_vault import load_note

        root = root or BUNDLED_VAULT_ROOT
        rules_dir = root / BUNDLED_RULES_DIR
        if not rules_dir.is_dir():
            return []
        notes = []
        for path in sorted(rules_dir.rglob('*.md')):
            note, error = load_note(path, root)
            if note is not None and error is None:
                notes.append(note)
        if not notes:
            return []
        if not self._missing_bundled(notes):
            return []
        # 同时打开案件的两个请求都会走到这里：拿写锁后重查，后到的请求不再重复入库。
        begin_sqlite_immediate(self.db)
        missing = self._missing_bundled(notes)
        if not missing:
            return []
        knowledge = KnowledgeService(self.db)
        knowledge._seed()
        created: list[str] = []
        for note in missing:
            category = self.db.scalar(select(KnowledgeCategory).where(KnowledgeCategory.name == note.category))
            if category is None:
                category = KnowledgeCategory(id=str(uuid4()), name=note.category, active=True)
                self.db.add(category)
                self.db.flush()
            row = KnowledgeEntry(
                id=str(uuid4()), category_id=category.id, title=note.title, content=note.body,
                keywords_json=json.dumps(note.keywords, ensure_ascii=False), active=True, deleted=False,
                current_version=1, vault_uid=note.uid, kind=note.kind, status=note.status, origin='vault',
                source_path=note.relative_path, source_sha256=note.sha256, source_ref=note.source_ref,
            )
            self.db.add(row)
            self.db.flush()
            self.set_bindings(row.id, [value for value in note.templates if binding_scope(value)], audit=False)
            knowledge._version(row, 'BUNDLE_CREATE')
            created.append(note.uid)
        return created

    # ----------------------------------------------------------- 加载

    def rules_for_template(self, template_key: str | None, case_type: str | None = None) -> list[dict]:
        targets = []
        if template_key:
            targets.append((KnowledgeCheckBinding.scope == 'TEMPLATE') & (KnowledgeCheckBinding.value == template_key))
        if case_type:
            targets.append((KnowledgeCheckBinding.scope == 'CASE_TYPE') & (KnowledgeCheckBinding.value == case_type))
        if not targets:
            return []
        rows = self.db.execute(
            select(KnowledgeCheckBinding, KnowledgeEntry, KnowledgeCategory)
            .join(KnowledgeEntry, KnowledgeEntry.id == KnowledgeCheckBinding.entry_id)
            .join(KnowledgeCategory, KnowledgeCategory.id == KnowledgeEntry.category_id)
            .where(or_(*targets), KnowledgeEntry.deleted.is_(False), KnowledgeEntry.active.is_(True),
                   KnowledgeEntry.status == 'verified', KnowledgeCategory.active.is_(True))
        ).all()
        # 模板专属规则排在案由通用规则前；同一条目同时绑了两者只出现一次。
        rows.sort(key=lambda item: (item[0].scope != 'TEMPLATE', item[1].title, item[1].id))
        rules: list[dict] = []
        seen: set[str] = set()
        for binding, entry, category in rows:
            if entry.id in seen:
                continue
            seen.add(entry.id)
            items = parse_check_items(entry.content)
            if not items:
                continue
            rules.append({
                'entryId': entry.id, 'title': entry.title, 'version': entry.current_version,
                'status': entry.status, 'origin': entry.origin, 'categoryName': category.name,
                'sourceRef': entry.source_ref, 'sourcePath': entry.source_path, 'vaultUid': entry.vault_uid,
                'matchedBy': {'scope': binding.scope, 'value': binding.value},
                'items': [{**item, 'key': f'{entry.id}#{index}'} for index, item in enumerate(items)],
            })
        return rules

    def rules_for_case(self, case_id: str) -> dict:
        from app.services.template_catalog_service import get_case_snapshot

        case_repo.get(self.db, case_id)
        self.ensure_bundled_rules()
        snapshot = get_case_snapshot(self.db, case_id)
        if snapshot is None or snapshot.blank:
            return {'caseId': case_id, 'templateKey': snapshot.template_key if snapshot else None,
                    'caseType': None, 'rules': []}
        catalog = json.loads(snapshot.snapshot_json).get('catalog') or {}
        case_type = catalog.get('category') or None
        return {
            'caseId': case_id, 'templateKey': snapshot.template_key, 'caseType': case_type,
            'rules': self.rules_for_template(snapshot.template_key, case_type),
        }
