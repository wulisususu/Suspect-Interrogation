from types import SimpleNamespace

from app import health
from app.database.models import LiveSpeechJob
from app.database.session import init_database, make_engine, make_session_factory
from app.repositories import cases as case_repo
from app.repositories.sessions import create as create_session
from app.repositories.asr_fragments import create_capture_session
from app.services.live_speech_coordinator import LiveSpeechCoordinator
from speech_worker.funasr_runtime import FunASRSpeechRuntime


def test_worker_core_ready_without_loading_retired_speaker(tmp_path, monkeypatch):
    monkeypatch.delenv("SUSPECT_LEGACY_VOICEPRINT_ENABLED", raising=False)
    for name in ("paraformer", "fsmn-vad"):
        (tmp_path / name).mkdir()
    runtime = FunASRSpeechRuntime(model_root=tmp_path, model_factory=lambda **kw: object())
    monkeypatch.setattr(runtime, "_load_eres2net", lambda: (_ for _ in ()).throw(AssertionError("retired speaker loaded")))
    runtime.load()
    assert runtime.loaded is True
    assert runtime.health()["status"] == "ready"
    assert runtime.health()["models"]["speaker"] is False


def test_recording_capability_depends_on_asr_and_vad_not_calibration(monkeypatch):
    caps = {name: {"state": "READY", "detail": name} for name in ("asr", "asrStreaming", "vad", "audioCapture")}
    caps["voiceprintCalibration"] = {"state": "NOT_CONFIGURED", "detail": "no retired speaker model"}
    monkeypatch.setattr(health, "readiness_snapshot", lambda request: {"capabilities": caps, "checks": {"database": {"state": "READY", "detail": "ok"}}})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    assert health.runtime_capabilities(request)["recording"]["state"] == "AVAILABLE"
    caps["vad"]["state"] = "UNAVAILABLE"
    assert health.runtime_capabilities(request)["recording"]["state"] == "NOT_CONFIGURED"


