import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_recording_migration_backfills_existing_captures_without_overwriting_options(tmp_path):
    migration_path = Path(__file__).parents[1] / 'alembic/versions/0025_case_recordings.py'
    spec = importlib.util.spec_from_file_location('recording_migration', migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE cases (id VARCHAR(64) PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE asr_capture_sessions (id VARCHAR(64) PRIMARY KEY, case_id VARCHAR(64))'))
        connection.execute(text("INSERT INTO cases VALUES ('case-1')"))
        connection.execute(text("INSERT INTO asr_capture_sessions VALUES ('old-capture', 'case-1')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text('SELECT full_recording_enabled FROM capture_recordings')).scalar() == 1
            connection.execute(text("UPDATE capture_recordings SET full_recording_enabled=0 WHERE capture_id='old-capture'"))
            migration.upgrade()
            assert connection.execute(text('SELECT full_recording_enabled FROM capture_recordings')).scalar() == 0
            migration.downgrade()
            assert set(inspect(connection).get_table_names()) == {'cases', 'asr_capture_sessions'}
    engine.dispose()
