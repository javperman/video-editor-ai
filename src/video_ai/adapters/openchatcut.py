"""Adaptador edit_plan.json → operaciones MCP de OpenChatCut."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..compile import compile_timeline
from ..occ_client import OccClient


def expected_duration(plan: dict[str, Any]) -> int:
    compiled = compile_timeline(plan)
    end = 0
    for track in compiled.get("timeline", {}).get("tracks", []):
        for item in track.get("items", []):
            end = max(end, int(item["timeline_in"]) + int(item["duration_frames"]))
    return end


def apply_plan(
    client: OccClient,
    plan: dict[str, Any],
    workspace_root: Path,
    *,
    project_id: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    compiled = compile_timeline(plan)
    timebase = plan["timebase"]
    if project_id:
        client.call("target_project", {"projectId": project_id})
    else:
        created = client.call("create_project", {
            "name": project_name or plan["project_id"],
            "compositionWidth": int(timebase["width"]),
            "compositionHeight": int(timebase["height"]),
            "fps": float(timebase["fps"]),
            "description": f"edit_plan revision {plan.get('revision')}",
        })
        project_id = created["id"]
        client.call("target_project", {"projectId": project_id})

    session = client.call("begin_edit_session", {
        "clientName": "video-editor-ai", "approvalMode": "auto", "editorProjectId": project_id,
    })
    edit_session_id = session["editSessionId"]
    applied = False
    try:
        source_paths = []
        for source in plan["sources"]:
            path = (workspace_root / source["path_rel"]).resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            source_paths.append(str(path))
        imported = client.call("import_assets", {"editSessionId": edit_session_id, "paths": source_paths})
        assets = {asset["name"]: asset for asset in imported.get("imported", [])}

        timeline = client.call("read_timeline", {"editSessionId": edit_session_id})
        existing = {track["alias"] for track in timeline.get("tracks", [])}
        for track in compiled["timeline"]["tracks"]:
            alias = track["id"]
            if alias in existing:
                continue
            kind = "audio" if track["kind"] == "audio" else "video"
            client.call("edit_track", {
                "action": "create", "json": f'{{"trackType":"{kind}","name":"{alias}"}}',
                "editSessionId": edit_session_id, "editorProjectId": project_id,
            })

        adds = []
        for track in compiled["timeline"]["tracks"]:
            for item in track.get("items", []):
                source = next(source for source in plan["sources"] if source["id"] == item["source"])
                asset = assets.get(Path(source["path_rel"]).name)
                if asset is None:
                    raise RuntimeError(f"asset no importado: {source['path_rel']}")
                adds.append({
                    "type": asset["kind"],
                    "assetId": asset["id"],
                    "track": track["id"],
                    "fromFrame": int(item["timeline_in"]),
                    "durationInFrames": int(item["duration_frames"]),
                })
        if adds:
            result = client.call("edit_item", {"editSessionId": edit_session_id, "adds": adds})
            if result.get("ok") is False or result.get("outcome") == "failed":
                raise RuntimeError(f"edit_item falló: {result}")
        review = client.call("review_edit_session", {
            "editSessionId": edit_session_id, "editorProjectId": project_id,
            "summary": f"edit_plan {plan['project_id']} r{plan.get('revision')}",
        })
        applied = review.get("status") == "applied"
        if not applied:
            raise RuntimeError(f"review no aplicado: {review}")
        return {
            "project_id": project_id,
            "edit_session_id": edit_session_id,
            "tracks": [track["id"] for track in compiled["timeline"]["tracks"]],
            "clips": len(adds),
            "expected_duration_frames": expected_duration(plan),
            "applied": True,
        }
    finally:
        if not applied:
            try:
                client.call("discard_edit_session", {"editSessionId": edit_session_id, "editorProjectId": project_id})
            except Exception:  # noqa: BLE001
                pass
