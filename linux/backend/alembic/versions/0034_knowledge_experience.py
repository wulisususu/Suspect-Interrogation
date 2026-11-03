"""Experience distilled from closed cases: candidate questions awaiting human review."""

from alembic import op
import sqlalchemy as sa

revision = '0034_knowledge_experience'
down_revision = '0033_knowledge_suggestion_feedback'
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if 'knowledge_experience_candidates' not in tables:
        op.create_table(
            'knowledge_experience_candidates',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('scope_key', sa.String(64), nullable=False),
            sa.Column('scope_title', sa.String(128), nullable=False, server_default=''),
            sa.Column('template_key', sa.String(64), nullable=True),
            sa.Column('case_type', sa.String(64), nullable=True),
            sa.Column('element_key', sa.String(64), nullable=True),
            sa.Column('dedupe_key', sa.String(64), nullable=False),
            sa.Column('proposed_text', sa.String(300), nullable=False),
            sa.Column('mask_rules_json', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('status', sa.String(16), nullable=False, server_default='PENDING'),
            sa.Column('reviewed_by', sa.String(64), nullable=True),
            sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('review_note', sa.String(300), nullable=True),
            sa.Column('published_text', sa.String(300), nullable=True),
            sa.Column('published_entry_id', sa.String(64), sa.ForeignKey('knowledge_entries.id'), nullable=True),
            sa.Column('published_version', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('scope_key', 'dedupe_key', name='uq_knowledge_experience_scope_key'),
        )
        for column in ('scope_key', 'status'):
            op.create_index(f'ix_knowledge_experience_candidates_{column}', 'knowledge_experience_candidates', [column])
    if 'knowledge_experience_sources' not in tables:
        op.create_table(
            'knowledge_experience_sources',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('candidate_id', sa.String(64),
                      sa.ForeignKey('knowledge_experience_candidates.id', ondelete='CASCADE'), nullable=False),
            sa.Column('case_id', sa.String(64), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
            sa.Column('question_id', sa.String(64), nullable=False),
            sa.Column('original_text', sa.String(300), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('case_id', 'question_id', name='uq_knowledge_experience_source'),
        )
        for column in ('candidate_id', 'case_id'):
            op.create_index(f'ix_knowledge_experience_sources_{column}', 'knowledge_experience_sources', [column])


def downgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ('knowledge_experience_sources', 'knowledge_experience_candidates'):
        if table in tables:
            op.drop_table(table)
