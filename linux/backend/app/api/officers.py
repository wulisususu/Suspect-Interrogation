from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import envelope
from app.auth.context import current_actor, current_actor_id
from app.auth.middleware import SESSION_COOKIE, request_token
from app.domain.errors import DomainError
from app.services.officer_service import OfficerService, SESSION_HOURS


router = APIRouter(tags=['officers'])


class _Body(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')


class LoginBody(_Body):
    badge_number: str = Field(alias='badgeNumber', min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=256)


class UnlockBody(_Body):
    password: str | None = Field(default=None, max_length=256)


class OfficerCreateBody(_Body):
    badge_number: str = Field(alias='badgeNumber', min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    unit: str = Field(default='', max_length=256)
    password: str = Field(min_length=12, max_length=256)
    is_admin: bool = Field(default=False, alias='isAdmin')


class OfficerUpdateBody(_Body):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    unit: str | None = Field(default=None, max_length=256)
    enabled: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=256)
    is_admin: bool | None = Field(default=None, alias='isAdmin')


class CaseOfficersBody(_Body):
    interrogator_badge_number: str | None = Field(default=None, alias='interrogatorBadgeNumber', max_length=32)
    recorder_badge_number: str | None = Field(default=None, alias='recorderBadgeNumber', max_length=32)


class SignatureBody(_Body):
    image_data: str = Field(alias='imageData', max_length=683000)


class SignatureEnabledBody(_Body):
    enabled: bool


class SignatureApplyBody(_Body):
    signature_id: str = Field(alias='signatureId', min_length=1, max_length=64)


def _actor():
    actor = current_actor()
    if actor is None:
        raise DomainError('AUTH_SESSION_REQUIRED', '请先验证民警身份', 401)
    return actor


def _admin():
    actor = _actor()
    if not actor.is_admin:
        raise DomainError('AUTH_ADMIN_REQUIRED', '此操作仅管理员可执行', 403)
    return actor


def _signature_owner(badge_number: str):
    actor = _actor()
    if not actor.is_admin and actor.badge_number != badge_number:
        raise DomainError('OFFICER_SIGNATURE_FORBIDDEN', '只能维护本人的预录入签名', 403)
    return actor


@router.get('/auth/session')
def session_status(request: Request, db: Session = Depends(get_db)):
    return envelope(OfficerService(db).session_status(request_token(request), required=getattr(request.state, 'officer_auth_required', False)))


@router.post('/auth/login')
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)):
    result = OfficerService(db).login(body.badge_number, body.password)
    db.commit()
    response.set_cookie(SESSION_COOKIE, result.pop('token'), max_age=SESSION_HOURS*3600, httponly=True,
                        secure=request.url.scheme == 'https', samesite='strict', path='/')
    return envelope(result, '民警身份已验证')


@router.post('/auth/lock')
def lock(request: Request, db: Session = Depends(get_db)):
    _actor()
    result = OfficerService(db).lock(request_token(request))
    db.commit()
    return envelope(result, '面板已锁定')


@router.post('/auth/unlock')
def unlock(request: Request, body: UnlockBody | None = None, db: Session = Depends(get_db)):
    result = OfficerService(db).unlock(request_token(request), password=body.password if body else None)
    db.commit()
    return envelope(result, '面板已解锁')


@router.post('/auth/logout')
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    OfficerService(db).logout(request_token(request))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path='/')
    return envelope(None, '已退出验证')


@router.get('/officers')
def officers(active_only: bool = Query(False, alias='activeOnly'), db: Session = Depends(get_db)):
    _actor()
    return envelope(OfficerService(db).list_officers(active_only=active_only))


@router.post('/officers')
def create_officer(body: OfficerCreateBody, db: Session = Depends(get_db)):
    _admin()
    result = OfficerService(db).provision_officer(**body.model_dump())
    db.commit()
    return envelope(result, '民警名录已新增')


@router.patch('/officers/{badge_number}')
def update_officer(badge_number: str, body: OfficerUpdateBody, db: Session = Depends(get_db)):
    _admin()
    result = OfficerService(db).update_officer(badge_number, **body.model_dump(exclude_unset=True))
    db.commit()
    return envelope(result, '民警名录已更新')


@router.get('/cases/{case_id}/officers')
def case_officers(case_id: str, db: Session = Depends(get_db)):
    return envelope(OfficerService(db).case_officers(case_id))


@router.put('/cases/{case_id}/officers')
def bind_case_officers(case_id: str, body: CaseOfficersBody, db: Session = Depends(get_db)):
    _actor()
    result = OfficerService(db).bind_case_officers(case_id, **body.model_dump())
    db.commit()
    return envelope(result, '本案民警已更新')


@router.get('/officers/{badge_number}/signatures')
def signatures(badge_number: str, db: Session = Depends(get_db)):
    _actor()
    return envelope(OfficerService(db).list_signatures(badge_number))


@router.post('/officers/{badge_number}/signatures')
def save_signature(badge_number: str, body: SignatureBody, db: Session = Depends(get_db)):
    _signature_owner(badge_number)
    result = OfficerService(db).save_signature(badge_number, image_data=body.image_data, actor_id=current_actor_id())
    db.commit()
    return envelope(result, '民警签名已预录入')


@router.patch('/officer-signatures/{signature_id}')
def set_signature_enabled(signature_id: str, body: SignatureEnabledBody, db: Session = Depends(get_db)):
    service = OfficerService(db)
    row = service._signature(signature_id)
    _signature_owner(row.badge_number)
    result = service.set_signature_enabled(signature_id, body.enabled, actor_id=current_actor_id())
    db.commit()
    return envelope(result, '民警签名状态已更新')


@router.post('/cases/{case_id}/officer-signatures/apply')
def apply_signature(case_id: str, body: SignatureApplyBody, db: Session = Depends(get_db)):
    service = OfficerService(db)
    row = service._signature(body.signature_id)
    # A saved signature is a reusable personal credential: no other officer can
    # silently sign on its owner's behalf, including a roster administrator.
    if _actor().badge_number != row.badge_number:
        raise DomainError('OFFICER_SIGNATURE_FORBIDDEN', '必须由签名民警本人确认调用', 403)
    result = service.apply_signature(case_id, body.signature_id, actor_id=current_actor_id())
    db.commit()
    return envelope(result, '民警签名已写入笔录')


@router.get('/officers/{badge_number}/signature-uses')
def signature_uses(badge_number: str, limit: int = Query(100, ge=1, le=200), db: Session = Depends(get_db)):
    _signature_owner(badge_number)
    return envelope(OfficerService(db).signature_uses(badge_number, limit=limit))
