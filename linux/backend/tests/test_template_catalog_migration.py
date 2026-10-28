import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_catalog_migration_upgrades_legacy_and_preserves_rows_on_repeat(tmp_path):
    path = Path(__file__).parents[1] / 'alembic' / 'versions' / '0022_template_knowledge_catalog.py'
    assert path.exists(), 'catalog schema migration is required for production upgrades'
    spec = importlib.util.spec_from_file_location('catalog_migration_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE cases (id VARCHAR(64) PRIMARY KEY)'))
        connection.execute(text("INSERT INTO cases(id) VALUES ('existing')"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            connection.execute(text("INSERT INTO knowledge_categories(id,name,active,created_at,updated_at) VALUES ('old','既有分类',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            module.upgrade()
        names = set(inspect(connection).get_table_names())
        assert names >= {'record_templates', 'record_template_versions', 'case_template_snapshots', 'knowledge_categories', 'knowledge_entries', 'knowledge_entry_versions'}
        assert connection.scalar(text('SELECT name FROM knowledge_categories WHERE id=\'old\'')) == '既有分类'
        assert connection.scalar(text('SELECT id FROM cases')) == 'existing'
        with Operations.context(MigrationContext.configure(connection)):
            module.downgrade()
        assert set(inspect(connection).get_table_names()) == {'cases'}
