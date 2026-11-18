"""Zooms a partir de las paradas del cursor.

El cursor se graba en captura (ver `scripts/record_cursor.sh`); aquí se convierte
cada parada en un zoom del plan, mapeando el tiempo de origen a la timeline.
"""

from __future__ import annotations

import copy
from typing import Any

from .compile import compile_timeline
from .subtitles import map_source_frame, timeline_segments


def zooms_from_dwells(
    plan: dict[str, Any],
    dwells: list[dict[str, Any]],
    source_id: str,
    *,
    magnification: float = 1.6,
    lead_frames: int = 6,
    tail_frames: int = 18,
    fps: float | None = None,
) -> list[dict[str, Any]]:
    """Convierte paradas de cursor (`x`,`y` normalizados, frames) en zooms.

    Un zoom necesita un `target` (item de la timeline) y una posición en la
    timeline; ambos se deducen del segmento compilado de la fuente.
    """
    fps = float(fps or plan["timebase"]["fps"])
    compiled = compile_timeline(plan)
    compiled_segments = timeline_segments(plan, source_id)
    zooms: list[dict[str, Any]] = []
    for index, dwell in enumerate(dwells, start=1):
        source_start = int(dwell.get("start_frame", round(float(dwell["start"]) * fps)))
        source_end = int(dwell.get("end_frame", round(float(dwell["end"]) * fps)))
        timeline_in = map_source_frame(compiled_segments, source_start)
        if timeline_in is None:
            continue
        timeline_out = map_source_frame(compiled_segments, max(source_start, source_end - 1))
        if timeline_out is None:
            timeline_out = timeline_in
        timeline_in = max(0, timeline_in - lead_frames)
        duration = max(1, (timeline_out + tail_frames) - timeline_in)
        zooms.append({
            "id": f"zoom-{index:04d}",
            "target": _target_item(compiled, source_id, source_start),
            "timeline_in": timeline_in,
            "duration_frames": duration,
            "center_x": round(float(dwell.get("x", 0.5)), 4),
            "center_y": round(float(dwell.get("y", 0.5)), 4),
            "magnification": magnification,
        })
    return zooms


def _target_item(compiled: dict[str, Any], source_id: str, source_frame: int) -> str:
    for track in compiled.get("timeline", {}).get("tracks", []):
        for item in track.get("items", []):
            if item["source"] != source_id:
                continue
            start = int(item.get("source_in", 0))
            end = int(item.get("source_out", start + int(item.get("duration_frames", 0))))
            if start <= source_frame < end:
                return item["id"]
    return f"{source_id}-full"


def attach_zooms(plan: dict[str, Any], zooms: list[dict[str, Any]]) -> dict[str, Any]:
    result = copy.deepcopy(plan)
    result.setdefault("edits", {}).setdefault("zooms", [])
    result["edits"]["zooms"].extend(zooms)
    from .plan import validate

    report = validate(result)
    if report["errors"]:
        raise ValueError("plan inválido con zooms: " + "; ".join(report["errors"]))
    return result
