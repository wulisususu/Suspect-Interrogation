"""Drop the MOSS long-audio transcription tables (MOSS is retired).

Revision ID: 0020_drop_moss_transcription
Revises: 0019_deferred_speaker_analysis
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision = "0020_drop_moss_transcription"
down_revision = "0019_deferred_speaker_analysis"
branch_labels = None
depends_on = None


# Children before parents: revisions reference moss_transcriptions.
_TABLES = ("moss_speaker_mappings", "moss_transcription_revisions", "moss_transcriptions")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for table in _TABLES:
        if table not in existing:
            continue
        for index in inspector.get_indexes(table):
            if index.get("name"):
                op.drop_index(str(index["name"]), table_name=table)
        op.drop_table(table)


def downgrade() -> None:
    # Recreate exactly what 0013 created; the dropped rows are not restorable.
    source = Path(__file__).with_name("0013_moss_transcription_integration.py")
    spec = importlib.util.spec_from_file_location("_moss_0013", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.upgrade()
