import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.database import case_management_models
from app.database.session import init_database, make_engine


def test_case_management_migration_preserves_existing_cases_and_is_repeatable(tmp_path):
    source=Path(__file__).resolve().parents[1]/'alembic'/'versions'/'0024_case_management.py'
    spec=importlib.util.spec_from_file_location('case_management_migration',source)
    migration=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine=make_engine(f"sqlite:///{tmp_path/'migration.db'}")
    init_database(engine)
    tables=[case_management_models.AnswerCorrection.__table__,
            case_management_models.RecordTimelineEvidence.__table__,
            case_management_models.CaseManagement.__table__]
    with engine.begin() as connection:
        for table in tables:table.drop(connection)
        connection.execute(text("INSERT INTO cases (id,officer_name,suspect_name,case_type,workflow_state,stage,document_status,report_status,created_at,updated_at) VALUES ('legacy','民警','当事人','suspect_interrogation','IDENTITY_REQUIRED','IDENTITY','DRAFT','PENDING',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        migration.op=Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
        assert set(t.name for t in tables)<=set(inspect(connection).get_table_names())
        connection.execute(text("INSERT INTO case_management (case_id,interruption_reason,created_at,updated_at) VALUES ('legacy','POWER_RECOVERY',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        assert connection.scalar(text("SELECT interruption_reason FROM case_management WHERE case_id='legacy'"))=='POWER_RECOVERY'
        indexes={x['name'] for x in inspect(connection).get_indexes('answer_corrections')}
        assert {'ix_answer_corrections_case_id','ix_answer_corrections_question_id'}<=indexes
        migration.downgrade()
        assert connection.scalar(text("SELECT COUNT(*) FROM cases WHERE id='legacy'"))==1
        assert not (set(t.name for t in tables)&set(inspect(connection).get_table_names()))
        migration.upgrade()
        assert connection.scalar(text("SELECT COUNT(*) FROM cases WHERE id='legacy'"))==1
    engine.dispose()
