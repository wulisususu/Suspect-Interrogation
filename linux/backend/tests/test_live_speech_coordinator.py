from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.database.models import ASRCaptureSession
from app.ai.speech.types import SpeechEvent, SpeechEventType
from app.database.session import init_database, make_engine, make_session_factory
from app.repositories import asr_fragments as asr_repo
from app.repositories import cases as case_repo
from app.repositories import sessions as session_repo
from app.services.durable_audio_archive import DurableAudioArchive
from app.services.live_speech_coordinator import LiveSpeechCoordinator
from app.services.source_aware_asr_capture_service import SourceAwareAsrCaptureService


class FakeDevice:
    def __init__(self, frames: list[bytes]):
        self.frames = list(frames)
        self.read_count = 0
        self.drained = threading.Event()

    def start_record(self) -> None:
        pass

    def read_audio_frames(self, timeout: float = 0.01) -> bytes:
        self.read_count += 1
        if self.frames:
            frame = self.frames.pop(0)
            if not self.frames:
                self.drained.set()
            return frame
        self.drained.set()
        time.sleep(min(timeout, 0.005))
        return b""

    def stop_record(self) -> None:
        pass


class BlockingSpeechWorker:
    speaker_accept_threshold = 0.7
    speaker_margin = 0.1

    def __init__(self) -> None:
        self.push_started = threading.Event()
        self.release_push = threading.Event()
        self.pushed: list[bytes] = []

    def open_speech_session(self, session_id: str, **kwargs):
        return {"session_id": session_id}

    def push_speech_pcm(self, session_id: str, pcm: bytes):
        self.pushed.append(bytes(pcm))
        self.push_started.set()
        self.release_push.wait(timeout=5)
        return []

    def finalize_speech_session(self, session_id: str):
        return []

    def close_speech_session(self, session_id: str) -> None:
        pass


class FailingSpeechWorker(BlockingSpeechWorker):
    def push_speech_pcm(self, session_id: str, pcm: bytes):
        self.pushed.append(bytes(pcm))
        self.push_started.set()
        raise RuntimeError("simulated ASR failure")


class FinalizeAndCloseFailSpeechWorker:
    def __init__(self, failing_session_id: str) -> None:
        self.failing_session_id = failing_session_id
        self.finalize_failed = threading.Event()
        self.close_failed = threading.Event()
        self.first_push = threading.Event()
        self.second_push = threading.Event()
        self.pushed_sessions: list[str] = []

    def open_speech_session(self, session_id: str, **kwargs):
        return {"session_id": session_id}

    def push_speech_pcm(self, session_id: str, pcm: bytes):
        del pcm
        self.pushed_sessions.append(session_id)
        if session_id == self.failing_session_id:
            self.first_push.set()
        else:
            self.second_push.set()
        return []

    def finalize_speech_session(self, session_id: str):
        if session_id == self.failing_session_id:
            self.finalize_failed.set()
            raise RuntimeError("simulated finalize failure")
        return []

    def close_speech_session(self, session_id: str) -> None:
        if session_id == self.failing_session_id:
            self.close_failed.set()
            raise RuntimeError("simulated close failure")


class ReplaySpeechWorker:
    def __init__(self, *, emit_final: bool, crash_before_finalize: bool = False) -> None:
        self.emit_final = emit_final
        self.crash_before_finalize = crash_before_finalize
        self.push_started = threading.Event()
        self.finalize_called = threading.Event()
        self.open_base_samples: list[int] = []
        self.pushed: list[bytes] = []

    def open_speech_session(self, session_id: str, **kwargs):
        self.open_base_samples.append(int(kwargs.get("base_sample", 0)))
        return {"session_id": session_id}

    def push_speech_pcm(self, session_id: str, pcm: bytes):
        self.pushed.append(bytes(pcm))
        self.push_started.set()
        if not self.emit_final:
            return [
                SpeechEvent(
                    type=SpeechEventType.VAD_START,
                    session_id=session_id,
                    start_ms=0,
                    details={"replay_start_sample": 0},
                )
            ]
        return [
            SpeechEvent(
                type=SpeechEventType.VAD_START,
                session_id=session_id,
                start_ms=0,
                details={"replay_start_sample": 0},
            ),
            SpeechEvent(
                type=SpeechEventType.VAD_END,
                session_id=session_id,
                start_ms=0,
                end_ms=1000,
            ),
            SpeechEvent(
                type=SpeechEventType.ASR_FINAL,
                session_id=session_id,
                start_ms=0,
                end_ms=1000,
                text="完整记录",
                confidence=0.95,
                model_id="paraformer",
                details={
                    "stage_one_asr_only": True,
                    "asr_start_sample": 0,
                    "asr_end_sample": 16_000,
                    "model_version": "test-v1",
                },
            ),
        ]

    def finalize_speech_session(self, session_id: str):
        self.finalize_called.set()
        if self.crash_before_finalize:
            raise RuntimeError("simulated crash before VAD finalization")
        return []

    def close_speech_session(self, session_id: str) -> None:
        pass


class VADTransitionReplaySpeechWorker:
    def __init__(self) -> None:
        self.push_count = 0
        self.open_base_samples: list[int] = []
        self.push_started = threading.Event()

    def open_speech_session(self, session_id: str, **kwargs):
        self.open_base_samples.append(int(kwargs.get("base_sample", 0)))
        return {"session_id": session_id}

    def push_speech_pcm(self, session_id: str, pcm: bytes):
        del pcm
        self.push_count += 1
        self.push_started.set()
        if self.push_count == 1:
            return [
                SpeechEvent(
                    type=SpeechEventType.VAD_END,
                    session_id=session_id,
                    start_ms=0,
                    end_ms=1000,
                ),
                SpeechEvent(
                    type=SpeechEventType.ASR_FINAL,
                    session_id=session_id,
                    start_ms=0,
                    end_ms=1000,
                    text="前一段",
                    confidence=0.95,
                    model_id="paraformer",
                    details={
                        "stage_one_asr_only": True,
                        "asr_start_sample": 0,
                        "asr_end_sample": 16_000,
                        "model_version": "test-v1",
                    },
                ),
                SpeechEvent(
                    type=SpeechEventType.VAD_START,
                    session_id=session_id,
                    start_ms=2000,
                    details={"replay_start_sample": 12_800},
                ),
            ]
        return [
            SpeechEvent(
                type=SpeechEventType.VAD_START,
                session_id=session_id,
                start_ms=2000,
                details={"replay_start_sample": 12_800},
            ),
            SpeechEvent(
                type=SpeechEventType.VAD_END,
                session_id=session_id,
                start_ms=2000,
                end_ms=3000,
            ),
            SpeechEvent(
                type=SpeechEventType.ASR_FINAL,
                session_id=session_id,
                start_ms=2000,
                end_ms=3000,
                text="后一段",
                confidence=0.95,
                model_id="paraformer",
                details={
                    "stage_one_asr_only": True,
                    "asr_start_sample": 32_000,
                    "asr_end_sample": 48_000,
                    "model_version": "test-v1",
                },
            ),
        ]

    def finalize_speech_session(self, session_id: str):
        del session_id
        return []

    def close_speech_session(self, session_id: str) -> None:
        pass


