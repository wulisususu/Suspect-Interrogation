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
