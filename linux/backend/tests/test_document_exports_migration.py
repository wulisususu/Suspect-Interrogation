import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_export_migration_preserves_snapshots_and_is_idempotent(tmp_path):
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/0026_document_exports.py'
    assert path.exists()
    spec = importlib.util.spec_from_file_location('exports_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == '0025_case_recordings'
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE cases (id VARCHAR(64) PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE document_snapshots (id VARCHAR(64) PRIMARY KEY)'))
        connection.execute(text("INSERT INTO cases VALUES ('case-a')"))
        connection.execute(text("INSERT INTO document_snapshots VALUES ('snapshot-a')"))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        module.upgrade()
        assert 'document_exports' in inspect(connection).get_table_names()
        connection.execute(text("INSERT INTO document_exports (id,case_id,snapshot_id,snapshot_hash,format,stored_name,sha256,size_bytes,actor_id,signature_manifest_json,created_at) VALUES ('export-a','case-a','snapshot-a','hash','DOCX','export-a.docx','sha',123,'038291','[]',CURRENT_TIMESTAMP)"))
        module.downgrade()
        assert 'document_exports' not in inspect(connection).get_table_names()
        assert connection.scalar(text('SELECT id FROM document_snapshots')) == 'snapshot-a'
        module.upgrade()
        assert connection.scalar(text('SELECT COUNT(*) FROM document_exports')) == 0
