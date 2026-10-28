import base64
import hashlib
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.errors import install_error_handlers
from app.auth.context import Actor, actor_context
from app.database.models import AuditLog, Case, DocumentSnapshot, SignatureRecord
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.errors import DomainError


PNG = 'data:image/png;base64,' + base64.b64encode(bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    '0000000d49444154789c63606060f80f00010401005fe5c34b0000000049454e44ae426082'
)).decode()


@pytest.fixture
def exports(tmp_path):
    from app.database import document_export_models, document_mark_models  # noqa: F401
    from app.database.document_mark_models import DocumentFingerprint
    factory = make_session_factory(make_engine(f"sqlite:///{tmp_path / 'exports.db'}"))
    init_database(factory.kw['bind'])
    content = json.dumps({'case': {'case_id': 'CASE-A', 'suspectName': '张某', 'officerName': '李警官'},
                          'transcript': {'source': 'TEMPLATE_ROUNDS', 'templateKey': 'VICTIM',
                                         'questions': [{'text': '何时发现？', 'formalAnswerText': '昨晚八点。', 'sortOrder': 0},
                                                       {'text': '丢失物品？', 'formalAnswerText': '手机<&>一部。', 'sortOrder': 1}],
                                         'entries': [{'answerText': '不能用临时回合替换正本'}]}}, ensure_ascii=False)
    with factory() as db:
        db.add_all([Case(id='CASE-A', suspect_name='实时姓名不得用于导出', workflow_state='SIGNED'),
                    Case(id='CASE-B', suspect_name='乙')])
        db.flush()
        db.add(DocumentSnapshot(id='snapshot-a', case_id='CASE-A', version=1, status='SIGNED',
                                content_json=content, content_hash=hashlib.sha256(content.encode()).hexdigest()))
        db.flush()
        for role in ('SUSPECT', 'OFFICER'):
            db.add(SignatureRecord(id=role, case_id='CASE-A', snapshot_id='snapshot-a', signer_role=role,
                                   signer_name='张某' if role == 'SUSPECT' else '李警官', image_data=PNG, status='SAVED'))
        db.add(DocumentFingerprint(id='fingerprint-a', case_id='CASE-A', snapshot_id='snapshot-a', image_data=PNG,
                                  device_id='REAL-TEST', sha256=hashlib.sha256(base64.b64decode(PNG.split(',')[1])).hexdigest()))
        db.commit()
    token = actor_context.set(Actor('038291', '李警官', '刑侦', True))
    yield factory, tmp_path / 'data'
    actor_context.reset(token)


