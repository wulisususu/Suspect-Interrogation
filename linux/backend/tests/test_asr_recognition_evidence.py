from __future__ import annotations

from app.api.asr import FragmentUpdateRequest, update_fragment as update_fragment_api
from app.database.models import AuditLog
from app.database.recognition_models import ASRRecognitionEvidence, ASRRecognitionRevision
from app.database.session import init_database, make_engine, make_session_factory
from app.repositories import asr_fragments as asr_repo
from app.repositories import cases as case_repo
from app.repositories import sessions as session_repo
from app.repositories import speaker_calibrations as calibration_repo


def _seed(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'recognition-evidence.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        case = case_repo.create(db, {"id": "CASE-EVIDENCE", "suspectName": "张某", "officerName": "李警官"})
        session = session_repo.create(db, case.id)
        capture = asr_repo.create_capture_session(db, case_id=case.id, interrogation_session_id=session.id, sample_rate=16_000)
        calibration_repo.create_session_snapshot(
            db,
            capture_session_id=capture.id,
            interrogation_session_id=session.id,
            calibration_id=None,
            threshold=0.78,
            margin=0.06,
            threshold_source="DEVICE_CALIBRATED",
            calibration_status="VALID",
            speaker_model_fingerprint="a" * 64,
            microphone_fingerprint="b" * 64,
        )
        fragment = asr_repo.create_fragment(
            db,
            capture_session_id=capture.id,
            case_id=case.id,
            ordinal=0,
            started_at_ms=0,
            ended_at_ms=1600,
            raw_text="原始识别文本",
            asr_confidence=0.93,
            speaker="SUSPECT",
            speaker_id="suspect-vp-1",
            speaker_name="张某",
            speaker_score=0.91,
            second_best_score=0.61,
            speaker_threshold=0.78,
            speaker_margin=0.06,
            speaker_source="X_VECTOR",
            voiceprint_verified=True,
            low_confidence=False,
            model_id="paraformer",
            model_version="asr-v3",
            speaker_threshold_source="DEVICE_CALIBRATED",
            speaker_model_id="xvector",
            speaker_model_version="sv-v2",
            speaker_model_fingerprint="a" * 64,
            microphone_fingerprint="b" * 64,
        )
        db.commit()
        return engine, factory, case.id, fragment.id


def test_every_fragment_records_independent_immutable_ai_evidence(tmp_path):
    engine, factory, _, fragment_id = _seed(tmp_path)
    with factory() as db:
        evidence = db.query(ASRRecognitionEvidence).filter_by(fragment_id=fragment_id).one()
        assert evidence.ai_speaker == "SUSPECT"
        assert evidence.speaker_id == "suspect-vp-1"
        assert evidence.speaker_name == "张某"
        assert evidence.speaker_source == "X_VECTOR"
        assert evidence.score == 0.91
        assert evidence.second_best_score == 0.61
        assert evidence.threshold == 0.78
        assert evidence.margin == 0.06
        assert evidence.threshold_source == "DEVICE_CALIBRATED"
        assert evidence.asr_model_id == "paraformer"
        assert evidence.asr_model_version == "asr-v3"
        assert evidence.speaker_model_id == "xvector"
        assert evidence.speaker_model_version == "sv-v2"
        assert evidence.speaker_model_fingerprint == "a" * 64
        assert evidence.microphone_fingerprint == "b" * 64
        assert evidence.voiceprint_verified is True
        assert evidence.low_confidence is False
    engine.dispose()


def test_manual_correction_keeps_ai_evidence_and_appends_revision(tmp_path):
    engine, factory, case_id, fragment_id = _seed(tmp_path)
    with factory() as db:
        payload = update_fragment_api(
            case_id,
            fragment_id,
            FragmentUpdateRequest(
                edited_text="人工修订文本",
                speaker="INTERROGATOR",
                actor_id="officer-001",
                reason="现场人工确认说话人为主审民警",
            ),
            request=None,
            db=db,
        )
        assert payload["rawText"] == "原始识别文本"
        assert payload["editedText"] == "人工修订文本"
        assert payload["speaker"] == "INTERROGATOR"
        assert payload["speakerSource"] == "MANUAL"
        assert payload["recognitionEvidence"]["aiSpeaker"] == "SUSPECT"
        assert payload["recognitionEvidence"]["score"] == 0.91
        assert len(payload["recognitionRevisions"]) == 1
        assert payload["recognitionRevisions"][0]["afterSpeaker"] == "INTERROGATOR"
        assert payload["recognitionRevisions"][0]["actorId"] == "officer-001"
        assert payload["recognitionRevisions"][0]["reason"] == "现场人工确认说话人为主审民警"

    with factory() as db:
        evidence = db.query(ASRRecognitionEvidence).filter_by(fragment_id=fragment_id).one()
        revision = db.query(ASRRecognitionRevision).filter_by(fragment_id=fragment_id).one()
        assert evidence.ai_speaker == "SUSPECT"
        assert evidence.score == 0.91
        assert revision.before_speaker == "SUSPECT"
        assert revision.after_speaker == "INTERROGATOR"
        assert revision.before_text == "原始识别文本"
        assert revision.after_text == "人工修订文本"
        assert revision.actor_id == "officer-001"
        assert revision.reason == "现场人工确认说话人为主审民警"
        assert db.query(AuditLog).filter_by(target_id=fragment_id, action="ASR_FRAGMENT_UPDATE").count() == 1
    engine.dispose()


def test_text_only_correction_preserves_speaker_and_still_appends_revision(tmp_path):
    engine, factory, case_id, fragment_id = _seed(tmp_path)
    with factory() as db:
        payload = update_fragment_api(
            case_id,
            fragment_id,
            FragmentUpdateRequest(
                edited_text="只修订文字",
                speaker="SUSPECT",
                actor_id="officer-002",
                reason="修正同音字",
            ),
            request=None,
            db=db,
        )
        assert payload["speaker"] == "SUSPECT"
        assert payload["speakerId"] == "suspect-vp-1"
        assert payload["speakerSource"] == "X_VECTOR"
        assert payload["recognitionEvidence"]["aiSpeaker"] == "SUSPECT"
        assert payload["recognitionRevisions"][0]["afterText"] == "只修订文字"

    with factory() as db:
        revision = db.query(ASRRecognitionRevision).filter_by(fragment_id=fragment_id).one()
        assert revision.before_speaker == "SUSPECT"
        assert revision.after_speaker == "SUSPECT"
        assert revision.before_text == "原始识别文本"
        assert revision.after_text == "只修订文字"
        assert revision.reason == "修正同音字"
    engine.dispose()
