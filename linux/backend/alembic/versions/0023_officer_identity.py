"""Independent officer roster, sessions, case roles and versioned signatures.

Revision ID: 0023_officer_identity
Revises: 0022_template_knowledge_catalog
"""
from alembic import op
import sqlalchemy as sa


revision = '0023_officer_identity'
down_revision = '0022_template_knowledge_catalog'
branch_labels = None
depends_on = None


def _timestamps():
    return [sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))]


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if 'officers' not in existing:
        op.create_table('officers',
            sa.Column('badge_number', sa.String(32), primary_key=True),
            sa.Column('name', sa.String(128), nullable=False),
            sa.Column('unit', sa.String(256), nullable=False, server_default=''),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('password_hash', sa.Text(), nullable=False),
            sa.Column('failed_login_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('login_blocked_until', sa.DateTime(timezone=True), nullable=True),
            *_timestamps())
    if 'officer_sessions' not in existing:
        op.create_table('officer_sessions',
            sa.Column('token_hash', sa.String(64), primary_key=True),
            sa.Column('badge_number', sa.String(32), sa.ForeignKey('officers.badge_number', ondelete='CASCADE'), nullable=False),
            sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('exemption_until', sa.DateTime(timezone=True), nullable=False),
            sa.Column('locked', sa.Boolean(), nullable=False, server_default=sa.false()))
    if 'case_officer_bindings' not in existing:
        op.create_table('case_officer_bindings',
            sa.Column('case_id', sa.String(64), sa.ForeignKey('cases.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('interrogator_badge_number', sa.String(32), sa.ForeignKey('officers.badge_number'), nullable=True),
            sa.Column('recorder_badge_number', sa.String(32), sa.ForeignKey('officers.badge_number'), nullable=True),
            *_timestamps())
    if 'officer_signatures' not in existing:
        op.create_table('officer_signatures',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('badge_number', sa.String(32), sa.ForeignKey('officers.badge_number'), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('image_data', sa.Text(), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('actor_id', sa.String(128), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.UniqueConstraint('badge_number', 'version', name='uq_officer_signature_version'))
    if 'officer_signature_uses' not in existing:
        op.create_table('officer_signature_uses',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('case_id', sa.String(64), sa.ForeignKey('cases.id'), nullable=False),
            sa.Column('snapshot_id', sa.String(64), sa.ForeignKey('document_snapshots.id'), nullable=False),
            sa.Column('signature_record_id', sa.String(64), sa.ForeignKey('signature_records.id'), nullable=False),
            sa.Column('officer_signature_id', sa.String(64), sa.ForeignKey('officer_signatures.id'), nullable=False),
            sa.Column('badge_number', sa.String(32), sa.ForeignKey('officers.badge_number'), nullable=False),
            sa.Column('actor_id', sa.String(128), nullable=True),
            sa.Column('used_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.UniqueConstraint('signature_record_id', name='uq_officer_signature_use_record'))
    for table, columns in {
        'officer_sessions': ['badge_number', 'expires_at'],
        'officer_signatures': ['badge_number'],
        'officer_signature_uses': ['case_id', 'officer_signature_id', 'badge_number'],
    }.items():
        indexes = {index['name'] for index in sa.inspect(op.get_bind()).get_indexes(table)}
        for column in columns:
            name = f'ix_{table}_{column}'
            if name not in indexes:
                op.create_index(name, table, [column])


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ['officer_signature_uses', 'officer_signatures', 'case_officer_bindings', 'officer_sessions', 'officers']:
        if table in existing:
            op.drop_table(table)
