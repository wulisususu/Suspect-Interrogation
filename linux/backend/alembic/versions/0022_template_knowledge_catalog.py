"""Persistent template versions, case snapshots and versioned knowledge entries."""

from alembic import op
import sqlalchemy as sa

revision = '0022_template_knowledge_catalog'
down_revision = '0021_question_capture_ownership'
branch_labels = None
depends_on = None


def _timestamps():
    return [sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False)]


def _create(name, *columns):
    if name not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(name, *columns, *_timestamps())


def upgrade():
    _create('record_templates',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('backend_key', sa.String(64), nullable=False, unique=True),
            sa.Column('catalog_json', sa.Text(), nullable=False),
            sa.Column('current_version', sa.Integer(), nullable=False),
            sa.Column('active', sa.Boolean(), nullable=False))
    _create('record_template_versions',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('template_id', sa.String(64), sa.ForeignKey('record_templates.id'), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('structure_json', sa.Text(), nullable=False),
            sa.Column('catalog_json', sa.Text(), nullable=False),
            sa.UniqueConstraint('template_id', 'version', name='uq_record_template_version'))
    _create('case_template_snapshots',
            sa.Column('case_id', sa.String(64), sa.ForeignKey('cases.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('template_id', sa.String(64), sa.ForeignKey('record_templates.id'), nullable=True),
            sa.Column('version_id', sa.String(64), sa.ForeignKey('record_template_versions.id'), nullable=True),
            sa.Column('template_key', sa.String(64), nullable=False),
            sa.Column('blank', sa.Boolean(), nullable=False),
            sa.Column('snapshot_json', sa.Text(), nullable=False))
    _create('knowledge_categories',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('name', sa.String(128), nullable=False, unique=True),
            sa.Column('active', sa.Boolean(), nullable=False))
    _create('knowledge_entries',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('category_id', sa.String(64), sa.ForeignKey('knowledge_categories.id'), nullable=False),
            sa.Column('title', sa.String(256), nullable=False),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('keywords_json', sa.Text(), nullable=False),
            sa.Column('active', sa.Boolean(), nullable=False),
            sa.Column('deleted', sa.Boolean(), nullable=False),
            sa.Column('current_version', sa.Integer(), nullable=False))
    _create('knowledge_entry_versions',
            sa.Column('id', sa.String(64), primary_key=True),
            sa.Column('entry_id', sa.String(64), sa.ForeignKey('knowledge_entries.id'), nullable=False),
            sa.Column('version', sa.Integer(), nullable=False),
            sa.Column('action', sa.String(16), nullable=False),
            sa.Column('data_json', sa.Text(), nullable=False),
            sa.UniqueConstraint('entry_id', 'version', name='uq_knowledge_entry_version'))
    for table, column in [('record_template_versions', 'template_id'), ('knowledge_entries', 'category_id'), ('knowledge_entry_versions', 'entry_id')]:
        index = f'ix_{table}_{column}'
        if index not in {x['name'] for x in sa.inspect(op.get_bind()).get_indexes(table)}:
            op.create_index(index, table, [column])


def downgrade():
    for name in ['knowledge_entry_versions', 'knowledge_entries', 'knowledge_categories', 'case_template_snapshots', 'record_template_versions', 'record_templates']:
        if name in sa.inspect(op.get_bind()).get_table_names():
            op.drop_table(name)
