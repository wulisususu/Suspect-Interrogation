#!/usr/bin/env python3
"""知识库 Vault 导入 CLI（板端可离线运行）。

用法：
  python scripts/knowledge_sync.py --vault /var/lib/suspect-interrogation/knowledge-vault
  python scripts/knowledge_sync.py --vault ... --apply
  python scripts/knowledge_sync.py --vault ... --apply --export-corrections /tmp/corrections.json

默认 dry-run，只打印将要发生的变更。数据库路径取 SUSPECT_DB_PATH 或 --db。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'linux' / 'backend'))

from app.database.session import init_database, make_engine, make_session_factory  # noqa: E402
from app.services.knowledge_service import KnowledgeService  # noqa: E402


def _summary(report: dict) -> str:
    keys = ('added', 'updated', 'unchanged', 'disabled', 'conflicts', 'rejected')
    parts = [f'{key}={len(report.get(key) or [])}' for key in keys]
    corrections = len(report.get('correctionsAdded') or []) + len(report.get('correctionsUpdated') or [])
    parts.append(f'corrections={corrections}')
    return ' '.join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description='导入 Obsidian Vault 到知识库')
    parser.add_argument('--vault', required=True, help='Vault 根目录')
    parser.add_argument('--db', default=os.environ.get('SUSPECT_DB_PATH',
                                                      '/var/lib/suspect-interrogation/interrogation.db'))
    parser.add_argument('--apply', action='store_true', help='真正写入；缺省只做 dry-run')
    parser.add_argument('--actor', default=None, help='操作人警号，写入审计')
    parser.add_argument('--export-corrections', default=None, help='导出 asr-stack corrections.json 的路径')
    parser.add_argument('--json', action='store_true', help='输出完整报告 JSON')
    args = parser.parse_args()

    vault = Path(args.vault).expanduser()
    if not vault.is_dir():
        print(f'知识库目录不存在：{vault}', file=sys.stderr)
        return 2

    engine = make_engine(f'sqlite:///{args.db}')
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        service = KnowledgeService(db)
        report = service.import_vault(vault, dry_run=not args.apply, actor_id=args.actor)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        if args.export_corrections:
            payload = service.export_corrections()
            target = Path(args.export_corrections).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload['corrections'], ensure_ascii=False, indent=2), encoding='utf-8')
            hotwords = target.with_name(target.stem + '.hotwords.txt')
            hotwords.write_text('\n'.join(payload['hotwords']) + '\n', encoding='utf-8')
            print(f'已导出纠错规则 {len(payload["corrections"]["rules"])} 条 -> {target}')
            print(f'已导出热词 {len(payload["hotwords"])} 个 -> {hotwords}')

    mode = 'APPLY' if args.apply else 'DRY-RUN'
    print(f'[{mode}] {_summary(report)}')
    for item in report.get('conflicts') or []:
        print(f'  冲突 {item["path"]}: {item["reason"]}')
    for item in report.get('rejected') or []:
        print(f'  拒绝 {item["path"]}: {item["reason"]}')
    for item in report.get('correctionConflicts') or []:
        print(f'  纠错冲突 {item["wrong"]}: 保留 {item["kept"]}，忽略 {item["ignored"]}')
    for warning in report.get('warnings') or []:
        print(f'  提示 {warning}')
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if (report.get('conflicts') or report.get('rejected')) else 0


if __name__ == '__main__':
    raise SystemExit(main())