class CrashWindowRecoverySpeechWorker:
    def __init__(self, *, emit_completed_then_open: bool) -> None:
        self.emit_completed_then_open = emit_completed_then_open
        self.push_count = 0
        self.open_base_samples: list[int] = []
        self.push_started = threading.Event()

    def open_speech_session(self, session_id: str, **kwargs):
        self.open_base_samples.append(int(kwargs.get("base_sample", 0)))
        return {"session_id": session_id}

    def push_speech_pcm(self, session_id: str, pcm: bytes):
        del pcm
        self.push_count += 1
        self.push_started.set()
        if self.emit_completed_then_open:
            if self.push_count != 1:
                return []
            return [
                SpeechEvent(
                    type=SpeechEventType.VAD_END,
                    session_id=session_id,
                    start_ms=2000,
                    end_ms=2500,
                ),
                SpeechEvent(
                    type=SpeechEventType.ASR_FINAL,
                    session_id=session_id,
                    start_ms=2000,
                    end_ms=2500,
                    text="崩溃前已结束的片段",
                    confidence=0.95,
                    model_id="paraformer",
                    details={
                        "stage_one_asr_only": True,
                        "asr_start_sample": 32_000,
                        "asr_end_sample": 40_000,
                        "model_version": "test-v1",
                    },
                ),
                SpeechEvent(
                    type=SpeechEventType.VAD_START,
                    session_id=session_id,
                    start_ms=3750,
                    details={"replay_start_sample": 40_000},
                ),
            ]
        return [
            SpeechEvent(
                type=SpeechEventType.VAD_START,
                session_id=session_id,
                start_ms=3750,
                details={"replay_start_sample": 40_000},
            ),
            SpeechEvent(
                type=SpeechEventType.VAD_END,
                session_id=session_id,
                start_ms=3750,
                end_ms=4000,
            ),
            SpeechEvent(
                type=SpeechEventType.ASR_FINAL,
                session_id=session_id,
                start_ms=3750,
                end_ms=4000,
                text="崩溃时仍打开的片段",
                confidence=0.95,
                model_id="paraformer",
                details={
                    "stage_one_asr_only": True,
                    "asr_start_sample": 60_000,
                    "asr_end_sample": 64_000,
                    "model_version": "test-v1",
                },
            ),
        ]

    def finalize_speech_session(self, session_id: str):
        del session_id
        return []

    def close_speech_session(self, session_id: str) -> None:
        pass


class FailFirstConsumeRecoveryService:
    def __init__(self, delegate, *, final_only: bool = False) -> None:
        self.delegate = delegate
        self.final_only = final_only
        self.consume_failed = threading.Event()
        self._failed = False

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def build_recovery_runtime(self, capture):
        runtime = self.delegate.build_recovery_runtime(capture)
        consume_events = runtime.consume_events

        def consume_once(events):
            has_final = any(event.type is SpeechEventType.ASR_FINAL for event in events or [])
            if not self._failed and (not self.final_only or has_final):
                self._failed = True
                self.consume_failed.set()
                raise RuntimeError("simulated crash before ASR_FINAL commit")
            return consume_events(events)

        runtime.consume_events = consume_once
        return runtime


class FinalizeRecoverySpeechWorker:
    def __init__(self, *, emit_final_during_finalize: bool, audio_sample_count: int) -> None:
        self.emit_final_during_finalize = emit_final_during_finalize
        self.audio_sample_count = audio_sample_count
        self.current_sample = 0
        self.open_base_samples: list[int] = []
        self.finalize_called = threading.Event()

    def open_speech_session(self, session_id: str, **kwargs):
        self.current_sample = int(kwargs.get("base_sample", 0))
        self.open_base_samples.append(self.current_sample)
        return {"session_id": session_id}

    def push_speech_pcm(self, session_id: str, pcm: bytes):
        self.current_sample += len(pcm) // 2
        if self.emit_final_during_finalize or self.current_sample < self.audio_sample_count:
            return []
        return self._final_events(session_id)

    def finalize_speech_session(self, session_id: str):
        self.finalize_called.set()
        if self.emit_final_during_finalize:
            return self._final_events(session_id)
        return []

    def close_speech_session(self, session_id: str) -> None:
        pass

    @staticmethod
    def _final_events(session_id: str) -> list[SpeechEvent]:
        return [
            SpeechEvent(
                type=SpeechEventType.VAD_START,
                session_id=session_id,
                start_ms=7500,
                details={
                    "replay_start_sample": 100_800,
                    "asr_start_sample": 120_000,
                },
            ),
            SpeechEvent(
                type=SpeechEventType.VAD_END,
                session_id=session_id,
                start_ms=7500,
                end_ms=8000,
            ),
            SpeechEvent(
                type=SpeechEventType.ASR_FINAL,
                session_id=session_id,
                start_ms=7500,
                end_ms=8000,
                text="最终录音片段",
                confidence=0.95,
                model_id="paraformer",
                details={
                    "stage_one_asr_only": True,
                    "asr_start_sample": 120_000,
                    "asr_end_sample": 128_000,
                    "model_version": "test-v1",
                },
            ),
        ]


class EventCollector:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def __call__(self, session_id: str, event: str, payload: dict) -> None:
        self.events.append((session_id, event, payload))


