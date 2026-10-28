"""Persist interruption, void metadata and evidence-backed record validation."""
from alembic import op
import sqlalchemy as sa

revision = "0024_case_management"
down_revision = "0023_officer_identity"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "case_management" not in existing:
        op.create_table("case_management",
            sa.Column("case_id", sa.String(64), sa.ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("interruption_reason", sa.String(40)),
            sa.Column("interruption_detail", sa.String(1000)),
            sa.Column("interrupted_at", sa.DateTime(timezone=True)),
            sa.Column("stopped_question_id", sa.String(64), sa.ForeignKey("case_questions.id", ondelete="SET NULL")),
            sa.Column("void_reason", sa.String(1000)),
            sa.Column("voided_at", sa.DateTime(timezone=True)),
            sa.Column("voided_by", sa.String(128)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    if "record_timeline_evidence" not in existing:
        op.create_table("record_timeline_evidence",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("case_id", sa.String(64), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source", sa.String(256), nullable=False),
            sa.Column("actor_id", sa.String(128)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
        op.create_index("ix_record_timeline_evidence_case_id", "record_timeline_evidence", ["case_id"])
    if "answer_corrections" not in existing:
        op.create_table("answer_corrections",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("case_id", sa.String(64), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("question_id", sa.String(64), sa.ForeignKey("case_questions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("answer_hash", sa.String(64), nullable=False),
            sa.Column("start_index", sa.Integer(), nullable=False),
            sa.Column("original", sa.String(256), nullable=False),
            sa.Column("suggestion", sa.String(256), nullable=False),
            sa.Column("source", sa.String(128), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True)),
            sa.Column("resolved_by", sa.String(128)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("question_id", "answer_hash", "start_index", "original", "suggestion", name="uq_answer_correction_revision"))
        op.create_index("ix_answer_corrections_case_id", "answer_corrections", ["case_id"])
        op.create_index("ix_answer_corrections_question_id", "answer_corrections", ["question_id"])


def downgrade():
    for table in ("answer_corrections", "record_timeline_evidence", "case_management"):
        if table in sa.inspect(op.get_bind()).get_table_names():
            op.drop_table(table)
