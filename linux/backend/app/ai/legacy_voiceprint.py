"""Explicit opt-in for the retired voiceprint compatibility pipeline."""
import os


def legacy_voiceprint_enabled() -> bool:
    return os.environ.get("SUSPECT_LEGACY_VOICEPRINT_ENABLED", "").strip().lower() in {"1", "true", "yes"}
