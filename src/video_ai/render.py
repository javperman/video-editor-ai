"""Render local con FFmpeg desde el `edit_plan.json` compilado.

Alternativa al export de OpenChatCut (que usa WebCodecs del navegador por
software). Aquí se concatenan los segmentos conservados de la timeline y se
codifica con **NVENC** cuando está disponible.

Alcance actual: una fuente de vídeo primaria con su audio embebido y subtítulos
opcionales quemados. Los cambios de pista múltiple (PiP), zooms y música se
añadirán cuando su aplicación esté verificada.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .compile import compile_timeline


def available_encoders() -> list[str]:
    result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
    return [line.split()[1] for line in result.stdout.splitlines() if " h264" in line or " hevc" in line]


def _segments(plan: dict[str, Any], source_id: str, track_kind: str) -> list[tuple[int, int]]:
    compiled = compile_timeline(plan)
    for track in compiled["timeline"]["tracks"]:
        if track["kind"] != track_kind:
            continue
        items = [item for item in track["items"] if item["source"] == source_id]
        if not items:
            continue
        items.sort(key=lambda item: int(item["timeline_in"]))
        return [(int(item["source_in"]), int(item["duration_frames"])) for item in items]
    return []


def _has_audio(path: Path) -> bool:
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
                            capture_output=True, text=True)
    return bool(result.stdout.strip())


def _overlay_layer(plan: dict[str, Any], video_source: str) -> tuple[str, dict[str, float]] | None:
    """Primera capa de vídeo con `transform` distinta de la principal (PiP)."""
    for track in plan.get("timeline", {}).get("tracks", []):
        if track.get("kind") not in {"video", "overlay"}:
            continue
        for item in track.get("items", []):
            if item["source"] != video_source and item.get("transform"):
                return item["source"], item["transform"]
    return None


def render_plan(
    plan: dict[str, Any],
    root: Path,
    output: Path,
    *,
    source_id: str | None = None,
    encoder: str = "h264_nvenc",
    quality: int = 21,
    subtitles: Path | None = None,
    pip: bool = True,
) -> Path:
    """Renderiza la timeline compilada a un MP4.

    Soporta vídeo primario, una capa PiP opcional (según el `transform`
    normalizado del plan), audio embebido o de otra fuente y subtítulos.

    `encoder` admite `h264_nvenc`, `libx264`, `hevc_nvenc`, etc. Con NVENC
    `quality` es el CQ; con `libx264` es el CRF.
    """
    fps = float(plan["timebase"]["fps"])
    width = int(plan["timebase"]["width"])
    height = int(plan["timebase"]["height"])
    video_source = source_id or next((s["id"] for s in plan["sources"] if s.get("kind") == "video"), plan["sources"][0]["id"])
    media = (root / next(s["path_rel"] for s in plan["sources"] if s["id"] == video_source)).resolve()
    if not media.is_file():
        raise FileNotFoundError(media)

    video_segments = _segments(plan, video_source, "video")
    if not video_segments:
        raise ValueError("no hay segmentos de vídeo que renderizar")

    inputs = ["-i", str(media)]
    next_input = 1

    overlay = _overlay_layer(plan, video_source) if pip else None
    overlay_input = None
    overlay_segments: list[tuple[int, int]] = []
    transform: dict[str, float] = {}
    if overlay:
        overlay_source, transform = overlay
        overlay_segments = _segments(plan, overlay_source, "video")
        if overlay_segments:
            overlay_media = (root / next(s["path_rel"] for s in plan["sources"] if s["id"] == overlay_source)).resolve()
            if not overlay_media.is_file():
                raise FileNotFoundError(overlay_media)
            inputs += ["-i", str(overlay_media)]
            overlay_input = next_input
            next_input += 1

    audio_source = next((s["id"] for s in plan["sources"]
                         if s.get("kind") == "audio" and _segments(plan, s["id"], "audio")), None)
    if audio_source and audio_source != video_source:
        audio_media = (root / next(s["path_rel"] for s in plan["sources"] if s["id"] == audio_source)).resolve()
        if not audio_media.is_file():
            raise FileNotFoundError(audio_media)
        audio_segments = _segments(plan, audio_source, "audio")
        audio_input = next_input
        audio_path = audio_media
        inputs += ["-i", str(audio_media)]
    else:
        audio_segments = _segments(plan, video_source, "audio") or video_segments
        audio_input = 0
        audio_path = media
    has_audio = _has_audio(audio_path)

    parts: list[str] = []
    for index, (start, duration) in enumerate(video_segments):
        start_s = start / fps
        end_s = (start + duration) / fps
        parts.append(f"[0:v]trim=start={start_s:.6f}:end={end_s:.6f},setpts=PTS-STARTPTS[v{index}]")
    parts.append("".join(f"[v{i}]" for i in range(len(video_segments)))
                 + f"concat=n={len(video_segments)}:v=1:a=0[vcat]")

    last_video = "vcat"
    if overlay_input is not None:
        pip_width = max(2, int(round(width * float(transform.get("scale", 0.3)))))
        pip_width -= pip_width % 2
        x = int(round(float(transform.get("x", 0.0)) * width))
        y = int(round(float(transform.get("y", 0.0)) * height))
        crop = ""
        fit_aspect = transform.get("fit_aspect")
        if fit_aspect:
            # Recorte tipo «cover» a la proporción de caja pedida (alto/ancho),
            # sin deformar. `ow`/`oh` son las dimensiones de salida del crop.
            ta = float(fit_aspect)
            focus = transform.get("focus", "center")
            # Si la fuente es más alta que la caja (móvil vertical), se recorta el
            # alto; si es más ancha, el ancho. `ow`/`oh` = salida del crop.
            w_expr = f"'if(gte(ih/iw,{ta}),iw,ih/{ta})'"
            h_expr = f"'if(gte(ih/iw,{ta}),iw*{ta},ih)'"
            x_expr = "'(iw-ow)/2'"
            y_expr = {"top": "'0'", "bottom": "'ih-oh'"}.get(focus, "'(ih-oh)/2'")
            crop = f"crop=w={w_expr}:h={h_expr}:x={x_expr}:y={y_expr},"
        for index, (start, duration) in enumerate(overlay_segments):
            start_s = start / fps
            end_s = (start + duration) / fps
            parts.append(f"[{overlay_input}:v]trim=start={start_s:.6f}:end={end_s:.6f},"
                         f"setpts=PTS-STARTPTS,{crop}scale={pip_width}:-2[o{index}]")
        parts.append("".join(f"[o{i}]" for i in range(len(overlay_segments)))
                     + f"concat=n={len(overlay_segments)}:v=1:a=0[ocat]")
        parts.append(f"[vcat][ocat]overlay={x}:{y}:eof_action=pass[vpip]")
        last_video = "vpip"

    if has_audio:
        for index, (start, duration) in enumerate(audio_segments):
            start_s = start / fps
            end_s = (start + duration) / fps
            parts.append(f"[{audio_input}:a]atrim=start={start_s:.6f}:end={end_s:.6f},asetpts=PTS-STARTPTS[a{index}]")
        parts.append("".join(f"[a{i}]" for i in range(len(audio_segments)))
                     + f"concat=n={len(audio_segments)}:v=0:a=1[aout]")

    video_map = f"[{last_video}]"
    if subtitles is not None:
        parts.append(f"[{last_video}]subtitles={subtitles}[vsub]")
        video_map = "[vsub]"

    filter_complex = ";".join(parts)
    output.parent.mkdir(parents=True, exist_ok=True)
    if "nvenc" in encoder:
        quality_args = ["-rc", "vbr", "-cq", str(quality), "-b:v", "0"]
    else:
        quality_args = ["-crf", str(quality)]
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
        "-filter_complex", filter_complex, "-map", video_map,
    ]
    if has_audio:
        command += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    command += [
        "-c:v", encoder, *quality_args, "-pix_fmt", "yuv420p",
        "-r", str(fps), "-s", f"{width}x{height}",
        "-movflags", "+faststart", str(output),
    ]
    subprocess.run(command, check=True)
    return output