def _seed_database(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'capture.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        case = case_repo.create(db, {"id": "CASE-COORD", "suspectName": "待识别"})
        session = session_repo.create(db, case.id)
        db.commit()
        return factory, case.id, session.id


def _source_service(factory, device, speech, events) -> SourceAwareAsrCaptureService:
    return SourceAwareAsrCaptureService(
        session_factory=factory,
        device_manager=device,
        browser_audio_input=None,
        ai_supervisor=speech,
        publish_event=events,
        read_timeout=0.01,
    )


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not met before timeout")


def _asr_cursor(factory, capture_id: str) -> int:
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
    return -1 if capture is None else int(capture.asr_cursor_sample)


def test_browser_frame_appends_are_serialized_and_exact_replay_is_queued_once(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    class CaptureServiceStub:
        def set_live_speech_coordinator(self, _coordinator):
            pass

    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=CaptureServiceStub(),
        ai_supervisor=object(),
    )
    runtime = SimpleNamespace(case_id=case_id, capture_session_id=capture_id, durable_sample_cursor=0)
    coordinator.open_capture(runtime)
    first_entered = threading.Event()
    release_first = threading.Event()
    archive_sequences = []
    original_append = coordinator.archive.append

    def block_first_append(append_capture_id, pcm, **kwargs):
        sequence = kwargs.get("source_sequence")
        archive_sequences.append(sequence)
        if sequence == 1:
            first_entered.set()
            assert release_first.wait(timeout=2)
        return original_append(append_capture_id, pcm, **kwargs)

    coordinator.archive.append = block_first_append
    failures = []

    def append(sequence: int, start_sample: int, pcm: bytes):
        try:
            coordinator.append_audio(
                runtime,
                pcm,
                source_sequence=sequence,
                expected_start_sample=start_sample,
            )
        except Exception as exc:  # surfaced in the main test thread
            failures.append(exc)

    original = threading.Thread(target=append, args=(1, 0, b"\x01\x00" * 100))
    duplicate = threading.Thread(target=append, args=(1, 0, b"\x01\x00" * 100))
    following = threading.Thread(target=append, args=(2, 100, b"\x02\x00" * 50))
    original.start()
    assert first_entered.wait(timeout=1)
    duplicate.start()
    following.start()
    time.sleep(0.03)
    assert archive_sequences == [1]
    release_first.set()
    for thread in (original, duplicate, following):
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert failures == []
    ranges = []
    while not coordinator.asr_queue.empty():
        item = coordinator.asr_queue.get_nowait()
        ranges.append((item.start_sample, item.end_sample))
    assert ranges == [(0, 100), (100, 150)]
    assert coordinator._durable_cursors[capture_id] == 150
    assert runtime.durable_sample_cursor == 150


def test_browser_capture_marker_reconnect_is_limited_to_capturing_or_incomplete(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capturing = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        incomplete = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        incomplete_with_audio = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        complete = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_ids = (capturing.id, incomplete.id, incomplete_with_audio.id, complete.id)
        db.commit()

    class CaptureServiceStub:
        def set_live_speech_coordinator(self, _coordinator):
            pass

    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=CaptureServiceStub(),
        ai_supervisor=object(),
    )
    capturing_id, incomplete_id, incomplete_with_audio_id, complete_id = capture_ids
    for capture_id in capture_ids:
        coordinator.archive.open_capture(capture_id, case_id=case_id)
        coordinator.register_browser_capture(capture_id)
    coordinator.mark_browser_capture_incomplete(case_id, incomplete_id, "first frame failed")
    incomplete_frame = b"\x02\x00" * 10
    coordinator.archive.append(
        incomplete_with_audio_id,
        incomplete_frame,
        source_sequence=1,
        expected_start_sample=0,
    )
    coordinator.mark_browser_capture_incomplete(case_id, incomplete_with_audio_id, "later frame failed")
    with factory() as db:
        incomplete_capture = db.get(ASRCaptureSession, incomplete_with_audio_id)
        assert incomplete_capture is not None
        incomplete_ended_at = incomplete_capture.ended_at
    coordinator.mark_browser_capture_incomplete(case_id, incomplete_with_audio_id, "retry after lost ack")
    with factory() as db:
        incomplete_capture = db.get(ASRCaptureSession, incomplete_with_audio_id)
        assert incomplete_capture is not None
        assert incomplete_capture.ended_at == incomplete_ended_at
    coordinator.archive.append(
        complete_id,
        b"\x01\x00" * 10,
        source_sequence=1,
        expected_start_sample=0,
    )
    coordinator.archive.finalize_capture(complete_id)

    restarted = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=CaptureServiceStub(),
        ai_supervisor=object(),
    )

    assert restarted.has_browser_frame_receipt(case_id, capturing_id) is True
    assert restarted.has_browser_frame_receipt(case_id, incomplete_id) is True
    assert restarted.has_browser_frame_receipt(case_id, incomplete_with_audio_id) is True
    assert restarted.has_browser_frame_receipt(case_id, complete_id) is True

    restarted.mark_browser_capture_incomplete(case_id, complete_id, "stale socket")
    with factory() as db:
        capture = db.get(ASRCaptureSession, complete_id)
        assert capture is not None
        assert capture.recording_status == "COMPLETE"

    with pytest.raises(RuntimeError, match="not accepting audio"):
        restarted.archive.append(
            incomplete_id,
            b"\x03\x00" * 10,
            source_sequence=1,
            expected_start_sample=0,
        )
    assert restarted.archive.append(
        incomplete_with_audio_id,
        incomplete_frame,
        source_sequence=1,
        expected_start_sample=0,
    ) == 10
    with pytest.raises(RuntimeError, match="not accepting audio"):
        restarted.archive.append(
            incomplete_with_audio_id,
            b"\x04\x00" * 5,
            source_sequence=2,
            expected_start_sample=10,
        )


def test_browser_capture_without_interrogation_session_is_finalized_as_orphan(tmp_path: Path):
    factory, case_id, _session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=None,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    class CaptureServiceStub:
        def set_live_speech_coordinator(self, _coordinator):
            pass

    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=CaptureServiceStub(),
        ai_supervisor=object(),
    )
    coordinator.archive.open_capture(capture_id, case_id=case_id)
    coordinator.register_browser_capture(capture_id)
    coordinator.start()
    try:
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "COMPLETE"
    finally:
        coordinator.shutdown()


def test_browser_recovery_without_browser_runtime_marks_incomplete_and_replays_durable_audio(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    audio = b"\x07\x00" * 160
    speech = ReplaySpeechWorker(emit_final=False)
    capture_service = _source_service(factory, FakeDevice([]), speech, EventCollector())
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=capture_service,
        ai_supervisor=speech,
    )
    coordinator.archive.open_capture(capture_id, case_id=case_id)
    coordinator.register_browser_capture(capture_id)
    coordinator.archive.append(
        capture_id,
        audio,
        source_sequence=1,
        expected_start_sample=0,
    )

    coordinator.start()
    try:
        coordinator.asr_queue.join()
        assert speech.pushed == [audio]
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "INCOMPLETE"
        status = capture_service.status(case_id)
        assert status["source"] == "BROWSER"
        assert status["status"] == "FAILED"
        receipt = capture_service.ingest_browser_frame(case_id, capture_id, 2, len(audio) // 2, audio)
        assert receipt == {"ackSequence": 2, "durableSampleEnd": len(audio)}
    finally:
        coordinator.shutdown()


def test_browser_runtime_resume_failure_marks_incomplete_and_finishes_durable_asr(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)

    class FailingBrowserInput:
        def start_record(self):
            raise RuntimeError("browser input could not resume")

        def stop_record(self):
            pass

    audio = b"\x0c\x00" * 160
    speech = ReplaySpeechWorker(emit_final=False)
    capture_service = SourceAwareAsrCaptureService(
        session_factory=factory,
        device_manager=FakeDevice([]),
        browser_audio_input=FailingBrowserInput(),
        ai_supervisor=speech,
        publish_event=EventCollector(),
        read_timeout=0.01,
    )
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=capture_service,
        ai_supervisor=speech,
    )
    coordinator.archive.open_capture(capture_id, case_id=case_id)
    coordinator.register_browser_capture(capture_id)
    coordinator.archive.append(
        capture_id,
        audio,
        source_sequence=1,
        expected_start_sample=0,
    )

    coordinator.start()
    try:
        coordinator.asr_queue.join()
        assert speech.pushed == [audio]
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "INCOMPLETE"
        assert capture_service.status(case_id)["source"] == "BROWSER"
        assert capture_id not in coordinator._asr_blocked
    finally:
        coordinator.shutdown()


def test_marking_browser_capture_incomplete_does_not_block_durable_asr_ranges(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    speech = ReplaySpeechWorker(emit_final=False)
    capture_service = _source_service(factory, FakeDevice([]), speech, EventCollector())
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=capture_service,
        ai_supervisor=speech,
    )
    coordinator.start()
    try:
        with factory() as db:
            capture = asr_repo.create_capture_session(
                db,
                case_id=case_id,
                interrogation_session_id=session_id,
                sample_rate=16_000,
            )
            capture_id = capture.id
            db.commit()
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            runtime = capture_service.build_recovery_runtime(capture)
        assert runtime is not None
        coordinator.open_capture(runtime)
        coordinator.register_browser_capture(capture_id)
        audio = b"\x08\x00" * 160
        coordinator.append_audio(
            runtime,
            audio,
            source_sequence=1,
            expected_start_sample=0,
        )
        assert coordinator.mark_browser_capture_incomplete(case_id, capture_id, "outbox full") is True
        coordinator.asr_queue.join()

        assert speech.pushed == [audio]
        assert runtime.storage_error is None
        assert capture_id not in coordinator._asr_blocked
    finally:
        coordinator.shutdown()


