"""Persist authenticated exports of frozen document snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '0026_document_exports'
down_revision = '0025_case_recordings'
branch_labels = None
depends_on = None


def upgrade():
    if 'document_exports' not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table('document_exports',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('case_id', sa.String(64), sa.ForeignKey('cases.id'), nullable=False),
            sa.Column('snapshot_id', sa.String(64), sa.ForeignKey('document_snapshots.id'), nullable=False),
            sa.Column('snapshot_hash', sa.String(64), nullable=False),
            sa.Column('format', sa.String(8), nullable=False),
            sa.Column('stored_name', sa.String(80), nullable=False, unique=True),
            sa.Column('sha256', sa.String(64), nullable=False),
            sa.Column('size_bytes', sa.Integer(), nullable=False),
            sa.Column('actor_id', sa.String(128), nullable=False),
            sa.Column('signature_manifest_json', sa.Text(), nullable=False),
            sa.Column('fingerprint_sha256', sa.String(64)),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    indexes = {row['name'] for row in sa.inspect(op.get_bind()).get_indexes('document_exports')}
    if 'ix_document_exports_case_id' not in indexes:
        op.create_index('ix_document_exports_case_id', 'document_exports', ['case_id'])


def downgrade():
    if 'document_exports' in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table('document_exports')
