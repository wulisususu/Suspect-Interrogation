"""Obsidian Vault 解析与单向导入。

只依赖标准库：仓库的运行依赖里没有 PyYAML，因此这里实现一个**受限**的
Frontmatter 解析器，只接受 `obsidian-vault/README.md` 里公开的那几种写法
（标量、标量列表、单层对象列表）。超出范围的结构不猜测，直接记为警告，
由报告暴露给使用者。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.catalog_models import (
    AsrTermCorrection,
    KnowledgeCategory,
    KnowledgeEntry,
    KnowledgeEntryLink,
    KnowledgeSyncRun,
)
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo

UID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{2,63}$')
LINK_PATTERN = re.compile(r'\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]')
FRONTMATTER_KEYS = {
    'uid', 'title', 'category', 'kind', 'status', 'version',
    'keywords', 'source', 'corrections',
}
DEFAULT_CATEGORY = '问话要点'
VALID_STATUS = {'verified', 'pending'}
VALID_KINDS = {'faq', 'wiki'}
SKIP_DIRS = {'raw'}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def parse_frontmatter(text: str) -> tuple[dict, str, list[str]]:
    """返回 (frontmatter 字典, 正文, 警告列表)。"""
    warnings: list[str] = []
    if not text.startswith('---'):
        return {}, text, ['缺少 frontmatter']
    lines = text.splitlines()
    if lines[0].strip() != '---':
        return {}, text, ['frontmatter 起始行不规范']
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == '---':
            end = index
            break
    if end is None:
        return {}, text, ['frontmatter 未闭合']

    data: dict = {}
    block = lines[1:end]
    index = 0
    while index < len(block):
        raw = block[index]
        stripped = raw.strip()
        if not stripped or stripped.startswith('#'):
            index += 1
            continue
        match = re.match(r'^([A-Za-z_][\w-]*):\s*(.*)$', raw)
        if not match:
            warnings.append(f'无法解析的 frontmatter 行：{stripped[:60]}')
            index += 1
            continue
        key, rest = match.group(1), match.group(2).strip()
        if key not in FRONTMATTER_KEYS:
            warnings.append(f'未知字段 {key}（已忽略）')
            index += 1
            continue
        if rest:
            data[key] = _unquote(rest)
            index += 1
            continue
        # 空值 → 开始列表；支持标量列表与单层对象列表
        items: list = []
        index += 1
        current_map: dict | None = None
        while index < len(block):
            line = block[index]
            if not line.strip():
                index += 1
                continue
            if not line.lstrip().startswith('-'):
                break
            item_text = line.lstrip()[1:].strip()
            index += 1
            if not item_text:
                continue
            if ':' in item_text:
                name, value = item_text.split(':', 1)
                current_map = {name.strip(): _unquote(value)}
                items.append(current_map)
            else:
                if current_map is not None:
                    current_map = None
                items.append(_unquote(item_text))
            # 单层对象列表的续行（缩进且非 '-'）
            while index < len(block) and current_map is not None:
                follow = block[index]
                if not follow.strip() or follow.lstrip().startswith('-'):
                    break
                follow_match = re.match(r'^\s+([A-Za-z_][\w-]*):\s*(.*)$', follow)
                if not follow_match:
                    break
                current_map[follow_match.group(1)] = _unquote(follow_match.group(2))
                index += 1
        data[key] = items
    return data, '\n'.join(lines[end + 1:]).strip(), warnings


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@dataclass
class VaultNote:
    relative_path: str
    sha256: str
    uid: str
    title: str
    category: str
    kind: str
    status: str
    keywords: list[str]
    source_ref: str | None
    corrections: list[dict]
    body: str
    warnings: list[str] = field(default_factory=list)


def load_note(path: Path, root: Path) -> tuple[VaultNote | None, str | None]:
    raw = path.read_text(encoding='utf-8')
    data, body, warnings = parse_frontmatter(raw)
    relative = path.relative_to(root).as_posix()
    kind = str(data.get('kind') or '').strip().lower()
    if kind not in VALID_KINDS:
        kind = 'faq' if '/dict/faq/' in f'/{relative}' else 'wiki'
    uid = str(data.get('uid') or '').strip()
    if not uid:
        return None, f'{relative}: 缺少 uid'
    if not UID_PATTERN.match(uid):
        return None, f'{relative}: uid 不合法（需 3–64 位小写字母/数字/连字符）'
    title = str(data.get('title') or '').strip() or path.stem
    category = str(data.get('category') or '').strip() or DEFAULT_CATEGORY
    status = str(data.get('status') or '').strip().lower()
    if status not in VALID_STATUS:
        if status:
            warnings.append(f'未知 status={status}，按 pending 处理')
        status = 'pending'
    keywords = data.get('keywords') or []
    if not isinstance(keywords, list):
        warnings.append('keywords 不是列表，已忽略')
        keywords = []
    keywords = [str(item).strip()[:128] for item in keywords if isinstance(item, (str, int)) and str(item).strip()]
    if not body:
        return None, f'{relative}: 正文为空'
    corrections: list[dict] = []
    raw_corrections = data.get('corrections') or []
    if raw_corrections:
        if kind != 'faq':
            warnings.append('corrections 仅对 faq 生效，已忽略')
        else:
            for item in raw_corrections:
                if not isinstance(item, dict):
                    warnings.append('corrections 项不是对象，已忽略')
                    continue
                wrong = str(item.get('wrong') or '').strip()
                right = str(item.get('right') or '').strip()
                if not wrong or not right or wrong == right:
                    warnings.append(f'无效纠错项 {item}')
                    continue
                corrections.append({'wrong': wrong[:128], 'right': right[:128]})
    return VaultNote(
        relative_path=relative,
        sha256=_sha256(raw),
        uid=uid,
        title=title[:256],
        category=category[:128],
        kind=kind,
        status=status,
        keywords=keywords[:100],
        source_ref=(str(data.get('source')).strip()[:512] if data.get('source') else None),
        corrections=corrections,
        body=body,
        warnings=warnings,
    ), None


def scan_vault(root: Path) -> tuple[list[VaultNote], list[dict]]:
    notes: list[VaultNote] = []
    rejected: list[dict] = []
    if not root.is_dir():
        raise DomainError('KNOWLEDGE_VAULT_NOT_FOUND', f'知识库目录不存在：{root}', 404)
    seen: dict[str, str] = {}
    for path in sorted(root.rglob('*.md')):
        relative = path.relative_to(root)
        if any(part.startswith('.') for part in relative.parts):
            continue
        if relative.parts and relative.parts[0] in SKIP_DIRS:
            continue
        if len(relative.parts) == 1:
            # 根目录只有入口索引，不作为知识条目
            continue
        note, error = load_note(path, root)
        if error:
            rejected.append({'path': relative.as_posix(), 'reason': error})
            continue
        assert note is not None
        if note.uid in seen:
            rejected.append({'path': note.relative_path, 'reason': f'uid 与 {seen[note.uid]} 重复'})
            continue
        seen[note.uid] = note.relative_path
        notes.append(note)
    return notes, rejected


class KnowledgeVaultImporter:
    """按 sha256 增量导入；dry-run 只计算不落库。"""

    def __init__(self, db: Session, service):
        self.db = db
        self.service = service

    def _category_id(self, name: str, report: dict) -> str:
        row = self.db.scalar(select(KnowledgeCategory).where(KnowledgeCategory.name == name))
        if row is not None:
            if not row.active:
                row.active = True
                report['categoriesReactivated'].append(name)
            return row.id
        row = KnowledgeCategory(id=str(uuid4()), name=name, active=True)
        self.db.add(row)
        self.db.flush()
        report['categoriesCreated'].append(name)
        audit_repo.add(self.db, case_id=None, action='KNOWLEDGE_CATEGORY_CREATE',
                       target_type='KNOWLEDGE_CATEGORY', target_id=row.id, after={'name': name, 'source': 'vault'})
        return row.id

    def run(self, root: Path, *, dry_run: bool = False, actor_id: str | None = None) -> dict:
        self.service._seed()
        notes, rejected = scan_vault(root)
        report = {
            'root': str(root),
            'dryRun': bool(dry_run),
            'scanned': len(notes),
            'added': [], 'updated': [], 'unchanged': [], 'disabled': [],
            'conflicts': [], 'rejected': rejected,
            'correctionsAdded': [], 'correctionsUpdated': [],
            'correctionConflicts': [],
            'categoriesCreated': [], 'categoriesReactivated': [],
            'warnings': [],
        }
        run = KnowledgeSyncRun(
            id=str(uuid4()), started_at=utc_now(), dry_run=bool(dry_run), actor_id=actor_id,
            source_root=str(root), report_json='{}',
        )
        if not dry_run:
            self.db.add(run)
            self.db.flush()

        entries = list(self.db.scalars(select(KnowledgeEntry).where(KnowledgeEntry.deleted.is_(False))))
        by_uid = {row.vault_uid: row for row in entries if row.vault_uid}
        by_path = {row.source_path: row for row in entries if row.source_path}
        touched: set[str] = set()

        for note in notes:
            for warning in note.warnings:
                report['warnings'].append(f'{note.relative_path}: {warning}')
            row = by_uid.get(note.uid) or by_path.get(note.relative_path)
            if row is None:
                if dry_run:
                    report['added'].append({'path': note.relative_path, 'uid': note.uid, 'title': note.title})
                    continue
                category_id = self._category_id(note.category, report)
                row = KnowledgeEntry(
                    id=str(uuid4()), category_id=category_id, title=note.title, content=note.body,
                    keywords_json=json.dumps(note.keywords, ensure_ascii=False), active=True, deleted=False,
                    current_version=1, vault_uid=note.uid, kind=note.kind, status=note.status, origin='vault',
                    source_path=note.relative_path, source_sha256=note.sha256, source_ref=note.source_ref,
                )
                self.db.add(row)
                self.db.flush()
                report['added'].append({'path': note.relative_path, 'uid': note.uid, 'title': note.title})
                touched.add(row.id)
                self.service._version(row, 'IMPORT_CREATE')
                continue

            touched.add(row.id)
            if row.origin != 'vault':
                report['conflicts'].append({
                    'path': note.relative_path, 'uid': note.uid,
                    'reason': '数据库中的同路径/同 uid 条目为手工维护（origin=manual），未覆盖',
                })
                continue
            if row.source_sha256 == note.sha256:
                report['unchanged'].append({'path': note.relative_path, 'uid': note.uid})
                continue
            if dry_run:
                report['updated'].append({'path': note.relative_path, 'uid': note.uid, 'title': note.title})
                continue
            row.title = note.title
            row.category_id = self._category_id(note.category, report)
            row.content = note.body
            row.keywords_json = json.dumps(note.keywords, ensure_ascii=False)
            row.kind = note.kind
            row.status = note.status
            row.source_path = note.relative_path
            row.source_sha256 = note.sha256
            row.source_ref = note.source_ref
            if row.vault_uid != note.uid:
                report['warnings'].append(f'{note.relative_path}: uid 由 {row.vault_uid} 变为 {note.uid}，已跟随')
                row.vault_uid = note.uid
            row.active = True
            row.current_version += 1
            self.db.flush()
            report['updated'].append({'path': note.relative_path, 'uid': note.uid, 'title': note.title})
            self.service._version(row, 'IMPORT_UPDATE')

        seen_paths = {note.relative_path for note in notes}
        for row in entries:
            if row.origin != 'vault' or row.source_path is None or row.source_path in seen_paths:
                continue
            if not row.active:
                continue
            if dry_run:
                report['disabled'].append({'path': row.source_path, 'uid': row.vault_uid, 'title': row.title})
                continue
            row.active = False
            row.current_version += 1
            self.db.flush()
            report['disabled'].append({'path': row.source_path, 'uid': row.vault_uid, 'title': row.title})
            self.service._version(row, 'IMPORT_DISABLE')

        if not dry_run:
            self._sync_corrections(notes, report)
            self._sync_links(notes, touched, report)
            self.db.flush()
            run.finished_at = utc_now()
            run.added = len(report['added'])
            run.updated = len(report['updated'])
            run.disabled = len(report['disabled'])
            run.conflicts = len(report['conflicts'])
            run.rejected = len(report['rejected'])
            run.report_json = json.dumps(report, ensure_ascii=False)
            self.db.flush()
            audit_repo.add(
                self.db, case_id=None, action='KNOWLEDGE_IMPORT', actor_id=actor_id,
                target_type='KNOWLEDGE_SYNC', target_id=run.id,
                after={'added': run.added, 'updated': run.updated, 'disabled': run.disabled,
                       'conflicts': run.conflicts, 'rejected': run.rejected, 'root': str(root)},
            )
        report['runId'] = run.id if not dry_run else None
        return report

    def _sync_corrections(self, notes: list[VaultNote], report: dict) -> None:
        active_wrong: set[str] = set()
        for note in notes:
            if not note.corrections:
                continue
            entry = self.db.scalar(select(KnowledgeEntry).where(KnowledgeEntry.vault_uid == note.uid))
            for item in note.corrections:
                active_wrong.add(item['wrong'])
                row = self.db.scalar(select(AsrTermCorrection).where(AsrTermCorrection.wrong_text == item['wrong']))
                if row is None:
                    self.db.add(AsrTermCorrection(
                        id=str(uuid4()), wrong_text=item['wrong'], right_text=item['right'],
                        category='TERM', active=True, entry_id=entry.id if entry else None,
                    ))
                    report['correctionsAdded'].append(item)
                    continue
                if row.right_text != item['right']:
                    report['correctionConflicts'].append({
                        'wrong': item['wrong'], 'kept': row.right_text, 'ignored': item['right'],
                        'reason': '同一误写已有不同更正，保留先导入者',
                    })
                    continue
                if not row.active:
                    row.active = True
                    report['correctionsUpdated'].append(item)
        stale = list(self.db.scalars(select(AsrTermCorrection).where(AsrTermCorrection.active.is_(True))))
        for row in stale:
            if row.entry_id is None:
                continue
            if row.wrong_text not in active_wrong:
                row.active = False
                report['correctionsUpdated'].append({'wrong': row.wrong_text, 'active': False})

    def _sync_links(self, notes: list[VaultNote], touched: set[str], report: dict) -> None:
        title_to_entry = {
            row.title: row.id
            for row in self.db.scalars(select(KnowledgeEntry).where(KnowledgeEntry.deleted.is_(False)))
        }
        for note in notes:
            entry = self.db.scalar(select(KnowledgeEntry).where(KnowledgeEntry.vault_uid == note.uid))
            if entry is None:
                continue
            existing = list(self.db.scalars(select(KnowledgeEntryLink).where(KnowledgeEntryLink.from_entry_id == entry.id)))
            for link in existing:
                self.db.delete(link)
            self.db.flush()
            targets: list[str] = []
            for match in LINK_PATTERN.findall(note.body):
                target = match.strip()[:256]
                if not target or target in targets:
                    continue
                targets.append(target)
                self.db.add(KnowledgeEntryLink(
                    id=str(uuid4()), from_entry_id=entry.id, to_entry_id=title_to_entry.get(target),
                    target_title=target, relation='REFERENCES', created_at=utc_now(),
                ))
            if targets:
                report.setdefault('links', []).append({'entry': note.uid, 'targets': len(targets)})
