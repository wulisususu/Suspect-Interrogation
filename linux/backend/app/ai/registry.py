from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    kind: str
    backend: str
    path: str
    architecture: str
    required_files: tuple[str, ...]
    device: str
    context: int
    memory_mb: int
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class InstallationStatus:
    installed: bool
    model_dir: Path
    missing_files: list[Path]


class ModelRegistry:
    """Dependency-free registry loader.

    model-registry.yaml is intentionally JSON-compatible YAML, so the runtime
    can parse it with the Python standard library on an offline appliance.
    """

    def __init__(self, specs: dict[str, ModelSpec], model_root: Path):
        self._specs = specs
        self.model_root = model_root.expanduser().resolve()

    @classmethod
    def load(cls, registry_path: str | Path, model_root: str | Path) -> "ModelRegistry":
        path = Path(registry_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryError(f"Cannot load model registry: {path}: {exc}") from exc
        raw_models = payload.get("models")
        if not isinstance(raw_models, dict):
            raise RegistryError("model registry must contain an object named 'models'")

        root = Path(model_root).expanduser().resolve()
        specs: dict[str, ModelSpec] = {}
        for model_id, raw in raw_models.items():
            if not isinstance(raw, dict):
                raise RegistryError(f"registry entry {model_id!r} must be an object")
            rel_path = str(raw.get("path", ""))
            if not rel_path:
                raise RegistryError(f"registry entry {model_id!r} has no path")
            candidate = (root / rel_path).resolve()
            if candidate != root and root not in candidate.parents:
                raise RegistryError(f"registry entry {model_id!r} escapes MODEL_ROOT")
            required = raw.get("required_files", [])
            if not isinstance(required, list) or not all(isinstance(x, str) for x in required):
                raise RegistryError(f"registry entry {model_id!r} required_files must be strings")
            kind = str(raw.get("kind", model_id.split(".", 1)[0])).lower()
            if kind not in {"asr", "ocr", "llm", "vad", "speaker"}:
                raise RegistryError(f"registry entry {model_id!r} has invalid kind {kind!r}")
            specs[model_id] = ModelSpec(
                model_id=model_id,
                kind=kind,
                backend=str(raw.get("backend", "")),
                path=rel_path,
                architecture=str(raw.get("architecture", "unknown")),
                required_files=tuple(required),
                device=str(raw.get("device", "cpu")),
                context=int(raw.get("context", 0)),
                memory_mb=max(0, int(raw.get("memory_mb", 0))),
                capabilities=tuple(str(x) for x in raw.get("capabilities", [])),
            )
        return cls(specs, root)

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._specs[model_id]
        except KeyError as exc:
            raise RegistryError(f"Unknown model id: {model_id}") from exc

    def default_for(self, kind: str) -> ModelSpec:
        preferred = f"{kind}.default"
        if preferred in self._specs:
            return self._specs[preferred]
        for spec in self._specs.values():
            if spec.kind == kind:
                return spec
        raise RegistryError(f"No model registered for kind {kind!r}")

    def list(self) -> list[ModelSpec]:
        return list(self._specs.values())

    def with_backend_overrides(self, overrides: dict[str, str | None]) -> "ModelRegistry":
        specs = dict(self._specs)
        for kind, backend in overrides.items():
            if not backend:
                continue
            model_id = f"{kind}.default"
            if model_id in specs:
                specs[model_id] = replace(specs[model_id], backend=backend)
        return ModelRegistry(specs, self.model_root)

    def installation_status(self, model_id: str) -> InstallationStatus:
        spec = self.get(model_id)
        model_dir = (self.model_root / spec.path).resolve()
        missing = [model_dir / name for name in spec.required_files if not (model_dir / name).is_file()]
        return InstallationStatus(installed=not missing, model_dir=model_dir, missing_files=missing)

    def capabilities(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for spec in self._specs.values():
            status = self.installation_status(spec.model_id)
            result[spec.model_id] = {
                "kind": spec.kind,
                "backend": spec.backend,
                "architecture": spec.architecture,
                "device": spec.device,
                "context": spec.context,
                "memory_mb": spec.memory_mb,
                "capabilities": list(spec.capabilities),
                "installed": status.installed,
                "missing_files": [str(p) for p in status.missing_files],
            }
        return result
