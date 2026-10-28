from fastapi.testclient import TestClient

from app.database.models import InterrogationSession
from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app
from app.repositories import asr_fragments as asr_repo


def payload(response):
    body = response.json()
    assert response.status_code == 200, body
    assert body["ok"] is True, body
    return body["data"]


def create_case(client: TestClient) -> str:
    return payload(
        client.post(
            "/api/v1/cases",
            json={"operator_id": "op-template", "suspectName": "测试对象", "officerName": "测试警官"},
        )
    )["id"]


def test_template_workspace_question_crud_library_and_validation(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'template-api.db'}",
        hardware_gateway=MockHardwareGateway(simulated=True),
    )
    with TestClient(app) as client:
        case_id = create_case(client)

        workspace = payload(client.get(f"/api/v1/cases/{case_id}/template-workspace"))
        assert set(workspace) >= {"caseId", "questions", "rounds", "pendingQuestions", "qaUnits"}
        assert workspace["questions"] == []
        assert workspace["rounds"] == []
        assert workspace["pendingQuestions"] == []
        assert workspace["qaUnits"] == []

        first = payload(
            client.post(
                f"/api/v1/cases/{case_id}/questions",
                json={
                    "text": "你什么时候到现场？",
                    "source": "CASE",
                    "regexPatterns": ["什么时候.*现场"],
                },
            )
        )
        second = payload(
            client.post(
                f"/api/v1/cases/{case_id}/questions",
                json={"text": "你为什么去现场？", "source": "CASE", "regexPatterns": ["为什么.*现场"]},
            )
        )

        updated = payload(
            client.patch(
                f"/api/v1/cases/{case_id}/questions/{first['id']}",
                json={"text": "你何时到达现场？", "regexPatterns": ["何时.*现场", "几点.*现场"]},
            )
        )
        assert updated["text"] == "你何时到达现场？"
        assert "你什么时候到现场？" in updated["aliases"]

        reordered = payload(
            client.post(
                f"/api/v1/cases/{case_id}/questions/reorder",
                json={"questionIds": [second["id"], first["id"]]},
            )
        )
        assert [item["id"] for item in reordered] == [second["id"], first["id"]]

        saved = payload(
            client.post(
                f"/api/v1/cases/{case_id}/questions/{first['id']}/save-to-library",
                json={"category": "现场情况"},
            )
        )
        assert saved["category"] == "现场情况"
        library = payload(client.get("/api/v1/question-library?category=现场情况"))
        assert [item["id"] for item in library] == [saved["id"]]

        missing = client.patch(
            f"/api/v1/cases/{case_id}/questions/not-found",
            json={"text": "不存在"},
        )
        assert missing.status_code == 404

        invalid_reorder = client.post(
            f"/api/v1/cases/{case_id}/questions/reorder",
            json={"questionIds": [first["id"]]},
        )
        assert invalid_reorder.status_code == 400