def test_incomplete_browser_capture_can_reingest_and_finalize_local_outbox_frames(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    worker = ReplaySpeechWorker(emit_final=False)
    service = _source_service(factory, FakeDevice([]), worker, EventCollector())
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=service,
        ai_supervisor=worker,
    )
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    runtime = service.build_recovery_runtime(capture)
    assert runtime is not None
    coordinator.open_capture(runtime)
    coordinator.register_browser_capture(capture_id)
    first_pcm = b"\x01\x00" * 10
    coordinator.append_audio(
        runtime,
        first_pcm,
        source_sequence=1,
        expected_start_sample=0,
    )
    coordinator.mark_browser_capture_incomplete(case_id, capture_id, "lost browser acknowledgement")
    coordinator.start()
    try:
        missing_pcm = b"\x02\x00" * 10
        receipt = coordinator.replay_browser_frame(
            case_id=case_id,
            capture_id=capture_id,
            source_sequence=2,
            start_sample=10,
            pcm=missing_pcm,
        )
        assert receipt == {"ackSequence": 2, "durableSampleEnd": 20}
        assert coordinator.replay_browser_frame(
            case_id=case_id,
            capture_id=capture_id,
            source_sequence=2,
            start_sample=10,
            pcm=missing_pcm,
        ) == receipt
        with pytest.raises(ValueError, match="cursors do not match"):
            coordinator.complete_browser_capture_recovery(
                case_id=case_id,
                capture_id=capture_id,
                next_sequence=4,
                next_sample=20,
            )

        finalized = coordinator.complete_browser_capture_recovery(
            case_id=case_id,
            capture_id=capture_id,
            next_sequence=3,
            next_sample=20,
        )
        assert finalized["recordingStatus"] == "COMPLETE"
        assert coordinator.archive.read_samples(capture_id, 0, 20) == first_pcm + missing_pcm
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "COMPLETE"
            assert capture.audio_sample_count == 20
    finally:
        coordinator.shutdown()


def test_stopping_incomplete_browser_capture_keeps_queued_durable_audio_processable(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    speech = BlockingSpeechWorker()
    capture_service = _source_service(factory, FakeDevice([]), speech, EventCollector())
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=capture_service,
        ai_supervisor=speech,
    )
    coordinator.start()
    try:
        with factory() as db:
            capture = asr_repo.create_capture_session(
                db,
                case_id=case_id,
                interrogation_session_id=session_id,
                sample_rate=16_000,
            )
            capture_id = capture.id
            db.commit()
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            runtime = capture_service.build_recovery_runtime(capture)
        assert runtime is not None
        coordinator.open_capture(runtime)
        coordinator.register_browser_capture(capture_id)
        audio = b"\x09\x00" * 160
        coordinator.append_audio(
            runtime,
            audio,
            source_sequence=1,
            expected_start_sample=0,
        )
        assert speech.push_started.wait(timeout=1)

        coordinator.mark_browser_capture_incomplete(case_id, capture_id, "outbox full")
        coordinator.finish_capture(runtime)
        speech.release_push.set()
        coordinator.asr_queue.join()

        assert speech.pushed == [audio]
        assert runtime.storage_error is None
        assert capture_id not in coordinator._asr_blocked
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "INCOMPLETE"
    finally:
        speech.release_push.set()
        coordinator.shutdown()


def test_browser_sequence_gap_after_durable_frame_keeps_committed_asr_range_processable(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    speech = BlockingSpeechWorker()
    capture_service = _source_service(factory, FakeDevice([]), speech, EventCollector())
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=capture_service,
        ai_supervisor=speech,
    )
    coordinator.start()
    try:
        with factory() as db:
            capture = asr_repo.create_capture_session(
                db,
                case_id=case_id,
                interrogation_session_id=session_id,
                sample_rate=16_000,
            )
            capture_id = capture.id
            db.commit()
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            runtime = capture_service.build_recovery_runtime(capture)
        assert runtime is not None
        coordinator.open_capture(runtime)
        coordinator.register_browser_capture(capture_id)
        audio = b"\x0a\x00" * 160
        coordinator.append_audio(
            runtime,
            audio,
            source_sequence=1,
            expected_start_sample=0,
        )
        assert speech.push_started.wait(timeout=1)

        with pytest.raises(RuntimeError, match="discontinuity"):
            coordinator.append_audio(
                runtime,
                b"\x0b\x00" * 80,
                source_sequence=3,
                expected_start_sample=160,
            )
        coordinator.finish_capture(runtime)
        speech.release_push.set()
        coordinator.asr_queue.join()

        assert speech.pushed == [audio]
        assert runtime.storage_error is None
        assert capture_id not in coordinator._asr_blocked
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "INCOMPLETE"
    finally:
        speech.release_push.set()
        coordinator.shutdown()


def test_capture_persists_audio_while_asr_worker_is_blocked(tmp_path: Path):
    factory, case_id, _session_id = _seed_database(tmp_path)
    frames = [b"\x01\x00" * 160, b"\x02\x00" * 160, b"\x03\x00" * 160]
    device = FakeDevice(frames)
    speech = BlockingSpeechWorker()
    events = EventCollector()
    capture_service = _source_service(factory, device, speech, events)
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=capture_service,
        ai_supervisor=speech,
    )
    coordinator.start()
    try:
        started = capture_service.start(case_id)
        assert started["active"] is True
        assert speech.push_started.wait(timeout=1)
        _wait_for(lambda: device.read_count >= 4)

        capture_id = started["captureSessionId"]
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.audio_sample_count == 480
            assert capture.speaker_status == "PENDING"
        assert coordinator.archive.read_samples(capture_id, 0, 480) == b"".join(
            [b"\x01\x00" * 160, b"\x02\x00" * 160, b"\x03\x00" * 160]
        )
        assert capture_service.stop(case_id)["active"] is False
        assert len(speech.pushed) == 1
    finally:
        speech.release_push.set()
        capture_service.shutdown()
        coordinator.shutdown()


def test_startup_recovers_and_queues_unfinished_audio_before_speaker_work(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SUSPECT_LEGACY_VOICEPRINT_ENABLED", "true")
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    data_dir = tmp_path / "data"
    archive = DurableAudioArchive(data_dir, factory)
    archive.open_capture(capture_id, case_id=case_id)
    archive.append(capture_id, b"\x05\x00" * 160)

    speech = BlockingSpeechWorker()
    speech.release_push.set()
    capture_service = _source_service(factory, FakeDevice([]), speech, EventCollector())
    coordinator = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=capture_service,
        ai_supervisor=speech,
    )
    speaker_work = threading.Event()
    coordinator.start()
    coordinator.enqueue_speaker_work(speaker_work.set)
    try:
        assert speech.push_started.wait(timeout=1)
        assert not speaker_work.is_set()
        speech.release_push.set()
        _wait_for(speaker_work.is_set)
        assert speech.pushed == [b"\x05\x00" * 160]
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "COMPLETE"
            assert capture.asr_cursor_sample == 160
    finally:
        speech.release_push.set()
        coordinator.shutdown()


def test_startup_replays_completed_pending_audio_from_finalize_checkpoint(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    data_dir = tmp_path / "data"
    archive = DurableAudioArchive(data_dir, factory)
    archive.open_capture(capture_id, case_id=case_id)
    audio = b"\x06\x00" * 480
    archive.append(capture_id, audio)
    archive.finalize_capture(capture_id)
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        capture.asr_cursor_sample = 160
        db.commit()

    speech = BlockingSpeechWorker()
    speech.release_push.set()
    capture_service = _source_service(factory, FakeDevice([]), speech, EventCollector())
    coordinator = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=capture_service,
        ai_supervisor=speech,
    )
    coordinator.start()
    try:
        assert speech.push_started.wait(timeout=1)
        _wait_for(lambda: _asr_cursor(factory, capture_id) == 480)
        _wait_for(lambda: _asr_status(factory, capture_id) == "COMPLETE")
        assert speech.pushed == [audio]
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "COMPLETE"
            assert capture.asr_cursor_sample == capture.audio_sample_count == 480
    finally:
        coordinator.shutdown()


