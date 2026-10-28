import base64
import struct
import zlib

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AuditLog, Case
from app.database.session import init_database, make_engine
from app.domain.errors import DomainError
from app.services.document_service import DocumentService


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    raw = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00\xff')) + chunk(b'IEND', b'')
    return 'data:image/png;base64,' + base64.b64encode(raw).decode()


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f'sqlite:///{tmp_path / "marks.db"}')
    init_database(engine)
    with Session(engine) as session:
        session.add(Case(id='case', suspect_name='测试对象', workflow_state='SUMMARY'))
        session.commit()
        yield session
    engine.dispose()


def test_fingerprint_is_bound_to_frozen_snapshot_and_idempotent(db):
    from app.services.document_mark_service import DocumentMarkService

    DocumentService(db).freeze('case')
    class Device:
        def capture_fingerprint(self):
            return {'imageDataUrl': png(), 'deviceId': 'fp-test', 'simulated': False}
    service = DocumentMarkService(db, Device())
    mark = service.capture('case', actor_id='038291')
    db.commit()
    assert mark['snapshotId'] == DocumentService(db).signing_state('case')['id']
    assert mark['placement'] == 'DOCUMENT_END'
    assert len(mark['sha256']) == 64
    assert service.capture('case', actor_id='038291')['id'] == mark['id']
    assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == 'FINGERPRINT_CAPTURE')))) == 1


def test_fingerprint_rejects_simulation_unavailable_and_invalid_images(db):
    from app.services.document_mark_service import DocumentMarkService
    DocumentService(db).freeze('case')
    for result, code in [({'simulated': True, 'imageDataUrl': png()}, 'FINGERPRINT_SIMULATED'), ({'simulated': False}, 'FINGERPRINT_IMAGE_REQUIRED'), ({'imageDataUrl': 'data:image/png;base64,bad'}, 'INVALID_SIGNATURE_IMAGE')]:
        class Device:
            def capture_fingerprint(self):
                return result
        with pytest.raises(DomainError) as exc:
            DocumentMarkService(db, Device()).capture('case')
        assert exc.value.code == code
    with pytest.raises(DomainError, match='指纹'):
        DocumentMarkService(db, object()).capture('case')


def test_fingerprint_never_touches_device_before_frozen_or_after_void(db):
    from app.services.document_mark_service import DocumentMarkService
    class Device:
        def capture_fingerprint(self):
            raise AssertionError('device must not be called')
    with pytest.raises(DomainError) as exc:
        DocumentMarkService(db, Device()).capture('case')
    assert exc.value.code == 'DOCUMENT_NOT_FROZEN'
    row = db.get(Case, 'case')
    row.workflow_state = 'VOIDED'
    row.document_status = 'VOIDED'
    db.flush()
    with pytest.raises(DomainError) as exc:
        DocumentMarkService(db, Device()).capture('case')
    assert exc.value.code == 'CASE_VOIDED'
