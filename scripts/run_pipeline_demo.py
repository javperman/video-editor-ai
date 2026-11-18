#!/usr/bin/env python3
"""Demo real de pipeline: ASR → análisis → plan → OpenChatCut → render → QC.

Requiere la app OpenChatCut arrancada con scripts/run-openchatcut.sh.

Incluye transcripción real (large-v3-turbo en GPU si está disponible), detección
de silencios/muletillas/repeticiones, subtítulos mapeados a la timeline y quemado
opcional de los subtítulos en el vídeo final.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "src"))

from video_ai.adapters.openchatcut import apply_plan, expected_duration
from video_ai.audio import transcribe
from video_ai.audio_events import analyze_audio
from video_ai.ingest import inspect
from video_ai.master_audio import normalize_audio
from video_ai.occ_client import OccClient, export_project
from video_ai.plan import validate
from video_ai.plan_builder import build_plan
from video_ai.qc import qc_video
from video_ai.subtitles import (
    cues_to_plan_subtitles,
    plan_subtitles_to_cues,
    segment_words,
    write_srt,
)

FIXTURES = BASE / "tests" / "fixtures" / "spike"
ARTIFACTS = BASE / "data" / "artifacts"
DB = BASE / "data" / "home" / ".openchatcut" / "project-store-v1.sqlite3"


def ensure_screen_with_voice() -> Path:
    output = FIXTURES / "screen-voice.mp4"
    voice = FIXTURES / "voice-es.wav"
    if output.is_file():
        return output
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=20",
        "-i", str(voice), "-shortest",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", str(output),
    ], check=True)
    return output


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    screen = ensure_screen_with_voice()
    phone = FIXTURES / "phone.mp4"
    voice = FIXTURES / "voice-es.wav"

    words: list[dict] = []
    asr: dict = {}
    try:
        asr = transcribe(voice, model="large-v3-turbo", device="cuda", compute_type="float16", language="es")
        words = asr["words"]
    except Exception as error:  # noqa: BLE001
        asr = {"error": f"{type(error).__name__}: {error}"}

    events = analyze_audio(voice, words=words, fps=30)
    candidates = events["candidates"]
    screen_info = inspect(screen)
    phone_info = inspect(phone)
    voice_info = inspect(voice)
    for info, role in ((screen_info, "screen"), (phone_info, "phone_cam"), (voice_info, "voice")):
        info["role"] = role
        info["path_rel"] = str(Path(info["path_rel"]).resolve().relative_to(BASE.resolve()))
    sources = [screen_info, phone_info, voice_info]

    plan = build_plan(
        "pipeline-demo", sources, candidates,
        fps=float(screen_info["fps"]), width=screen_info["width"], height=screen_info["height"],
        primary_source=screen_info["id"],
    )
    # Subtítulos generados desde la transcripción y mapeados a la timeline con cortes.
    cues = segment_words(words)
    plan["edits"]["subtitles"] = cues_to_plan_subtitles(cues, plan, voice_info["id"], fps=float(screen_info["fps"]))
    report = validate(plan, BASE)
    if report["errors"]:
        raise SystemExit("plan inválido: " + "; ".join(report["errors"]))
    duration_frames = expected_duration(plan)

    srt_source = write_srt(cues, ARTIFACTS / "pipeline-demo.source.srt")
    timeline_cues = plan_subtitles_to_cues(plan["edits"]["subtitles"], float(screen_info["fps"]))
    srt_timeline = write_srt(timeline_cues, ARTIFACTS / "pipeline-demo.srt")

    client = OccClient()
    client.initialize()
    applied = apply_plan(client, plan, BASE, project_name="Pipeline demo")
    output = ARTIFACTS / "pipeline-demo.mp4"
    export_project(applied["project_id"], output, DB)
    mastered = normalize_audio(output, ARTIFACTS / "pipeline-demo-final.mp4")
    final = ARTIFACTS / "pipeline-demo-subtitled.mp4"
    from video_ai.subtitles import burn_subtitles

    burn_subtitles(mastered, final, timeline_cues)
    qc = qc_video(final, expected={"width": 1920, "height": 1080, "fps": 30.0,
                                   "duration": duration_frames / float(screen_info["fps"])})
    result = {
        "asr": {key: asr[key] for key in ("model", "device", "compute_type", "duration_seconds") if key in asr} or asr,
        "words": len(words),
        "plan_candidates": candidates,
        "subtitles": len(plan["edits"]["subtitles"]),
        "expected_duration_frames": duration_frames,
        "openchatcut": applied,
        "video_raw": str(output),
        "video_mastered": str(mastered),
        "video": str(final),
        "srt_source": str(srt_source),
        "srt_timeline": str(srt_timeline),
        "qc": qc,
    }
    (ARTIFACTS / "pipeline-demo-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "words": len(words),
        "candidates": len(candidates),
        "subtitles": len(plan["edits"]["subtitles"]),
        "expected_seconds": round(duration_frames / float(screen_info["fps"]), 3),
        "project_id": applied["project_id"],
        "clips": applied["clips"],
        "qc_ok": qc["ok"],
        "qc_failed": [check["name"] for check in qc["checks"] if check["critical"] and not check["ok"]],
    }, ensure_ascii=False, indent=2))
    return 0 if qc["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
