from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.database.base import Base
import app.database.models  # noqa: F401 - registers core ORM tables
import app.database.recognition_models  # noqa: F401 - registers recognition evidence tables
import app.database.voiceprint_models  # noqa: F401 - registers global voiceprint/calibration tables

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

url = os.getenv("DATABASE_URL")
if not url:
    # Production RuntimeSettings uses the SUSPECT_ prefix. Keep DB_PATH as a
    # legacy/test alias, but make the production variable authoritative.
    db_path = os.getenv("SUSPECT_DB_PATH") or os.getenv("DB_PATH")
    if db_path:
        url = f"sqlite:///{os.path.abspath(db_path)}"
if url:
    config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
