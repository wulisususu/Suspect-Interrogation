import itertools
import threading
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    badge_number: str
    name: str
    unit: str
    is_admin: bool


actor_context: ContextVar[Actor | None] = ContextVar('authenticated_officer', default=None)


def current_actor() -> Actor | None:
    return actor_context.get()


def current_actor_id() -> str | None:
    actor = current_actor()
    return actor.badge_number if actor is not None else None


_revocation_lock = threading.Lock()
_revocation_counter = itertools.count(1)
_revocation_epoch = 0


def session_revocation_epoch() -> int:
    return _revocation_epoch


def bump_session_revocation() -> None:
    """Tell open audio sockets to re-authenticate on their next frame.

    Called after a lock, logout or roster change has been committed, so a
    socket that rechecks because of the bump is guaranteed to see the change.
    """
    global _revocation_epoch
    with _revocation_lock:
        _revocation_epoch = next(_revocation_counter)
