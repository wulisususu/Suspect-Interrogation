import base64

from fastapi.testclient import TestClient

from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app
from app.repositories import persons as person_repo


VALID_SIGNATURE_PNG = 'data:image/png;base64,' + base64.b64encode(bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    '0000000d49444154789c63606060f80f00010401005fe5c34b0000000049454e44ae426082'
)).decode()


def payload(response):
    body = response.json()
    assert body["ok"] is True, body
    assert body["code"] == "OK"
    return body["data"]


def test_formal_api_rejects_unknown_request_fields_while_legacy_ignores_them(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'strict-request-fields.db'}", hardware_gateway=MockHardwareGateway(simulated=True))
    with TestClient(app) as client:
        formal = client.post("/api/v1/cases", json={"suspectName": "测试对象", "unexpected": "must fail"})
        assert formal.status_code == 422
        assert formal.json()["code"] == "VALIDATION_ERROR"
        assert any(item["type"] == "extra_forbidden" for item in formal.json()["data"]["errors"])

        legacy = client.post("/api/cases/create", json={"suspectName": "测试对象", "unexpected": "ignored"})
        assert legacy.status_code == 200
        assert payload(legacy)["suspectName"] == "测试对象"


def test_canonical_api_full_case_flow(tmp_path, enroll_test_suspect_voiceprint):
    db_url = f"sqlite:///{tmp_path / 'api.db'}"
    app = create_app(database_url=db_url, hardware_gateway=MockHardwareGateway(simulated=True))
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert payload(health)["platform"] == "linux"

        created = payload(client.post("/api/v1/cases", json={"operator_id": "op-1", "suspectName": "测试对象", "officerName": "测试警官"}))
        case_id = created["id"]
        assert created["workflowState"] == "IDENTITY_REQUIRED"

        listed = payload(client.get("/api/v1/cases"))
        assert [x["id"] for x in listed] == [case_id]

        updated = payload(client.put(f"/api/v1/cases/{case_id}", json={"age": "22"}))
        assert updated["age"] == "22"

        identity = payload(client.post("/api/v1/identity/read", json={"case_id": case_id, "actor_id": "op-1"}))
        assert identity["name"] == "联调测试对象"
        assert payload(client.get(f"/api/v1/cases/{case_id}"))["workflowState"] == "IDENTITY_READY"
        enroll_test_suspect_voiceprint(app, case_id)

        session = payload(client.post(f"/api/v1/cases/{case_id}/session/start", json={"actor_id": "op-1"}))
        assert session["status"] == "RUNNING"
        assert session["state"] == "QUESTIONING"

        message = payload(client.post(f"/api/v1/cases/{case_id}/messages", json={"text": "你叫什么名字？", "speaker": "民警", "actor_id": "op-1"}))
        message_id = message["id"]
        assert message["version"] == 1

        revised = payload(client.put(f"/api/v1/cases/{case_id}/messages/{message_id}", json={"text": "请说明你的姓名。", "reason": "联调修订", "actor_id": "op-1"}))
        assert revised["id"] == message_id
        assert revised["version"] == 2

        revisions = payload(client.get(f"/api/v1/cases/{case_id}/messages/{message_id}/revisions"))
        assert len(revisions) == 1
        assert revisions[0]["oldText"] == "你叫什么名字？"
        assert revisions[0]["newText"] == "请说明你的姓名。"

        marked = payload(client.post(f"/api/v1/cases/{case_id}/messages/{message_id}/mark", json={"mark": "conflict", "actor_id": "op-1"}))
        assert marked["id"] == message_id
        assert marked["mark"] == "conflict"
        assert len(payload(client.get(f"/api/v1/cases/{case_id}/messages"))) == 1

        facts = payload(client.get(f"/api/v1/cases/{case_id}/facts"))
        assert len(facts) >= 7
        fact = payload(client.put(f"/api/v1/cases/{case_id}/facts/time", json={"value": "20:00", "status": "confirmed", "actor_id": "op-1"}))
        assert fact["value"] == "20:00"

        assert payload(client.post(f"/api/v1/cases/{case_id}/session/pause", json={}))["state"] == "PAUSED"
        assert payload(client.post(f"/api/v1/cases/{case_id}/session/resume", json={}))["state"] == "QUESTIONING"
        assert payload(client.post(f"/api/v1/cases/{case_id}/session/stage", json={"stage": "STATEMENT"}))["stage"] == "STATEMENT"
        assert payload(client.post(f"/api/v1/cases/{case_id}/session/finish", json={}))["state"] == "SUMMARY"

        assert client.get(f"/api/v1/cases/{case_id}/document").status_code == 200
        assert payload(client.get(f"/api/v1/cases/{case_id}/document")) is None

        frozen = payload(client.post(f"/api/v1/cases/{case_id}/document/freeze", json={"actor_id": "op-1"}))
        assert frozen["status"] == "FROZEN"
        assert frozen["integrityValid"] is True
        assert frozen["signatures"] == []
        assert frozen["documentHash"]
        assert payload(client.get(f"/api/v1/cases/{case_id}/document"))["documentId"] == frozen["documentId"]

        suspect_signed = payload(client.post(f"/api/v1/cases/{case_id}/document/sign", json={
            "signerRole": "SUSPECT",
            "signerName": "测试对象",
            "imageDataUrl": VALID_SIGNATURE_PNG,
            "strokesJson": "[]",
            "actorId": "op-1",
        }))
        assert suspect_signed["status"] == "FROZEN"
        assert [item["signerRole"] for item in suspect_signed["signatures"]] == ["SUSPECT"]

        officer_signed = payload(client.post(f"/api/v1/cases/{case_id}/document/sign", json={
            "signerRole": "OFFICER",
            "signerName": "测试警官",
            "imageDataUrl": VALID_SIGNATURE_PNG,
            "strokesJson": "[]",
            "actorId": "op-1",
        }))
        assert officer_signed["status"] == "LOCKED"
        assert [item["signerRole"] for item in officer_signed["signatures"]] == ["SUSPECT", "OFFICER"]

        report = payload(client.post(f"/api/v1/cases/{case_id}/report/generated", json={"actor_id": "op-1"}))
        assert report["reportStatus"] == "GENERATED"
        assert report["workflowState"] == "REPORT_GENERATED"

        audit = payload(client.get(f"/api/v1/cases/{case_id}/audit"))
        update_audit = next(x for x in audit if x["action"] == "QA_UPDATE")
        assert update_audit["before"]["text"] == "你叫什么名字？"
        assert update_audit["after"]["text"] == "请说明你的姓名。"