def test_restart_replays_unfinished_vad_when_complete_cursor_reached_audio_end(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    data_dir = tmp_path / "data"
    archive = DurableAudioArchive(data_dir, factory)
    audio = b"\x0a\x00" * 16_000
    archive.open_capture(capture_id, case_id=case_id)
    archive.append(capture_id, audio)
    archive.finalize_capture(capture_id)

    crashed_worker = ReplaySpeechWorker(emit_final=False, crash_before_finalize=True)
    first_service = _source_service(factory, FakeDevice([]), crashed_worker, EventCollector())
    first = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=first_service,
        ai_supervisor=crashed_worker,
    )
    first.start()
    try:
        assert crashed_worker.push_started.wait(timeout=1)
        assert crashed_worker.finalize_called.wait(timeout=1)
        first.asr_queue.join()
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "COMPLETE"
            assert capture.asr_cursor_sample == 16_000
            assert capture.audio_sample_count == 16_000
            assert capture.asr_unfinished_start_sample == 0
    finally:
        first.shutdown()

    replay_worker = ReplaySpeechWorker(emit_final=True)
    replay_service = _source_service(factory, FakeDevice([]), replay_worker, EventCollector())
    replay = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=replay_service,
        ai_supervisor=replay_worker,
    )
    replay.start()
    try:
        _wait_for(lambda: len(_fragments(factory, capture_id)) == 1)
        _wait_for(lambda: _unfinished_start(factory, capture_id) is None)
        assert replay_worker.finalize_called.wait(timeout=1)
        replay.asr_queue.join()
        first_result = replay.process_asr_range(capture_id, 0, 16_000)
        second_result = replay.process_asr_range(capture_id, 0, 16_000)
        assert first_result.fragment_ids == second_result.fragment_ids
        assert replay_worker.open_base_samples == [0, 0]
        fragments = _fragments(factory, capture_id)
        assert len(fragments) == 1
        assert fragments[0].ordinal == 0
        assert fragments[0].raw_text == "完整记录"
        assert fragments[0].speaker == "UNKNOWN"
        assert fragments[0].speaker_source == "PENDING_ANALYSIS"
        assert fragments[0].asr_idempotency_key
    finally:
        replay.shutdown()


def test_restart_keeps_later_vad_start_after_end_in_same_batch(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    data_dir = tmp_path / "data"
    archive = DurableAudioArchive(data_dir, factory)
    audio = b"\x0b\x00" * 48_000
    archive.open_capture(capture_id, case_id=case_id)
    archive.append(capture_id, audio[:32_000])
    archive.append(capture_id, audio[32_000:64_000])
    archive.append(capture_id, audio[64_000:])
    archive.finalize_capture(capture_id)

    first_worker = VADTransitionReplaySpeechWorker()
    first_service = _source_service(factory, FakeDevice([]), first_worker, EventCollector())
    first = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=first_service,
        ai_supervisor=first_worker,
    )
    first_result = first.process_asr_range(capture_id, 0, 48_000)
    assert first_worker.push_started.is_set()
    assert len(first_result.fragment_ids) == 1
    assert _asr_cursor(factory, capture_id) == 48_000
    assert _unfinished_start(factory, capture_id) == 12_800
    assert [fragment.raw_text for fragment in _fragments(factory, capture_id)] == ["前一段"]

    replay_worker = VADTransitionReplaySpeechWorker()
    replay_service = _source_service(factory, FakeDevice([]), replay_worker, EventCollector())
    replay = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=replay_service,
        ai_supervisor=replay_worker,
    )
    replay.start()
    try:
        _wait_for(lambda: len(_fragments(factory, capture_id)) == 2)
        _wait_for(lambda: _unfinished_start(factory, capture_id) is None)
        assert replay_worker.push_started.wait(timeout=1)
        assert replay_worker.open_base_samples == [12_800]
        fragments = _fragments(factory, capture_id)
        assert [(fragment.ordinal, fragment.raw_text) for fragment in fragments] == [
            (0, "前一段"),
            (1, "后一段"),
        ]
        assert sum(fragment.raw_text == "后一段" for fragment in fragments) == 1
    finally:
        replay.shutdown()


def test_restart_replays_from_old_cursor_before_later_open_vad_marker(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    data_dir = tmp_path / "data"
    archive = DurableAudioArchive(data_dir, factory)
    audio = b"\x0c\x00" * 64_000
    archive.open_capture(capture_id, case_id=case_id)
    for offset in range(0, len(audio), 32_000):
        archive.append(capture_id, audio[offset : offset + 32_000])
    archive.finalize_capture(capture_id)
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        capture.asr_cursor_sample = 16_000
        capture.asr_unfinished_start_sample = 32_000
        db.commit()

    completed_worker = CrashWindowRecoverySpeechWorker(emit_completed_then_open=True)
    completed_service = _source_service(factory, FakeDevice([]), completed_worker, EventCollector())
    completed_recovery = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=completed_service,
        ai_supervisor=completed_worker,
    )
    completed_recovery.start()
    try:
        assert completed_worker.push_started.wait(timeout=1)
        _wait_for(lambda: _asr_cursor(factory, capture_id) == 64_000)
        assert completed_worker.open_base_samples == [16_000]
        assert _unfinished_start(factory, capture_id) == 40_000
        assert [fragment.raw_text for fragment in _fragments(factory, capture_id)] == [
            "崩溃前已结束的片段"
        ]
    finally:
        completed_recovery.shutdown()

    tail_worker = CrashWindowRecoverySpeechWorker(emit_completed_then_open=False)
    tail_service = _source_service(factory, FakeDevice([]), tail_worker, EventCollector())
    tail_recovery = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=tail_service,
        ai_supervisor=tail_worker,
    )
    tail_recovery.start()
    try:
        _wait_for(lambda: len(_fragments(factory, capture_id)) == 2)
        _wait_for(lambda: _unfinished_start(factory, capture_id) is None)
        assert tail_worker.push_started.wait(timeout=1)
        assert tail_worker.open_base_samples == [40_000]
        fragments = _fragments(factory, capture_id)
        assert [(fragment.ordinal, fragment.raw_text) for fragment in fragments] == [
            (0, "崩溃前已结束的片段"),
            (1, "崩溃时仍打开的片段"),
        ]
        assert sum(fragment.raw_text == "崩溃前已结束的片段" for fragment in fragments) == 1
        assert sum(fragment.raw_text == "崩溃时仍打开的片段" for fragment in fragments) == 1
    finally:
        tail_recovery.shutdown()


