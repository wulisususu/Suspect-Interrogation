from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .speech.calibration import SpeakerCalibration


@dataclass(frozen=True)
class AISettings:
    mode: str
    model_root: Path
    registry_path: Path
    request_timeout: float
    idle_unload_seconds: float
    memory_budget_mb: int
    speech_socket: Path
    speaker_accept_threshold: float | None
    speaker_effective_threshold: float
    speaker_threshold_source: str
    speaker_margin: float | None
    asr_backend: str | None
    ocr_backend: str | None
    llm_backend: str | None
    llamapi_base_url: str
    llamapi_model_hint: str

    @classmethod
    def from_env(cls) -> "AISettings":
        backend_dir = Path(__file__).resolve().parents[2]
        mode = os.getenv("AI_MODE", "mock").strip().lower()
        if mode not in {"mock", "real"}:
            raise ValueError("AI_MODE must be 'mock' or 'real'")
        speaker_backend = os.getenv("SUSPECT_SPEAKER_BACKEND", "eres2net_large")
        calibration = SpeakerCalibration.from_env(backend_key=speaker_backend)
        return cls(
            mode=mode,
            model_root=Path(os.getenv("MODEL_ROOT", str(backend_dir / "models"))).expanduser(),
            registry_path=Path(os.getenv("MODEL_REGISTRY", str(backend_dir / "config/model-registry.yaml"))).expanduser(),
            request_timeout=max(0.05, float(os.getenv("AI_REQUEST_TIMEOUT", "30"))),
            idle_unload_seconds=max(0.0, float(os.getenv("AI_IDLE_UNLOAD_SECONDS", "300"))),
            memory_budget_mb=max(0, int(os.getenv("AI_MEMORY_BUDGET_MB", "6144"))),
            speech_socket=Path(
                os.getenv("SUSPECT_SPEECH_SOCKET", "/run/suspect-interrogation/speech.sock")
            ).expanduser(),
            speaker_accept_threshold=calibration.accept_threshold,
            speaker_effective_threshold=calibration.effective_threshold,
            speaker_threshold_source=calibration.threshold_source,
            speaker_margin=calibration.margin,
            asr_backend=os.getenv("ASR_BACKEND"),
            ocr_backend=os.getenv("OCR_BACKEND"),
            llm_backend=os.getenv("LLM_BACKEND"),
            llamapi_base_url=os.getenv("LLAMAPI_BASE_URL", "http://127.0.0.1:9265/v1").strip().rstrip("/"),
            llamapi_model_hint=os.getenv("LLAMAPI_MODEL_HINT", "qwen3:4b").strip(),
        )
