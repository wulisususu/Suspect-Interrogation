import hashlib
import json
import zipfile
from datetime import datetime, timezone

from sqlalchemy import select

from app.auth.context import Actor, actor_context
from app.database.models import Case, CaseQuestion, DocumentSnapshot, Fact, InterrogationSession, Person, QuestionRound
from app.database.officer_models import Officer
from app.database.session import init_database, make_engine, make_session_factory
from app.repositories import facts as fact_repo
from app.services.case_service import CaseService
from app.services.document_export_service import DocumentExportService, _paragraphs
from app.services.document_service import DocumentService


def test_actual_freeze_preserves_identity_roster_location_session_and_canonical_answer(tmp_path):
    factory = make_session_factory(make_engine(f"sqlite:///{tmp_path / 'frozen-header.db'}"))
    init_database(factory.kw['bind'])
    with factory() as db:
        db.add_all([Officer(badge_number='001', name='冻结询问人', unit='原单位', password_hash='not-used'),
                    Officer(badge_number='002', name='冻结记录人', unit='原单位', password_hash='not-used'),
                    Case(id='CASE-OLD', workflow_state='FROZEN')])
        db.flush()
        old_content = '{"case":{"id":"CASE-OLD","suspectName":"历史姓名"}}'
        old_hash = hashlib.sha256(old_content.encode()).hexdigest()
        db.add(DocumentSnapshot(id='old-snapshot', case_id='CASE-OLD', version=1,
                                content_json=old_content, content_hash=old_hash))
        db.commit()
        token = actor_context.set(Actor('001', '冻结询问人', '原单位', False))
        try:
            case = CaseService(db).intake(
                {'interrogatorBadgeNumber': '001', 'recorderBadgeNumber': '002'},
                {'name': '冻结身份姓名', 'idNumber': 'ID-FROZEN-001', 'source': 'MANUAL'})
            case_id = case['id']
            fact_repo.update(db, case_id, 'interrogation_place', {'value': '冻结询问室', 'status': 'confirmed'})
            db.get(Case, case_id).workflow_state = 'SUMMARY'
            session = InterrogationSession(id='session-frozen', case_id=case_id, status='COMPLETED',
                                           started_at=datetime(2026, 10, 28, 2, 0, tzinfo=timezone.utc),
                                           ended_at=datetime(2026, 10, 28, 3, 5, tzinfo=timezone.utc))
            question = CaseQuestion(id='question-frozen', case_id=case_id, source='CASE', sort_order=0,
                                    text='冻结问题？', formal_answer_text='冻结正本回答')
            db.add_all([session, question])
            db.flush()
            db.add(QuestionRound(id='round-frozen', case_id=case_id, session_id=session.id,
                                 case_question_id=question.id, round_no=1, actual_question_text='实际问法',
                                 answer_text='冻结时的草稿不得导出', status='CLOSED'))
            db.commit()
            state = DocumentService(db).freeze(case_id)
            snapshot = db.get(DocumentSnapshot, state['id'])
            original_json, original_hash = snapshot.content_json, snapshot.content_hash
            content = json.loads(original_json)
            assert content['case']['idNumber'] == 'ID-FROZEN-001'
            assert content['case']['interrogator']['name'] == '冻结询问人'
            assert content['case']['recorder']['name'] == '冻结记录人'
            assert content['session']['startedAt'] == '2026-10-28T02:00:00+00:00'
            assert content['session']['endedAt'] == '2026-10-28T03:05:00+00:00'
            # Bypass normal frozen-case guards only to prove exports never consult live data.
            person = db.scalar(select(Person).where(Person.case_id == case_id))
            person.name, person.id_number = '变更后的身份姓名', 'ID-MUTATED'
            db.get(Officer, '001').name = '变更后的询问人'
            db.get(Officer, '002').name = '变更后的记录人'
            db.scalar(select(Fact).where(Fact.case_id == case_id, Fact.fact_key == 'interrogation_place')).value = '变更后的地点'
            session.started_at = session.ended_at = datetime(2027, 1, 1, tzinfo=timezone.utc)
            question.formal_answer_text = '变更后的正本回答'
            db.commit()
            service = DocumentExportService(db, tmp_path / 'data')
            export = service.create(case_id, 'DOCX')
            path, _ = service.download(case_id, export['id'])
            with zipfile.ZipFile(path) as archive:
                xml = archive.read('word/document.xml').decode()
            for expected in ('冻结身份姓名', 'ID-FROZEN-001', '冻结询问人', '冻结记录人', '冻结询问室',
                             '2026-10-28 10:00:00', '2026-10-28 11:05:00', '冻结正本回答'):
                assert expected in xml
            assert '变更后' not in xml and 'ID-MUTATED' not in xml and '草稿不得导出' not in xml
            assert snapshot.content_json == original_json and snapshot.content_hash == original_hash
            assert hashlib.sha256(snapshot.content_json.encode()).hexdigest() == original_hash
            old_snapshot = db.get(DocumentSnapshot, 'old-snapshot')
            assert old_snapshot.content_json == old_content and old_snapshot.content_hash == old_hash
        finally:
            actor_context.reset(token)


def test_old_snapshot_missing_header_fields_shows_unrecorded_without_inventing_metadata():
    lines = _paragraphs({'case': {'id': 'CASE-OLD', 'suspectName': '历史姓名', 'officerName': '历史民警',
                                  'createdAt': '2026-10-01T00:00:00+00:00'},
                         'facts': [{'key': 'interrogation_place', 'value': '未录入'},
                                   {'key': 'recorder_name', 'value': '未录入'}]})
    assert any('询问时间' in line and '未记录 至 未记录' in line for line in lines)
    assert '询问地点：未记录' in lines
    assert any('询问人：历史民警' in line and '记录人：未记录' in line for line in lines)
    assert any('证件号码：未记录' in line for line in lines)
    assert all('2026-10-01' not in line for line in lines)


def test_real_legacy_message_snapshot_preserves_chinese_question_and_answer_roles(tmp_path):
    from app.repositories import messages as message_repo

    engine = make_engine(f'sqlite:///{tmp_path / "legacy-messages.db"}')
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        db.add(Case(id='LEGACY-CASE', workflow_state='SUMMARY'))
        db.flush()
        db.add(InterrogationSession(id='LEGACY-SESSION', case_id='LEGACY-CASE', status='COMPLETED'))
        db.flush()
        message_repo.create(db, case_id='LEGACY-CASE', session_id='LEGACY-SESSION', speaker='民警', text='什么时候到的？')
        message_repo.create(db, case_id='LEGACY-CASE', session_id='LEGACY-SESSION', speaker='嫌疑人', text='上午八点。')
        db.commit()
        DocumentService(db).freeze('LEGACY-CASE')
        snapshot = db.scalar(select(DocumentSnapshot).where(DocumentSnapshot.case_id == 'LEGACY-CASE'))
        lines = _paragraphs(json.loads(snapshot.content_json))
        assert lines[-2:] == ['问：什么时候到的？', '答：上午八点。']
    engine.dispose()
