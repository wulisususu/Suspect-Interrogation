"""知识条目全文索引（SQLite FTS5）。

FTS5 虚表无法由 SQLAlchemy 元数据创建，因此这里集中做「建表 + 触发器 + 补数据」，
由 `init_database`（开发/测试）与 Alembic 迁移（生产）共同调用，且必须幂等。

中文场景下 `unicode61` 会把整段汉字当成一个 token，无法子串命中；优先使用
`trigram` 分词器（SQLite ≥ 3.34，支持 ≥3 字的子串匹配）。低版本或未编译 FTS5
时降级返回 False，检索侧自动退回 LIKE。
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

TABLE = 'knowledge_entries_fts'

_TRIGGERS = (
    (
        'tr_knowledge_entries_fts_insert',
        """
        CREATE TRIGGER IF NOT EXISTS tr_knowledge_entries_fts_insert
        AFTER INSERT ON knowledge_entries
        BEGIN
            INSERT INTO knowledge_entries_fts(entry_id, title, content, keywords)
            VALUES (new.id, new.title, new.content, new.keywords_json);
        END
        """,
    ),
    (
        'tr_knowledge_entries_fts_update',
        """
        CREATE TRIGGER IF NOT EXISTS tr_knowledge_entries_fts_update
        AFTER UPDATE OF title, content, keywords_json, deleted ON knowledge_entries
        BEGIN
            DELETE FROM knowledge_entries_fts WHERE entry_id = old.id;
            INSERT INTO knowledge_entries_fts(entry_id, title, content, keywords)
            SELECT new.id, new.title, new.content, new.keywords_json WHERE new.deleted = 0;
        END
        """,
    ),
    (
        'tr_knowledge_entries_fts_delete',
        """
        CREATE TRIGGER IF NOT EXISTS tr_knowledge_entries_fts_delete
        AFTER DELETE ON knowledge_entries
        BEGIN
            DELETE FROM knowledge_entries_fts WHERE entry_id = old.id;
        END
        """,
    ),
)


def ensure_knowledge_fts(engine: Engine) -> bool:
    """幂等创建 FTS5 索引与同步触发器，并补齐缺失/清理已删除的行。"""
    if engine.dialect.name != 'sqlite':
        return False
    try:
        with engine.begin() as conn:
            existing = conn.execute(
                text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"),
                {'name': TABLE},
            ).first()
            if existing is None:
                created = False
                for tokenizer in ('trigram', 'unicode61'):
                    try:
                        conn.execute(text(
                            f"CREATE VIRTUAL TABLE {TABLE} USING fts5("
                            f"entry_id UNINDEXED, title, content, keywords, tokenize='{tokenizer}')"
                        ))
                        created = True
                        logger.info('knowledge FTS5 created with tokenizer=%s', tokenizer)
                        break
                    except Exception:  # noqa: BLE001 - 分词器/扩展缺失时换下一个
                        continue
                if not created:
                    logger.warning('knowledge FTS5 unavailable; search falls back to LIKE')
                    return False
            for _, statement in _TRIGGERS:
                conn.execute(text(statement))
            conn.execute(text(
                f"DELETE FROM {TABLE} WHERE entry_id IN (SELECT id FROM knowledge_entries WHERE deleted = 1)"
            ))
            conn.execute(text(
                f"INSERT INTO {TABLE}(entry_id, title, content, keywords) "
                f"SELECT id, title, content, keywords_json FROM knowledge_entries "
                f"WHERE deleted = 0 AND id NOT IN (SELECT entry_id FROM {TABLE})"
            ))
        return True
    except Exception:  # noqa: BLE001 - 索引是增强项，不能阻断建库
        logger.exception('knowledge FTS5 setup failed; search falls back to LIKE')
        return False
