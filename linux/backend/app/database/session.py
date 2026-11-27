from pathlib import Path
import threading
import time
from typing import Iterator
import weakref

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base

_SQLITE_LOCK_RETRY_SECONDS = 15.0
_SQLITE_LOCK_RETRY_INTERVAL = 0.02
_SQLITE_BUSY_TIMEOUT_MS = 30_000
_SQLITE_WRITE_LOCKS_GUARD = threading.Lock()
_SQLITE_WRITE_LOCKS: weakref.WeakKeyDictionary[Engine, threading.Lock] = weakref.WeakKeyDictionary()


def default_database_url() -> str:
    path = Path(__file__).resolve().parents[2] / "data" / "suspect-interrogation.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def make_engine(database_url: str | None = None) -> Engine:
    url = database_url or default_database_url()
    connect_args = {"check_same_thread": False, "timeout": _SQLITE_BUSY_TIMEOUT_MS / 1000.0} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        sqlite_write_lock(engine)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()
    return engine


def sqlite_write_lock(engine: Engine | None) -> threading.Lock | None:
    if engine is None or engine.dialect.name != "sqlite":
        return None
    with _SQLITE_WRITE_LOCKS_GUARD:
        lock = _SQLITE_WRITE_LOCKS.get(engine)
        if lock is None:
            lock = threading.Lock()
            _SQLITE_WRITE_LOCKS[engine] = lock
        return lock


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def _is_sqlite_lock_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message or "database is busy" in message


def begin_sqlite_immediate(db: Session) -> None:
    """Serialize a read-then-write allocation before its first database read.

    The session is usually already autobegun by an earlier read in the same request,
    but pysqlite only opens the SQLite transaction before the first write, so ask the
    driver. An open driver transaction has already written and holds the write lock.
    """
    if db.get_bind().dialect.name != "sqlite":
        return
    connection = db.connection()
    if connection.connection.driver_connection.in_transaction:
        return
    deadline = time.monotonic() + _SQLITE_LOCK_RETRY_SECONDS
    while True:
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            return
        except OperationalError as exc:
            if not _is_sqlite_lock_error(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(_SQLITE_LOCK_RETRY_INTERVAL)


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
