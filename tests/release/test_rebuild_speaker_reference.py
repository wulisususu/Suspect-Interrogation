from __future__ import annotations

import hashlib
import json
import struct
import sys
import wave
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "linux" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database.models import AuditLog
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.errors import DomainError
from app.repositories import cases as case_repo
from app.repositories import voiceprints as voiceprint_repo
from app.services.speaker_reference_rebuild import SpeakerReferenceRebuildService

SCRIPT = ROOT / "scripts" / "ci" / "rebuild-speaker-reference.py"
SAMPLE_RATE = 16_000
ERES = "eres2net_large"


def pcm16(duration_ms: int = 90_000, sample: int = 1200) -> bytes:
    count = duration_ms * SAMPLE_RATE // 1000
    return int(sample).to_bytes(2, "little", signed=True) * count


def write_wav(path: Path, pcm: bytes, *, sample_rate: int = SAMPLE_RATE, channels: int = 1, width: int = 2) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


class FakeSpeechClient:
    def __init__(self, *, vector: tuple[float, ...] = (0.0, 1.0, 0.0)) -> None:
        self.vector = vector
        self.embedding_calls: list[tuple[str | None, bytes]] = []

    def speech_segments(self, pcm: bytes, sample_rate: int = SAMPLE_RATE):
        assert sample_rate == SAMPLE_RATE
        assert pcm
        return [[0, 20000], [21000, 41000], [42000, 62000]]

    def extract_embedding(self, pcm: bytes, sample_rate: int = SAMPLE_RATE, backend: str | None = None):
        assert sample_rate == SAMPLE_RATE
        self.embedding_calls.append((backend, bytes(pcm)))
        return {
            "backend_key": backend,
            "embedding": list(self.vector),
            "model_id": "iic/speech_eres2net_large_200k_sv_zh-cn_16k-common",
            "model_version": "task11-fixture",
            "model_fingerprint": "e" * 64,
        }


def db_factory(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'task11.sqlite3'}")
    init_database(engine)
    return make_session_factory(engine)


def seed_case(db, case_id: str = "CASE-T11"):
    return case_repo.create(db, {"id": case_id, "suspectName": "测试对象", "officerName": "测试民警"})


def seed_xvector_suspect(db, case_id: str):
    return voiceprint_repo.enroll_suspect(
        db,
        case_id=case_id,
        model_key="xvector",
        embedding=struct.pack("<2f", 1.0, 0.0),
        embedding_dim=2,
        model_id="xvector-model",
        model_version="legacy",
        enrollment_quality="EXISTING",
        usable_duration_ms=20_000,
    )


def test_rebuilds_new_eres_reference_from_explicit_wav_without_using_xvector_embedding(tmp_path: Path):
    factory = db_factory(tmp_path)
    audio = pcm16()
    source = tmp_path / "suspect.wav"
    write_wav(source, audio)
    speech = FakeSpeechClient()

    with factory() as db:
        case = seed_case(db)
        xvector = seed_xvector_suspect(db, case.id)
        xvector_bytes = bytes(xvector.embedding)
        db.commit()

        result = SpeakerReferenceRebuildService(db, speech_client=speech).rebuild(
            identity_type="suspect",
            identity_id=case.id,
            audio_path=source,
            target_backend=ERES,
            actor_id="admin",
        )

        assert result["status"] == "REBUILT"
        assert result["targetBackend"] == ERES
        assert result["modelFingerprint"] == "e" * 64
        assert result["sourceAudioSha256"] == hashlib.sha256(audio).hexdigest()
        target = voiceprint_repo.get_suspect(db, case.id, model_key=ERES)
        assert target is not None
        assert target.model_key == ERES
        assert target.embedding_dim == 3
        assert all(backend == ERES for backend, _ in speech.embedding_calls)
        assert all(chunk != xvector_bytes for _, chunk in speech.embedding_calls)

        audit = db.scalar(select(AuditLog).where(AuditLog.action == "SPEAKER_REFERENCE_REBUILD"))
        assert audit is not None
        detail = json.loads(audit.detail_json)
        assert detail["source_audio_sha256"] == hashlib.sha256(audio).hexdigest()
        assert detail["source_path_class"] == "EXPLICIT_WAV_FILE"
        assert detail["target_backend"] == ERES
        assert detail["target_model_fingerprint"] == "e" * 64
        assert "source_path" not in detail
        assert "pcm" not in detail
        assert "audio" not in detail
        assert "embedding" not in detail


def test_duplicate_target_reference_is_refused_without_replace(tmp_path: Path):
    factory = db_factory(tmp_path)
    source = tmp_path / "suspect.pcm"
    source.write_bytes(pcm16())
    with factory() as db:
        case = seed_case(db)
        seed_xvector_suspect(db, case.id)
        existing = voiceprint_repo.enroll_suspect(
            db,
            case_id=case.id,
            model_key=ERES,
            embedding=struct.pack("<3f", 1.0, 0.0, 0.0),
            embedding_dim=3,
            model_id="existing-eres",
            model_version="old",
            enrollment_quality="EXISTING",
            usable_duration_ms=20_000,
        )
        before = bytes(existing.embedding)
        db.commit()

        with pytest.raises(DomainError) as exc:
            SpeakerReferenceRebuildService(db, speech_client=FakeSpeechClient()).rebuild(
                identity_type="suspect",
                identity_id=case.id,
                audio_path=source,
                audio_format="pcm16",
                target_backend=ERES,
            )
        assert exc.value.code == "SPEAKER_REFERENCE_TARGET_EXISTS"
        assert bytes(voiceprint_repo.get_suspect(db, case.id, model_key=ERES, active_only=False).embedding) == before


