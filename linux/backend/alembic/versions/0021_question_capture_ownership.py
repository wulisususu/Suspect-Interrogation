"""Persist question elements and per-question capture ownership."""
from alembic import op
import sqlalchemy as sa

revision = '0021_question_capture_ownership'
down_revision = '0020_drop_moss_transcription'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    fields = {c['name'] for c in sa.inspect(bind).get_columns('case_questions')}
    if 'element_key' not in fields:
        op.add_column('case_questions', sa.Column('element_key', sa.String(64), nullable=True))
    fields = {c['name'] for c in sa.inspect(bind).get_columns('asr_capture_sessions')}
    for column in [
        sa.Column('target_question_id', sa.String(64), nullable=True),
        sa.Column('replace_answer', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('answer_replacement_applied', sa.Boolean(), nullable=False, server_default='0'),
    ]:
        if column.name not in fields:
            op.add_column('asr_capture_sessions', column)
    # Only explicit legacy keys are safe to backfill. Never infer evidence from wording.
    keys = ('time', 'place', 'motive', 'method', 'process', 'evidence', 'after')
    for key in keys:
        bind.execute(sa.text(
            "UPDATE case_questions SET element_key=:key WHERE section_type='BODY' "
            "AND element_key IS NULL AND template_item_key IN (:key, :body_key) "
            "AND case_id IN (SELECT id FROM cases WHERE workflow_state NOT IN ('FROZEN','SIGNED','REPORT_GENERATED'))"
        ), {'key': key, 'body_key': f'body-{key}'})


def downgrade():
    for name in ('answer_replacement_applied', 'replace_answer', 'target_question_id'):
        op.drop_column('asr_capture_sessions', name)
    op.drop_column('case_questions', 'element_key')
