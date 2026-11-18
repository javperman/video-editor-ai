"""Compilación del plan: convierte decisiones de corte en timeline real."""

from __future__ import annotations

import copy
from typing import Any


def _apply_cuts_to_range(start: int, end: int, cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    segments = [(start, end)]
    for cut_start, cut_end in sorted(cuts):
        next_segments: list[tuple[int, int]] = []
        for seg_start, seg_end in segments:
            if cut_end <= seg_start or cut_start >= seg_end:
                next_segments.append((seg_start, seg_end))
                continue
            if cut_start > seg_start:
                next_segments.append((seg_start, min(cut_start, seg_end)))
            if cut_end < seg_end:
                next_segments.append((max(cut_end, seg_start), seg_end))
        segments = next_segments
    return [(a, b) for a, b in segments if b > a]


def compile_timeline(plan: dict[str, Any], applied_risks: tuple[str, ...] = ("automatic", "conservative")) -> dict[str, Any]:
    """Devuelve una copia con la timeline recortada según los cortes aplicables.

    Solo se aplican cortes cuyo riesgo está en `applied_risks` y cuya aprobación
    no sea `rejected`; `human_review` exige `approval == "approved"`.
    """
    compiled = copy.deepcopy(plan)
    sources = {source["id"]: source for source in plan.get("sources", [])}
    cuts_by_source: dict[str, list[tuple[int, int]]] = {}
    for cut in plan.get("edits", {}).get("cuts", []):
        if cut.get("approval") == "rejected":
            continue
        risk = cut.get("risk")
        if risk == "human_review":
            if cut.get("approval") != "approved":
                continue
        elif risk not in applied_risks:
            continue
        for target in cut.get("targets") or [cut["source"]]:
            cuts_by_source.setdefault(target, []).append((int(cut["source_in"]), int(cut["source_out"])))

    for track in compiled.get("timeline", {}).get("tracks", []):
        new_items = []
        timeline_cursor = 0
        for item in track.get("items", []):
            source = sources.get(item["source"])
            if source is None:
                new_items.append(item)
                continue
            source_in = int(item.get("source_in", 0))
            source_out = int(item.get("source_out", source["duration_frames"]))
            segments = _apply_cuts_to_range(source_in, source_out, cuts_by_source.get(item["source"], []))
            for index, (seg_start, seg_end) in enumerate(segments):
                new_items.append({
                    **item,
                    "id": f"{item['id']}-s{index}",
                    "source_in": seg_start,
                    "source_out": seg_end,
                    "timeline_in": timeline_cursor,
                    "duration_frames": seg_end - seg_start,
                })
                timeline_cursor += seg_end - seg_start
        track["items"] = new_items
    compiled.setdefault("provenance", {})["compiled_from"] = int(plan.get("revision", 1))
    return compiled
