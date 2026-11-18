"""Redacción de datos sensibles horneada en una copia de la fuente.

Se aplica con FFmpeg sobre una **copia**; el original nunca se modifica. Al
hornear la redacción en la fuente se evita depender de que el editor soporte
desenfoque por región y se conservan las marcas de tiempo de origen.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from .ingest import sha256_file
from .plan import validate


def _even(value: float) -> int:
    number = max(2, int(round(value)))
    return number - (number % 2)


def _frame_size(source: Path) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(source)],
        capture_output=True, text=True, check=True,
    )
    width, height = result.stdout.strip().split("x")
    return int(width), int(height)


def _window(item: dict[str, Any], fps: float) -> tuple[float, float]:
    start = float(item["source_in"]) / fps
    end = float(item["source_out"]) / fps
    return (start, end) if end >= start else (end, start)


def apply_box_redactions(
    source: Path,
    redactions: list[dict[str, Any]],
    output: Path,
    *,
    fps: float = 30.0,
    blur: int = 18,
    crf: int = 20,
    preset: str = "medium",
) -> Path:
    """Desenfoca las cajas indicadas durante sus ventanas temporales."""
    boxes: list[tuple[float, float, dict[str, float]]] = []
    for item in redactions:
        start, end = _window(item, fps)
        for box in item.get("boxes", []):
            boxes.append((start, end, box))
    if not boxes:
        raise ValueError("no hay cajas que redactar")

    parts: list[str] = []
    frame_width, frame_height = _frame_size(source)
    last = "0:v"
    for index, (start, end, box) in enumerate(boxes):
        x = _even(box["x"] * frame_width)
        y = _even(box["y"] * frame_height)
        w = _even(min(box["width"], 1.0 - box["x"]) * frame_width)
        h = _even(min(box["height"], 1.0 - box["y"]) * frame_height)
        w = min(w, frame_width - x)
        h = min(h, frame_height - y)
        parts.append(f"[{last}]crop=w={w}:h={h}:x={x}:y={y},gblur=sigma={blur}[b{index}]")
        parts.append(
            f"[{last}][b{index}]overlay={x}:{y}:enable='between(t,{start:.3f},{end:.3f})'[v{index}]"
        )
        last = f"v{index}"
    graph = ";".join(parts)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-filter_complex", graph, "-map", f"[{last}]", "-map", "0:a?",
         "-c:v", "libx264", "-crf", str(crf), "-preset", preset, "-pix_fmt", "yuv420p",
         "-c:a", "copy", str(output)],
        check=True,
    )
    return output


def bake_redactions(
    plan: dict[str, Any],
    root: Path,
    out_dir: Path,
    *,
    fps: float | None = None,
    blur: int = 18,
    preset: str = "medium",
) -> dict[str, Any]:
    """Devuelve una copia del plan con las fuentes redactadas y sin `redactions`.

    Crea un archivo nuevo por fuente afectada, actualiza su `path_rel` y su
    `sha256`, y libera la lista `edits.redactions` (ya está aplicada).
    """
    import copy

    fps = float(fps or plan["timebase"]["fps"])
    baked = copy.deepcopy(plan)
    by_source: dict[str, list[dict[str, Any]]] = {}
    for redaction in baked.get("edits", {}).get("redactions", []):
        by_source.setdefault(redaction["source"], []).append(redaction)
    if not by_source:
        return baked

    out_dir.mkdir(parents=True, exist_ok=True)
    for source in baked["sources"]:
        items = by_source.get(source["id"])
        if not items:
            continue
        original = (root / source["path_rel"]).resolve()
        if not original.is_file():
            raise FileNotFoundError(original)
        previous = source["path_rel"]
        target = (out_dir / f"{original.stem}-redacted{original.suffix}").resolve()
        apply_box_redactions(original, items, target, fps=fps, blur=blur, preset=preset)
        source["path_rel"] = str(target.relative_to(root.resolve()))
        source["sha256"] = sha256_file(target)
        source["redacted_from"] = previous

    baked["edits"]["redactions"] = []
    baked.setdefault("provenance", {})["redactions_baked"] = True
    report = validate(baked)
    if report["errors"]:
        raise ValueError("plan inválido tras hornear redacciones: " + "; ".join(report["errors"]))
    return baked


def plan_digest(plan: dict[str, Any]) -> str:
    import json

    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
