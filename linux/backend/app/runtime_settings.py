from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    """Production-safe Linux runtime defaults.

    LAN exposure, browser microphone test mode, debug mode and CORS are opt-in.
    Mutable/model/web paths are configurable so tests and deployments do not
    need to run as root.
    """

    model_config = SettingsConfigDict(
        env_prefix="SUSPECT_",
        case_sensitive=False,
        protected_namespaces=("settings_",),
    )

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    debug: bool = False
    cors_origins: str = ""
    audio_input_mode: str = "ALSA"
    formal_routing_mode: str = "legacy"
    speaker_backend: str = "eres2net_large"
    qa_idle_close_seconds: float = 4.0

    data_dir: Path = Path("/var/lib/suspect-interrogation")
    log_dir: Path = Path("/var/log/suspect-interrogation")
    db_path: Path = Path("/var/lib/suspect-interrogation/interrogation.db")
    model_path: Path | None = None
    web_dist_dir: Path = Path("/opt/suspect-interrogation/current/webapp/dist")
    # Obsidian Vault 所在目录（单向导入源）。生产建议放在数据目录下，随备份走。
    knowledge_vault_dir: Path = Path("/var/lib/suspect-interrogation/knowledge-vault")
    min_free_mb: int = 10_240

    @field_validator("audio_input_mode")
    @classmethod
    def validate_audio_input_mode(cls, value: str) -> str:
        normalized = str(value or "ALSA").strip().upper()
        if normalized not in {"ALSA", "BROWSER"}:
            raise ValueError("audio_input_mode must be ALSA or BROWSER")
        return normalized

    @field_validator("formal_routing_mode")
    @classmethod
    def validate_formal_routing_mode(cls, value: str) -> str:
        normalized = str(value or "legacy").strip().lower()
        if normalized not in {"legacy", "qwen"}:
            raise ValueError("formal_routing_mode must be legacy or qwen")
        return normalized

    @field_validator("speaker_backend")
    @classmethod
    def validate_speaker_backend(cls, value: str) -> str:
        normalized = str(value or "eres2net_large").strip().lower()
        if normalized != "eres2net_large":
            raise ValueError("speaker_backend must be eres2net_large")
        return normalized

    @field_validator("qa_idle_close_seconds")
    @classmethod
    def validate_qa_idle_close_seconds(cls, value: float) -> float:
        seconds = float(value)
        if seconds <= 0:
            raise ValueError("qa_idle_close_seconds must be positive")
        return seconds

    @field_validator("min_free_mb")
    @classmethod
    def validate_min_free_mb(cls, value: int) -> int:
        megabytes = int(value)
        if megabytes <= 0:
            raise ValueError("min_free_mb must be positive")
        return megabytes

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [item.strip() for item in self.cors_origins.split(",") if item.strip()]
        if "*" in origins:
            raise ValueError("Wildcard CORS is not allowed; configure explicit origins")
        return origins
