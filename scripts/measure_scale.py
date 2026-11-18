#!/usr/bin/env python3
"""Mide tiempos y memoria pico de las etapas de análisis a una duración dada.

No ejecuta el render de OpenChatCut (es la etapa más lenta); para eso se mide
aparte. Sirve para extrapolar a un proyecto largo con datos reales.

Uso: PYTHONPATH=src .venv/bin/python scripts/measure_scale.py [segundos]
"""

from __future__ import annotations

import json
import resource
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "src"))

from video_ai.audio import transcribe
from video_ai.audio_events import analyze_audio
from video_ai.vision import analyze_vision

WORK = BASE / "data" / "scale"
VOICE = BASE / "tests" / "fixtures" / "spike" / "voice-es.wav"


def peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def build_clip(seconds: float, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file():
        return output
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={seconds}",
        "-stream_loop", "-1", "-i", str(VOICE), "-shortest",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", str(output),
    ], check=True)
    return output


def timed(label: str, function) -> tuple[object, dict]:
    start = time.time()
    result = function()
    elapsed = time.time() - start
    return result, {"stage": label, "seconds": round(elapsed, 2), "peak_rss_mb": round(peak_rss_mb(), 1)}


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0
    clip = build_clip(seconds, WORK / f"clip-{int(seconds)}s.mp4")

    stages = []
    _, stats_audio = timed("analizar_audio", lambda: analyze_audio(clip, words=[], fps=30.0))
    stages.append(stats_audio)

    words, stats_asr = timed("transcribir_gpu", lambda: transcribe(clip, model="large-v3-turbo",
                                                                  device="cuda", compute_type="float16", language="es"))
    stages.append(stats_asr)
    stages.append({"stage": "palabras", "count": len(words["words"]), "device": words["device"]})

    _, stats_vision = timed("vision_ocr_1fps", lambda: analyze_vision(clip, source_id="clip", fps=30.0,
                                                                      ocr_fps=1.0, frames_dir=WORK / "frames"))
    stages.append(stats_vision)

    report = {
        "clip_seconds": seconds,
        "stages": stages,
        "peak_rss_mb": round(peak_rss_mb(), 1),
        "note": "El render de OpenChatCut se mide aparte; es la etapa dominante.",
    }
    (WORK / f"scale-report-{int(seconds)}s.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                             encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
