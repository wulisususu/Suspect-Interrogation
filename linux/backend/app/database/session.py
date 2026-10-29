from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base


def default_database_url() -> str:
    path = Path(__file__).resolve().parents[2] / "data" / "suspect-interrogation.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def make_engine(database_url: str | None = None) -> Engine:
    url = database_url or default_database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def begin_sqlite_immediate(db: Session) -> None:
    """Serialize a read-then-write allocation before its first database read."""
    if db.get_bind().dialect.name == "sqlite" and not db.in_transaction():
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")


def init_database(engine: Engine) -> None:
    # Import modular tables before create_all so fresh/dev databases receive the
    # same schema that Alembic creates in deployed environments.
    from app.database import case_management_models, catalog_models, document_export_models, document_mark_models, officer_models, recording_models, recognition_models, voiceprint_models  # noqa: F401

    Base.metadata.create_all(engine)
    from app.database.knowledge_fts import ensure_knowledge_fts

    ensure_knowledge_fts(engine)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
