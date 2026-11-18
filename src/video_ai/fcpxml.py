"""Exportación a FCPXML desde el `edit_plan.json`.

Genera un documento FCPXML 1.9 con los recursos y una secuencia por pista de
vídeo. Es un formato de intercambio: permite abrir el proyecto en
DaVinci Resolve, Final Cut o Kdenlive (import parcial) sin depender del editor.

Los `timeline_items` se toman de la timeline **compilada** (con los cortes ya
aplicados), de modo que el intercambio conserva las decisiones del plan.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.dom import minidom

from .compile import compile_timeline


def _frame_duration(frames: int, fps: float) -> str:
    denominator = int(round(fps))
    return f"{int(frames)}/{denominator}s"


def _format_name(width: int, height: int, fps: float) -> str:
    return f"FFVideoFormat{height}p{int(round(fps))}"


def build_fcpxml(plan: dict[str, Any], root: Path) -> str:
    compiled = compile_timeline(plan)
    timebase = plan["timebase"]
    fps = float(timebase["fps"])
    width = int(timebase["width"])
    height = int(timebase["height"])

    fcpxml = ET.Element("fcpxml", {"version": "1.9"})
    resources = ET.SubElement(fcpxml, "resources")
    ET.SubElement(resources, "format", {
        "id": "r1", "name": _format_name(width, height, fps),
        "frameDuration": _frame_duration(1, fps), "width": str(width), "height": str(height),
    })

    asset_ids: dict[str, str] = {}
    for index, source in enumerate(plan.get("sources", []), start=1):
        asset_id = f"a{index}"
        asset_ids[source["id"]] = asset_id
        path = (root / source["path_rel"]).resolve()
        attributes = {
            "id": asset_id,
            "name": Path(source["path_rel"]).name,
            "src": path.as_uri(),
            "duration": _frame_duration(int(source["duration_frames"]), fps),
        }
        if source.get("kind") == "video":
            attributes["hasVideo"] = "1"
        if source.get("kind") in {"video", "audio"}:
            attributes["hasAudio"] = "1" if source.get("kind") == "audio" or source.get("audio_codec") else "0"
        if source.get("kind") == "audio":
            attributes["hasVideo"] = "0"
        ET.SubElement(resources, "asset", attributes)

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", {"name": plan.get("project_id", "video-editor-ai")})
    project = ET.SubElement(event, "project", {"name": plan.get("project_id", "video-editor-ai")})

    total_frames = 0
    for track in compiled.get("timeline", {}).get("tracks", []):
        for item in track.get("items", []):
            total_frames = max(total_frames, int(item["timeline_in"]) + int(item["duration_frames"]))

    sequence = ET.SubElement(project, "sequence", {
        "format": "r1", "duration": _frame_duration(total_frames, fps),
        "tcStart": "0s", "tcFormat": "NDF",
    })
    spine = ET.SubElement(sequence, "spine")

    # Pistas de vídeo: una por `lane` (la primera pista es la base).
    video_tracks = [track for track in compiled.get("timeline", {}).get("tracks", [])
                    if track["kind"] in {"video", "overlay"}]
    for lane, track in enumerate(video_tracks):
        for item in track.get("items", []):
            attributes = {
                "ref": asset_ids[item["source"]],
                "offset": _frame_duration(int(item["timeline_in"]), fps),
                "duration": _frame_duration(int(item["duration_frames"]), fps),
                "start": _frame_duration(int(item.get("source_in", 0)), fps),
                "name": item["id"],
            }
            if lane:
                attributes["lane"] = str(-lane)
            ET.SubElement(spine, "asset-clip", attributes)

    # Audio: como elementos `audio` con offset/duracion.
    for track in compiled.get("timeline", {}).get("tracks", []):
        if track["kind"] != "audio":
            continue
        for item in track.get("items", []):
            ET.SubElement(spine, "audio", {
                "ref": asset_ids[item["source"]],
                "offset": _frame_duration(int(item["timeline_in"]), fps),
                "duration": _frame_duration(int(item["duration_frames"]), fps),
                "start": _frame_duration(int(item.get("source_in", 0)), fps),
                "lane": "1",
            })

    rough = ET.tostring(fcpxml, encoding="utf-8")
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def write_fcpxml(plan: dict[str, Any], root: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_fcpxml(plan, root), encoding="utf-8")
    return output
