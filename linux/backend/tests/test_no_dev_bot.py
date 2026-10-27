"""The solo-testing BOT (cloud LLM judge + fake interrogator injection) was removed.

Nothing in the production app may expose it again: no route, no capture hook.
"""

from app.main import create_app
from app.services.asr_capture_service import AsrCaptureService
from app.services.source_aware_asr_capture_service import SourceAwareAsrCaptureService


def test_app_exposes_no_dev_bot_routes():
    paths = create_app().openapi()["paths"]
    assert any(path.startswith("/api/v1/cases") for path in paths)
    assert [path for path in paths if "/dev/bot" in path] == []


def test_capture_services_have_no_bot_injection_hook():
    assert not hasattr(AsrCaptureService, "inject_officer_text")
    assert not hasattr(SourceAwareAsrCaptureService, "inject_officer_text")
