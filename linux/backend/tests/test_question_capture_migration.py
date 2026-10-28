import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_real_legacy_question_and_capture_schema_upgrade_is_conservative(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'alembic/versions/0021_question_capture_ownership.py'
    spec = importlib.util.spec_from_file_location('question_capture_migration', source)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f'sqlite:///{tmp_path / "legacy-ownership.db"}')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE cases (id TEXT PRIMARY KEY, workflow_state TEXT NOT NULL)'))
        connection.execute(text('CREATE TABLE case_questions (id TEXT PRIMARY KEY, case_id TEXT, section_type TEXT, template_item_key TEXT)'))
        connection.execute(text('CREATE TABLE asr_capture_sessions (id TEXT PRIMARY KEY, case_id TEXT)'))
        connection.execute(text("INSERT INTO cases VALUES ('mutable','QUESTIONING'),('frozen','FROZEN')"))
        connection.execute(text("INSERT INTO case_questions VALUES ('explicit','mutable','BODY','body-time'),('unknown','mutable','BODY',NULL),('fixed','mutable','OPENING','time'),('historical','frozen','BODY','time')"))
        connection.execute(text("INSERT INTO asr_capture_sessions VALUES ('capture','mutable')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
        assert dict(connection.execute(text('SELECT id,element_key FROM case_questions')).all()) == {
            'explicit': 'time', 'unknown': None, 'fixed': None, 'historical': None,
        }
        assert connection.execute(text('SELECT target_question_id,replace_answer,answer_replacement_applied FROM asr_capture_sessions')).one() == (None, 0, 0)
        migration.downgrade()
        assert 'element_key' not in {column['name'] for column in inspect(connection).get_columns('case_questions')}
        assert connection.scalar(text('SELECT COUNT(*) FROM case_questions')) == 4
        migration.upgrade()
        assert connection.scalar(text("SELECT element_key FROM case_questions WHERE id='explicit'")) == 'time'
    engine.dispose()
