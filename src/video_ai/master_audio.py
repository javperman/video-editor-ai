"""Normalización de audio de master con loudnorm de dos pasadas."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

MEASURED = re.compile(r"\{[\s\S]*\}")


def normalize_audio(video: Path, output: Path, target_lufs: float = -16.0, true_peak: float = -1.5) -> Path:
    first = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
         "-af", f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    match = MEASURED.search(first.stderr)
    if not match:
        raise RuntimeError("loudnorm no devolvió mediciones")
    data = json.loads(match.group(0))
    filter_graph = (
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11"
        f":measured_I={data['input_i']}:measured_TP={data['input_tp']}"
        f":measured_LRA={data['input_lra']}:measured_thresh={data['input_thresh']}"
        f":offset={data['target_offset']}:linear=true,"
        # Limitador de seguridad: `loudnorm` en modo lineal puede superar el
        # true peak objetivo; el limitador lo garantiza.
        f"alimiter=limit={10 ** (true_peak / 20):.6f}:attack=5:release=50:level=false"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
         "-af", filter_graph,
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(output)],
        check=True,
    )
    return output
