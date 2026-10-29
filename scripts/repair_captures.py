#!/usr/bin/env python3
"""修复被误标为 INCOMPLETE、但音频档案实际完整的采集（板端可离线运行）。

用法：
  python scripts/repair_captures.py                                  # 预检，列出可修项
  python scripts/repair_captures.py --apply                          # 真正重新收尾（校验每段 sha256）
  python scripts/repair_captures.py --case CASE-20261029-BCCA00 --apply
  python scripts/repair_captures.py --capture <captureId> --apply --actor 001

默认 dry-run。apply 时逐条走 DurableAudioArchive.finalize_capture，先校验分段
状态、采样数与文件 sha256，全部自洽才改成 COMPLETE；不一致的保持原状并给出原因。
每次 apply 都写一条 CAPTURE_INTEGRITY_REPAIR 审计。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'linux' / 'backend'))

from app.database.session import make_engine, make_session_factory  # noqa: E402
from app.services.capture_integrity_repair import CaptureIntegrityRepair  # noqa: E402
from app.services.durable_audio_archive import DurableAudioArchive  # noqa: E402


def _print_table(report: dict) -> None:
    rows = report['captures']
    if not rows:
        print('没有 INCOMPLETE 采集，无需修复。')
        return
    width = max(len(row['captureId']) for row in rows)
    for row in rows:
        flag = '可修' if row['repairable'] else '跳过'
        if row['repaired']:
            flag = '已修'
        print(f"{flag}  {row['captureId']:<{width}}  {row['caseId']}  "
              f"segments={row['segments']} samples={row['samples']} asr={row['asrStatus']}")
        print(f"      {row['reason']}")
    print()
    print(f"扫描 {report['scanned']} 条：可修 {report['repairable']}，"
          f"已修 {report['repaired']}，跳过 {report['blocked']}")


def main() -> int:
    parser = argparse.ArgumentParser(description='修复误标为 INCOMPLETE 的录音采集')
    parser.add_argument('--db', default=os.environ.get('SUSPECT_DB_PATH',
                                                      '/var/lib/suspect-interrogation/interrogation.db'))
    parser.add_argument('--data-dir', default=os.environ.get('SUSPECT_DATA_DIR',
                                                             '/var/lib/suspect-interrogation'),
                        help='音频档案根目录（其下有 audio/）')
    parser.add_argument('--apply', action='store_true', help='真正写入；缺省只做预检')
    parser.add_argument('--case', default=None, help='只处理指定案件')
    parser.add_argument('--capture', default=None, help='只处理指定采集')
    parser.add_argument('--actor', default=None, help='操作人警号，写入审计')
    parser.add_argument('--json', action='store_true', help='输出完整报告 JSON')
    args = parser.parse_args()

    db_path = Path(args.db).expanduser()
    if not db_path.is_file():
        print(f'数据库不存在：{db_path}', file=sys.stderr)
        return 2
    data_dir = Path(args.data_dir).expanduser()
    if not data_dir.is_dir():
        print(f'数据目录不存在：{data_dir}', file=sys.stderr)
        return 2

    engine = make_engine(f'sqlite:///{db_path.as_posix()}')
    session_factory = make_session_factory(engine)
    archive = DurableAudioArchive(data_dir, session_factory)
    report = CaptureIntegrityRepair(session_factory, archive).run(
        dry_run=not args.apply,
        actor_id=args.actor,
        case_id=args.case,
        capture_id=args.capture,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print('=== 预检（不会写入）===' if not args.apply else '=== 修复（已写入审计）===')
        _print_table(report)
        if not args.apply and report['repairable']:
            print('\n确认无误后加 --apply 执行修复。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
