from __future__ import annotations

import base64
import json
import struct

from fastapi.testclient import TestClient

from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app
from app.repositories import asr_fragments as asr_repo
from app.repositories import documents as document_repo
from app.repositories import voiceprints as voiceprint_repo
from app.runtime_settings import RuntimeSettings


_TEST_VOICEPRINT = struct.pack("<4f", 1.0, 0.0, 0.0, 0.0)
_TEST_SIGNATURE = "data:image/png;base64," + base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63606060f80f00010401005fe5c34b0000000049454e44ae426082"
)).decode()


def _payload(response):
    body = response.json()
    assert response.status_code == 200, body
    assert body.get("ok") is True, body
    return body["data"]


def test_template_interrogation_release_lifecycle_preserves_raw_and_formal_records(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'template-release-e2e.db'}",
        hardware_gateway=MockHardwareGateway(simulated=True),
        runtime_settings=RuntimeSettings(data_dir=tmp_path / "data", min_free_mb=1),
    )

    try:
        with TestClient(app) as client:
            case = _payload(
                client.post(
                    "/api/v1/cases",
                    json={
                        "operator_id": "officer-e2e",
                        "suspectName": "测试对象",
                        "officerName": "测试警官",
                    },
                )
            )
            case_id = case["id"]

            _payload(
                client.post(
                    "/api/v1/identity/read",
                    json={"case_id": case_id, "actor_id": "officer-e2e"},
                )
            )

            with app.state.session_factory() as db:
                voiceprint_repo.enroll_suspect(
                    db,
                    case_id=case_id,
                    embedding=_TEST_VOICEPRINT,
                    embedding_dim=4,
                    model_id="release-e2e-xvector",
                    model_version="fixture",
                    enrollment_quality="E2E_FIXTURE",
                    usable_duration_ms=20_000,
                )
                db.commit()

            formal_question = _payload(
                client.post(
                    f"/api/v1/cases/{case_id}/questions",
                    json={
                        "text": "你什么时候到现场？",
                        "source": "CASE",
                        "regexPatterns": ["什么时候.*现场"],
                    },
                )
            )

            session = _payload(
                client.post(
                    f"/api/v1/cases/{case_id}/session/start",
                    json={"actor_id": "officer-e2e"},
                )
            )
            assert session["status"] == "RUNNING"

            with app.state.session_factory() as db:
                capture = asr_repo.create_capture_session(
                    db,
                    case_id=case_id,
                    interrogation_session_id=session["id"],
                    sample_rate=16_000,
                )
                db.commit()
                capture_id = capture.id

            ordinal = 0
            fragment_ids: list[str] = []
            officer_fragment_ids: list[str] = []

            def fragment(speaker: str, text: str) -> str:
                nonlocal ordinal
                ordinal += 1
                with app.state.session_factory() as db:
                    row = asr_repo.create_fragment(
                        db,
                        capture_session_id=capture_id,
                        case_id=case_id,
                        ordinal=ordinal,
                        started_at_ms=ordinal * 1_000,
                        ended_at_ms=ordinal * 1_000 + 600,
                        raw_text=text,
                        speaker=speaker,
                        speaker_source="MANUAL",
                        voiceprint_verified=True,
                        low_confidence=False,
                        model_id="release-e2e-asr",
                        model_version="fixture",
                    )
                    db.commit()
                    fragment_ids.append(row.id)
                    if speaker == "INTERROGATOR":
                        officer_fragment_ids.append(row.id)
                    return row.id

            def process(fragment_id: str):
                return _payload(
                    client.post(
                        f"/api/v1/cases/{case_id}/speech-fragments/{fragment_id}/process"
                    )
                )

            first_officer = fragment("INTERROGATOR", "你什么时候到现场的？")
            first_match = process(first_officer)
            assert first_match["status"] == "MATCHED"
            first_round_id = first_match["round"]["id"]

            first_answer = process(fragment("SUSPECT", "晚上八点左右。"))
            second_answer = process(fragment("SUSPECT", "我从北门进去的。"))
            assert first_answer["status"] == "ROUND_APPEND"
            assert second_answer["status"] == "ROUND_APPEND"
            assert second_answer["round"]["id"] == first_round_id
            assert second_answer["round"]["answerText"] == "晚上八点左右。 我从北门进去的。"

            continue_turn = process(fragment("INTERROGATOR", "继续说。"))
            assert continue_turn == {"status": "RAW_ONLY"}
            workspace_after_continue = _payload(
                client.get(f"/api/v1/cases/{case_id}/template-workspace")
            )
            first_round_after_continue = next(
                row for row in workspace_after_continue["rounds"] if row["id"] == first_round_id
            )
            assert first_round_after_continue["status"] == "ACTIVE"
            assert first_round_after_continue["answerText"] == "晚上八点左右。 我从北门进去的。"

            unmatched_officer = fragment("INTERROGATOR", "你把钥匙放到哪里去了？")
            unmatched = process(unmatched_officer)
            assert unmatched["status"] == "UNMATCHED"
            unmatched_pending_id = unmatched["pendingQuestion"]["id"]

            buffered = process(fragment("SUSPECT", "我放在门口鞋柜里了。"))
            assert buffered["status"] == "PENDING_BUFFER"
            assert buffered["pendingQuestion"]["id"] == unmatched_pending_id
            assert buffered["pendingQuestion"]["bufferedAnswerText"] == "我放在门口鞋柜里了。"

            added_round = _payload(
                client.post(
                    f"/api/v1/cases/{case_id}/pending-questions/{unmatched_pending_id}/add",
                    json={"afterQuestionId": formal_question["id"]},
                )
            )
            assert added_round["answerText"] == "我放在门口鞋柜里了。"
            live_round_id = added_round["id"]

            repeat_officer = fragment("INTERROGATOR", "那你什么时候到现场的？")
            repeated = process(repeat_officer)
            assert repeated["status"] == "MATCHED_EXISTING"
            repeat_pending_id = repeated["pendingQuestion"]["id"]

            repeat_buffer = process(fragment("SUSPECT", "准确说是八点十分。"))
            assert repeat_buffer["status"] == "PENDING_BUFFER"
            repeat_round = _payload(
                client.post(
                    f"/api/v1/cases/{case_id}/pending-questions/{repeat_pending_id}/link",
                    json={
                        "caseQuestionId": formal_question["id"],
                        "roundMode": "NEW_ROUND",
                    },
                )
            )
            assert repeat_round["roundNo"] == 2
            assert repeat_round["answerText"] == "准确说是八点十分。"
            repeat_round_id = repeat_round["id"]

            workspace_with_repeat = _payload(
                client.get(f"/api/v1/cases/{case_id}/template-workspace")
            )
            same_question_rounds = [
                row
                for row in workspace_with_repeat["rounds"]
                if row["caseQuestionId"] == formal_question["id"]
            ]
            assert [row["roundNo"] for row in same_question_rounds] == [1, 2]

            reassociated = _payload(
                client.post(
                    f"/api/v1/cases/{case_id}/rounds/{repeat_round_id}/reassociate",
                    json={"newQuestionText": "你第二次什么时候回到现场？"},
                )
            )
            assert reassociated["id"] == repeat_round_id
            assert reassociated["caseQuestionId"] != formal_question["id"]
            assert reassociated["actualQuestionText"] == "那你什么时候到现场的？"

            # This fixture injects final ASR fragments directly. Complete its real
            # archive and transcription checkpoint before asking the API to freeze.
            archive = app.state.live_speech_coordinator.archive
            archive.open_capture(capture_id, case_id=case_id)
            for _ in range(ordinal + 1):
                archive.append(capture_id, b"\x01\x00" * 16_000)
            archive.finalize_capture(capture_id)
            with app.state.session_factory() as db:
                capture = asr_repo.get_capture_session(db, capture_id)
                capture.asr_status = "COMPLETE"
                capture.asr_cursor_sample = capture.audio_sample_count
                capture.speaker_status = "DISABLED"
                db.commit()

            with app.state.session_factory() as db:
                capture = asr_repo.get_capture_session(db, capture_id)
                assert capture.status == "STOPPED"
                assert capture.recording_status == "COMPLETE"
                assert capture.asr_status == "COMPLETE"

            reviewed = client.post(
                f"/api/v1/cases/{case_id}/asr/fragments/confirm",
                json={"fragment_ids": officer_fragment_ids},
            )
            assert reviewed.status_code == 200, reviewed.text
            assert reviewed.json()["confirmedCount"] == len(officer_fragment_ids)

            finished = _payload(
                client.post(
                    f"/api/v1/cases/{case_id}/session/finish",
                    json={"actor_id": "officer-e2e"},
                )
            )
            assert finished["status"] == "COMPLETED"

            frozen = _payload(
                client.post(
                    f"/api/v1/cases/{case_id}/document/freeze",
                    json={"actor_id": "officer-e2e"},
                )
            )
            assert frozen["status"] == "FROZEN"
            assert frozen["integrityValid"] is True

            suspect_signed = _payload(
                client.post(
                    f"/api/v1/cases/{case_id}/document/sign",
                    json={
                        "signerRole": "SUSPECT",
                        "signerName": "测试对象",
                        "imageDataUrl": _TEST_SIGNATURE,
                        "strokesJson": "[]",
                        "actorId": "officer-e2e",
                    },
                )
            )
            assert suspect_signed["status"] == "FROZEN"
            assert [row["signerRole"] for row in suspect_signed["signatures"]] == ["SUSPECT"]

            locked = _payload(
                client.post(
                    f"/api/v1/cases/{case_id}/document/sign",
                    json={
                        "signerRole": "OFFICER",
                        "signerName": "测试警官",
                        "imageDataUrl": _TEST_SIGNATURE,
                        "strokesJson": "[]",
                        "actorId": "officer-e2e",
                    },
                )
            )
            assert locked["status"] == "LOCKED"
            assert {row["signerRole"] for row in locked["signatures"]} == {"SUSPECT", "OFFICER"}

            raw_response = client.get(
                f"/api/v1/cases/{case_id}/asr/fragments?include_confirmed=true"
            )
            assert raw_response.status_code == 200, raw_response.text
            raw_fragments = raw_response.json()
            assert [row["fragmentId"] for row in raw_fragments] == fragment_ids
            assert [row["rawText"] for row in raw_fragments] == [
                "你什么时候到现场的？",
                "晚上八点左右。",
                "我从北门进去的。",
                "继续说。",
                "你把钥匙放到哪里去了？",
                "我放在门口鞋柜里了。",
                "那你什么时候到现场的？",
                "准确说是八点十分。",
            ]

            with app.state.session_factory() as db:
                snapshot = document_repo.latest_snapshot(db, case_id)
                assert snapshot is not None
                snapshot_payload = json.loads(snapshot.content_json)

            transcript = snapshot_payload["transcript"]
            assert transcript["source"] == "TEMPLATE_ROUNDS"
            entries = transcript["entries"]
            assert [row["roundId"] for row in entries] == [
                first_round_id,
                live_round_id,
                repeat_round_id,
            ]
            assert [row["startedAt"] for row in entries] == sorted(
                row["startedAt"] for row in entries
            )
            assert all(row["status"] != "DETACHED" for row in entries)
            assert entries[0]["answerText"] == "晚上八点左右。 我从北门进去的。"
            assert entries[1]["answerText"] == "我放在门口鞋柜里了。"
            assert entries[2]["actualQuestionText"] == "那你什么时候到现场的？"
    finally:
        app.state.engine.dispose()