def test_confirmed_identity_intake_allows_session_start_without_hardware_reread(tmp_path, enroll_test_suspect_voiceprint):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'identity-confirm.db'}",
        hardware_gateway=MockHardwareGateway(simulated=False),
    )
    with TestClient(app) as client:
        created = payload(client.post("/api/v1/cases", json={"operator_id": "op-2", "suspectName": "赵某"}))
        case_id = created["id"]

        confirmed = payload(client.post("/api/v1/identity/confirm", json={
            "case_id": case_id,
            "actor_id": "op-2",
            "name": "赵某",
            "id_number": "320101199001010011",
            "gender": "男",
            "nation": "汉",
            "birth_date": "1990-01-01",
            "address": "测试地址",
            "source": "MANUAL",
        }))
        assert confirmed["caseId"] == case_id
        assert confirmed["name"] == "赵某"
        assert confirmed["idNumber"] == "320101199001010011"
        assert confirmed["source"] == "MANUAL"

        case = payload(client.get(f"/api/v1/cases/{case_id}"))
        assert case["workflowState"] == "IDENTITY_READY"
        assert case["suspectName"] == "赵某"
        assert case["idNumber"] == "320101199001010011"
        assert case["nation"] == "汉"
        assert case["birthDate"] == "1990-01-01"
        assert case["address"] == "测试地址"
        assert case["identitySource"] == "MANUAL"
        enroll_test_suspect_voiceprint(app, case_id)

        session = payload(client.post(f"/api/v1/cases/{case_id}/session/start", json={"actor_id": "op-2"}))
        assert session["status"] == "RUNNING"
        assert session["state"] == "QUESTIONING"


def test_case_intake_creates_case_and_confirmed_identity_in_one_request(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'case-intake.db'}",
        hardware_gateway=MockHardwareGateway(simulated=False),
    )
    with TestClient(app) as client:
        created = payload(client.post("/api/v1/cases/intake", json={
            "operatorId": "op-intake",
            "officerName": "李警官",
            "caseType": "suspect_interrogation",
            "identity": {
                "name": "赵某",
                "gender": "男",
                "nation": "汉",
                "birthDate": "1990-01-01",
                "idNumber": "320101199001010011",
                "address": "测试地址",
                "source": "ID_CARD_READER",
            },
        }))

        assert created["workflowState"] == "IDENTITY_READY"
        assert created["suspectName"] == "赵某"
        assert created["idNumber"] == "320101199001010011"
        assert created["identitySource"] == "ID_CARD_READER"
        assert len(payload(client.get(f"/api/v1/cases/{created['id']}/facts"))) >= 7
        actions = [item["action"] for item in payload(client.get(f"/api/v1/cases/{created['id']}/audit"))]
        assert {"CASE_CREATE", "IDENTITY_CONFIRM"} <= set(actions)


