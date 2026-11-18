"""Subtítulos: agrupa palabras en cues, genera SRT y los mapea a la timeline.

El dueño asumió que los subtítulos funcionan; aquí solo se generan de forma
determinista a partir de las palabras con tiempos. Ningún modelo externo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .compile import compile_timeline

PUNCTUATION_END = ".!?…"


@dataclass
class Cue:
    start: float
    end: float
    text: str


def _clean(token: str) -> str:
    return " ".join(token.split())


def segment_words(
    words: list[dict[str, Any]],
    *,
    max_gap: float = 0.8,
    max_duration: float = 6.0,
    max_chars: int = 84,
    max_chars_line: int = 42,
) -> list[Cue]:
    """Agrupa palabras en cues legibles con las reglas habituales de subtítulos."""
    cues: list[Cue] = []
    buffer: list[dict[str, Any]] = []

    def flush() -> None:
        if not buffer:
            return
        text = _wrap(" ".join(_clean(str(word.get("word", ""))) for word in buffer).strip(), max_chars_line)
        cues.append(Cue(start=float(buffer[0]["start"]), end=float(buffer[-1]["end"]), text=text))
        buffer.clear()

    for word in words:
        if buffer:
            gap = float(word["start"]) - float(buffer[-1]["end"])
            duration = float(word["end"]) - float(buffer[0]["start"])
            pending = len(" ".join(str(item.get("word", "")) for item in buffer)) + len(str(word.get("word", "")))
            ends_sentence = str(buffer[-1].get("word", "")).strip().endswith(tuple(PUNCTUATION_END))
            if gap > max_gap or duration > max_duration or pending > max_chars or ends_sentence:
                flush()
        buffer.append(word)
    flush()
    return cues


def _wrap(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > width and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines[:2])


def _srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_srt(cues: list[Cue]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(f"{index}\n{_srt_time(cue.start)} --> {_srt_time(cue.end)}\n{cue.text}\n")
    return "\n".join(blocks)


def write_srt(cues: list[Cue], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_srt(cues), encoding="utf-8")
    return path


def timeline_segments(plan: dict[str, Any], source_id: str) -> list[tuple[int, int, int]]:
    """Segmentos (source_in, source_out, timeline_in) tras aplicar los cortes."""
    compiled = compile_timeline(plan)
    segments: list[tuple[int, int, int]] = []
    for track in compiled.get("timeline", {}).get("tracks", []):
        for item in track.get("items", []):
            if item["source"] == source_id:
                segments.append((int(item["source_in"]), int(item["source_out"]), int(item["timeline_in"])))
    return sorted(segments)


def map_source_frame(segments: list[tuple[int, int, int]], frame: int) -> int | None:
    for source_in, source_out, timeline_in in segments:
        if source_in <= frame < source_out:
            return timeline_in + (frame - source_in)
    return None


def cues_to_plan_subtitles(
    cues: list[Cue],
    plan: dict[str, Any],
    source_id: str,
    *,
    fps: float | None = None,
    style: str = "tutorial",
) -> list[dict[str, Any]]:
    """Convierte cues en `edits.subtitles` mapeados a la timeline compilada.

    Los cues que caen por completo en una zona cortada se descartan; los que
    cruzan un corte se recortan al segmento conservado.
    """
    fps = float(fps or plan["timebase"]["fps"])
    segments = timeline_segments(plan, source_id)
    subtitles: list[dict[str, Any]] = []
    for index, cue in enumerate(cues, start=1):
        start_frame = int(round(cue.start * fps))
        end_frame = int(round(cue.end * fps))
        pieces: list[tuple[int, int]] = []
        for source_in, source_out, timeline_in in segments:
            overlap_start = max(start_frame, source_in)
            overlap_end = min(end_frame, source_out)
            if overlap_end - overlap_start < 2:
                continue
            mapped_start = timeline_in + (overlap_start - source_in)
            mapped_end = timeline_in + (overlap_end - source_in)
            if mapped_end > mapped_start:
                pieces.append((mapped_start, mapped_end))
        if not pieces:
            continue
        timeline_in = pieces[0][0]
        timeline_out = pieces[-1][1]
        subtitles.append({
            "id": f"sub-{index:04d}",
            "timeline_in": timeline_in,
            "timeline_out": timeline_out,
            "text": cue.text,
            "style": style,
        })
    return subtitles


def plan_subtitles_to_cues(subtitles: list[dict[str, Any]], fps: float) -> list[Cue]:
    """Convierte `edits.subtitles` (frames de timeline) en cues en segundos."""
    cues: list[Cue] = []
    for item in subtitles:
        cues.append(Cue(start=float(item["timeline_in"]) / fps,
                        end=float(item["timeline_out"]) / fps,
                        text=str(item.get("text", ""))))
    return sorted(cues, key=lambda cue: cue.start)


def _ass_time(seconds: float) -> str:
    centiseconds = int(round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, centis = divmod(remainder, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{centis:02d}"


# Estilos de subtítulo. `size_ratio`/`margin_*_ratio` son fracciones del alto o
# ancho real del vídeo, para que el tamaño no dependa del lienzo por defecto de
# libass (que asume 384x288 y hace los subtítulos enormes si se usa FontSize fijo).
STYLES: dict[str, dict[str, object]] = {
    "tutorial": {
        "font": "DejaVu Sans",
        "size_ratio": 0.042,        # ~45 px a 1080p
        "primary": "&H00FFFFFF",    # blanco
        "outline": "&H00000000",    # negro
        "back": "&H80000000",       # caja negra al 50 %
        "border": 3, "outline_w": 1, "shadow": 0,
        "align": 2,                 # abajo centrado
        "margin_lr_ratio": 0.05, "margin_v_ratio": 0.045,
    },
    "minimal": {
        "font": "DejaVu Sans",
        "size_ratio": 0.038,
        "primary": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000",
        "border": 1, "outline_w": 3, "shadow": 1,
        "align": 2,
        "margin_lr_ratio": 0.06, "margin_v_ratio": 0.05,
    },
}


def build_ass(cues: list[Cue], width: int, height: int, *, style: str = "tutorial") -> str:
    """Genera un ASS con resolución explícita y un estilo legible para tutorial."""
    spec = STYLES.get(style, STYLES["tutorial"])
    size = max(12, int(round(height * float(spec["size_ratio"]))))
    margin_lr = int(width * float(spec["margin_lr_ratio"]))
    margin_v = int(height * float(spec["margin_v_ratio"]))
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{spec['font']},{size},{spec['primary']},{spec['primary']},"
        f"{spec['outline']},{spec['back']},-1,0,0,0,100,100,0,0,{spec['border']},"
        f"{spec['outline_w']},{spec['shadow']},{spec['align']},"
        f"{margin_lr},{margin_lr},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events = []
    for cue in cues:
        text = cue.text.replace("\n", "\\N")
        events.append(f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},Default,,0,0,0,,{text}")
    return header + "\n".join(events) + "\n"


def write_ass(cues: list[Cue], path: Path, width: int, height: int, *, style: str = "tutorial") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_ass(cues, width, height, style=style), encoding="utf-8")
    return path


def _probe_size(video: Path) -> tuple[int, int]:
    import subprocess
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(video)],
        capture_output=True, text=True, check=True)
    width, _, height = result.stdout.strip().partition("x")
    return int(width), int(height)


def burn_subtitles(
    video: Path,
    output: Path,
    cues: list[Cue],
    *,
    width: int | None = None,
    height: int | None = None,
    style: str = "tutorial",
    encoder: str = "libx264",
    quality: int = 20,
) -> Path:
    """Quema los cues en el vídeo con un ASS de resolución real.

    A diferencia del `force_style` anterior, el tamaño es en píxeles reales del
    vídeo y la posición es configurable (estilos en `STYLES`).
    """
    import subprocess

    output.parent.mkdir(parents=True, exist_ok=True)
    if width is None or height is None:
        probed_w, probed_h = _probe_size(video)
        width = width or probed_w
        height = height or probed_h
    ass = output.with_suffix(".ass")
    write_ass(cues, ass, width, height, style=style)
    if "nvenc" in encoder:
        quality_args = ["-rc", "vbr", "-cq", str(quality), "-b:v", "0"]
    else:
        quality_args = ["-crf", str(quality), "-preset", "medium"]
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
         "-vf", f"ass={ass}", "-c:v", encoder, *quality_args,
         "-c:a", "copy", str(output)],
        check=True,
    )
    return output
