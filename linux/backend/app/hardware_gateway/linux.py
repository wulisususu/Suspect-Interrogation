from __future__ import annotations

from typing import Any

from app.domain.errors import DomainError
from hardware.base import DeviceState, HardwareError
from hardware.device_manager import DeviceManager


_AVAILABLE_STATES = {DeviceState.READY.value, DeviceState.ACTIVE.value}


class LinuxHardwareGateway:
    """Adapter from the concrete Linux HAL to the core business gateway.

    The business layer consumes stable dictionaries and never imports ctypes,
    ALSA, V4L2 or vendor device classes directly.
    """

    def __init__(self, manager: DeviceManager):
        self.manager = manager

    @staticmethod
    def _device_status(item: dict[str, Any] | None) -> dict[str, Any]:
        item = item or {}
        status = str(item.get("status") or "unconfigured")
        return {
            "available": status in _AVAILABLE_STATES,
            "status": status,
            "health": item.get("health"),
            "device_info": item.get("device_info"),
        }

    def status(self) -> dict[str, Any]:
        report = self.manager.capability_report()
        devices = report.get("devices", {})
        identity = self._device_status(devices.get("identity"))
        camera = self._device_status(devices.get("camera"))
        audio = self._device_status(devices.get("audio"))
        signature = self._device_status(devices.get("signature"))
        return {
            "backend": "ready",
            "simulator": self.manager.mode == "mock",
            "mode": self.manager.mode,
            "devices": {
                "identity": identity,
                "camera": camera,
                "microphone": audio,
                "audio": audio,
                "signature": signature,
                # Compatibility names retained for the legacy frontend/API surface.
                "face": camera,
                "fingerprint": {"available": False, "status": "not_configured"},
                "scanner": {"available": False, "status": "not_configured"},
            },
        }

    @staticmethod
    def _domain_error(exc: HardwareError) -> DomainError:
        status = 409 if exc.code in {"DEVICE_NOT_CONNECTED", "DEVICE_NOT_CONFIGURED", "SDK_NOT_FOUND"} else 500
        return DomainError(exc.code, exc.message, status)

    def read_identity(self) -> dict[str, Any]:
        try:
            result = self.manager.read_identity()
        except HardwareError as exc:
            raise self._domain_error(exc) from exc
        data = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        # Core persistence names this field birth_date; HAL deliberately keeps the
        # normalized device payload field `birth`.
        data["birth_date"] = data.get("birth_date") or data.get("birth") or ""
        return data

    def action(self, device_type: str) -> dict[str, Any]:
        try:
            if device_type == "identity":
                data = self.read_identity()
                return {
                    "success": True,
                    "simulated": self.manager.mode == "mock",
                    "message": "身份证读取完成",
                    **data,
                    "idNumber": data.get("id_number", ""),
                }
            if device_type in {"camera", "face"}:
                result = self.manager.capture_image()
                payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
                return {"success": True, "simulated": self.manager.mode == "mock", **payload}
            if device_type == "signature":
                self.manager.start_signature_capture()
                return {"success": True, "simulated": self.manager.mode == "mock", "status": "capturing"}
        except HardwareError as exc:
            raise self._domain_error(exc) from exc
        raise DomainError("UNKNOWN_DEVICE", f"未知或不支持的设备操作：{device_type}", 400)

    def capture_fingerprint(self) -> dict[str, Any]:
        capture = getattr(self.manager, "capture_fingerprint", None)
        if not callable(capture):
            raise DomainError("FINGERPRINT_NOT_CONFIGURED", "尚未配置可输出图像的指纹设备驱动", 503)
        try:
            result = capture()
        except HardwareError as exc:
            raise self._domain_error(exc) from exc
        payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        return {**payload, "simulated": self.manager.mode == "mock"}