def test_fragment_processing_pending_actions_round_edit_and_reassociation(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'template-actions.db'}",
        hardware_gateway=MockHardwareGateway(simulated=True),
    )
    with TestClient(app) as client:
        # This endpoint intentionally remains even after Qwen routing is added:
        # operators/releases can use it as the explicit legacy/manual fallback.
        assert "/api/v1/cases/{case_id}/speech-fragments/{fragment_id}/process" in app.openapi()["paths"]
        case_id = create_case(client)
        first = payload(
            client.post(
                f"/api/v1/cases/{case_id}/questions",
                json={"text": "你什么时候到现场？", "source": "CASE", "regexPatterns": ["什么时候.*现场"]},
            )
        )
        second = payload(
            client.post(
                f"/api/v1/cases/{case_id}/questions",
                json={"text": "你为什么去现场？", "source": "CASE", "regexPatterns": ["为什么.*现场"]},
            )
        )

        with app.state.session_factory() as db:
            session = InterrogationSession(
                id="SESSION-TEMPLATE-API",
                case_id=case_id,
                status="RUNNING",
                stage="QUESTIONING",
            )
            db.add(session)
            db.flush()
            capture = asr_repo.create_capture_session(
                db,
                case_id=case_id,
                interrogation_session_id=session.id,
                sample_rate=16000,
            )
            db.commit()
            capture_id = capture.id

        ordinal = 0

        def fragment(speaker: str, text: str) -> str:
            nonlocal ordinal
            ordinal += 1
            with app.state.session_factory() as db:
                row = asr_repo.create_fragment(
                    db,
                    capture_session_id=capture_id,
                    case_id=case_id,
                    ordinal=ordinal,
                    started_at_ms=ordinal * 1000,
                    ended_at_ms=ordinal * 1000 + 600,
                    raw_text=text,
                    speaker=speaker,
                    speaker_source="MANUAL",
                    voiceprint_verified=True,
                    low_confidence=False,
                    model_id="test-asr",
                )
                db.commit()
                return row.id

        officer = fragment("INTERROGATOR", "你什么时候到现场的？")
        matched = payload(client.post(f"/api/v1/cases/{case_id}/speech-fragments/{officer}/process"))
        assert matched["status"] == "MATCHED"
        first_round_id = matched["round"]["id"]

        suspect = fragment("SUSPECT", "晚上八点。")
        appended = payload(client.post(f"/api/v1/cases/{case_id}/speech-fragments/{suspect}/process"))
        assert appended["round"]["answerText"] == "晚上八点。"

        repeated = fragment("INTERROGATOR", "那你什么时候到现场的？")
        pending_repeat = payload(client.post(f"/api/v1/cases/{case_id}/speech-fragments/{repeated}/process"))
        assert pending_repeat["status"] == "MATCHED_EXISTING"
        repeat_pending_id = pending_repeat["pendingQuestion"]["id"]
        repeat_answer = fragment("SUSPECT", "准确说是八点半。")
        payload(client.post(f"/api/v1/cases/{case_id}/speech-fragments/{repeat_answer}/process"))

        linked = payload(
            client.post(
                f"/api/v1/cases/{case_id}/pending-questions/{repeat_pending_id}/link",
                json={"caseQuestionId": first["id"], "roundMode": "NEW_ROUND"},
            )
        )
        assert linked["roundNo"] == 2
        assert linked["answerText"] == "准确说是八点半。"

        edited = payload(
            client.patch(
                f"/api/v1/cases/{case_id}/rounds/{linked['id']}",
                json={"answerText": "准确时间为晚上八点半。"},
            )
        )
        assert edited["answerText"] == "准确时间为晚上八点半。"

        reassociated = payload(
            client.post(
                f"/api/v1/cases/{case_id}/rounds/{linked['id']}/reassociate",
                json={"caseQuestionId": second["id"]},
            )
        )
        assert reassociated["caseQuestionId"] == second["id"]

        unmatched_officer = fragment("INTERROGATOR", "你为什么把钥匙带走了？")
        unmatched = payload(client.post(f"/api/v1/cases/{case_id}/speech-fragments/{unmatched_officer}/process"))
        assert unmatched["status"] == "UNMATCHED"
        unmatched_id = unmatched["pendingQuestion"]["id"]
        unmatched_answer = fragment("SUSPECT", "我以为是我的。")
        payload(client.post(f"/api/v1/cases/{case_id}/speech-fragments/{unmatched_answer}/process"))

        workspace = payload(client.get(f"/api/v1/cases/{case_id}/template-workspace"))
        assert [item["id"] for item in workspace["pendingQuestions"]] == [unmatched_id]
        assert "qaUnits" in workspace

        added = payload(
            client.post(
                f"/api/v1/cases/{case_id}/pending-questions/{unmatched_id}/add",
                json={"afterQuestionId": second["id"]},
            )
        )
        assert added["answerText"] == "我以为是我的。"

        ignored_officer = fragment("INTERROGATOR", "你还有没有别的钥匙？")
        ignored_pending = payload(client.post(f"/api/v1/cases/{case_id}/speech-fragments/{ignored_officer}/process"))
        ignored_id = ignored_pending["pendingQuestion"]["id"]
        ignored = payload(client.post(f"/api/v1/cases/{case_id}/pending-questions/{ignored_id}/ignore"))
        assert ignored["status"] == "IGNORED"

        final_workspace = payload(client.get(f"/api/v1/cases/{case_id}/template-workspace"))
        assert all(item["id"] != ignored_id for item in final_workspace["pendingQuestions"])
        assert any(row["id"] == first_round_id for row in final_workspace["rounds"])


