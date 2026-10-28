"""Bind hardware fingerprint images to immutable document snapshots."""
from alembic import op
import sqlalchemy as sa

revision = '0027_document_fingerprints'
down_revision = '0026_document_exports'
branch_labels = None
depends_on = None


def upgrade():
    if 'document_fingerprints' not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table('document_fingerprints',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('case_id', sa.String(64), sa.ForeignKey('cases.id'), nullable=False),
            sa.Column('snapshot_id', sa.String(64), sa.ForeignKey('document_snapshots.id'), nullable=False),
            sa.Column('image_data', sa.Text(), nullable=False),
            sa.Column('sha256', sa.String(64), nullable=False),
            sa.Column('device_id', sa.String(128), nullable=False),
            sa.Column('actor_id', sa.String(128)),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('snapshot_id', name='uq_document_fingerprint_snapshot'))
        op.create_index('ix_document_fingerprints_case_id', 'document_fingerprints', ['case_id'])


def downgrade():
    if 'document_fingerprints' in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table('document_fingerprints')