def test_replay_crash_keeps_batch_start_until_prior_final_commits(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    data_dir = tmp_path / "data"
    archive = DurableAudioArchive(data_dir, factory)
    audio = b"\x0d\x00" * 64_000
    archive.open_capture(capture_id, case_id=case_id)
    for offset in range(0, len(audio), 32_000):
        archive.append(capture_id, audio[offset : offset + 32_000])
    archive.finalize_capture(capture_id)
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        capture.asr_cursor_sample = 64_000
        capture.asr_unfinished_start_sample = 32_000
        db.commit()

    failed_worker = CrashWindowRecoverySpeechWorker(emit_completed_then_open=True)
    failed_service = FailFirstConsumeRecoveryService(
        _source_service(factory, FakeDevice([]), failed_worker, EventCollector())
    )
    failed_recovery = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=failed_service,
        ai_supervisor=failed_worker,
    )
    failed_recovery.start()
    try:
        assert failed_service.consume_failed.wait(timeout=1)
        failed_recovery.asr_queue.join()
        assert failed_worker.open_base_samples == [32_000]
        assert _asr_cursor(factory, capture_id) == 32_000
        assert _unfinished_start(factory, capture_id) == 32_000
        assert _fragments(factory, capture_id) == []
    finally:
        failed_recovery.shutdown()

    replay_worker = CrashWindowRecoverySpeechWorker(emit_completed_then_open=True)
    replay_service = _source_service(factory, FakeDevice([]), replay_worker, EventCollector())
    replay = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=replay_service,
        ai_supervisor=replay_worker,
    )
    replay.start()
    try:
        _wait_for(lambda: _asr_cursor(factory, capture_id) == 64_000)
        _wait_for(lambda: _unfinished_start(factory, capture_id) == 40_000)
        assert replay_worker.open_base_samples == [32_000]
        assert [fragment.raw_text for fragment in _fragments(factory, capture_id)] == [
            "崩溃前已结束的片段"
        ]
    finally:
        replay.shutdown()

    tail_worker = CrashWindowRecoverySpeechWorker(emit_completed_then_open=False)
    tail_service = _source_service(factory, FakeDevice([]), tail_worker, EventCollector())
    tail_recovery = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=tail_service,
        ai_supervisor=tail_worker,
    )
    tail_recovery.start()
    try:
        _wait_for(lambda: len(_fragments(factory, capture_id)) == 2)
        _wait_for(lambda: _unfinished_start(factory, capture_id) is None)
        assert tail_worker.open_base_samples == [40_000]
        fragments = _fragments(factory, capture_id)
        assert [(fragment.ordinal, fragment.raw_text) for fragment in fragments] == [
            (0, "崩溃前已结束的片段"),
            (1, "崩溃时仍打开的片段"),
        ]
        assert sum(fragment.raw_text == "崩溃前已结束的片段" for fragment in fragments) == 1
        assert sum(fragment.raw_text == "崩溃时仍打开的片段" for fragment in fragments) == 1
    finally:
        tail_recovery.shutdown()


def test_finalize_failure_replays_bounded_tail_when_no_vad_marker_exists(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    data_dir = tmp_path / "data"
    archive = DurableAudioArchive(data_dir, factory)
    audio_sample_count = 128_000
    audio = b"\x0e\x00" * audio_sample_count
    archive.open_capture(capture_id, case_id=case_id)
    for offset in range(0, len(audio), 32_000):
        archive.append(capture_id, audio[offset : offset + 32_000])
    archive.finalize_capture(capture_id)
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        capture.asr_cursor_sample = audio_sample_count
        capture.asr_status = "COMPLETE"
        db.commit()

    failed_worker = FinalizeRecoverySpeechWorker(
        emit_final_during_finalize=True,
        audio_sample_count=audio_sample_count,
    )
    failed_service = FailFirstConsumeRecoveryService(
        _source_service(factory, FakeDevice([]), failed_worker, EventCollector()),
        final_only=True,
    )
    failed_recovery = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=failed_service,
        ai_supervisor=failed_worker,
    )
    failed_recovery.start()
    try:
        # An empty completed backlog starts no ASR work. Opening and pushing the capture
        # leaves the worker session active with no VAD marker or pending fragment.
        for start_sample in range(0, audio_sample_count, 16_000):
            pushed = failed_recovery.process_asr_range(
                capture_id,
                start_sample,
                min(audio_sample_count, start_sample + 16_000),
            )
            assert pushed.fragment_ids == []
        assert _asr_cursor(factory, capture_id) == audio_sample_count
        assert _unfinished_start(factory, capture_id) is None

        runtime = failed_recovery._runtimes[capture_id]
        failed_recovery.finish_capture(runtime)
        assert failed_worker.finalize_called.wait(timeout=1)
        assert failed_service.consume_failed.wait(timeout=1)
        failed_recovery.asr_queue.join()
        # Eight seconds minus the five-second VAD cap and 1.2-second pre-roll.
        assert _asr_cursor(factory, capture_id) == audio_sample_count
        assert _finalize_checkpoint(factory, capture_id) == 28_800
        assert _unfinished_start(factory, capture_id) is None
        assert _fragments(factory, capture_id) == []
    finally:
        failed_recovery.shutdown()

    replay_worker = FinalizeRecoverySpeechWorker(
        emit_final_during_finalize=False,
        audio_sample_count=audio_sample_count,
    )
    replay_service = _source_service(factory, FakeDevice([]), replay_worker, EventCollector())
    replay = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=replay_service,
        ai_supervisor=replay_worker,
    )
    replay.start()
    try:
        _wait_for(lambda: len(_fragments(factory, capture_id)) == 1)
        _wait_for(lambda: _asr_cursor(factory, capture_id) == audio_sample_count)
        _wait_for(lambda: _asr_status(factory, capture_id) == "COMPLETE")
        assert replay_worker.open_base_samples == [28_800]
        fragments = _fragments(factory, capture_id)
        assert [(fragment.ordinal, fragment.raw_text) for fragment in fragments] == [
            (0, "最终录音片段")
        ]
        assert fragments[0].speaker_source == "PENDING_ANALYSIS"
    finally:
        replay.shutdown()


def test_finish_capture_persists_replay_checkpoint_before_archive_completion(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    data_dir = tmp_path / "data"
    audio_sample_count = 128_000
    worker = FinalizeRecoverySpeechWorker(
        emit_final_during_finalize=True,
        audio_sample_count=audio_sample_count,
    )
    service = _source_service(factory, FakeDevice([]), worker, EventCollector())
    coordinator = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=service,
        ai_supervisor=worker,
    )
    coordinator.start()
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    coordinator.archive.open_capture(capture_id, case_id=case_id)
    audio = b"\x0e\x00" * audio_sample_count
    for offset in range(0, len(audio), 32_000):
        coordinator.archive.append(capture_id, audio[offset : offset + 32_000])
    for start_sample in range(0, audio_sample_count, 16_000):
        assert coordinator.process_asr_range(
            capture_id,
            start_sample,
            min(audio_sample_count, start_sample + 16_000),
        ).fragment_ids == []
    assert _asr_cursor(factory, capture_id) == audio_sample_count
    assert _unfinished_start(factory, capture_id) is None

    runtime = coordinator._runtimes[capture_id]
    coordinator.shutdown()
    original_finalize = coordinator.archive.finalize_capture
    observed_before_complete: dict[str, int | str | None] = {}

    def inspect_checkpoint_then_finalize(capture_session_id: str) -> None:
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_session_id)
            assert capture is not None
            observed_before_complete["status"] = capture.recording_status
            observed_before_complete["cursor"] = capture.asr_cursor_sample
            observed_before_complete["marker"] = capture.asr_unfinished_start_sample
            observed_before_complete["asr_status"] = capture.asr_status
            observed_before_complete["checkpoint"] = capture.asr_finalize_checkpoint_sample
        original_finalize(capture_session_id)

    coordinator.archive.finalize_capture = inspect_checkpoint_then_finalize
    try:
        coordinator.finish_capture(runtime)
        assert observed_before_complete == {
            "status": "CAPTURING",
            "cursor": audio_sample_count,
            "marker": None,
            "asr_status": "FINALIZING",
            "checkpoint": 28_800,
        }
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "COMPLETE"
            assert capture.asr_cursor_sample == audio_sample_count
            assert capture.asr_status == "FINALIZING"
            assert capture.asr_finalize_checkpoint_sample == 28_800
        assert coordinator.process_asr_range(
            capture_id,
            audio_sample_count - 16_000,
            audio_sample_count,
        ).fragment_ids == []
        assert _asr_cursor(factory, capture_id) == audio_sample_count
        assert _finalize_checkpoint(factory, capture_id) == 28_800
    finally:
        coordinator.shutdown()

    replay_worker = FinalizeRecoverySpeechWorker(
        emit_final_during_finalize=True,
        audio_sample_count=audio_sample_count,
    )
    replay = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=_source_service(factory, FakeDevice([]), replay_worker, EventCollector()),
        ai_supervisor=replay_worker,
    )
    replay.start()
    try:
        _wait_for(lambda: len(_fragments(factory, capture_id)) == 1)
        _wait_for(lambda: _asr_cursor(factory, capture_id) == audio_sample_count)
        _wait_for(lambda: _asr_status(factory, capture_id) == "COMPLETE")
        assert replay_worker.open_base_samples == [28_800]
        assert [fragment.raw_text for fragment in _fragments(factory, capture_id)] == [
            "最终录音片段"
        ]
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.asr_status == "COMPLETE"
    finally:
        replay.shutdown()


