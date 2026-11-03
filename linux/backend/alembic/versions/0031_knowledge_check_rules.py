"""Knowledge-driven finalize checks: bind knowledge entries to templates / case types."""

from alembic import op
import sqlalchemy as sa

revision = '0031_knowledge_check_rules'
down_revision = '0029_session_recording_segments'
branch_labels = None
depends_on = None


def upgrade():
    if 'knowledge_check_bindings' in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        'knowledge_check_bindings',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('entry_id', sa.String(64), sa.ForeignKey('knowledge_entries.id'), nullable=False),
        sa.Column('scope', sa.String(16), nullable=False),
        sa.Column('value', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('entry_id', 'scope', 'value', name='uq_knowledge_check_binding'),
    )
    op.create_index('ix_knowledge_check_bindings_entry_id', 'knowledge_check_bindings', ['entry_id'])
    op.create_index('ix_knowledge_check_bindings_value', 'knowledge_check_bindings', ['value'])


def downgrade():
    if 'knowledge_check_bindings' in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table('knowledge_check_bindings')