def test_case_intake_rolls_back_case_when_identity_persistence_fails(tmp_path, monkeypatch):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'case-intake-rollback.db'}",
        hardware_gateway=MockHardwareGateway(simulated=False),
    )

    def fail_person_create(*_args, **_kwargs):
        raise RuntimeError("simulated identity persistence failure")

    monkeypatch.setattr(person_repo, "create", fail_person_create)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/cases/intake", json={
            "operatorId": "op-intake",
            "identity": {"name": "赵某", "idNumber": "320101199001010011", "source": "MANUAL"},
        })
        assert response.status_code == 500
        assert payload(client.get("/api/v1/cases")) == []


def test_formal_record_header_updates_persist_identity_and_missing_facts(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'formal-header.db'}",
        hardware_gateway=MockHardwareGateway(simulated=False),
    )
    with TestClient(app) as client:
        created = payload(client.post("/api/v1/cases", json={"operator_id": "op-header", "suspectName": "初始姓名"}))
        case_id = created["id"]
        payload(client.post("/api/v1/identity/confirm", json={
            "case_id": case_id,
            "name": "初始姓名",
            "id_number": "320101199001010011",
            "gender": "男",
            "birth_date": "1990-01-01",
            "address": "初始地址",
            "source": "MANUAL",
        }))

        updated = payload(client.put(f"/api/v1/cases/{case_id}", json={
            "suspectName": "修订姓名",
            "idNumber": "320101199001010022",
            "birthDate": "1991-02-03",
            "address": "修订地址",
        }))
        assert updated["suspectName"] == "修订姓名"
        assert updated["idNumber"] == "320101199001010022"
        assert updated["birthDate"] == "1991-02-03"
        assert updated["address"] == "修订地址"

        place = payload(client.put(
            f"/api/v1/cases/{case_id}/facts/interrogation_place",
            json={"value": "第一讯问室", "status": "confirmed"},
        ))
        assert place["value"] == "第一讯问室"
        facts = payload(client.get(f"/api/v1/cases/{case_id}/facts"))
        assert next(item for item in facts if item["key"] == "interrogation_place")["value"] == "第一讯问室"


def test_session_start_does_not_require_suspect_voiceprint(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'voiceprint-optional.db'}",
        hardware_gateway=MockHardwareGateway(simulated=False),
    )
    with TestClient(app) as client:
        created = payload(client.post("/api/v1/cases", json={"operator_id": "op", "suspectName": "钱某"}))
        case_id = created["id"]
        payload(client.post("/api/v1/identity/confirm", json={
            "case_id": case_id,
            "actor_id": "op",
            "name": "钱某",
            "id_number": "320101199001010022",
            "source": "MANUAL",
        }))

        start = client.post(f"/api/v1/cases/{case_id}/session/start", json={"actor_id": "op"})
        assert start.status_code == 200
        assert payload(start)["status"] == "RUNNING"


def test_canonical_api_errors_are_structured(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'errors.db'}", hardware_gateway=MockHardwareGateway(simulated=False))
    with TestClient(app) as client:
        missing = client.get("/api/v1/cases/does-not-exist")
        assert missing.status_code == 404
        assert missing.json() == {"ok": False, "code": "CASE_NOT_FOUND", "message": "案件不存在", "data": None}

        created = payload(client.post("/api/v1/cases", json={"operator_id": "op"}))
        case_id = created["id"]
        start = client.post(f"/api/v1/cases/{case_id}/session/start", json={})
        assert start.status_code == 409
        assert start.json()["code"] == "IDENTITY_REQUIRED"

        identity = client.post("/api/v1/identity/read", json={"case_id": case_id})
        assert identity.status_code == 409
        assert identity.json()["code"] == "DEVICE_NOT_CONNECTED"

        validation = client.post(f"/api/v1/cases/{case_id}/session/stage", json={})
        assert validation.status_code == 422
        assert validation.json()["ok"] is False
        assert validation.json()["code"] == "VALIDATION_ERROR"


def test_case_list_searches_exact_name_and_identity_prefix(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'case-search.db'}",
        hardware_gateway=MockHardwareGateway(simulated=False),
    )
    with TestClient(app) as client:
        first = payload(client.post("/api/v1/cases", json={"operator_id": "op", "suspectName": "发噶发"}))
        second = payload(client.post("/api/v1/cases", json={"operator_id": "op", "suspectName": "发噶爱"}))
        payload(client.post("/api/v1/identity/confirm", json={
            "case_id": first["id"], "name": "发噶发", "id_number": "320101199001010011", "source": "MANUAL",
        }))
        payload(client.post("/api/v1/identity/confirm", json={
            "case_id": second["id"], "name": "发噶爱", "id_number": "320101199001010022", "source": "MANUAL",
        }))

        assert [row["id"] for row in payload(client.get("/api/v1/cases", params={"query": "发噶发"}))] == [first["id"]]
        assert [row["id"] for row in payload(client.get("/api/v1/cases", params={"query": "3201011"}))] == [second["id"], first["id"]]
        assert payload(client.get("/api/v1/cases", params={"query": "发"})) == []
