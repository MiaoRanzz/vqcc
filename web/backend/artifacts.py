"""Explicit small-report registry for the private console."""
from __future__ import annotations

import hashlib
from pathlib import Path

from automation.runner import redact


class ArtifactRegistry:
    def __init__(self, storage: Path, max_bytes: int = 4 * 1024 * 1024):
        self.storage = Path(storage).resolve()
        self.max_bytes = max_bytes
        self._paths: dict[str, Path] = {}

    def _checked(self, path: Path) -> Path:
        path = Path(path)
        resolved = path.resolve()
        if not resolved.is_relative_to(self.storage):
            raise ValueError("Report is outside the artifact store")
        relative = resolved.relative_to(self.storage)
        if not relative.parts or relative.parts[0] not in {"experiments", "runs", "research"}:
            raise ValueError("Not a report directory")
        if path.is_symlink() or path.suffix not in {".json", ".md", ".txt", ".csv"}:
            raise ValueError("Not a supported report")
        if not resolved.is_file() or resolved.stat().st_size > self.max_bytes:
            raise ValueError("Report is missing or exceeds the inline report limit")
        return resolved

    def register(self, path: Path, name: str | None = None) -> dict:
        resolved = self._checked(path)
        relative = resolved.relative_to(self.storage).as_posix()
        identifier = "report_" + hashlib.sha256(relative.encode()).hexdigest()[:24]
        self._paths[identifier] = resolved
        return {"id": identifier, "name": name or resolved.name,
                "bytes": resolved.stat().st_size, "media_type": "text/plain"}

    def resolve(self, identifier: str) -> Path:
        if identifier not in self._paths:
            # IDs can be bookmarked. Rebuild from the same small-report allowlist after a restart.
            patterns = ("experiments/*/candidate.json", "experiments/*/generation.json",
                        "experiments/*/official*.json", "experiments/*/robustness*.json", "runs/*/report.md")
            for pattern in patterns:
                for path in self.storage.glob(pattern):
                    relative = path.relative_to(self.storage).as_posix()
                    expected = "report_" + hashlib.sha256(relative.encode()).hexdigest()[:24]
                    if expected == identifier:
                        self.register(path)
                        break
                if identifier in self._paths:
                    break
        if identifier not in self._paths:
            raise KeyError(identifier)
        return self._checked(self._paths[identifier])

    def read(self, identifier: str) -> str:
        return redact(self.resolve(identifier).read_text(encoding="utf-8"))
