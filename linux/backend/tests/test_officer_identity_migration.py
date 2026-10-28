import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_officer_migration_preserves_case_and_upgrades_idempotently(tmp_path):
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/0023_officer_identity.py'
    assert path.exists(), 'Officer identity requires a deployable Alembic migration'
    spec = importlib.util.spec_from_file_location('officer_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE cases (id VARCHAR(64) PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE document_snapshots (id VARCHAR(64) PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE signature_records (id VARCHAR(64) PRIMARY KEY)'))
        connection.execute(text("INSERT INTO cases VALUES ('preserved-case')"))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        module.upgrade()
        tables = set(inspect(connection).get_table_names())
        assert {'officers', 'officer_sessions', 'case_officer_bindings', 'officer_signatures', 'officer_signature_uses'} <= tables
        connection.execute(text("INSERT INTO officers (badge_number,name,unit,enabled,is_admin,password_hash,failed_login_count,created_at,updated_at) VALUES ('038291','姓名','单位',1,1,'hash',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        module.downgrade()
        assert 'officers' not in inspect(connection).get_table_names()
        assert connection.scalar(text('SELECT id FROM cases')) == 'preserved-case'
        module.upgrade()
        assert connection.scalar(text('SELECT COUNT(*) FROM officers')) == 0
