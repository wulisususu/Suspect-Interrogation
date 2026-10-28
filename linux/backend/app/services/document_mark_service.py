import base64
import hashlib
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.context import current_actor_id
from app.database.document_mark_models import DocumentFingerprint
from app.database.session import begin_sqlite_immediate
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo, documents as document_repo
from app.services.case_management_service import assert_case_not_void
from app.services.officer_service import validate_signature_image
from app.services.serializers import iso_utc


class DocumentMarkService:
    def __init__(self, db: Session, hardware_gateway):
        self.db = db
        self.hardware = hardware_gateway

    @staticmethod
    def payload(row: DocumentFingerprint) -> dict:
        return {'id': row.id, 'caseId': row.case_id, 'snapshotId': row.snapshot_id,
                'imageDataUrl': row.image_data, 'sha256': row.sha256, 'deviceId': row.device_id,
                'actorId': row.actor_id, 'createdAt': iso_utc(row.created_at), 'placement': 'DOCUMENT_END'}

    def get(self, case_id: str) -> dict | None:
        assert_case_not_void(self.db, case_id)
        snapshot = document_repo.latest_snapshot(self.db, case_id)
        if snapshot is None:
            return None
        row = self.db.scalar(select(DocumentFingerprint).where(DocumentFingerprint.snapshot_id == snapshot.id))
        return None if row is None else self.payload(row)

    def capture(self, case_id: str, actor_id: str | None = None) -> dict:
        begin_sqlite_immediate(self.db)
        case = assert_case_not_void(self.db, case_id)
        snapshot = document_repo.latest_snapshot(self.db, case_id)
        if snapshot is None or case.workflow_state not in {'FROZEN', 'SIGNED'}:
            raise DomainError('DOCUMENT_NOT_FROZEN', '笔录冻结后、归档前才能采集指纹', 409)
        existing = self.db.scalar(select(DocumentFingerprint).where(DocumentFingerprint.snapshot_id == snapshot.id))
        if existing is not None:
            return self.payload(existing)
        capture = getattr(self.hardware, 'capture_fingerprint', None)
        if not callable(capture):
            raise DomainError('FINGERPRINT_NOT_CONFIGURED', '尚未接入可输出图像的指纹采集设备', 503)
        result = capture()
        if not isinstance(result, dict):
            raise DomainError('FINGERPRINT_IMAGE_REQUIRED', '指纹设备未返回图像', 502)
        if result.get('simulated'):
            raise DomainError('FINGERPRINT_SIMULATED', '模拟采集结果不能写入正式文书', 409)
        image = result.get('imageDataUrl') or result.get('image_data')
        if not image:
            raise DomainError('FINGERPRINT_IMAGE_REQUIRED', '指纹设备未返回图像', 502)
        image = validate_signature_image(image)
        row = DocumentFingerprint(
            id=str(uuid4()), case_id=case_id, snapshot_id=snapshot.id, image_data=image,
            sha256=hashlib.sha256(base64.b64decode(image.split(',', 1)[1])).hexdigest(),
            device_id=str(result.get('deviceId') or 'HARDWARE')[:128], actor_id=current_actor_id() or actor_id,
        )
        self.db.add(row)
        self.db.flush()
        audit_repo.add(self.db, case_id=case_id, actor_id=row.actor_id, action='FINGERPRINT_CAPTURE',
                       target_type='DOCUMENT', target_id=snapshot.id,
                       after={'fingerprintId': row.id, 'sha256': row.sha256, 'deviceId': row.device_id})
        return self.payload(row)