def test_retired_speaker_jobs_neither_restart_nor_block_finalization(tmp_path, monkeypatch):
    monkeypatch.delenv("SUSPECT_LEGACY_VOICEPRINT_ENABLED", raising=False)
    engine = make_engine(f"sqlite:///{tmp_path / 'retirement.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        case = case_repo.create(db, {"id": "CASE-RETIRED", "suspectName": "测试"})
        session = create_session(db, case.id)
        session_id = session.id
        capture = create_capture_session(db, case_id=case.id, interrogation_session_id=session.id, sample_rate=16000)
        capture.recording_status = "COMPLETE"
        capture.asr_status = "COMPLETE"
        capture_id = capture.id
        db.add(LiveSpeechJob(id="retired-job", idempotency_key="retired-job", kind="SPEAKER", capture_session_id=capture.id, start_sample=0, end_sample=16000, state="PENDING"))
        db.commit()
    service = SimpleNamespace(set_live_speech_coordinator=lambda c: None)
    coordinator = LiveSpeechCoordinator(data_dir=tmp_path / "audio", session_factory=factory, capture_service=service, ai_supervisor=object())
    assert coordinator.schedule_speaker_jobs(capture_id, force=True) == []
    assert coordinator._recover_speaker_jobs() == []
    coordinator.wait_for_session_processing(session_id, timeout=0.02)
    coordinator.start()
    try:
        assert coordinator._speaker_thread is None
        with factory() as db:
            assert db.get(LiveSpeechJob, "retired-job").state == "PENDING"
    finally:
        coordinator.shutdown()
    engine.dispose()


def test_startup_retries_original_recording_without_reprocessing_asr(tmp_path):
    from app.database.models import ASRCaptureSession
    from app.database.recording_models import CaptureRecording
    engine = make_engine(f"sqlite:///{tmp_path / 'original.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        case_repo.create(db, {"id": "CASE-ORIGINAL", "suspectName": "Test"})
        capture = create_capture_session(db, case_id="CASE-ORIGINAL", interrogation_session_id=None, sample_rate=16000)
        capture_id = capture.id
        db.commit()
    coordinator = LiveSpeechCoordinator(data_dir=tmp_path / "audio", session_factory=factory, capture_service=SimpleNamespace(set_live_speech_coordinator=lambda c: None), ai_supervisor=object())
    coordinator.archive.open_capture(capture_id, case_id="CASE-ORIGINAL")
    coordinator.archive.append(capture_id, b"\x01\x00" * 16000)
    coordinator.archive.finalize_capture(capture_id)
    with factory() as db:
        db.get(ASRCaptureSession, capture_id).asr_status = "COMPLETE"
        db.commit()
    coordinator.start()
    try:
        with factory() as db:
            recording = db.get(CaptureRecording, capture_id)
            assert recording.original_sha256
            assert recording.original_sample_count == 16000
            from app.database.case_management_models import CaseManagement
            assert db.get(CaseManagement, "CASE-ORIGINAL") is None
        assert coordinator.asr_queue.empty()
    finally:
        coordinator.shutdown()
    engine.dispose()


def test_restart_persists_power_interruption_only_for_active_capture(tmp_path):
    from app.database.case_management_models import CaseManagement
    from app.database.models import CaseQuestion
    engine = make_engine(f"sqlite:///{tmp_path / 'power.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        case_repo.create(db, {"id": "CASE-POWER", "suspectName": "Test"})
        db.add(CaseQuestion(id="q-power", case_id="CASE-POWER", text="What happened?", source="CASE", sort_order=1))
        capture = create_capture_session(db, case_id="CASE-POWER", interrogation_session_id=None, sample_rate=16000)
        capture.target_question_id = "q-power"
        capture_id = capture.id
        db.commit()
    coordinator = LiveSpeechCoordinator(data_dir=tmp_path / "audio", session_factory=factory, capture_service=SimpleNamespace(set_live_speech_coordinator=lambda c: None), ai_supervisor=object())
    coordinator.archive.open_capture(capture_id, case_id="CASE-POWER")
    coordinator.archive.append(capture_id, b"\x01\x00" * 16000)
    coordinator.start()
    try:
        with factory() as db:
            saved = db.get(CaseManagement, "CASE-POWER")
            assert saved.interruption_reason == "POWER_RECOVERY"
            assert saved.stopped_question_id == "q-power"
    finally:
        coordinator.shutdown()
    engine.dispose()


def test_network_interruption_is_saved_once_and_keeps_question_target(tmp_path):
    from app.database.case_management_models import CaseManagement
    from app.database.models import ASRCaptureSession, AuditLog, CaseQuestion
    from sqlalchemy import select, func
    engine = make_engine(f"sqlite:///{tmp_path / 'interrupt.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        case = case_repo.create(db, {"id": "CASE-NETWORK", "suspectName": "测试"})
        question = CaseQuestion(id="q-network", case_id=case.id, text="What happened?", source="CASE", sort_order=1)
        db.add(question)
        capture = create_capture_session(db, case_id=case.id, interrogation_session_id=None, sample_rate=16000)
        capture.target_question_id = question.id
        capture_id = capture.id
        db.commit()
    coordinator = LiveSpeechCoordinator(data_dir=tmp_path / "audio", session_factory=factory, capture_service=SimpleNamespace(set_live_speech_coordinator=lambda c: None), ai_supervisor=object())
    assert coordinator.mark_browser_capture_incomplete("CASE-NETWORK", capture_id, "network disconnected")
    with factory() as db:
        saved = db.get(CaseManagement, "CASE-NETWORK")
        assert saved.interruption_reason == "NETWORK_INTERRUPTED"
        assert saved.stopped_question_id == "q-network"
        timestamp = saved.interrupted_at
    coordinator.mark_browser_capture_incomplete("CASE-NETWORK", capture_id, "retry acknowledgement")
    with factory() as db:
        assert db.get(CaseManagement, "CASE-NETWORK").interrupted_at == timestamp
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "CASE_INTERRUPTED")) == 1
        db.get(ASRCaptureSession, capture_id).recording_status = "CAPTURING"
        db.get(type(case), "CASE-NETWORK").workflow_state = "FROZEN"
        db.commit()
    assert coordinator.mark_browser_capture_incomplete("CASE-NETWORK", capture_id, "closed record network loss")
    engine.dispose()