def test_replace_is_explicit_and_updates_existing_target_reference(tmp_path: Path):
    factory = db_factory(tmp_path)
    source = tmp_path / "suspect.pcm"
    source.write_bytes(pcm16(sample=1600))
    with factory() as db:
        case = seed_case(db)
        seed_xvector_suspect(db, case.id)
        existing = voiceprint_repo.enroll_suspect(
            db,
            case_id=case.id,
            model_key=ERES,
            embedding=struct.pack("<3f", 1.0, 0.0, 0.0),
            embedding_dim=3,
            model_id="existing-eres",
            model_version="old",
            enrollment_quality="EXISTING",
            usable_duration_ms=20_000,
        )
        existing_id = existing.id
        db.commit()

        result = SpeakerReferenceRebuildService(db, speech_client=FakeSpeechClient()).rebuild(
            identity_type="suspect",
            identity_id=case.id,
            audio_path=source,
            audio_format="pcm16",
            target_backend=ERES,
            replace=True,
        )
        replaced = voiceprint_repo.get_suspect(db, case.id, model_key=ERES, active_only=False)
        assert result["status"] == "REPLACED"
        assert replaced.id == existing_id
        assert replaced.model_id.startswith("iic/speech_eres2net_large")
        assert bytes(replaced.embedding) != struct.pack("<3f", 1.0, 0.0, 0.0)


def test_invalid_wav_format_fails_before_embedding_extraction(tmp_path: Path):
    factory = db_factory(tmp_path)
    source = tmp_path / "stereo.wav"
    write_wav(source, pcm16(), channels=2)
    speech = FakeSpeechClient()
    with factory() as db:
        case = seed_case(db)
        seed_xvector_suspect(db, case.id)
        db.commit()
        with pytest.raises(DomainError) as exc:
            SpeakerReferenceRebuildService(db, speech_client=speech).rebuild(
                identity_type="suspect",
                identity_id=case.id,
                audio_path=source,
                target_backend=ERES,
            )
        assert exc.value.code == "SPEAKER_REFERENCE_AUDIO_INVALID"
        assert speech.embedding_calls == []


def test_missing_source_audio_returns_needs_reenroll_without_creating_reference(tmp_path: Path):
    factory = db_factory(tmp_path)
    missing = tmp_path / "not-retained.wav"
    with factory() as db:
        case = seed_case(db)
        seed_xvector_suspect(db, case.id)
        db.commit()
        result = SpeakerReferenceRebuildService(db, speech_client=FakeSpeechClient()).rebuild(
            identity_type="suspect",
            identity_id=case.id,
            audio_path=missing,
            target_backend=ERES,
        )
        assert result == {
            "status": "NEEDS_REENROLL",
            "identityType": "suspect",
            "identityId": case.id,
            "targetBackend": ERES,
            "reason": "SOURCE_AUDIO_UNAVAILABLE",
        }
        assert voiceprint_repo.get_suspect(db, case.id, model_key=ERES) is None


def test_officer_reference_rebuild_uses_existing_identity_metadata_not_embedding(tmp_path: Path):
    factory = db_factory(tmp_path)
    source = tmp_path / "officer.wav"
    write_wav(source, pcm16(sample=900))
    speech = FakeSpeechClient(vector=(0.1, 0.9, 0.0))
    with factory() as db:
        voiceprint_repo.enroll_officer(
            db,
            officer_id="P-T11",
            officer_name="张警官",
            model_key="xvector",
            embedding=struct.pack("<2f", 1.0, 0.0),
            embedding_dim=2,
            model_id="xvector-model",
            model_version="legacy",
            enrollment_quality="EXISTING",
            usable_duration_ms=20_000,
        )
        db.commit()
        result = SpeakerReferenceRebuildService(db, speech_client=speech).rebuild(
            identity_type="officer",
            identity_id="P-T11",
            audio_path=source,
            target_backend=ERES,
        )
        target = voiceprint_repo.get_officer(db, "P-T11", model_key=ERES)
        assert result["status"] == "REBUILT"
        assert target is not None
        assert target.officer_name == "张警官"
        assert all(backend == ERES for backend, _ in speech.embedding_calls)


def test_cli_contract_is_explicit_and_does_not_offer_embedding_copy_mode():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--identity-type" in text
    assert "--identity-id" in text
    assert "--audio" in text
    assert "--target-backend" in text
    assert "--replace" in text
    assert "NEEDS_REENROLL" in text
    assert "eres2net_large" in text
    assert "copy-embedding" not in text
    assert "source_embedding" not in text
