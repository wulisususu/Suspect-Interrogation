import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database.models import AuditLog
from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    from app.api.case_management import router
    app=create_app(database_url=f"sqlite:///{tmp_path/'management-api.db'}",
                   hardware_gateway=MockHardwareGateway(simulated=True))
    if not any(getattr(route,'path',None)=="/api/v1/audit-logs" for route in app.routes):
        app.include_router(router,prefix="/api/v1")
    with TestClient(app) as test_client:
        yield app,test_client


def create(client,name="测试对象"):
    response=client.post('/api/v1/cases',json={'suspectName':name})
    assert response.status_code == 200,response.text
    return response.json()['data']['id']


def test_case_lifecycle_api_envelope_and_cross_case_validation(client):
    app,c=client
    cid=create(c)
    other=create(c,"另一案件")
    q=c.post(f'/api/v1/cases/{other}/questions',json={'text':'什么时候？','source':'CASE'}).json()['data']
    rejected=c.post(f'/api/v1/cases/{cid}/interruption',json={'reason':'PARTY_LEFT','questionId':q['id']})
    assert rejected.status_code == 404
    assert c.get(f'/api/v1/cases/{cid}/management').json()['data']['interruptionReason'] is None
    interrupted=c.post(f'/api/v1/cases/{cid}/interruption',json={'reason':'NETWORK_INTERRUPTED','detail':'用户断开'})
    assert interrupted.status_code == 200
    assert interrupted.json()['ok'] is True
    assert interrupted.json()['data']['interruptedAt'].endswith('+00:00')
    spoofed=c.post(f'/api/v1/cases/{cid}/void',json={'reason':'重复建案','actorId':'fake'})
    assert spoofed.status_code == 422
    assert c.post(f'/api/v1/cases/{cid}/void',json={'reason':'  '}).status_code == 400
    voided=c.post(f'/api/v1/cases/{cid}/void',json={'reason':'重复建案'})
    assert voided.status_code == 200 and voided.json()['data']['documentStatus']=='VOIDED'
    assert c.get('/api/v1/audit-logs',params={'action':'CASE_VOID','caseId':cid}).json()['data']['total']==1


def test_global_audit_pagination_and_unknown_result_inputs(client):
    _,c=client
    for name in ['一','二']:create(c,name)
    result=c.get('/api/v1/audit-logs',params={'action':'CASE_CREATE','pageSize':1}).json()
    assert result['ok'] and result['data']['total']==2
    assert len(result['data']['items'])==1
    assert result['data']['items'][0]['result']=='SUCCESS'
    assert c.get('/api/v1/audit-logs',params={'pageSize':201}).status_code == 422
    assert c.get('/api/v1/audit-logs',params={'result':'invented'}).status_code == 400


def test_validation_reports_evidence_not_fake_pass(client):
    _,c=client
    cid=create(c)
    data=c.get(f'/api/v1/cases/{cid}/validation').json()['data']
    assert data['timeline']['status']=='UNAVAILABLE'
    assert data['homophones']['configured'] is False
    assert c.post(f'/api/v1/cases/{cid}/timeline-evidence',json={
        'kind':'EVENT','at':'2026-10-28T12:00:00+08:00','source':'当事人核对'}).status_code==200
    assert c.post(f'/api/v1/cases/{cid}/timeline-evidence',json={
        'kind':'REPORT','at':'2026-10-28T13:00:00+08:00','source':'登记记录'}).status_code==200
    assert c.get(f'/api/v1/cases/{cid}/validation').json()['data']['timeline']['status']=='CONSISTENT'