def test_finalization_checkpoint_preserves_progress_before_recovery(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    data_dir = tmp_path / "data"
    audio_sample_count = 128_000
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    archive = DurableAudioArchive(data_dir, factory)
    archive.open_capture(capture_id, case_id=case_id)
    audio = b"\x0e\x00" * audio_sample_count
    for offset in range(0, len(audio), 32_000):
        archive.append(capture_id, audio[offset : offset + 32_000])
    archive.finalize_capture(capture_id)
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        capture.asr_cursor_sample = 0
        capture.asr_status = "FINALIZING"
        capture.asr_finalize_checkpoint_sample = 28_800
        db.commit()

    first_worker = FinalizeRecoverySpeechWorker(
        emit_final_during_finalize=True,
        audio_sample_count=audio_sample_count,
    )
    first = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=_source_service(factory, FakeDevice([]), first_worker, EventCollector()),
        ai_supervisor=first_worker,
    )
    assert first.process_asr_range(capture_id, 0, 16_000).fragment_ids == []
    assert _asr_cursor(factory, capture_id) == 16_000
    assert _finalize_checkpoint(factory, capture_id) == 28_800

    replay_worker = FinalizeRecoverySpeechWorker(
        emit_final_during_finalize=True,
        audio_sample_count=audio_sample_count,
    )
    replay = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=_source_service(factory, FakeDevice([]), replay_worker, EventCollector()),
        ai_supervisor=replay_worker,
    )
    replay.start()
    try:
        _wait_for(lambda: bool(replay_worker.open_base_samples))
        assert replay_worker.open_base_samples == [16_000]
        _wait_for(lambda: _asr_status(factory, capture_id) == "COMPLETE")
        assert _finalize_checkpoint(factory, capture_id) is None
    finally:
        replay.shutdown()


def test_pending_completed_backlog_is_checkpointed_before_replay_and_finalize(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    data_dir = tmp_path / "data"
    audio_sample_count = 128_000
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    archive = DurableAudioArchive(data_dir, factory)
    archive.open_capture(capture_id, case_id=case_id)
    audio = b"\x0e\x00" * audio_sample_count
    for offset in range(0, len(audio), 32_000):
        archive.append(capture_id, audio[offset : offset + 32_000])
    archive.finalize_capture(capture_id)
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        capture.asr_cursor_sample = 96_000
        capture.asr_status = "PENDING"
        db.commit()

    worker = FinalizeRecoverySpeechWorker(
        emit_final_during_finalize=True,
        audio_sample_count=audio_sample_count,
    )
    coordinator = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=_source_service(factory, FakeDevice([]), worker, EventCollector()),
        ai_supervisor=worker,
    )
    before_first_queue: list[tuple[str, int | None, int]] = []
    before_finalize: list[tuple[str, int | None, int]] = []
    original_put = coordinator.asr_queue.put
    original_finalize = worker.finalize_speech_session

    def observe_queue(item, *args, **kwargs):
        if item is not None and not before_first_queue:
            with factory() as db:
                capture = db.get(ASRCaptureSession, capture_id)
                assert capture is not None
                before_first_queue.append(
                    (
                        capture.asr_status,
                        capture.asr_finalize_checkpoint_sample,
                        capture.asr_cursor_sample,
                    )
                )
        return original_put(item, *args, **kwargs)

    def observe_finalize(session_id: str):
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            before_finalize.append(
                (
                    capture.asr_status,
                    capture.asr_finalize_checkpoint_sample,
                    capture.asr_cursor_sample,
                )
            )
        return original_finalize(session_id)

    coordinator.asr_queue.put = observe_queue
    worker.finalize_speech_session = observe_finalize
    coordinator.start()
    try:
        _wait_for(lambda: len(_fragments(factory, capture_id)) == 1)
        _wait_for(lambda: _asr_status(factory, capture_id) == "COMPLETE")
        assert before_first_queue == [("FINALIZING", 28_800, 96_000)]
        assert before_finalize == [("FINALIZING", 28_800, audio_sample_count)]
        assert _finalize_checkpoint(factory, capture_id) is None
        assert _fragments(factory, capture_id)[0].speaker_source == "PENDING_ANALYSIS"
    finally:
        coordinator.shutdown()


def test_finalize_checkpoint_failure_keeps_capture_incomplete(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    worker = FinalizeRecoverySpeechWorker(
        emit_final_during_finalize=True,
        audio_sample_count=0,
    )
    service = _source_service(factory, FakeDevice([]), worker, EventCollector())
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=service,
        ai_supervisor=worker,
    )
    coordinator.start()
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()
    coordinator.archive.open_capture(capture_id, case_id=case_id)
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        runtime = service.build_recovery_runtime(capture)
    assert runtime is not None
    finalized: list[str] = []
    coordinator.archive.finalize_capture = lambda capture_session_id: finalized.append(
        capture_session_id
    )

    def fail_checkpoint(*_args, **_kwargs) -> None:
        raise RuntimeError("simulated checkpoint storage failure")

    coordinator._begin_asr_finalization = fail_checkpoint
    try:
        coordinator.finish_capture(runtime)
        coordinator.asr_queue.join()
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "INCOMPLETE"
            assert capture.asr_status == "PENDING"
        assert runtime.storage_error == "simulated checkpoint storage failure"
        assert finalized == []
    finally:
        coordinator.shutdown()


def test_startup_finalizes_zero_sample_capture_with_asr_status_finalizing(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()
    archive = DurableAudioArchive(tmp_path / "data", factory)
    archive.open_capture(capture_id, case_id=case_id)
    archive.finalize_capture(capture_id)
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        assert capture.audio_sample_count == capture.asr_cursor_sample == 0
        capture.asr_status = "FINALIZING"
        db.commit()

    worker = ReplaySpeechWorker(emit_final=False)
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=_source_service(factory, FakeDevice([]), worker, EventCollector()),
        ai_supervisor=worker,
    )
    coordinator.start()
    try:
        assert worker.finalize_called.wait(timeout=1)
        _wait_for(lambda: _asr_status(factory, capture_id) == "COMPLETE")
        assert worker.open_base_samples == [0]
    finally:
        coordinator.shutdown()


