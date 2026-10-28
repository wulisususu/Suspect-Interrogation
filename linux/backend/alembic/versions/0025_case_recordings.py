"""Persist per-case recording option and capture-time original-file provenance."""
from alembic import op
import sqlalchemy as sa

revision = '0025_case_recordings'
down_revision = '0024_case_management'
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if 'case_recording_options' not in existing:
        op.create_table('case_recording_options',
            sa.Column('case_id', sa.String(64), sa.ForeignKey('cases.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('full_recording_enabled', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    if 'capture_recordings' not in existing:
        op.create_table('capture_recordings',
            sa.Column('capture_id', sa.String(64), sa.ForeignKey('asr_capture_sessions.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('full_recording_enabled', sa.Boolean(), nullable=False),
            sa.Column('original_sha256', sa.String(64)),
            sa.Column('original_sample_count', sa.Integer()),
            sa.Column('original_size_bytes', sa.Integer()),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    # Existing captures were always archived. Preserve their enabled state while
    # every new capture snapshots the case option in its start transaction.
    op.execute(sa.text('''INSERT INTO capture_recordings
        (capture_id, full_recording_enabled, created_at, updated_at)
        SELECT c.id, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM asr_capture_sessions c
        WHERE NOT EXISTS (SELECT 1 FROM capture_recordings r WHERE r.capture_id=c.id)'''))


def downgrade():
    op.drop_table('capture_recordings')
    op.drop_table('case_recording_options')
