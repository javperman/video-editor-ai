"""Música de fondo con ducking: baja automáticamente cuando hay voz.

Se resuelve con `sidechaincompress` de FFmpeg: la voz es la señal de control y la
música se atenúa solo mientras se habla.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


def duck_filter_complex(
    *,
    music_gain_db: float,
    threshold: float,
    ratio: float,
    attack_ms: float,
    release_ms: float,
    mix: bool = True,
) -> str:
    """Grafo de filtros: música atenuada por la voz; opcionalmente mezclada."""
    chain = (
        f"[1:a]volume={music_gain_db}dB[music];"
        f"[music][0:a]sidechaincompress=threshold={threshold}:ratio={ratio}"
        f":attack={attack_ms}:release={release_ms}[ducked]"
    )
    if mix:
        chain += ";[0:a][ducked]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    return chain


def duck_music_only(
    voice: Path,
    music: Path,
    output: Path,
    *,
    music_gain_db: float = -18.0,
    threshold: float = 0.05,
    ratio: float = 8.0,
    attack_ms: float = 5.0,
    release_ms: float = 400.0,
) -> Path:
    """Escribe solo la música ya atenuada (útil para verificar el ducking)."""
    filter_complex = duck_filter_complex(music_gain_db=music_gain_db, threshold=threshold,
                                         ratio=ratio, attack_ms=attack_ms, release_ms=release_ms, mix=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    codec = "pcm_s16le" if output.suffix.lower() == ".wav" else "aac"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(voice), "-i", str(music),
         "-filter_complex", filter_complex, "-map", "[ducked]", "-c:a", codec, str(output)],
        check=True,
    )
    return output


def duck_music(
    voice: Path,
    music: Path,
    output: Path,
    *,
    music_gain_db: float = -18.0,
    threshold: float = 0.05,
    ratio: float = 8.0,
    attack_ms: float = 5.0,
    release_ms: float = 400.0,
) -> Path:
    """Mezcla `music` por debajo de `voice` con atenuación dinámica."""
    filter_complex = duck_filter_complex(music_gain_db=music_gain_db, threshold=threshold,
                                         ratio=ratio, attack_ms=attack_ms, release_ms=release_ms, mix=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    codec = "pcm_s16le" if output.suffix.lower() == ".wav" else "aac"
    codec_args = ["-c:a", codec] if codec == "pcm_s16le" else ["-c:a", "aac", "-b:a", "192k"]
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(voice), "-i", str(music),
         "-filter_complex", filter_complex, "-map", "0:v?", "-map", "[aout]",
         "-c:v", "copy", *codec_args, "-shortest", str(output)],
        check=True,
    )
    return output


def mean_volume_db(media: Path, start: float, duration: float) -> float:
    """Volumen medio (dBFS) de un fragmento; útil para verificar el ducking."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
         "-i", str(media), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    match = re.search(r"mean_volume:\s*(-?[\d.]+)", result.stderr)
    if not match:
        raise RuntimeError("volumedetect no devolvió media")
    return float(match.group(1))
