from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import pytest
from app.database.models import (
    ASRCaptureSession,
    ASRFragment,
    ASRFragmentLineage,
    LiveSpeechJob,
)
from app.database.recognition_models import ASRRecognitionEvidence, ASRSpeakerAnalysisResult
from app.database.session import init_database, make_engine, make_session_factory
from app.repositories import asr_fragments as asr_repo
from app.repositories import cases as case_repo
from app.repositories import speaker_calibrations as calibration_repo
from app.repositories.sessions import create as create_session
from app.repositories.voiceprints import enroll_suspect
from app.services.asr_capture_service import AsrCaptureService
from app.services.durable_audio_archive import DurableAudioArchive
from app.services.live_speech_coordinator import LiveSpeechCoordinator
from speech_worker.speaker_turn_splitter import TurnSpan


@pytest.fixture(autouse=True)
def enable_legacy_voiceprint_compatibility(monkeypatch):
    """These tests exercise retained historical speaker analysis explicitly."""
    monkeypatch.setenv("SUSPECT_LEGACY_VOICEPRINT_ENABLED", "true")


@dataclass
class _Transcript:
    text: str
    confidence: float = 0.9
    model_id: str = "paraformer"
    session_id: str = "speaker-child"


class _Speech:
    speaker_accept_threshold = 0.7
    speaker_margin = 0.1

    def __init__(self, *, fail_transcription: int | None = None):
        self.transcriptions: list[bytes] = []
        self.fail_transcription = fail_transcription

    def extract_speaker_embedding(self, pcm: bytes, *, sample_rate: int = 16_000):
        assert sample_rate == 16_000
        assert pcm
        return {
            "embedding": [1.0, 0.0],
            "model_id": "eres2net_large",
            "model_version": "speaker-v4",
            "model_fingerprint": "c" * 64,
        }

    def transcribe(self, pcm: bytes, *, session_id: str, options=None):
        del session_id, options
        self.transcriptions.append(bytes(pcm))
        if self.fail_transcription == len(self.transcriptions):
            raise RuntimeError("child transcription failed")
        return _Transcript(text=f"child-{pcm[0]}")


class _Device:
    def start_record(self):
        pass

    def stop_record(self):
        pass


class _Events:
    def __init__(self):
        self.events: list[tuple[str, str, dict]] = []

    def __call__(self, session_id: str, name: str, payload: dict):
        self.events.append((session_id, name, payload))


class _TwoTurnSplitter:
    def split(self, pcm, sample_rate, embed, reference=None):
        del reference
        assert len(pcm) == 2 * sample_rate * 2
        embed(pcm[: sample_rate * 2])
        embed(pcm[sample_rate * 2 :])
        return [TurnSpan(0, 1000), TurnSpan(1000, 2000)]


class _AmbiguousSplitter:
    def split(self, pcm, sample_rate, embed, reference=None):
        del pcm, sample_rate, embed, reference
        return [TurnSpan(0, 2000, ambiguous=True)]


