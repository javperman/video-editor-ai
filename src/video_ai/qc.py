"""Control de calidad de un render con FFprobe y filtros de FFmpeg."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

INTEGRATED = re.compile(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS")
TRUE_PEAK = re.compile(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS")
BLACK_START = re.compile(r"black_start:([\d.]+)")
FREEZE_START = re.compile(r"freeze_start:\s*([\d.]+)")


def _run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True)
    return result.stderr + result.stdout


def probe(video: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size,bit_rate",
         "-show_entries", "stream=index,codec_type,codec_name,width,height,avg_frame_rate,nb_frames,sample_rate,channels",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def qc_video(video: Path, expected: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = expected or {}
    info = probe(video)
    streams = info.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(info.get("format", {}).get("duration", 0.0))
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any, critical: bool = True) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "critical": critical})

    if "width" in expected:
        check("width", video_stream.get("width") == expected["width"], video_stream.get("width"))
    if "height" in expected:
        check("height", video_stream.get("height") == expected["height"], video_stream.get("height"))
    if "fps" in expected:
        check("fps", abs(_fps(video_stream) - float(expected["fps"])) < 0.01, _fps(video_stream))
    if "duration" in expected:
        delta = abs(duration - float(expected["duration"]))
        check("duration", delta <= 0.5, {"measured": round(duration, 3), "delta": round(delta, 3)})
    check("has_audio", audio_stream is not None, bool(audio_stream))

    black = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vf", "blackdetect=d=0.5:pix_th=0.10", "-an", "-f", "null", "-"])
    blacks = [float(value) for value in BLACK_START.findall(black)]
    check("blackdetect", not blacks, blacks)

    freeze = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vf", "freezedetect=n=-60dB:d=2", "-an", "-f", "null", "-"])
    freezes = [float(value) for value in FREEZE_START.findall(freeze)]
    check("freezedetect", True, freezes, critical=False)

    loudness = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-af", "ebur128=peak=true", "-f", "null", "-"])
    integrated = [float(value) for value in INTEGRATED.findall(loudness)]
    peaks = [float(value) for value in TRUE_PEAK.findall(loudness)]
    if integrated and peaks:
        check("true_peak", peaks[-1] <= -1.0, peaks[-1])
        check("integrated_loudness", -20.0 <= integrated[-1] <= -12.0, integrated[-1], critical=False)
    else:
        check("loudness_available", False, "sin datos ebur128")

    ok = all(item["ok"] for item in checks if item["critical"])
    return {"ok": ok, "checks": checks, "duration": duration, "video": str(video)}


def _fps(stream: dict[str, Any]) -> float:
    value = stream.get("avg_frame_rate") or "0/0"
    try:
        numerator, denominator = value.split("/")
        return float(numerator) / float(denominator) if float(denominator) else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0
