"""Entrega final y bucle de edición: render → master → subtítulos → QC.

Centraliza lo que antes estaba duplicado en `scripts/run_project.py`, para poder
re-renderizar tras una edición (`video-ai apply … --render`) con las mismas
garantías.

Al aplicar una instrucción que cambia los cortes, la timeline se desplaza y los
subtítulos guardados (`edits.subtitles`, en frames de timeline) quedan obsoletos;
por eso `refresh_subtitles` los recalcula desde la transcripción antes de guardar.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .compile import compile_timeline
from .master_audio import normalize_audio
from .music import duck_music
from .qc import qc_video
from .render import render_plan
from .subtitles import burn_subtitles, cues_to_plan_subtitles, plan_subtitles_to_cues, segment_words, write_srt


def timeline_frames(plan: dict[str, Any]) -> int:
    compiled = compile_timeline(plan)
    total = 0
    for track in compiled["timeline"]["tracks"]:
        for item in track["items"]:
            total = max(total, int(item["timeline_in"]) + int(item["duration_frames"]))
    return total


def subtitle_source_id(plan: dict[str, Any]) -> str:
    for source in plan.get("sources", []):
        if source.get("role") == "voice":
            return source["id"]
    for source in plan.get("sources", []):
        if source.get("kind") == "video":
            return source["id"]
    return plan["sources"][0]["id"]


def refresh_subtitles(plan: dict[str, Any], work: Path) -> dict[str, Any]:
    """Recalcula `edits.subtitles` desde `work/transcript.json` si existe.

    Devuelve el mismo plan (modificado). Si no hay transcripción, no toca nada.
    """
    transcript = Path(work) / "transcript.json"
    if not transcript.is_file():
        return plan
    data = json.loads(transcript.read_text(encoding="utf-8"))
    words = data.get("words") if isinstance(data, dict) else None
    if not words:
        return plan
    fps = float(plan["timebase"]["fps"])
    style = next((s.get("style") for s in plan.get("edits", {}).get("subtitles", [])
                  if s.get("style")), "tutorial")
    cues = segment_words(words)
    plan.setdefault("edits", {})["subtitles"] = cues_to_plan_subtitles(
        cues, plan, subtitle_source_id(plan), fps=fps, style=style)
    return plan


def write_timeline_srt(plan: dict[str, Any], work: Path) -> Path:
    fps = float(plan["timebase"]["fps"])
    cues = plan_subtitles_to_cues(plan.get("edits", {}).get("subtitles", []), fps)
    return write_srt(cues, Path(work) / "subtitles.timeline.srt")


def deliver(
    plan: dict[str, Any],
    root: Path,
    work: Path,
    *,
    encoder: str = "h264_nvenc",
    quality: int = 21,
    music: str | Path | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Renderiza, masteriza, quema subtítulos y pasa QC. Devuelve el informe."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    fps = float(plan["timebase"]["fps"])
    width = int(plan["timebase"]["width"])
    height = int(plan["timebase"]["height"])
    expected = round(timeline_frames(plan) / fps, 3)

    cues = plan_subtitles_to_cues(plan.get("edits", {}).get("subtitles", []), fps)
    srt = write_srt(cues, work / "subtitles.timeline.srt")
    subtitle_style = next((s.get("style") for s in plan.get("edits", {}).get("subtitles", [])
                           if s.get("style")), "tutorial")

    raw = render_plan(plan, Path(root), work / "render-raw.mp4", encoder=encoder,
                      quality=quality, source_id=source_id)
    normalization = plan.get("audio", {}).get("normalization", {}) or {}
    mastered = normalize_audio(raw, work / "render-master.mp4",
                               target_lufs=float(normalization.get("target_lufs", -16.0)),
                               true_peak=float(normalization.get("true_peak_db", -1.5)))
    mixed = mastered
    if music:
        mixed = duck_music(mastered, Path(music), work / "render-music.mp4")
    final = work / "render-final.mp4"
    burn_subtitles(mixed, final, cues, width=width, height=height, style=subtitle_style,
                   encoder=encoder, quality=quality)

    qc = qc_video(final, expected={"width": width, "height": height, "fps": fps,
                                   "duration": expected})
    return {
        "renderer": encoder,
        "video": str(final),
        "srt": str(srt),
        "expected_seconds": expected,
        "qc_ok": qc["ok"],
        "qc_failed": [c["name"] for c in qc["checks"] if c["critical"] and not c["ok"]],
    }


def load_words(work: Path) -> list[dict[str, Any]]:
    transcript = Path(work) / "transcript.json"
    if not transcript.is_file():
        return []
    data = json.loads(transcript.read_text(encoding="utf-8"))
    return data.get("words", []) if isinstance(data, dict) else []


def ops_disable_subtitles(ops: list[dict[str, Any]]) -> bool:
    """True si las operaciones dejan `edits.subtitles` vacío a propósito."""
    for op in ops:
        if op.get("op") in {"replace", "add"} and op.get("path") == "/edits/subtitles" \
                and op.get("value") in ([], {}):
            return True
    return False


def apply_ops_and_deliver(
    store,
    ops: list[dict[str, Any]],
    work: Path,
    root: Path,
    *,
    encoder: str = "h264_nvenc",
    music: str | Path | None = None,
    render: bool = True,
    quality: int = 21,
    refresh: bool | None = None,
) -> dict[str, Any]:
    """Aplica operaciones JSON Patch explícitas (nueva revisión) y re-renderiza.

    Es la puerta de entrada para que un agente/LLM proponga ediciones fuera del
    catálogo de frases: mismas garantías (validación, revisión inmutable, render).
    """
    if refresh is None:
        refresh = not ops_disable_subtitles(ops)
    transform = (lambda plan: refresh_subtitles(plan, work)) if refresh else None
    patched = store.apply_patch(ops, transform=transform)
    result: dict[str, Any] = {
        "revision": int(patched["revision"]),
        "parent_revision": int(patched["parent_revision"]),
    }
    if render:
        result["render"] = deliver(patched, Path(root), Path(work), encoder=encoder,
                                   music=music, quality=quality)
    return result


def apply_and_deliver(
    store,
    instruction: str,
    work: Path,
    root: Path,
    *,
    encoder: str = "h264_nvenc",
    music: str | Path | None = None,
    render: bool = True,
    quality: int = 21,
) -> dict[str, Any]:
    """Aplica una instrucción (nueva revisión) y, opcionalmente, re-renderiza.

    Al guardar, recalcula los subtítulos sobre la timeline resultante.
    """
    from .commands import parse_instruction

    current = store.current()
    if current is None:
        raise ValueError("no hay revisión actual")
    intent = parse_instruction(instruction, current, load_words(work))
    result: dict[str, Any] = {"instruction": instruction, "intent": intent.as_dict()}
    result.update(apply_ops_and_deliver(
        store, intent.ops, work, root, encoder=encoder, music=music, render=render,
        quality=quality, refresh=intent.action != "subtitles_off"))
    return result
