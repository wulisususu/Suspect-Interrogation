"""Knowledge citations: source document, article/page locator, document version, validity window, supersession."""

from alembic import op
import sqlalchemy as sa

revision = '0032_knowledge_citations'
down_revision = '0031_knowledge_check_rules'
branch_labels = None
depends_on = None


# 用普通 ADD COLUMN 而不是 batch 重建：knowledge_entries 上挂着 FTS5 同步触发器，
# SQLite 重建表会连带删掉触发器。
NEW_COLUMNS = (
    ('source_document', sa.String(256), None),
    ('source_locator', sa.String(128), None),
    ('source_version', sa.String(64), None),
    ('effective_from', sa.Date(), None),
    ('effective_until', sa.Date(), None),
    ('superseded', sa.Boolean(), sa.text('0')),
    ('superseded_by_id', sa.String(64), None),
)


def _columns(table):
    return {row[1] for row in op.get_bind().exec_driver_sql(f'PRAGMA table_info({table})')}


def upgrade():
    if 'knowledge_entries' not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    columns = _columns('knowledge_entries')
    for name, column_type, default in NEW_COLUMNS:
        if name in columns:
            continue
        op.add_column('knowledge_entries', sa.Column(
            name, column_type, nullable=default is None, server_default=default,
        ))
    op.execute("UPDATE knowledge_entries SET superseded = 0 WHERE superseded IS NULL")


def downgrade():
    if 'knowledge_entries' not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    columns = _columns('knowledge_entries')
    for name, _, _ in reversed(NEW_COLUMNS):
        if name in columns:
            op.get_bind().exec_driver_sql(f'ALTER TABLE knowledge_entries DROP COLUMN {name}')
