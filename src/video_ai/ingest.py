"""Inspección e ingesta de medios: ffprobe, hash y metadatos del plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_fraction(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 0.0


def ffprobe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,size,bit_rate,format_name",
            "-show_entries", "stream=index,codec_type,codec_name,width,height,avg_frame_rate,sample_rate,channels",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def inspect(path: Path, fps_default: float = 30.0) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    probe = ffprobe(path)
    video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float(probe.get("format", {}).get("duration", 0.0))
    fps = _parse_fraction(video.get("avg_frame_rate")) if video else fps_default
    if fps <= 0:
        fps = fps_default
    return {
        "id": path.stem.lower().replace(" ", "_"),
        "sha256": sha256_file(path),
        "path_rel": str(path),
        "kind": "video" if video else "audio" if audio else "unknown",
        "duration_frames": int(round(duration * fps)),
        "duration_seconds": duration,
        "fps": fps,
        "width": video.get("width") if video else None,
        "height": video.get("height") if video else None,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "sample_rate": audio.get("sample_rate") if audio else None,
        "channels": audio.get("channels") if audio else None,
        "read_only": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspecciona medios y emite JSON compatible con sources[]")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--fps", type=float, default=30.0, help="FPS de respaldo si ffprobe no lo da")
    parser.add_argument("--out", type=Path, help="Escribe el JSON en este archivo")
    args = parser.parse_args(argv)
    sources = []
    for path in args.paths:
        try:
            sources.append(inspect(path, args.fps))
        except Exception as error:  # noqa: BLE001
            print(f"error inspeccionando {path}: {error}", file=sys.stderr)
            return 1
    payload = json.dumps({"sources": sources}, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
