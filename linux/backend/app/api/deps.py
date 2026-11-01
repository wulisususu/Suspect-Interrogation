from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session


def get_db(request: Request) -> Generator[Session, None, None]:
    db = request.app.state.session_factory()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_hardware(request: Request):
    return request.app.state.hardware_gateway


def require_admin(request: Request) -> None:
    """Gate roster-level administration.

    Before the first administrator is provisioned the deployment runs in legacy
    preview mode, where the middleware leaves requests anonymous; afterwards the
    middleware guarantees an actor and only administrators pass.
    """
    from app.auth.context import current_actor
    from app.domain.errors import DomainError

    actor = current_actor()
    if actor is None:
        if getattr(request.state, "officer_auth_required", False):
            raise DomainError("AUTH_SESSION_REQUIRED", "请先验证民警身份", 401)
        return
    if not actor.is_admin:
        raise DomainError("AUTH_ADMIN_REQUIRED", "此操作仅管理员可执行", 403)