def _build(tmp_path: Path, *, fail_transcription: int | None = None):
    engine = make_engine(f"sqlite:///{tmp_path / 'speaker.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    speech = _Speech(fail_transcription=fail_transcription)
    events = _Events()
    with factory() as db:
        case = case_repo.create(db, {"id": "CASE-SPEAKER", "suspectName": "张某"})
        interrogation = create_session(db, case.id)
        suspect = enroll_suspect(
            db,
            case_id=case.id,
            embedding=struct.pack("<ff", 1.0, 0.0),
            embedding_dim=2,
            model_id="eres2net_large",
            model_version="speaker-v4",
            enrollment_quality="GOOD",
            usable_duration_ms=3000,
        )
        from app.database.models import SessionVoiceAssignment

        db.add(
            SessionVoiceAssignment(
                id="assignment-speaker",
                session_id=interrogation.id,
                suspect_voiceprint_id=suspect.id,
                recognition_mode="SUSPECT_ONLY",
            )
        )
        capture = asr_repo.create_capture_session(
            db,
            case_id=case.id,
            interrogation_session_id=interrogation.id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        calibration_repo.create_session_snapshot(
            db,
            capture_session_id=capture_id,
            interrogation_session_id=interrogation.id,
            calibration_id=None,
            threshold=0.7,
            margin=0.1,
            threshold_source="DEVICE_CALIBRATED",
            calibration_status="VALID",
            speaker_model_fingerprint="c" * 64,
            microphone_fingerprint="d" * 64,
        )
        db.commit()

    capture_service = AsrCaptureService(
        session_factory=factory,
        device_manager=_Device(),
        ai_supervisor=speech,
        publish_event=events,
    )
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "audio",
        session_factory=factory,
        capture_service=capture_service,
        ai_supervisor=speech,
    )
    coordinator.archive.open_capture(capture_id, case_id="CASE-SPEAKER")
    pcm = b"\x11\x00" * 16_000 + b"\x22\x00" * 16_000
    coordinator.archive.append(capture_id, pcm[:32_000])
    coordinator.archive.append(capture_id, pcm[32_000:])
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        capture.recording_status = "COMPLETE"
        capture.voiced_ms = 2000
        db.commit()
    parent, _ = _create_pending_fragment(factory, capture_id, "父片段原始文本")
    return engine, factory, capture_id, parent, coordinator, speech, events


def _create_pending_fragment(factory, capture_id: str, text: str, *, start_ms=0, end_ms=2000):
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        fragment, created = asr_repo.create_or_update_asr_only_fragment(
            db,
            capture_session_id=capture_id,
            case_id=capture.case_id,
            started_at_ms=start_ms,
            ended_at_ms=end_ms,
            raw_text=text,
            asr_confidence=0.8,
            model_id="paraformer",
            model_version="asr-v3",
            idempotency_key=f"{capture_id}:{start_ms}:{end_ms}",
        )
        assert created
        fragment_id = fragment.id
        db.commit()
        return fragment_id, created


def _job_for(factory, coordinator, capture_id: str, *, force: bool = True) -> str:
    coordinator.schedule_speaker_jobs(capture_id, force=force)
    with factory() as db:
        job = db.query(LiveSpeechJob).filter_by(kind="SPEAKER", capture_session_id=capture_id).one()
        return job.id


def test_speaker_jobs_require_both_voiced_time_and_final_fragment_count(tmp_path):
    _engine, _factory, _capture_id, _parent, coordinator, _speech, _events = _build(tmp_path)

    assert coordinator.speaker_jobs_ready("capture", voiced_ms=9_999, final_count=3) is False
    assert coordinator.speaker_jobs_ready("capture", voiced_ms=10_000, final_count=2) is False
    assert coordinator.speaker_jobs_ready("capture", voiced_ms=10_000, final_count=3) is True


def test_stop_schedules_unresolved_fragments_below_threshold_and_is_idempotent(tmp_path):
    engine, factory, capture_id, parent_id, coordinator, _speech, _events = _build(tmp_path)
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        capture.voiced_ms = 999
        db.commit()

    job_id = _job_for(factory, coordinator, capture_id, force=True)
    coordinator.schedule_speaker_jobs(capture_id, force=True)

    with factory() as db:
        jobs = db.query(LiveSpeechJob).filter_by(kind="SPEAKER", fragment_id=parent_id).all()
        assert len(jobs) == 1
        assert jobs[0].id == job_id
        assert jobs[0].state == "PENDING"
        assert db.query(ASRFragment).filter_by(id=parent_id).one().state == "PENDING"
    engine.dispose()


def test_threshold_activation_backfills_all_unresolved_ranges(tmp_path):
    engine, factory, capture_id, _first, coordinator, _speech, _events = _build(tmp_path)
    second, _ = _create_pending_fragment(factory, capture_id, "第二段", start_ms=2000, end_ms=3000)
    third, _ = _create_pending_fragment(factory, capture_id, "第三段", start_ms=3000, end_ms=4000)
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        capture.voiced_ms = 10_000
        db.commit()

    coordinator.schedule_speaker_jobs(capture_id)
    coordinator.schedule_speaker_jobs(capture_id)
    fourth, _ = _create_pending_fragment(factory, capture_id, "第四段", start_ms=4000, end_ms=5000)
    coordinator.schedule_speaker_jobs(capture_id)

    with factory() as db:
        jobs = db.query(LiveSpeechJob).filter_by(kind="SPEAKER", capture_session_id=capture_id).all()
        assert {job.fragment_id for job in jobs} == {
            db.query(ASRFragment.id).filter_by(capture_session_id=capture_id).order_by(ASRFragment.ordinal).first()[0],
            second,
            third,
            fourth,
        }
        assert len(jobs) == 4
    engine.dispose()


def test_restart_requeues_persisted_pending_and_interrupted_speaker_jobs(tmp_path):
    engine, factory, capture_id, first, coordinator, speech, events = _build(tmp_path)
    second, _ = _create_pending_fragment(factory, capture_id, "第二段", start_ms=2000, end_ms=3000)
    coordinator.schedule_speaker_jobs(capture_id, force=True)
    with factory() as db:
        jobs = db.query(LiveSpeechJob).filter_by(kind="SPEAKER", capture_session_id=capture_id).all()
        assert len(jobs) == 2
        jobs[0].state = "RUNNING"
        db.commit()
        expected_ids = {job.id for job in jobs}

    capture_service = AsrCaptureService(
        session_factory=factory,
        device_manager=_Device(),
        ai_supervisor=speech,
        publish_event=events,
    )
    restarted = LiveSpeechCoordinator(
        data_dir=tmp_path / "audio",
        session_factory=factory,
        capture_service=capture_service,
        ai_supervisor=speech,
    )
    assert set(restarted._recover_speaker_jobs()) == expected_ids
    queued = [restarted.speaker_queue.get_nowait() for _ in range(2)]
    assert {item.job_id for item in queued} == expected_ids
    with factory() as db:
        assert all(job.state == "PENDING" for job in db.query(LiveSpeechJob).filter_by(kind="SPEAKER").all())
        assert {job.fragment_id for job in db.query(LiveSpeechJob).filter_by(kind="SPEAKER").all()} == {
            first,
            second,
        }
    engine.dispose()


def test_two_turn_retranscription_atomically_replaces_parent_and_keeps_lineage(tmp_path, monkeypatch):
    from app.services import live_speech_coordinator

    monkeypatch.setattr(live_speech_coordinator, "SpeakerTurnSplitter", lambda: _TwoTurnSplitter())
    engine, factory, capture_id, parent_id, coordinator, speech, events = _build(tmp_path)
    job_id = _job_for(factory, coordinator, capture_id)
    routed: list[tuple[str, str]] = []

    def route_after_commit(case_id: str, fragment_id: str):
        with factory() as db:
            assert db.get(LiveSpeechJob, job_id).state == "COMPLETE"
            child = db.get(ASRFragment, fragment_id)
            assert child is not None and child.speaker == "SUSPECT"
        routed.append((case_id, fragment_id))

    coordinator.capture_service.fragment_sink = route_after_commit
    priority_yields: list[bool] = []
    monkeypatch.setattr(coordinator, "_wait_for_asr_priority", lambda: priority_yields.append(True))

    coordinator.process_speaker_job(job_id)
    coordinator.process_speaker_job(job_id)

    with factory() as db:
        parent = db.get(ASRFragment, parent_id)
        assert parent is not None
        assert parent.state == "SUPERSEDED"
        assert parent.raw_text == "父片段原始文本"
        lineage = db.query(ASRFragmentLineage).filter_by(parent_fragment_id=parent_id).all()
        assert len(lineage) == 2
        children = [db.get(ASRFragment, row.child_fragment_id) for row in lineage]
        assert [child.raw_text for child in children] == ["child-17", "child-34"]
        assert [child.started_at_ms for child in children] == [0, 1000]
        assert [child.ended_at_ms for child in children] == [1000, 2000]
        results = (
            db.query(ASRSpeakerAnalysisResult)
            .filter_by(analysis_job_id=job_id)
            .order_by(ASRSpeakerAnalysisResult.created_at, ASRSpeakerAnalysisResult.id)
            .all()
        )
        assert len(results) == 2
        assert all(result.role == "SUSPECT" for result in results)
        assert all(result.score == 1.0 and result.threshold == 0.7 for result in results)
        assert all(result.margin == 0.1 and result.threshold_source == "DEVICE_CALIBRATED" for result in results)
        assert all(result.model_id == "eres2net_large" for result in results)
        assert all(result.model_version == "speaker-v4" for result in results)
        assert all(result.model_fingerprint == "c" * 64 for result in results)
        assert all(result.overlap is False for result in results)
        placeholder = db.query(ASRRecognitionEvidence).filter_by(fragment_id=parent_id).one()
        assert placeholder.ai_speaker == "UNKNOWN"
        assert placeholder.speaker_source == "PENDING_ANALYSIS"
        job = db.get(LiveSpeechJob, job_id)
        assert job is not None and job.state == "COMPLETE"
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None and capture.speaker_status == "COMPLETE"
    assert speech.transcriptions == [b"\x11\x00" * 16_000, b"\x22\x00" * 16_000]
    assert len(priority_yields) >= 6
    replacements = [event for event in events.events if event[1] == "ASR_FRAGMENT_REPLACED"]
    assert len(replacements) == 1
    assert replacements[0][2]["parentFragmentId"] == parent_id
    assert replacements[0][2]["jobId"] == job_id
    assert len(replacements[0][2]["fragments"]) == 2
    assert [fragment_id for case, fragment_id in routed if case == "CASE-SPEAKER"] == [
        fragment["fragmentId"] for fragment in replacements[0][2]["fragments"]
    ]
    engine.dispose()


def test_resolved_single_speaker_routes_once_after_commit(tmp_path, monkeypatch):
    from app.services import live_speech_coordinator

    class _SingleTurnSplitter:
        def split(self, pcm, sample_rate, embed, reference=None):
            del reference
            embed(pcm)
            return [TurnSpan(0, 2000)]

    monkeypatch.setattr(live_speech_coordinator, "SpeakerTurnSplitter", lambda: _SingleTurnSplitter())
    engine, factory, capture_id, parent_id, coordinator, _speech, events = _build(tmp_path)
    job_id = _job_for(factory, coordinator, capture_id)
    routed: list[tuple[str, str]] = []

    def route_after_commit(case_id: str, fragment_id: str):
        with factory() as db:
            assert db.get(LiveSpeechJob, job_id).state == "COMPLETE"
            parent = db.get(ASRFragment, fragment_id)
            assert parent is not None and parent.speaker == "SUSPECT"
        routed.append((case_id, fragment_id))

    coordinator.capture_service.fragment_sink = route_after_commit
    coordinator.process_speaker_job(job_id)
    coordinator.process_speaker_job(job_id)

    with factory() as db:
        parent = db.get(ASRFragment, parent_id)
        assert parent is not None and parent.speaker == "SUSPECT"
    assert routed == [("CASE-SPEAKER", parent_id)]
    assert len([event for event in events.events if event[1] == "ASR_FRAGMENT"]) == 1
    engine.dispose()


def test_failed_child_transcription_keeps_parent_and_creates_no_partial_lineage(tmp_path, monkeypatch):
    from app.services import live_speech_coordinator

    monkeypatch.setattr(live_speech_coordinator, "SpeakerTurnSplitter", lambda: _TwoTurnSplitter())
    engine, factory, capture_id, parent_id, coordinator, _speech, events = _build(
        tmp_path, fail_transcription=2
    )
    job_id = _job_for(factory, coordinator, capture_id)

    coordinator.process_speaker_job(job_id)

    with factory() as db:
        parent = db.get(ASRFragment, parent_id)
        assert parent is not None and parent.state == "PENDING"
        assert parent.speaker == "UNKNOWN"
        assert db.query(ASRFragmentLineage).filter_by(parent_fragment_id=parent_id).count() == 0
        assert db.query(ASRSpeakerAnalysisResult).filter_by(analysis_job_id=job_id).count() == 0
        job = db.get(LiveSpeechJob, job_id)
        assert job is not None and job.state == "NEEDS_REVIEW"
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None and capture.speaker_status == "NEEDS_REVIEW"
    assert not [event for event in events.events if event[1] == "ASR_FRAGMENT_REPLACED"]
    engine.dispose()


def test_ambiguous_short_turn_remains_unknown_and_needs_review(tmp_path, monkeypatch):
    from app.services import live_speech_coordinator

    monkeypatch.setattr(live_speech_coordinator, "SpeakerTurnSplitter", lambda: _AmbiguousSplitter())
    engine, factory, capture_id, parent_id, coordinator, _speech, _events = _build(tmp_path)
    job_id = _job_for(factory, coordinator, capture_id)

    coordinator.process_speaker_job(job_id)

    with factory() as db:
        parent = db.get(ASRFragment, parent_id)
        job = db.get(LiveSpeechJob, job_id)
        assert parent is not None and parent.state == "PENDING"
        assert parent.speaker == "UNKNOWN"
        assert parent.speaker_source == "PENDING_ANALYSIS"
        assert job is not None and job.state == "NEEDS_REVIEW"
        result = db.query(ASRSpeakerAnalysisResult).filter_by(analysis_job_id=job_id).one()
        assert result.role == "UNKNOWN"
        assert result.overlap is True
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None and capture.speaker_status == "NEEDS_REVIEW"
    engine.dispose()


@pytest.mark.parametrize("state", ["EDITED", "CONFIRMED"])
def test_manually_edited_or_confirmed_parent_is_never_replaced(tmp_path, monkeypatch, state):
    from app.services import live_speech_coordinator

    monkeypatch.setattr(live_speech_coordinator, "SpeakerTurnSplitter", lambda: _TwoTurnSplitter())
    engine, factory, capture_id, parent_id, coordinator, _speech, _events = _build(tmp_path)
    job_id = _job_for(factory, coordinator, capture_id)
    with factory() as db:
        parent = db.get(ASRFragment, parent_id)
        assert parent is not None
        if state == "EDITED":
            parent.edited_text = "人工修订"
        parent.state = state
        db.commit()

    coordinator.process_speaker_job(job_id)

    with factory() as db:
        parent = db.get(ASRFragment, parent_id)
        assert parent is not None and parent.state == state
        assert parent.edited_text == ("人工修订" if state == "EDITED" else "父片段原始文本")
        assert db.query(ASRFragmentLineage).filter_by(parent_fragment_id=parent_id).count() == 0
        job = db.get(LiveSpeechJob, job_id)
        assert job is not None and job.state == "COMPLETE"
    engine.dispose()


def test_short_unambiguous_decision_stays_unknown_by_policy(tmp_path, monkeypatch):
    from app.services import live_speech_coordinator

    class _ShortSplitter:
        def split(self, pcm, sample_rate, embed, reference=None):
            del reference
            embed(pcm)
            return [TurnSpan(0, 500)]

    monkeypatch.setattr(live_speech_coordinator, "SpeakerTurnSplitter", lambda: _ShortSplitter())
    engine, factory, capture_id, parent_id, coordinator, _speech, _events = _build(tmp_path)
    routed: list[tuple[str, str]] = []
    coordinator.capture_service.fragment_sink = lambda case, fragment: routed.append((case, fragment))
    with factory() as db:
        parent = db.get(ASRFragment, parent_id)
        assert parent is not None
        parent.ended_at_ms = 500
        db.commit()
    job_id = _job_for(factory, coordinator, capture_id)

    coordinator.process_speaker_job(job_id)

    with factory() as db:
        parent = db.get(ASRFragment, parent_id)
        assert parent is not None and parent.state == "PENDING"
        assert parent.speaker == "UNKNOWN"
        assert parent.speaker_source == "UNASSIGNED"
        result = db.query(ASRSpeakerAnalysisResult).filter_by(analysis_job_id=job_id).one()
        assert result.role == "UNKNOWN"
        assert result.overlap is False
    assert routed == []
    engine.dispose()
