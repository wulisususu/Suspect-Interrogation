"""Two requests opening a case on an empty database must not race the knowledge seeding.

The manual workspace sends ``GET /knowledge/guidance/match`` and ``POST /knowledge/suggestions``
together; both seed the default categories and the bundled check rules. Each request has
already read something (the case) before seeding, so its session is autobegun while SQLite
has no transaction open yet.
"""
import threading
import time
from contextlib import contextmanager

from sqlalchemy import func, select

from app.database.catalog_models import KnowledgeCategory, KnowledgeEntry
from app.database.session import init_database, make_engine, make_session_factory
from app.services.knowledge_checks import KnowledgeCheckService
from app.services.knowledge_service import KnowledgeService


@contextmanager
def race(tmp_path, seed):
    """Run ``seed`` on a second session while the first holds its uncommitted seed."""
    engine = make_engine(f"sqlite:///{tmp_path / 'seed-race.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    first, second = factory(), factory()
    for db in (first, second):
        db.execute(select(KnowledgeCategory.id)).all()  # 请求先读了案件，会话已自动开始
    outcome = {}

    def seed_second():
        try:
            outcome['result'] = seed(second)
            second.commit()
        except Exception as exc:  # noqa: BLE001 - 交给断言报告
            second.rollback()
            outcome['error'] = exc

    try:
        seed(first)
        worker = threading.Thread(target=seed_second)
        worker.start()
        time.sleep(0.3)  # 让第二个请求走到写锁等待
        first.commit()
        worker.join(10)
        assert not worker.is_alive()
        assert 'error' not in outcome, outcome.get('error')
        with factory() as db:
            yield db, outcome['result']
    finally:
        first.close()
        second.close()
        engine.dispose()


def test_concurrent_category_seed_on_an_empty_database(tmp_path):
    with race(tmp_path, lambda db: KnowledgeService(db)._seed()) as (db, _):
        assert sorted(db.scalars(select(KnowledgeCategory.id))) == ['evidence', 'law', 'questioning', 'safety']


def test_concurrent_bundled_rule_seed_creates_each_rule_once(tmp_path):
    with race(tmp_path, lambda db: KnowledgeCheckService(db).ensure_bundled_rules()) as (db, created):
        assert created == []
        counts = db.execute(select(KnowledgeEntry.vault_uid, func.count())
                            .where(KnowledgeEntry.origin == 'vault').group_by(KnowledgeEntry.vault_uid)).all()
        assert counts and all(count == 1 for _, count in counts)
