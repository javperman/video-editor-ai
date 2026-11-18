"""Construcción de un edit_plan.json a partir del análisis local."""

from __future__ import annotations

from typing import Any

from .plan import validate

CATEGORY = {"silence": "silence", "filler": "filler", "repetition": "repetition"}


def _plan_source(source: dict[str, Any], duration_frames: int) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": source["id"],
        "sha256": source["sha256"],
        "path_rel": source["path_rel"],
        "kind": source["kind"],
        "role": source.get("role"),
        "duration_frames": duration_frames,
        "read_only": True,
    }
    if source.get("width"):
        entry["width"] = int(source["width"])
    if source.get("height"):
        entry["height"] = int(source["height"])
    return entry

ROLE_TRACK = {
    "screen": ("V1", "video"),
    "phone_cam": ("V2", "video"),
    "webcam": ("V2", "video"),
    "voice": ("A1", "audio"),
    "music": ("A2", "audio"),
}


def candidate_to_cut(candidate: dict[str, Any], source_id: str, targets: list[str], index: int) -> dict[str, Any]:
    return {
        "id": f"cut-{index:04d}",
        "source": source_id,
        "targets": targets,
        "source_in": int(candidate.get("start_frame", 0)),
        "source_out": int(candidate.get("end_frame", 0)),
        "reason": candidate.get("reason", ""),
        "category": CATEGORY.get(candidate.get("kind"), "other"),
        "evidence_refs": candidate.get("evidence", []),
        "context_before": candidate.get("context_before", ""),
        "context_after": candidate.get("context_after", ""),
        "confidence": float(candidate.get("confidence", 0.5)),
        "risk": candidate.get("risk", "human_review"),
        "affects_meaning": bool(candidate.get("affects_meaning", False)),
        "approval": candidate.get("approval", "pending"),
    }


def build_plan(
    project_id: str,
    sources: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    fps: float = 30.0,
    width: int = 1920,
    height: int = 1080,
    primary_source: str | None = None,
    redactions: list[dict[str, Any]] | None = None,
    zooms: list[dict[str, Any]] | None = None,
    subtitles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tracks: dict[str, dict[str, Any]] = {}
    normalized_durations: dict[str, int] = {}
    for source in sources:
        # Todos los frames del plan van en el fps base. Si la fuente trae su
        # propia duración en segundos, se recalcula; si no, se respeta.
        duration_frames = int(source["duration_frames"])
        if source.get("duration_seconds"):
            duration_frames = int(round(float(source["duration_seconds"]) * fps))
        normalized_durations[source["id"]] = duration_frames
        role = source.get("role") or ("screen" if source["kind"] == "video" else "voice")
        alias, kind = ROLE_TRACK.get(role, ("V1" if source["kind"] == "video" else "A1", source["kind"] if source["kind"] == "audio" else "video"))
        track = tracks.setdefault(alias, {"id": alias, "kind": kind, "role": role, "items": []})
        track["items"].append({
            "id": f"{source['id']}-full",
            "source": source["id"],
            "source_in": 0,
            "source_out": duration_frames,
            "timeline_in": 0,
            "duration_frames": duration_frames,
        })
    primary = primary_source or next((source["id"] for source in sources if source["kind"] == "video"), sources[0]["id"])
    targets = [source["id"] for source in sources]
    cuts = [candidate_to_cut(candidate, primary, targets, index) for index, candidate in enumerate(candidates)]
    plan = {
        "schema_version": "1.0.0",
        "project_id": project_id,
        "revision": 1,
        "parent_revision": None,
        "timebase": {"fps": fps, "width": width, "height": height},
        "intent": {"goal": "Tutorial técnico", "language": "es"},
        "sources": [_plan_source(source, normalized_durations[source["id"]]) for source in sources],
        "timeline": {"tracks": list(tracks.values())},
        "edits": {"cuts": cuts, "layouts": [], "zooms": zooms or [], "annotations": [],
                  "subtitles": subtitles or [], "redactions": redactions or []},
        "audio": {"normalization": {"target_lufs": -16, "true_peak_db": -1.5}, "music": [], "ducking": {}},
        "render": {"codec": "h264", "container": "mp4", "resolution": "1080p", "fps": fps},
        "qc": {},
        "provenance": {"built_by": "plan_builder"},
        "approvals": [],
    }
    report = validate(plan)
    if report["errors"]:
        raise ValueError("plan generado inválido: " + "; ".join(report["errors"]))
    return plan