def test_finalize_and_close_failures_do_not_stop_asr_consumer(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        first_capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        first_id = first_capture.id
        second_capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        second_id = second_capture.id
        db.commit()

    worker = FinalizeAndCloseFailSpeechWorker(first_id)
    service = _source_service(factory, FakeDevice([]), worker, EventCollector())
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=service,
        ai_supervisor=worker,
    )
    coordinator.start()
    with factory() as db:
        first_row = db.get(ASRCaptureSession, first_id)
        second_row = db.get(ASRCaptureSession, second_id)
        assert first_row is not None and second_row is not None
        first_runtime = service.build_recovery_runtime(first_row)
        second_runtime = service.build_recovery_runtime(second_row)
    assert first_runtime is not None and second_runtime is not None
    coordinator.open_capture(first_runtime)
    coordinator.open_capture(second_runtime)

    first_finished = threading.Event()
    second_finished = threading.Event()
    first_inference_errors: list[Exception] = []
    first_original_finished = first_runtime.capture_finished_sink
    second_original_finished = second_runtime.capture_finished_sink
    first_original_error_sink = first_runtime.inference_error_sink

    def mark_first_finished() -> None:
        first_original_finished()
        first_finished.set()

    def mark_second_finished() -> None:
        second_original_finished()
        second_finished.set()

    def collect_first_error(exc: Exception) -> None:
        first_inference_errors.append(exc)
        first_original_error_sink(exc)

    first_runtime.capture_finished_sink = mark_first_finished
    second_runtime.capture_finished_sink = mark_second_finished
    first_runtime.inference_error_sink = collect_first_error

    try:
        coordinator.append_audio(first_runtime, b"\x03\x00" * 1600)
        assert worker.first_push.wait(timeout=1)
        coordinator.finish_capture(first_runtime)
        assert worker.finalize_failed.wait(timeout=1)
        assert worker.close_failed.wait(timeout=1)
        first_callback_ran = first_finished.wait(timeout=0.5)

        coordinator.append_audio(second_runtime, b"\x04\x00" * 1600)
        second_range_ran = worker.second_push.wait(timeout=1)
        coordinator.finish_capture(second_runtime)
        second_callback_ran = second_finished.wait(timeout=1)
        deadline = time.monotonic() + 1
        while coordinator.asr_queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.005)
        queue_drained = coordinator.asr_queue.unfinished_tasks == 0

        assert first_callback_ran
        assert second_range_ran
        assert second_callback_ran
        assert queue_drained
        assert coordinator._asr_thread is not None and coordinator._asr_thread.is_alive()
        assert any("close failure" in str(exc) for exc in first_inference_errors)
    finally:
        coordinator.shutdown()


def test_startup_does_not_replay_completed_asr_for_incomplete_audio(tmp_path: Path):
    factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    data_dir = tmp_path / "data"
    archive = DurableAudioArchive(data_dir, factory)
    audio_sample_count = 16_000
    archive.open_capture(capture_id, case_id=case_id)
    archive.append(capture_id, b"\x05\x00" * audio_sample_count)
    archive.finalize_capture(capture_id)
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        assert capture is not None
        capture.recording_status = "INCOMPLETE"
        capture.status = "FAILED"
        capture.asr_status = "COMPLETE"
        capture.asr_cursor_sample = audio_sample_count
        db.commit()

    worker = ReplaySpeechWorker(emit_final=False)
    coordinator = LiveSpeechCoordinator(
        data_dir=data_dir,
        session_factory=factory,
        capture_service=_source_service(factory, FakeDevice([]), worker, EventCollector()),
        ai_supervisor=worker,
    )
    coordinator.start()
    try:
        time.sleep(0.1)
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "INCOMPLETE"
            assert capture.asr_status == "COMPLETE"
            assert capture.asr_cursor_sample == audio_sample_count
            assert capture.asr_unfinished_start_sample is None
        assert worker.open_base_samples == []
        assert worker.pushed == []
        assert _fragments(factory, capture_id) == []
    finally:
        coordinator.shutdown()


def test_startup_does_not_finalize_capture_without_interrogation_session(tmp_path: Path):
    factory, case_id, _session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=None,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    archive = DurableAudioArchive(tmp_path / "data", factory)
    archive.open_capture(capture_id, case_id=case_id)
    archive.append(capture_id, b"\x05\x00" * 16_000)

    worker = ReplaySpeechWorker(emit_final=False)
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=_source_service(factory, FakeDevice([]), worker, EventCollector()),
        ai_supervisor=worker,
    )
    coordinator.start()
    try:
        time.sleep(0.1)
        with factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            assert capture is not None
            assert capture.recording_status == "COMPLETE"
            assert capture.asr_status == "PENDING"
            assert capture.asr_cursor_sample == 0
            assert capture.asr_finalize_checkpoint_sample is None
        assert worker.open_base_samples == []
        assert worker.pushed == []
    finally:
        coordinator.shutdown()


def _fragments(factory, capture_id: str):
    with factory() as db:
        return asr_repo.list_for_capture(db, capture_id)


def _unfinished_start(factory, capture_id: str) -> int | None:
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        return None if capture is None else capture.asr_unfinished_start_sample


def _asr_status(factory, capture_id: str) -> str | None:
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        return None if capture is None else capture.asr_status


def _finalize_checkpoint(factory, capture_id: str) -> int | None:
    with factory() as db:
        capture = db.get(ASRCaptureSession, capture_id)
        return None if capture is None else capture.asr_finalize_checkpoint_sample


def test_coordinator_inference_failure_does_not_stop_durable_capture(tmp_path: Path):
    factory, case_id, _session_id = _seed_database(tmp_path)
    frames = [b"\x07\x00" * 160, b"\x08\x00" * 160, b"\x09\x00" * 160]
    device = FakeDevice(frames)
    speech = FailingSpeechWorker()
    events = EventCollector()
    capture_service = _source_service(factory, device, speech, events)
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=capture_service,
        ai_supervisor=speech,
    )
    coordinator.start()
    try:
        started = capture_service.start(case_id)
        assert speech.push_started.wait(timeout=1)
        _wait_for(lambda: device.read_count >= 4)
        status = capture_service.status(case_id)
        assert status["active"] is True
        assert status["lastError"] == "simulated ASR failure"
        expected_audio = b"".join(frames)
        with factory() as db:
            capture = db.get(ASRCaptureSession, started["captureSessionId"])
            assert capture is not None
            assert capture.audio_sample_count == 480
        assert coordinator.archive.read_samples(started["captureSessionId"], 0, 480) == expected_audio
        assert capture_service.stop(case_id)["active"] is False
    finally:
        capture_service.shutdown()
        coordinator.shutdown()


def test_disk_failure_marks_capture_incomplete_and_publishes_storage_error(tmp_path: Path):
    factory, case_id, _session_id = _seed_database(tmp_path)
    device = FakeDevice([b"\x01\x00" * 160])
    speech = BlockingSpeechWorker()
    speech.release_push.set()
    events = EventCollector()
    capture_service = _source_service(factory, device, speech, events)
    coordinator = LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=capture_service,
        ai_supervisor=speech,
    )
    coordinator.start()

    def fail_append(*args, **kwargs):
        raise OSError("simulated disk full")

    coordinator.archive.append = fail_append
    try:
        started = capture_service.start(case_id)
        _wait_for(lambda: not capture_service.status(case_id).get("active"))

        with factory() as db:
            capture = db.get(ASRCaptureSession, started["captureSessionId"])
            assert capture is not None
            assert capture.recording_status == "INCOMPLETE"
        assert any(event == "ASR_STORAGE_ERROR" for _, event, _ in events.events)
        assert any(
            payload.get("message") == "simulated disk full"
            for _, event, payload in events.events
            if event == "ASR_STORAGE_ERROR"
        )
    finally:
        capture_service.shutdown()
        coordinator.shutdown()
