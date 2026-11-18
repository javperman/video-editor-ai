"""Validación estructural y semántica de edit_plan.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schemas" / "edit-plan.schema.json"


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def structural_errors(plan: dict[str, Any]) -> list[str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return ["falta la dependencia jsonschema: instala con `python3 -m pip install jsonschema`"]
    validator = jsonschema.Draft202012Validator(load_schema())
    return [f"{'/'.join(str(p) for p in error.path)}: {error.message}" for error in validator.iter_errors(plan)]


def _unique(errors: list[str], ids: list[str], label: str) -> None:
    seen: set[str] = set()
    for item_id in ids:
        if item_id in seen:
            errors.append(f"{label}: id duplicado {item_id}")
        seen.add(item_id)


def semantic_errors(plan: dict[str, Any], root: Path | None = None) -> list[str]:
    errors: list[str] = []
    sources = {source["id"]: source for source in plan.get("sources", [])}
    _unique(errors, list(sources), "sources")

    timebase = plan.get("timebase", {})
    fps = timebase.get("fps", 0)
    if not isinstance(fps, (int, float)) or fps <= 0:
        errors.append("timebase.fps debe ser mayor que cero")

    track_ids: list[str] = []
    item_ids: list[str] = []
    for track in plan.get("timeline", {}).get("tracks", []):
        track_ids.append(track["id"])
        for item in track.get("items", []):
            item_ids.append(item["id"])
            source_id = item["source"]
            if source_id not in sources:
                errors.append(f"item {item['id']}: source {source_id} no existe")
            source_in = item.get("source_in")
            source_out = item.get("source_out")
            if source_in is not None and source_out is not None and source_out <= source_in:
                errors.append(f"item {item['id']}: source_out debe ser mayor que source_in")
            for field in ("timeline_in", "source_in"):
                if item.get(field) is not None and item[field] < 0:
                    errors.append(f"item {item['id']}: {field} negativo")
            transform = item.get("transform") or {}
            for key in ("x", "y", "scale", "rotation", "opacity"):
                if key in transform and not isinstance(transform[key], (int, float)):
                    errors.append(f"item {item['id']}: transform.{key} no numérico")
    _unique(errors, track_ids, "tracks")
    _unique(errors, item_ids, "items")

    edits = plan.get("edits", {})
    cut_ids: list[str] = []
    for cut in edits.get("cuts", []):
        cut_ids.append(cut["id"])
        if cut["source"] not in sources:
            errors.append(f"cut {cut['id']}: source {cut['source']} no existe")
        if cut["source_out"] <= cut["source_in"]:
            errors.append(f"cut {cut['id']}: source_out debe ser mayor que source_in")
        if cut.get("risk") == "human_review" and cut.get("approval") == "not_required":
            errors.append(f"cut {cut['id']}: riesgo human_review no puede ser not_required")
        if cut.get("affects_meaning") and cut.get("risk") != "human_review" and \
                cut.get("approval") not in {"approved", "rejected"}:
            # Un corte automático/conservador que afecta al significado se aplicaría
            # sin aprobación: eso sí es un error. Como propuesta (human_review,
            # pendiente) está permitido y el compilador no lo aplica.
            errors.append(f"cut {cut['id']}: afecta al significado y no está aprobado")
    _unique(errors, cut_ids, "cuts")

    subtitle_ids: list[str] = []
    for subtitle in edits.get("subtitles", []):
        subtitle_ids.append(subtitle["id"])
        if subtitle["timeline_out"] <= subtitle["timeline_in"]:
            errors.append(f"subtitle {subtitle['id']}: timeline_out debe ser mayor que timeline_in")
    _unique(errors, subtitle_ids, "subtitles")

    for redaction in edits.get("redactions", []):
        if redaction["source"] not in sources:
            errors.append(f"redaction {redaction['id']}: source no existe")
        if redaction["source_out"] <= redaction["source_in"]:
            errors.append(f"redaction {redaction['id']}: source_out debe ser mayor que source_in")
        for box in redaction.get("boxes", []):
            if box["x"] + box["width"] > 1.0 or box["y"] + box["height"] > 1.0:
                errors.append(f"redaction {redaction['id']}: caja fuera del fotograma")

    for zoom in edits.get("zooms", []):
        for key in ("center_x", "center_y"):
            value = zoom.get(key)
            if value is not None and not 0 <= value <= 1:
                errors.append(f"zoom {zoom['id']}: {key} fuera de 0..1")

    if root is not None:
        for source in sources.values():
            candidate = (root / source["path_rel"]).resolve()
            if root.resolve() not in candidate.parents and candidate != root.resolve():
                errors.append(f"source {source['id']}: ruta fuera del workspace")
            elif not candidate.is_file():
                errors.append(f"source {source['id']}: no existe {candidate}")
    return errors


def validate(plan: dict[str, Any], root: Path | None = None) -> dict[str, list[str]]:
    errors = structural_errors(plan)
    if not errors:
        errors = semantic_errors(plan, root)
    return {"errors": errors, "warnings": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida un edit_plan.json")
    parser.add_argument("plan", type=Path)
    parser.add_argument("--root", type=Path, default=None, help="Raíz para resolver path_rel")
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    report = validate(plan, args.root)
    if report["errors"]:
        for error in report["errors"]:
            print(f"ERROR {error}", file=sys.stderr)
        return 1
    print("plan OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
