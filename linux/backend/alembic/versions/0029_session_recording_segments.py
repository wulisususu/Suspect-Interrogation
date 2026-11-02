"""Channel ② whole-segment recordings: one continuous file per start/resume → pause/finish."""
from alembic import op
import sqlalchemy as sa

revision = '0029_session_recording_segments'
down_revision = '0028_knowledge_vault_sync'
branch_labels = None
depends_on = None


def upgrade():
    if 'session_recording_segments' in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table('session_recording_segments',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('case_id', sa.String(64), sa.ForeignKey('cases.id', ondelete='CASCADE'), nullable=False),
        sa.Column('interrogation_session_id', sa.String(64), sa.ForeignKey('interrogation_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True)),
        sa.Column('end_reason', sa.String(32)),
        sa.Column('sample_rate', sa.Integer(), nullable=False),
        sa.Column('sample_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('client_sample_end', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_sequence', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('last_frame_at', sa.DateTime(timezone=True)),
        sa.Column('gaps_json', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('client_finalized', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('sha256', sa.String(64)),
        sa.Column('size_bytes', sa.Integer()),
        sa.Column('finalized_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('case_id', 'ordinal', name='uq_session_recording_segments_case_ordinal'))
    op.create_index('ix_session_recording_segments_case_id', 'session_recording_segments', ['case_id'])
    op.create_index('ix_session_recording_segments_interrogation_session_id', 'session_recording_segments', ['interrogation_session_id'])
    op.create_index('ix_session_recording_segments_status', 'session_recording_segments', ['status'])


def downgrade():
    op.drop_table('session_recording_segments')
