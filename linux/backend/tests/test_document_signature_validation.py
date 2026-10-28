import base64
import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.errors import install_error_handlers
from app.database.models import AuditLog, Case, DocumentSnapshot, SignatureRecord
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.errors import DomainError
from app.services.document_service import DocumentService


PNG = 'data:image/png;base64,' + base64.b64encode(bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    '0000000d49444154789c63606060f80f00010401005fe5c34b0000000049454e44ae426082'
)).decode()


@pytest.fixture
def frozen_case(tmp_path):
    factory = make_session_factory(make_engine(f"sqlite:///{tmp_path / 'sign-validation.db'}"))
    init_database(factory.kw['bind'])
    with factory() as db:
        db.add(Case(id='CASE-A', workflow_state='FROZEN', document_status='FROZEN'))
        db.flush()
        db.add(DocumentSnapshot(id='snapshot-a', case_id='CASE-A', version=1, content_json='{}',
                                content_hash=hashlib.sha256(b'{}').hexdigest()))
        db.commit()
    return factory


def test_invalid_signature_does_not_poison_snapshot_or_advance_state(frozen_case):
    with frozen_case() as db:
        service = DocumentService(db)
        with pytest.raises(DomainError) as error:
            service.sign('CASE-A', signer_role='SUSPECT', signer_name='当事人',
                         image_data='data:image/png;base64,AAA')
        assert error.value.code == 'INVALID_SIGNATURE_IMAGE'
        assert db.scalar(select(SignatureRecord)) is None
        assert db.scalar(select(AuditLog).where(AuditLog.action == 'SIGNATURE_SAVE')) is None
        case = db.get(Case, 'CASE-A')
        assert case.workflow_state == case.document_status == 'FROZEN'
        state = service.sign('CASE-A', signer_role='SUSPECT', signer_name='当事人', image_data=PNG)
        assert len(state['signatures']) == 1
        assert db.scalar(select(SignatureRecord)).image_data == PNG


@pytest.mark.parametrize('suffix', ['document/sign', 'signatures'])
def test_both_signing_aliases_reject_images_before_saving_or_finalizing(frozen_case, suffix):
    from app.api.signature import router
    app = FastAPI()
    app.state.session_factory = frozen_case
    install_error_handlers(app)
    app.include_router(router, prefix='/api/v1')
    with TestClient(app) as client:
        for index, role in enumerate(('SUSPECT', 'OFFICER')):
            body = {'signerRole': role, 'signerName': '签署人', 'imageDataUrl': 'data:image/png;base64,AAA'}
            if suffix == 'signatures':
                body = {'signer_role': role, 'signer_name': '签署人', 'image_data': 'data:image/png;base64,AAA'}
            response = client.post(f'/api/v1/cases/CASE-A/{suffix}', json=body)
            assert response.status_code == 400, response.text
            assert response.json()['code'] == 'INVALID_SIGNATURE_IMAGE'
            with frozen_case() as db:
                assert len(list(db.scalars(select(SignatureRecord)))) == index
                case = db.get(Case, 'CASE-A')
                assert case.workflow_state == case.document_status == 'FROZEN'
            body['image_data' if suffix == 'signatures' else 'imageDataUrl'] = PNG
            response = client.post(f'/api/v1/cases/CASE-A/{suffix}', json=body)
            assert response.status_code == 200, response.text
            assert len(response.json()['data']['signatures']) == index + 1
        with frozen_case() as db:
            assert db.get(Case, 'CASE-A').workflow_state == 'SIGNED'
