#!/usr/bin/env python3
"""Demo local del ciclo de revisión: visión → redacción → lenguaje natural → plan.

No necesita OpenChatCut. Muestra:

1. Análisis de audio (silencio) y de visión (OCR + redacciones) sobre fixtures.
2. Construcción de un `edit_plan.json` con cortes y redacciones.
3. Guardado como revisión inmutable 1.
4. Instrucción en lenguaje natural que produce la revisión 2.
5. Horneado de las redacciones en copias de las fuentes → revisión 3.
6. Compilación de la timeline resultante.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "src"))

from video_ai.audio_events import analyze_audio
from video_ai.commands import run_instruction
from video_ai.compile import compile_timeline
from video_ai.ingest import inspect
from video_ai.plan import validate
from video_ai.plan_builder import build_plan
from video_ai.redact import bake_redactions
from video_ai.revisions import RevisionStore
from video_ai.vision import analyze_vision

FIXTURES = BASE / "tests" / "fixtures"
WORK = BASE / "data" / "revision-demo"


def main() -> int:
    screen = FIXTURES / "vision" / "secret.mp4"
    voice = FIXTURES / "spike" / "voice-es.wav"
    if not screen.is_file() or not voice.is_file():
        raise SystemExit("faltan fixtures; ejecuta scripts/make_voice_fixture.sh y scripts/make_vision_fixture.sh")

    WORK.mkdir(parents=True, exist_ok=True)
    import shutil

    if (WORK / "project").exists():
        shutil.rmtree(WORK / "project")
    if (WORK / "redacted").exists():
        shutil.rmtree(WORK / "redacted")
    screen_info = inspect(screen)
    voice_info = inspect(voice)
    screen_info.update(role="screen", path_rel=str(screen.resolve().relative_to(BASE.resolve())))
    voice_info.update(role="voice", path_rel=str(voice.resolve().relative_to(BASE.resolve())))

    fps = float(screen_info["fps"])
    events = analyze_audio(voice, words=[], fps=fps)
    vision = analyze_vision(screen, source_id=screen_info["id"], fps=fps, ocr_fps=1.0,
                            frames_dir=WORK / "frames")

    plan = build_plan("revision-demo", [screen_info, voice_info], events["candidates"],
                      fps=fps, width=int(screen_info["width"]), height=int(screen_info["height"]),
                      primary_source=screen_info["id"], redactions=vision["redactions"])
    if validate(plan)["errors"]:
        raise SystemExit("plan inicial inválido: " + "; ".join(validate(plan)["errors"]))

    store = RevisionStore(WORK / "project", validate_root=BASE)
    store.save(plan)

    instruction = "aprueba el corte 1"
    revision_2 = run_instruction(store, instruction)

    current = store.current()
    assert current is not None
    baked = bake_redactions(current, BASE, WORK / "redacted")
    baked["revision"] = int(current["revision"]) + 1
    baked["parent_revision"] = int(current["revision"])
    baked["created_at"] = datetime.now(timezone.utc).isoformat()
    store.save(baked)

    compiled = compile_timeline(store.current())
    end = 0
    for track in compiled["timeline"]["tracks"]:
        for item in track["items"]:
            end = max(end, int(item["timeline_in"]) + int(item["duration_frames"]))

    result = {
        "screen_source": screen_info["id"],
        "candidates": len(events["candidates"]),
        "scenes": len(vision["scenes"]),
        "sensitive": vision["sensitive"],
        "redactions_proposed": len(vision["redactions"]),
        "instruction": instruction,
        "revisions": {
            "1": "plan con cortes y redacciones",
            "2": revision_2["intent"]["summary"],
            "3": "redacciones horneadas en la fuente",
        },
        "baked_sources": {s["id"]: s.get("redacted_from") for s in baked["sources"]},
        "timeline_frames": end,
        "timeline_seconds": round(end / fps, 3),
        "revision_files": sorted(p.name for p in (WORK / "project" / "revisions").glob("*.json")),
    }
    (WORK / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