def test_docx_is_real_puretext_from_frozen_snapshot_and_audited(exports):
    from app.services.document_export_service import DocumentExportService
    factory, data_dir = exports
    with factory() as db:
        service = DocumentExportService(db, data_dir)
        metadata = service.create('CASE-A', 'DOCX')
        assert metadata['actorId'] == '038291'
        assert metadata['exportCount'] == 1
        assert metadata['snapshotId'] == 'snapshot-a'
        assert metadata['downloadUrl'].endswith('/file')
        path, download = service.download('CASE-A', metadata['id'])
        assert path.resolve().is_relative_to((data_dir / 'exports').resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata['sha256']
        with zipfile.ZipFile(path) as archive:
            xml = archive.read('word/document.xml').decode()
            assert '张某' in xml and '昨晚八点。' in xml and '手机&lt;&amp;&gt;一部。' in xml
            assert '实时姓名' not in xml and '不能用临时回合' not in xml
            assert '<w:keepNext/>' in xml
            assert not any(name.startswith('word/media/') for name in archive.namelist())
        assert download['format'] == 'DOCX'
        rows = list(db.scalars(select(AuditLog).where(AuditLog.case_id == 'CASE-A')))
        assert {row.action for row in rows} == {'DOCUMENT_EXPORT', 'DOCUMENT_EXPORT_DOWNLOAD'}
        assert all(row.actor_id == '038291' for row in rows)
        assert service.list('CASE-A')['exportCount'] == 1


def test_pdf_embeds_images_and_preserves_chinese_text(exports):
    from app.services.document_export_service import DocumentExportService
    factory, data_dir = exports
    with factory() as db:
        service = DocumentExportService(db, data_dir)
        metadata = service.create('CASE-A', 'PDF')
        path, _ = service.download('CASE-A', metadata['id'])
        content = path.read_bytes()
        assert content.startswith(b'%PDF-')
        assert b'/Subtype /Image' in content
        assert b'STSong-Light' in content
        assert metadata['signatureCount'] == 2 and metadata['fingerprintSha256']


def test_live_questions_also_export_canonical_answers_and_legacy_police_labels():
    from app.services.document_export_service import _paragraphs
    lines = _paragraphs({'case': {}, 'transcript': {
        'source': 'TEMPLATE_ROUNDS', 'templateKey': None,
        'questions': [{'id': 'live-question', 'text': '追加一问？', 'formalAnswerText': '已摘入正本'},
                      {'id': 'empty-question', 'text': '未答题？', 'formalAnswerText': None}],
        'entries': [{'questionId': 'live-question', 'answerText': '待确认草稿不得导出'},
                    {'questionId': 'empty-question', 'answerText': '空正本待确认草稿不得导出'}],
    }})
    assert '答：已摘入正本' in lines
    assert all('待确认草稿' not in text for text in lines)
    legacy = _paragraphs({'transcript': {'source': 'LEGACY_MESSAGES', 'messages': [
        {'speaker': 'INTERROGATOR', 'text': '询问人发问'}, {'speaker': 'RECORDER', 'text': '记录员发问'},
        {'speaker': 'SUSPECT', 'text': '回答'},
    ]}})
    assert legacy[-3:] == ['问：询问人发问', '问：记录员发问', '答：回答']


@pytest.mark.parametrize('kind', ['DOCX', 'PDF'])
def test_export_refuses_corrupt_or_missing_snapshot(exports, kind):
    from app.services.document_export_service import DocumentExportService
    factory, data_dir = exports
    with factory() as db:
        with pytest.raises(DomainError) as error:
            DocumentExportService(db, data_dir).create('CASE-B', kind)
        assert error.value.code == 'DOCUMENT_NOT_FROZEN'
        db.rollback()
        db.get(DocumentSnapshot, 'snapshot-a').content_json += ' '
        db.commit()
        with pytest.raises(DomainError) as error:
            DocumentExportService(db, data_dir).create('CASE-A', kind)
        assert error.value.code == 'DOCUMENT_INTEGRITY_FAILED'
        assert not list(data_dir.rglob('*.docx')) and not list(data_dir.rglob('*.pdf'))


@pytest.mark.parametrize('missing', ['signature', 'fingerprint', 'hash'])
def test_pdf_requires_complete_same_snapshot_signing_marks(exports, missing):
    from app.database.document_mark_models import DocumentFingerprint
    from app.services.document_export_service import DocumentExportService
    factory, data_dir = exports
    with factory() as db:
        if missing == 'signature':
            db.delete(db.get(SignatureRecord, 'OFFICER'))
        elif missing == 'fingerprint':
            db.add(DocumentSnapshot(id='different-snapshot', case_id='CASE-B', version=1, status='FROZEN',
                                    content_json='{}', content_hash=hashlib.sha256(b'{}').hexdigest()))
            db.flush()
            db.get(DocumentFingerprint, 'fingerprint-a').snapshot_id = 'different-snapshot'
        else:
            db.get(DocumentFingerprint, 'fingerprint-a').sha256 = '0' * 64
        db.commit()
        with pytest.raises(DomainError):
            DocumentExportService(db, data_dir).create('CASE-A', 'PDF')


def test_export_and_download_always_require_current_actor(exports):
    from app.services.document_export_service import DocumentExportService
    factory, data_dir = exports
    token = actor_context.set(None)
    try:
        with factory() as db:
            service = DocumentExportService(db, data_dir)
            for call in (lambda: service.create('CASE-A', 'DOCX'), lambda: service.list('CASE-A'),
                         lambda: service.download('CASE-A', 'missing')):
                with pytest.raises(DomainError) as error:
                    call()
                assert error.value.status_code == 401
    finally:
        actor_context.reset(token)


def test_download_checks_case_path_and_file_integrity(exports):
    from app.database.document_export_models import DocumentExport
    from app.services.document_export_service import DocumentExportService
    factory, data_dir = exports
    with factory() as db:
        service = DocumentExportService(db, data_dir)
        metadata = service.create('CASE-A', 'DOCX')
        with pytest.raises(DomainError) as error:
            service.download('CASE-B', metadata['id'])
        assert error.value.status_code == 404
        row = db.get(DocumentExport, metadata['id'])
        original = row.stored_name
        row.stored_name = '../exports.db'
        db.commit()
        with pytest.raises(DomainError):
            service.download('CASE-A', metadata['id'])
        row.stored_name = original
        db.commit()
        (data_dir / 'exports' / original).write_bytes(b'tampered')
        with pytest.raises(DomainError) as error:
            service.download('CASE-A', metadata['id'])
        assert error.value.code == 'EXPORT_INTEGRITY_FAILED'


def test_export_rolls_back_file_and_record_when_audit_fails(exports, monkeypatch):
    from app.database.document_export_models import DocumentExport
    from app.services.document_export_service import DocumentExportService
    from app.repositories import audit
    factory, data_dir = exports
    monkeypatch.setattr(audit, 'add', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('audit failed')))
    with factory() as db:
        with pytest.raises(RuntimeError):
            DocumentExportService(db, data_dir).create('CASE-A', 'DOCX')
        assert not list(data_dir.rglob('*.docx'))
        assert db.scalar(select(DocumentExport)) is None


def test_export_api_envelope_and_authenticated_file_download(exports):
    from app.api.document_exports import router
    from app.runtime_settings import RuntimeSettings
    factory, data_dir = exports
    app = FastAPI()
    app.state.session_factory = factory
    app.state.runtime_settings = RuntimeSettings(data_dir=data_dir)
    install_error_handlers(app)
    app.include_router(router, prefix='/api/v1')
    with TestClient(app) as client:
        response = client.post('/api/v1/cases/CASE-A/exports', json={'format': 'DOCX'})
        assert response.status_code == 200, response.text
        metadata = response.json()['data']
        downloaded = client.get(metadata['downloadUrl'])
        assert downloaded.status_code == 200
        assert downloaded.content.startswith(b'PK')
        assert 'attachment' in downloaded.headers['content-disposition']
        assert client.post('/api/v1/cases/CASE-A/exports', json={'format': 'HTML', 'path': '../../x'}).status_code == 422
        token = actor_context.set(None)
        try:
            assert client.get(metadata['downloadUrl']).status_code == 401
        finally:
            actor_context.reset(token)
