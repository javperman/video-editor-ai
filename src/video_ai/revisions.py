"""Revisiones inmutables de edit_plan y aplicación de JSON Patch."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import jsonpatch  # type: ignore

from .plan import validate


def canon(plan: dict[str, Any]) -> str:
    return json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_plan(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canon(plan).encode("utf-8")).hexdigest()


class RevisionStore:
    """Guarda cada revisión como archivo inmutable y mantiene un puntero current."""

    def __init__(self, project_dir: Path, validate_root: Path | None = None) -> None:
        self.project_dir = project_dir
        self.validate_root = validate_root
        self.revisions_dir = project_dir / "revisions"
        self.revisions_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, revision: int) -> Path:
        return self.revisions_dir / f"edit_plan.r{revision:04d}.json"

    def save(self, plan: dict[str, Any]) -> Path:
        path = self.path_for(int(plan["revision"]))
        if path.exists():
            raise FileExistsError(f"la revisión {plan['revision']} ya existe: {path}")
        payload = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.revisions_dir, delete=False) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        os.replace(temporary, path)
        self._write_current(plan)
        return path

    def load(self, revision: int) -> dict[str, Any]:
        return json.loads(self.path_for(revision).read_text(encoding="utf-8"))

    def current_revision(self) -> int | None:
        pointer = self.project_dir / "current"
        if not pointer.is_file():
            return None
        return int(pointer.read_text(encoding="utf-8").strip())

    def current(self) -> dict[str, Any] | None:
        revision = self.current_revision()
        return self.load(revision) if revision is not None else None

    def _write_current(self, plan: dict[str, Any]) -> None:
        pointer = self.project_dir / "current"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.project_dir, delete=False) as handle:
            handle.write(f"{int(plan['revision'])}\n")
            temporary = Path(handle.name)
        os.replace(temporary, pointer)

    def apply_patch(self, operations: list[dict[str, Any]], base_revision: int | None = None,
                    transform: "Callable[[dict[str, Any]], dict[str, Any]] | None" = None) -> dict[str, Any]:
        current = self.current()
        if current is None:
            raise ValueError("no hay revisión actual")
        if base_revision is not None and int(current["revision"]) != base_revision:
            raise ValueError(
                f"conflicto de revisión: esperada {base_revision}, actual {current['revision']}"
            )
        patched = jsonpatch.apply_patch(current, operations)
        if transform is not None:
            # Permite derivar campos dependientes (p. ej. recalcular subtítulos
            # cuando los cortes cambian la timeline) antes de validar y guardar.
            patched = transform(patched)
        patched["parent_revision"] = int(current["revision"])
        patched["revision"] = int(current["revision"]) + 1
        patched["created_at"] = datetime.now(timezone.utc).isoformat()
        report = validate(patched, self.validate_root)
        if report["errors"]:
            raise ValueError("plan inválido tras el patch: " + "; ".join(report["errors"]))
        self.save(patched)
        return patched
