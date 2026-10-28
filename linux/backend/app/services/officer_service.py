from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import zlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.context import Actor, current_actor_id
from app.database.base import utc_now
from app.database.models import SignatureRecord
from app.database.officer_models import CaseOfficerBinding, Officer, OfficerSession, OfficerSignature, OfficerSignatureUse
from app.database.session import begin_sqlite_immediate
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo, cases as case_repo
from app.services.document_service import DocumentService
from app.services.formal_record_policy import assert_formal_record_mutable
from app.services.serializers import iso_utc


EXEMPTION_SECONDS = 600
SESSION_HOURS = 8
PASSWORD_ITERATIONS = 600_000
MAX_SIGNATURE_BYTES = 512_000


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _password_hash(password: str) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise DomainError('INVALID_OFFICER_PASSWORD', '密码至少12个字符，最多256个字符', 400)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, PASSWORD_ITERATIONS)
    return f'pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}'


def _password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or not isinstance(password, str) or len(password) > 256:
            return False
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or '').encode()).hexdigest()


def validate_signature_image(value: str) -> str:
    """Accept bounded, CRC-checked noninterlaced PNG; never persist arbitrary data URLs."""
    def invalid():
        return DomainError('INVALID_SIGNATURE_IMAGE', '签名必须是有效且不超过512KB、4096像素的PNG图像', 400)
    if not isinstance(value, str) or not value.startswith('data:image/png;base64,') or len(value) > MAX_SIGNATURE_BYTES * 4 // 3 + 100:
        raise invalid()
    try:
        raw = base64.b64decode(value.split(',', 1)[1], validate=True)
    except (ValueError, TypeError):
        raise invalid() from None
    if len(raw) > MAX_SIGNATURE_BYTES or raw[:8] != b'\x89PNG\r\n\x1a\n':
        raise invalid()
    pos, width, height, channels = 8, 0, 0, 0
    compressed = bytearray()
    ended = False
    try:
        while pos < len(raw):
            size = struct.unpack('>I', raw[pos:pos+4])[0]
            kind = raw[pos+4:pos+8]
            payload = raw[pos+8:pos+8+size]
            crc = struct.unpack('>I', raw[pos+8+size:pos+12+size])[0]
            if len(payload) != size or zlib.crc32(kind + payload) & 0xffffffff != crc:
                raise invalid()
            if pos == 8 and kind != b'IHDR':
                raise invalid()
            if kind == b'IHDR':
                if width or size != 13:
                    raise invalid()
                width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
                channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color, 0)
                if not (0 < width <= 4096 and 0 < height <= 4096 and width*height <= 4_194_304 and channels and depth == 8 and compression == filtering == interlace == 0):
                    raise invalid()
            elif kind == b'IDAT':
                compressed.extend(payload)
            elif kind == b'IEND':
                if size or pos+12 != len(raw):
                    raise invalid()
                ended = True
                break
            pos += size+12
        if not ended or not compressed:
            raise invalid()
        expected_size = (width*channels+1)*height
        inflater = zlib.decompressobj()
        decoded = inflater.decompress(bytes(compressed), expected_size+1)
        if len(decoded) != expected_size or not inflater.eof or inflater.unused_data or any(decoded[y*(width*channels+1)] > 4 for y in range(height)):
            raise invalid()
    except (struct.error, zlib.error, OverflowError):
        raise invalid() from None
    return value


