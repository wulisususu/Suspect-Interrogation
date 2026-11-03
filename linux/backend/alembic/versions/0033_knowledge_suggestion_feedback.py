"""Smart follow-up suggestions: one feedback row per case and suggested question."""

from alembic import op
import sqlalchemy as sa

revision = '0033_knowledge_suggestion_feedback'
down_revision = '0032_knowledge_citations'
branch_labels = None
depends_on = None


def upgrade():
    if 'knowledge_suggestion_feedback' in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        'knowledge_suggestion_feedback',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('case_id', sa.String(64), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('suggestion_key', sa.String(64), nullable=False),
        sa.Column('entry_id', sa.String(64), sa.ForeignKey('knowledge_entries.id'), nullable=True),
        sa.Column('entry_version', sa.Integer(), nullable=True),
        sa.Column('element_key', sa.String(64), nullable=True),
        sa.Column('suggestion_text', sa.String(300), nullable=False),
        sa.Column('anchor_question_id', sa.String(64), nullable=True),
        sa.Column('shown_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('shown_by', sa.String(64), nullable=True),
        sa.Column('decision', sa.String(16), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decided_by', sa.String(64), nullable=True),
        sa.Column('created_question_id', sa.String(64), nullable=True),
        sa.UniqueConstraint('case_id', 'suggestion_key', name='uq_knowledge_suggestion_case_key'),
    )
    for column in ('case_id', 'suggestion_key', 'entry_id', 'decision'):
        op.create_index(f'ix_knowledge_suggestion_feedback_{column}', 'knowledge_suggestion_feedback', [column])


def downgrade():
    if 'knowledge_suggestion_feedback' in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table('knowledge_suggestion_feedback')