def test_dragged_fragment_can_be_saved_as_formal_answer_with_provenance(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'template-fragment-answer.db'}",
        hardware_gateway=MockHardwareGateway(simulated=True),
    )
    with TestClient(app) as client:
        case_id = create_case(client)
        question = payload(
            client.post(
                f"/api/v1/cases/{case_id}/questions",
                json={"text": "你什么时候到现场？", "source": "CASE"},
            )
        )

        with app.state.session_factory() as db:
            session = InterrogationSession(
                id="SESSION-FRAGMENT-ANSWER",
                case_id=case_id,
                status="RUNNING",
                stage="QUESTIONING",
            )
            db.add(session)
            db.flush()
            capture = asr_repo.create_capture_session(
                db,
                case_id=case_id,
                interrogation_session_id=session.id,
                sample_rate=16000,
            )
            fragment = asr_repo.create_fragment(
                db,
                capture_session_id=capture.id,
                case_id=case_id,
                ordinal=1,
                started_at_ms=1000,
                ended_at_ms=1600,
                raw_text="晚上八点。",
                speaker="SUSPECT",
                speaker_source="MANUAL",
                voiceprint_verified=True,
                low_confidence=False,
                model_id="test-asr",
            )
            db.commit()
            fragment_id = fragment.id

        attached = payload(
            client.post(
                f"/api/v1/cases/{case_id}/questions/{question['id']}/answer-fragments",
                json={"fragmentIds": [fragment_id]},
            )
        )
        assert attached["answerText"] == "晚上八点。"
        assert attached["answerFragmentIds"] == [fragment_id]

        appended = payload(
            client.post(
                f"/api/v1/cases/{case_id}/questions/{question['id']}/answer-fragments",
                json={"fragmentIds": [fragment_id]},
            )
        )
        assert appended["answerText"] == "晚上八点。"
        assert appended["answerFragmentIds"] == [fragment_id]

        workspace = payload(client.get(f"/api/v1/cases/{case_id}/template-workspace"))
        saved_question = next(item for item in workspace["questions"] if item["id"] == question["id"])
        assert saved_question["formalAnswerText"] == "晚上八点。"
        assert saved_question["rounds"][0]["answerFragmentIds"] == [fragment_id]


def test_recorded_card_answer_stays_draft_until_written_into_the_record(tmp_path):
    """问答录入 · 逐题录音：录完先成待摘入草稿，重录替换草稿，摘入正本才写正式回答。"""
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'template-draft-answer.db'}",
        hardware_gateway=MockHardwareGateway(simulated=True),
    )
    with TestClient(app) as client:
        case_id = create_case(client)
        question = payload(
            client.post(
                f"/api/v1/cases/{case_id}/questions",
                json={"text": "车辆当时锁了吗？", "source": "CASE"},
            )
        )

        with app.state.session_factory() as db:
            session = InterrogationSession(id="SESSION-DRAFT-ANSWER", case_id=case_id, status="RUNNING", stage="QUESTIONING")
            db.add(session)
            db.flush()
            capture = asr_repo.create_capture_session(db, case_id=case_id, interrogation_session_id=session.id, sample_rate=16000)
            ids = []
            for ordinal, text in enumerate(["锁了，", "锁在单元门口。", "锁在柱子上。"], start=1):
                fragment = asr_repo.create_fragment(
                    db,
                    capture_session_id=capture.id,
                    case_id=case_id,
                    ordinal=ordinal,
                    started_at_ms=ordinal * 1000,
                    ended_at_ms=ordinal * 1000 + 600,
                    raw_text=text,
                    speaker="UNKNOWN",
                    speaker_source="MANUAL",
                    voiceprint_verified=False,
                    low_confidence=False,
                    model_id="test-asr",
                )
                ids.append(fragment.id)
            db.commit()

        url = f"/api/v1/cases/{case_id}/questions/{question['id']}/answer-fragments"
        drafted = payload(client.post(url, json={"fragmentIds": ids[:2], "draft": True}))
        assert drafted["answerText"] == "锁了，锁在单元门口。"

        def saved():
            workspace = payload(client.get(f"/api/v1/cases/{case_id}/template-workspace"))
            return next(item for item in workspace["questions"] if item["id"] == question["id"])

        assert saved()["formalAnswerText"] == ""

        rerecorded = payload(client.post(url, json={"fragmentIds": ids[2:], "draft": True, "replace": True}))
        assert rerecorded["answerText"] == "锁在柱子上。"
        assert rerecorded["answerFragmentIds"] == ids[2:]
        assert saved()["formalAnswerText"] == ""
        with app.state.session_factory() as db:
            states = {fragment_id: asr_repo.get_fragment(db, fragment_id).state for fragment_id in ids}
        assert states[ids[0]] == "DISCARDED"
        assert states[ids[1]] == "DISCARDED"
        assert states[ids[2]] != "DISCARDED"

        payload(client.put(f"/api/v1/cases/{case_id}/questions/{question['id']}/answer", json={"answerText": "锁了，锁在单元门口的柱子上。"}))
        assert saved()["formalAnswerText"] == "锁了，锁在单元门口的柱子上。"