class OfficerService:
    def __init__(self, db: Session, *, now=utc_now):
        self.db = db
        self.now = now

    def configured(self) -> bool:
        return self.db.scalar(select(Officer.badge_number).where(Officer.enabled.is_(True), Officer.is_admin.is_(True)).limit(1)) is not None

    def _officer(self, badge_number: str, *, active: bool = False) -> Officer:
        row = self.db.get(Officer, str(badge_number or '').strip())
        if row is None:
            raise DomainError('OFFICER_NOT_FOUND', '民警不存在', 404)
        if active and not row.enabled:
            raise DomainError('OFFICER_DISABLED', '该民警已停用', 409)
        return row

    @staticmethod
    def officer_payload(row: Officer) -> dict:
        return {'badgeNumber': row.badge_number, 'name': row.name, 'unit': row.unit,
                'enabled': row.enabled, 'isAdmin': row.is_admin,
                'displayName': f'{row.name}（{row.badge_number}）'}

    def get_officer(self, badge_number: str, *, include_disabled: bool = True) -> dict:
        return self.officer_payload(self._officer(badge_number, active=not include_disabled))

    def list_officers(self, *, active_only: bool = False) -> list[dict]:
        query = select(Officer).order_by(Officer.badge_number)
        if active_only:
            query = query.where(Officer.enabled.is_(True))
        return [self.officer_payload(row) for row in self.db.scalars(query)]

    def provision_officer(self, *, badge_number: str, name: str, unit: str = '', password: str, is_admin: bool = False) -> dict:
        begin_sqlite_immediate(self.db)
        badge = str(badge_number or '').strip()
        clean_name = str(name or '').strip()
        if not badge or len(badge) > 32 or not badge.isascii() or not badge.isalnum() or not clean_name or len(clean_name) > 128 or len(unit) > 256:
            raise DomainError('INVALID_OFFICER', '警号、姓名或工作单位格式无效', 400)
        if self.db.get(Officer, badge) is not None:
            raise DomainError('OFFICER_ALREADY_EXISTS', '警号已经存在', 409)
        row = Officer(badge_number=badge, name=clean_name, unit=unit.strip(), enabled=True,
                      is_admin=is_admin, password_hash=_password_hash(password))
        self.db.add(row)
        self.db.flush()
        audit_repo.add(self.db, case_id=None, actor_id=current_actor_id(), action='OFFICER_CREATE',
                       target_type='OFFICER', target_id=badge, after=self.officer_payload(row))
        return self.officer_payload(row)

    def update_officer(self, badge_number: str, *, name: str | None = None, unit: str | None = None,
                       enabled: bool | None = None, is_admin: bool | None = None, password: str | None = None) -> dict:
        begin_sqlite_immediate(self.db)
        row = self._officer(badge_number)
        if row.enabled and row.is_admin and (enabled is False or is_admin is False):
            admins = self.db.scalar(select(func.count()).select_from(Officer).where(Officer.enabled.is_(True), Officer.is_admin.is_(True)))
            if admins <= 1:
                raise DomainError('LAST_ADMIN_REQUIRED', '至少保留一名启用的管理员', 409)
        before = self.officer_payload(row)
        if name is not None:
            if not name.strip() or len(name) > 128:
                raise DomainError('INVALID_OFFICER', '姓名不能为空或过长', 400)
            row.name = name.strip()
        if unit is not None:
            if len(unit) > 256:
                raise DomainError('INVALID_OFFICER', '工作单位过长', 400)
            row.unit = unit.strip()
        if enabled is not None:
            row.enabled = enabled
        if is_admin is not None:
            row.is_admin = is_admin
        if password is not None:
            row.password_hash = _password_hash(password)
        if enabled is False or password is not None:
            for session in self.db.scalars(select(OfficerSession).where(OfficerSession.badge_number == row.badge_number)):
                self.db.delete(session)
        self.db.flush()
        audit_repo.add(self.db, case_id=None, action='OFFICER_UPDATE', target_type='OFFICER',
                       target_id=row.badge_number, before=before, after=self.officer_payload(row))
        return self.officer_payload(row)

    def _verify_credentials(self, badge_number: str, password: str) -> Officer:
        row = self.db.get(Officer, str(badge_number or '').strip())
        now = _utc(self.now())
        if row is not None and row.login_blocked_until is not None and _utc(row.login_blocked_until) > now:
            raise DomainError('AUTH_RATE_LIMITED', '登录尝试过多，请稍后再试', 429)
        if row is None or not row.enabled or not _password_matches(password, row.password_hash):
            if row is not None:
                row.failed_login_count += 1
                if row.failed_login_count >= 5:
                    row.login_blocked_until = now + timedelta(minutes=1)
                    row.failed_login_count = 0
                # Invalid credential attempts must survive the dependency rollback.
                self.db.commit()
            raise DomainError('AUTH_INVALID_CREDENTIALS', '警号或密码错误', 401)
        row.failed_login_count = 0
        row.login_blocked_until = None
        return row

    def login(self, badge_number: str, password: str) -> dict:
        if not self.configured():
            raise DomainError('AUTH_NOT_CONFIGURED', '请先由管理员通过命令行配置民警账号', 503)
        officer = self._verify_credentials(badge_number, password)
        now = _utc(self.now())
        token = secrets.token_urlsafe(32)
        row = OfficerSession(token_hash=_token_hash(token), badge_number=officer.badge_number, issued_at=now,
                             expires_at=now+timedelta(hours=SESSION_HOURS), exemption_until=now+timedelta(seconds=EXEMPTION_SECONDS), locked=False)
        self.db.add(row)
        self.db.flush()
        audit_repo.add(self.db, case_id=None, actor_id=officer.badge_number, action='OFFICER_LOGIN', target_type='OFFICER', target_id=officer.badge_number)
        return {**self.session_status(token), 'token': token}

    def _session(self, token: str, *, allow_locked: bool = False) -> tuple[OfficerSession, Officer]:
        row = self.db.get(OfficerSession, _token_hash(token)) if token else None
        if row is None or _utc(row.expires_at) <= _utc(self.now()):
            raise DomainError('AUTH_SESSION_REQUIRED', '请重新验证民警身份', 401)
        officer = self.db.get(Officer, row.badge_number)
        if officer is None or not officer.enabled:
            raise DomainError('AUTH_SESSION_REQUIRED', '账号已停用，请重新验证身份', 401)
        if row.locked and not allow_locked:
            raise DomainError('AUTH_SESSION_LOCKED', '面板已锁定，请先解锁', 423)
        return row, officer

    def authenticate(self, token: str, *, allow_locked: bool = False) -> Actor:
        _, officer = self._session(token, allow_locked=allow_locked)
        return Actor(officer.badge_number, officer.name, officer.unit, officer.is_admin)

    def session_status(self, token: str | None, *, required: bool | None = None) -> dict:
        configured = self.configured()
        result = {'configured': configured, 'required': configured if required is None else bool(required or configured),
                  'authenticated': False, 'locked': False, 'officer': None, 'exemptionRemainingSeconds': 0}
        if not token:
            return result
        row, officer = self._session(token, allow_locked=True)
        return {**result, 'authenticated': True, 'locked': row.locked, 'officer': self.officer_payload(officer),
                'expiresAt': iso_utc(row.expires_at), 'exemptionUntil': iso_utc(row.exemption_until),
                'exemptionRemainingSeconds': max(0, int((_utc(row.exemption_until)-_utc(self.now())).total_seconds()))}

    def lock(self, token: str) -> dict:
        row, _ = self._session(token)
        row.locked = True
        self.db.flush()
        audit_repo.add(self.db, case_id=None, actor_id=row.badge_number, action='OFFICER_LOCK', target_type='OFFICER', target_id=row.badge_number)
        return self.session_status(token)

    def unlock(self, token: str, *, password: str | None = None) -> dict:
        row, officer = self._session(token, allow_locked=True)
        now = _utc(self.now())
        if _utc(row.exemption_until) <= now:
            if password is None:
                raise DomainError('AUTH_REAUTHENTICATION_REQUIRED', '免验已过期，请重新输入密码', 401)
            self._verify_credentials(officer.badge_number, password)
            row.exemption_until = now+timedelta(seconds=EXEMPTION_SECONDS)
        row.locked = False
        self.db.flush()
        audit_repo.add(self.db, case_id=None, actor_id=officer.badge_number, action='OFFICER_UNLOCK', target_type='OFFICER', target_id=officer.badge_number)
        return self.session_status(token)

    def logout(self, token: str) -> None:
        row, _ = self._session(token, allow_locked=True)
        self.db.delete(row)
        self.db.flush()

    def bind_case_officers(self, case_id: str, *, interrogator_badge_number: str | None, recorder_badge_number: str | None) -> dict:
        case = assert_formal_record_mutable(self.db, case_id)
        interrogator = self._officer(interrogator_badge_number, active=True) if interrogator_badge_number else None
        recorder = self._officer(recorder_badge_number, active=True) if recorder_badge_number else None
        if interrogator is not None and recorder is not None and interrogator.badge_number == recorder.badge_number:
            raise DomainError('OFFICER_ROLE_CONFLICT', '询问人与记录员应选择不同民警', 409)
        row = self.db.get(CaseOfficerBinding, case_id)
        if row is None:
            row = CaseOfficerBinding(case_id=case_id)
            self.db.add(row)
        row.interrogator_badge_number = interrogator.badge_number if interrogator else None
        row.recorder_badge_number = recorder.badge_number if recorder else None
        if interrogator:
            case.officer_name = interrogator.name
        self.db.flush()
        result = self.case_officers(case_id)
        audit_repo.add(self.db, case_id=case_id, action='CASE_OFFICERS_UPDATE', target_type='CASE', target_id=case_id, after=result)
        return result

    def case_officers(self, case_id: str) -> dict:
        case_repo.get(self.db, case_id)
        row = self.db.get(CaseOfficerBinding, case_id)
        return {'caseId': case_id,
                'interrogator': self.get_officer(row.interrogator_badge_number) if row and row.interrogator_badge_number else None,
                'recorder': self.get_officer(row.recorder_badge_number) if row and row.recorder_badge_number else None}

    @staticmethod
    def _signature_payload(row: OfficerSignature) -> dict:
        return {'id': row.id, 'badgeNumber': row.badge_number, 'version': row.version,
                'imageData': row.image_data, 'enabled': row.enabled, 'createdAt': iso_utc(row.created_at)}

    def save_signature(self, badge_number: str, *, image_data: str, actor_id: str | None = None) -> dict:
        begin_sqlite_immediate(self.db)
        officer = self._officer(badge_number, active=True)
        image = validate_signature_image(image_data)
        version = self.db.scalar(select(func.max(OfficerSignature.version)).where(OfficerSignature.badge_number == badge_number)) or 0
        row = OfficerSignature(id=str(uuid4()), badge_number=officer.badge_number, version=version+1, image_data=image,
                               enabled=True, actor_id=current_actor_id() or actor_id, created_at=self.now())
        self.db.add(row)
        self.db.flush()
        audit_repo.add(self.db, case_id=None, actor_id=current_actor_id() or actor_id, action='OFFICER_SIGNATURE_SAVE',
                       target_type='OFFICER_SIGNATURE', target_id=row.id, after={'badgeNumber': badge_number, 'version': row.version})
        return self._signature_payload(row)

    def list_signatures(self, badge_number: str | None = None) -> list[dict]:
        query = select(OfficerSignature).order_by(OfficerSignature.created_at.desc(), OfficerSignature.version.desc())
        if badge_number:
            self._officer(badge_number)
            query = query.where(OfficerSignature.badge_number == badge_number)
        return [self._signature_payload(row) for row in self.db.scalars(query)]

    def _signature(self, signature_id: str) -> OfficerSignature:
        row = self.db.get(OfficerSignature, signature_id)
        if row is None:
            raise DomainError('OFFICER_SIGNATURE_NOT_FOUND', '预录入签名不存在', 404)
        return row

    def set_signature_enabled(self, signature_id: str, enabled: bool, *, actor_id: str | None = None) -> dict:
        row = self._signature(signature_id)
        row.enabled = enabled
        self.db.flush()
        audit_repo.add(self.db, case_id=None, actor_id=current_actor_id() or actor_id, action='OFFICER_SIGNATURE_ENABLE' if enabled else 'OFFICER_SIGNATURE_DISABLE',
                       target_type='OFFICER_SIGNATURE', target_id=row.id)
        return self._signature_payload(row)

    def apply_signature(self, case_id: str, signature_id: str, *, actor_id: str | None = None) -> dict:
        begin_sqlite_immediate(self.db)
        row = self._signature(signature_id)
        if not row.enabled:
            raise DomainError('OFFICER_SIGNATURE_DISABLED', '该预录入签名已停用', 409)
        officer = self._officer(row.badge_number, active=True)
        binding = self.db.get(CaseOfficerBinding, case_id)
        if binding is None or officer.badge_number not in {binding.interrogator_badge_number, binding.recorder_badge_number}:
            raise DomainError('SIGNATURE_OFFICER_NOT_BOUND', '该签名民警未被选为本案询问人或记录员', 409)
        # commit=False keeps document signature, invocation and audit in one transaction.
        state = DocumentService(self.db).sign(case_id, signer_role='OFFICER', signer_name=officer.name,
                                               image_data=row.image_data, actor_id=current_actor_id() or actor_id, commit=False)
        signature = self.db.scalar(select(SignatureRecord).where(SignatureRecord.snapshot_id == state['id'], SignatureRecord.signer_role == 'OFFICER'))
        self.db.add(OfficerSignatureUse(id=str(uuid4()), case_id=case_id, snapshot_id=state['id'],
                    signature_record_id=signature.id, officer_signature_id=row.id, badge_number=officer.badge_number,
                    actor_id=current_actor_id() or actor_id, used_at=self.now()))
        self.db.flush()
        audit_repo.add(self.db, case_id=case_id, actor_id=current_actor_id() or actor_id, action='OFFICER_SIGNATURE_APPLY',
                       target_type='OFFICER_SIGNATURE', target_id=row.id, after={'signatureRecordId': signature.id, 'version': row.version})
        result = next(x for x in DocumentService(self.db).list_signatures(case_id) if x['id'] == signature.id)
        return {**result, 'imageData': signature.image_data, 'officerSignatureId': row.id}

    def signature_uses(self, badge_number: str, *, limit: int = 100) -> list[dict]:
        self._officer(badge_number)
        rows = self.db.scalars(select(OfficerSignatureUse).where(OfficerSignatureUse.badge_number == badge_number)
                               .order_by(OfficerSignatureUse.used_at.desc()).limit(max(1, min(limit, 200))))
        return [{'id': row.id, 'caseId': row.case_id, 'snapshotId': row.snapshot_id, 'signatureId': row.officer_signature_id,
                 'badgeNumber': row.badge_number, 'actorId': row.actor_id, 'usedAt': iso_utc(row.used_at)} for row in rows]
