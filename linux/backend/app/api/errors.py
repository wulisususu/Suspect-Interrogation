from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import DomainError
import logging

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


def _record_failure(request: Request, code: str, status_code: int) -> None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"} or not request.url.path.startswith("/api/v1/"):
        return
    from app.database.models import Case
    from app.repositories import audit as audit_repo

    try:
        with request.app.state.session_factory() as db:
            requested_case = request.path_params.get("case_id")
            case_id = requested_case if requested_case and db.get(Case, requested_case) is not None else None
            audit_repo.add(db, case_id=case_id, action="API_REQUEST_FAILED", result="FAILURE",
                           target_type="CASE" if case_id else "API", target_id=case_id,
                           detail={"method": request.method, "path": request.url.path, "errorCode": code, "httpStatus": status_code})
            db.commit()
    except Exception:
        logger.exception("failed to persist unsuccessful API action")


def error_body(code: str, message: str, data=None) -> dict:
    return {"ok": False, "code": code, "message": message, "data": data}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(_request: Request, exc: DomainError):
        await run_in_threadpool(_record_failure, _request, exc.code, exc.status_code)
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.data))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        await run_in_threadpool(_record_failure, _request, "VALIDATION_ERROR", 422)
        details = []
        for item in exc.errors():
            safe = {k: v for k, v in item.items() if k not in {"input", "ctx"}}
            details.append(safe)
        return JSONResponse(status_code=422, content=error_body("VALIDATION_ERROR", "请求参数校验失败", {"errors": details}))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return JSONResponse(status_code=404, content=error_body("NOT_FOUND", "接口不存在"))
        return JSONResponse(status_code=exc.status_code, content=error_body(f"HTTP_{exc.status_code}", str(exc.detail)))