def test_officer_fragment_can_create_live_question_from_dynamic_drop(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'template-live-question-drop.db'}",
        hardware_gateway=MockHardwareGateway(simulated=True),
    )
    with TestClient(app) as client:
        case_id = create_case(client)
        anchor = payload(
            client.post(
                f"/api/v1/cases/{case_id}/questions",
                json={"text": "已存在的问题", "source": "CASE"},
            )
        )

        with app.state.session_factory() as db:
            session = InterrogationSession(
                id="SESSION-LIVE-QUESTION-DROP",
                case_id=case_id,
                status="RUNNING",
                stage="QUESTIONING",
            )
            db.add(session)
            db.flush()
            capture = asr_repo.create_capture_session(
                db,
                case_id=case_id,
                interrogation_session_id=session.id,
                sample_rate=16000,
            )
            officer = asr_repo.create_fragment(
                db,
                capture_session_id=capture.id,
                case_id=case_id,
                ordinal=1,
                started_at_ms=1000,
                ended_at_ms=1600,
                raw_text="你当时把笔记本放在哪里？",
                speaker="INTERROGATOR",
                speaker_source="MANUAL",
                voiceprint_verified=True,
                low_confidence=False,
                model_id="test-asr",
            )
            suspect = asr_repo.create_fragment(
                db,
                capture_session_id=capture.id,
                case_id=case_id,
                ordinal=2,
                started_at_ms=2000,
                ended_at_ms=2600,
                raw_text="我放在桌子上。",
                speaker="SUSPECT",
                speaker_source="MANUAL",
                voiceprint_verified=True,
                low_confidence=False,
                model_id="test-asr",
            )
            db.commit()
            officer_id = officer.id
            suspect_id = suspect.id

        created = payload(
            client.post(
                f"/api/v1/cases/{case_id}/questions/from-fragment",
                json={"fragmentId": officer_id, "afterQuestionId": anchor["id"]},
            )
        )
        assert created["question"]["text"] == "你当时把笔记本放在哪里？"
        assert created["question"]["source"] == "LIVE"
        assert created["round"]["caseQuestionId"] == created["question"]["id"]
        assert created["round"]["officerFragmentId"] == officer_id
        assert created["round"]["status"] == "ACTIVE"

        workspace = payload(client.get(f"/api/v1/cases/{case_id}/template-workspace"))
        assert [item["text"] for item in workspace["questions"]] == [
            "已存在的问题",
            "你当时把笔记本放在哪里？",
        ]

        rejected = client.post(
            f"/api/v1/cases/{case_id}/questions/from-fragment",
            json={"fragmentId": suspect_id, "afterQuestionId": anchor["id"]},
        )
        assert rejected.status_code == 400
        assert "民警" in rejected.json()["message"]
