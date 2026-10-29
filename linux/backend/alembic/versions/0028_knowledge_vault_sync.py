"""Knowledge base: vault traceability, verification status, wiki links, FTS5 and ASR term corrections."""

from alembic import op
import sqlalchemy as sa

revision = '0028_knowledge_vault_sync'
down_revision = '0027_document_fingerprints'
branch_labels = None
depends_on = None


NEW_COLUMNS = (
    ('vault_uid', sa.String(64)),
    ('kind', sa.String(16)),
    ('status', sa.String(16)),
    ('origin', sa.String(16)),
    ('source_path', sa.String(512)),
    ('source_sha256', sa.String(64)),
    ('source_ref', sa.String(512)),
)

FTS_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS tr_knowledge_entries_fts_insert
    AFTER INSERT ON knowledge_entries
    BEGIN
        INSERT INTO knowledge_entries_fts(entry_id, title, content, keywords)
        VALUES (new.id, new.title, new.content, new.keywords_json);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS tr_knowledge_entries_fts_update
    AFTER UPDATE OF title, content, keywords_json, deleted ON knowledge_entries
    BEGIN
        DELETE FROM knowledge_entries_fts WHERE entry_id = old.id;
        INSERT INTO knowledge_entries_fts(entry_id, title, content, keywords)
        SELECT new.id, new.title, new.content, new.keywords_json WHERE new.deleted = 0;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS tr_knowledge_entries_fts_delete
    AFTER DELETE ON knowledge_entries
    BEGIN
        DELETE FROM knowledge_entries_fts WHERE entry_id = old.id;
    END
    """,
)


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {row[1] for row in op.get_bind().exec_driver_sql(f'PRAGMA table_info({table})')}


def _ensure_fts(bind):
    exists = bind.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_entries_fts'"
    ).first()
    if not exists:
        for tokenizer in ('trigram', 'unicode61'):
            try:
                bind.exec_driver_sql(
                    "CREATE VIRTUAL TABLE knowledge_entries_fts USING fts5("
                    f"entry_id UNINDEXED, title, content, keywords, tokenize='{tokenizer}')"
                )
                break
            except Exception:  # noqa: BLE001 - 换下一个分词器
                continue
        else:
            return
    for statement in FTS_TRIGGERS:
        bind.exec_driver_sql(statement)
    bind.exec_driver_sql(
        "DELETE FROM knowledge_entries_fts WHERE entry_id IN "
        "(SELECT id FROM knowledge_entries WHERE deleted = 1)"
    )
    bind.exec_driver_sql(
        "INSERT INTO knowledge_entries_fts(entry_id, title, content, keywords) "
        "SELECT id, title, content, keywords_json FROM knowledge_entries "
        "WHERE deleted = 0 AND id NOT IN (SELECT entry_id FROM knowledge_entries_fts)"
    )


def upgrade():
    tables = _tables()
    if 'knowledge_entries' in tables:
        columns = _columns('knowledge_entries')
        with op.batch_alter_table('knowledge_entries') as batch:
            for name, column_type in NEW_COLUMNS:
                if name not in columns:
                    batch.add_column(sa.Column(name, column_type, nullable=True))
        # 回填：既有条目都是人工维护的，状态按「已验证」处理以免突然从 guidance 里消失。
        op.execute("UPDATE knowledge_entries SET kind = 'faq' WHERE kind IS NULL")
        op.execute("UPDATE knowledge_entries SET status = 'verified' WHERE status IS NULL")
        op.execute("UPDATE knowledge_entries SET origin = 'manual' WHERE origin IS NULL")
        op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_entries_vault_uid ON knowledge_entries (vault_uid)")
        op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_entries_source_path ON knowledge_entries (source_path)")

    if 'knowledge_entry_links' not in tables:
        op.create_table(
            'knowledge_entry_links',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('from_entry_id', sa.String(64), sa.ForeignKey('knowledge_entries.id'), nullable=False),
            sa.Column('to_entry_id', sa.String(64), sa.ForeignKey('knowledge_entries.id'), nullable=True),
            sa.Column('target_title', sa.String(256), nullable=False),
            sa.Column('relation', sa.String(16), nullable=False, server_default='REFERENCES'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('from_entry_id', 'target_title', name='uq_knowledge_link_target'),
        )
        op.create_index('ix_knowledge_entry_links_from_entry_id', 'knowledge_entry_links', ['from_entry_id'])
        op.create_index('ix_knowledge_entry_links_to_entry_id', 'knowledge_entry_links', ['to_entry_id'])

    if 'knowledge_sync_runs' not in tables:
        op.create_table(
            'knowledge_sync_runs',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('dry_run', sa.Boolean(), nullable=False, server_default=sa.text('0')),
            sa.Column('actor_id', sa.String(128), nullable=True),
            sa.Column('source_root', sa.String(512), nullable=False),
            sa.Column('added', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('updated', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('disabled', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('conflicts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('rejected', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('report_json', sa.Text(), nullable=False, server_default='{}'),
        )

    if 'asr_term_corrections' not in tables:
        op.create_table(
            'asr_term_corrections',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('wrong_text', sa.String(128), nullable=False, unique=True),
            sa.Column('right_text', sa.String(128), nullable=False),
            sa.Column('category', sa.String(32), nullable=False, server_default='TERM'),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
            sa.Column('entry_id', sa.String(64), sa.ForeignKey('knowledge_entries.id'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index('ix_asr_term_corrections_entry_id', 'asr_term_corrections', ['entry_id'])

    if op.get_bind().dialect.name == 'sqlite':
        _ensure_fts(op.get_bind())


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS tr_knowledge_entries_fts_insert")
    op.execute("DROP TRIGGER IF EXISTS tr_knowledge_entries_fts_update")
    op.execute("DROP TRIGGER IF EXISTS tr_knowledge_entries_fts_delete")
    op.execute("DROP TABLE IF EXISTS knowledge_entries_fts")
    for table in ('asr_term_corrections', 'knowledge_sync_runs', 'knowledge_entry_links'):
        if table in _tables():
            op.drop_table(table)
    if 'knowledge_entries' in _tables():
        # 先删索引再重建表：SQLite 批量模式重建时不接受引用已删列的索引。
        op.execute("DROP INDEX IF EXISTS ix_knowledge_entries_vault_uid")
        op.execute("DROP INDEX IF EXISTS ix_knowledge_entries_source_path")
        columns = _columns('knowledge_entries')
        with op.batch_alter_table('knowledge_entries') as batch:
            for name, _ in NEW_COLUMNS:
                if name in columns:
                    batch.drop_column(name)
