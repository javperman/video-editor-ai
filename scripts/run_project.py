#!/usr/bin/env python3
"""Pipeline completo de un proyecto real, en un solo comando.

Entrada: grabaciones (pantalla, webcam/móvil opcional, voz opcional, música
opcional). Salida: plan versionado, subtítulos, vídeo final 1080p con QC,
FCPXML y un informe.

Ejemplo:

    PYTHONPATH=src .venv/bin/python scripts/run_project.py \
      --screen grabacion-pantalla.mkv \
      --webcam grabacion-movil.mp4 \
      --voice voz.wav \
      --out-dir data/proyecto-tutorial \
      --project-name "Tutorial de ejemplo"

Con `--skip-render` solo se hace el análisis, el plan y los ficheros de
intercambio (no necesita OpenChatCut).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "src"))

from video_ai.audio import transcribe
from video_ai.audio_events import analyze_audio
from video_ai.deliver import timeline_frames
from video_ai.fcpxml import write_fcpxml
from video_ai.ingest import inspect
from video_ai.plan import validate
from video_ai.plan_builder import build_plan
from video_ai.redact import bake_redactions
from video_ai.render import _has_audio
from video_ai.revisions import RevisionStore
from video_ai.subtitles import cues_to_plan_subtitles, plan_subtitles_to_cues, segment_words, write_srt
from video_ai.vision import analyze_vision

DB = BASE / "data" / "home" / ".openchatcut" / "project-store-v1.sqlite3"


def prepare_source(path: Path, role: str, *, timebase_fps: float | None = None) -> dict:
    info = inspect(path)
    # El plan numerá todos los frames en el fps base (el de la pantalla). Una
    # fuente con otro fps (móvil ~29,9, webcam) debe normalizar su duración o el
    # item queda corto y el PiP se acaba antes de tiempo.
    if timebase_fps and info["duration_seconds"]:
        info["duration_frames"] = int(round(info["duration_seconds"] * timebase_fps))
    info["role"] = role
    info["path_rel"] = str(path.resolve().relative_to(BASE.resolve()))
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline completo de tutorial")
    parser.add_argument("--screen", required=True)
    parser.add_argument("--webcam", default=None)
    parser.add_argument("--voice", default=None)
    parser.add_argument("--music", default=None)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--project-name", default=None)
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute", default="float16")
    parser.add_argument("--language", default="es")
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--renderer", choices=["occ", "ffmpeg"], default="occ")
    parser.add_argument("--encoder", default="h264_nvenc")
    parser.add_argument("--align", action="store_true",
                        help="Alinea la voz con el audio de la pantalla (voz grabada aparte)")
    parser.add_argument("--no-pip", action="store_true", help="No montar el móvil como picture-in-picture")
    parser.add_argument("--pip-scale", type=float, default=0.16,
                        help="Tamaño del PiP: fracción del ancho del lienzo")
    parser.add_argument("--pip-aspect", type=float, default=1.33,
                        help="Proporción de la caja del PiP (alto/ancho); recorta el móvil a ese marco (4:3 ≈ 1.33)")
    parser.add_argument("--pip-focus", default="center", choices=["center", "top", "bottom"],
                        help="Anclaje vertical del recorte del PiP")
    parser.add_argument("--pip-max-height", type=float, default=0.45,
                        help="Altura máxima del PiP: fracción del alto del lienzo")
    parser.add_argument("--subtitle-style", default="tutorial", choices=["tutorial", "minimal"])
    parser.add_argument("--silence-db", type=int, default=-35, help="Umbral de silencio (dB)")
    parser.add_argument("--silence-min", type=float, default=0.5, help="Duración mínima para considerar silencio (s)")
    parser.add_argument("--silence-min-cut", type=float, default=1.2, help="Duración mínima para proponer corte (s)")
    parser.add_argument("--no-subtitles", action="store_true")
    args = parser.parse_args()

    work = Path(args.out_dir).resolve()
    if BASE.resolve() not in work.parents and work != BASE.resolve():
        raise SystemExit(f"--out-dir debe estar dentro del repositorio ({BASE}) para que las rutas del plan sean resolubles")
    work.mkdir(parents=True, exist_ok=True)
    project_name = args.project_name or work.name

    screen = Path(args.screen).resolve()
    if not screen.is_file():
        raise SystemExit(f"no existe la pantalla: {screen}")

    sources = [prepare_source(screen, "screen")]
    primary_fps = float(sources[0]["fps"])

    # Antes de construir el plan: si hay webcam, producir una copia alineada con
    # la pantalla. Manipular el item y cortar despues rompe la alineacion, porque
    # los cortes van en tiempo de pantalla y la webcam tiene otro origen.
    webcam = Path(args.webcam).resolve() if args.webcam else None
    pip_report = None
    if webcam and not args.no_pip:
        from video_ai.align import find_offset, make_time_aligned

        def _audio_wav(media: Path, name: str) -> Path:
            out = work / name
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(media),
                            "-vn", "-ac", "1", "-ar", "16000", str(out)], check=True)
            return out

        if _has_audio(screen) and _has_audio(webcam):
            screen_audio = _audio_wav(screen, "probe-screen.wav")
            cam_audio = _audio_wav(webcam, "probe-webcam.wav")
            offset, quality = find_offset(screen_audio, cam_audio)
            # `offset` = retraso de la webcam respecto a la pantalla: positivo si
            # empezó más tarde (hay que recortarle el principio), negativo si
            # empezó antes (hay que rellenar el principio con negro/silencio).
            shift = offset
            aligned = make_time_aligned(webcam, work / "webcam-aligned.mp4", shift)
            residual, residual_quality = find_offset(
                screen_audio, _audio_wav(aligned, "probe-webcam-aligned.wav"))
            print(json.dumps({"pip_align": {"offset_seconds": round(offset, 4),
                                            "quality": round(quality, 4),
                                            "residual_seconds": round(residual, 4),
                                            "residual_quality": round(residual_quality, 4)}},
                             ensure_ascii=False))
            webcam = aligned
            pip_report = {"offset_seconds": round(offset, 4), "quality": round(quality, 4),
                          "residual_seconds": round(residual, 4), "scale": args.pip_scale,
                          "aspect": args.pip_aspect, "focus": args.pip_focus,
                          "max_height": args.pip_max_height}
        else:
            pip_report = {"offset_seconds": None, "note": "sin audio para alinear",
                          "scale": args.pip_scale, "aspect": args.pip_aspect,
                          "focus": args.pip_focus, "max_height": args.pip_max_height}
    if webcam:
        webcam_info = prepare_source(webcam, "webcam", timebase_fps=primary_fps)
        # El móvil alineado puede ser algo más largo que la pantalla (por el
        # relleno inicial); se recorta para que ambas pistas terminen juntas.
        webcam_info["duration_frames"] = min(webcam_info["duration_frames"],
                                             sources[0]["duration_frames"])
        webcam_info["duration_seconds"] = min(float(webcam_info["duration_seconds"]),
                                              float(sources[0]["duration_seconds"]))
        sources.append(webcam_info)

    voice = Path(args.voice).resolve() if args.voice else None
    if voice and args.align and _has_audio(screen):
        from video_ai.align import apply_offset, find_offset
        screen_audio = work / "screen-audio.wav"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(screen),
                        "-vn", "-ac", "1", "-ar", "16000", str(screen_audio)], check=True)
        offset, quality = find_offset(screen_audio, voice)
        aligned = work / "voice-aligned.wav"
        apply_offset(voice, aligned, offset)
        print(json.dumps({"align": {"offset_seconds": round(offset, 4),
                                    "quality": round(quality, 4)}}, ensure_ascii=False))
        voice = aligned
    if voice:
        sources.append(prepare_source(voice, "voice", timebase_fps=primary_fps))

    primary = sources[0]
    fps = float(primary["fps"])
    audio_for_analysis = voice or screen

    # 1) Transcripción real.
    words: list[dict] = []
    asr: dict = {}
    try:
        asr = transcribe(audio_for_analysis, model=args.model, device=args.device,
                         compute_type=args.compute, language=args.language)
        words = asr["words"]
    except Exception as error:  # noqa: BLE001
        asr = {"error": f"{type(error).__name__}: {error}"}
    (work / "transcript.json").write_text(json.dumps(asr, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 2) Eventos de audio y 3) visión (redacciones).
    events = analyze_audio(audio_for_analysis, words=words, fps=fps,
                           noise_db=args.silence_db, min_seconds=args.silence_min,
                           min_cut=args.silence_min_cut)
    vision = analyze_vision(screen, source_id=primary["id"], fps=fps, ocr_fps=1.0,
                            frames_dir=work / "frames")

    # 4) Plan base.
    plan = build_plan(project_name, sources, events["candidates"], fps=fps,
                      width=int(primary["width"]), height=int(primary["height"]),
                      primary_source=primary["id"], redactions=vision["redactions"])

    # 5) PiP del móvil: ya esta alineado; solo se coloca en la esquina.
    webcam_id = next((s["id"] for s in sources if s.get("role") == "webcam"), None)
    if webcam_id and not args.no_pip:
        from video_ai.layouts import picture_in_picture

        webcam_source = next(s for s in sources if s["id"] == webcam_id)
        aspect = float(webcam_source["height"]) / float(webcam_source["width"])
        plan = picture_in_picture(plan, webcam_id, position="bottom-right",
                                  scale=args.pip_scale, margin=0.03, aspect=aspect,
                                  max_height=args.pip_max_height,
                                  fit_aspect=args.pip_aspect, focus=args.pip_focus)

    # 6) Subtítulos mapeados a la timeline.
    def source_id_for_role(role: str) -> str:
        return next((s["id"] for s in sources if s.get("role") == role), primary["id"])

    subtitle_source = source_id_for_role("voice") if voice else primary["id"]
    subs: list[dict] = []
    if not args.no_subtitles and words:
        subs = cues_to_plan_subtitles(segment_words(words), plan, subtitle_source, fps=fps,
                                      style=args.subtitle_style)
        plan["edits"]["subtitles"] = subs

    errors = validate(plan, BASE)["errors"]
    if errors:
        raise SystemExit("plan inválido: " + "; ".join(errors))
    store = RevisionStore(work / "project", validate_root=BASE)
    store.save(plan)
    baked = bake_redactions(store.current(), BASE, work / "redacted")
    baked["revision"] = 2
    baked["parent_revision"] = 1
    baked["created_at"] = datetime.now(timezone.utc).isoformat()
    store.save(baked)

    frames = timeline_frames(baked)
    expected_seconds = round(frames / fps, 3)

    # 7) Ficheros auxiliares.
    write_srt(segment_words(words), work / "subtitles.source.srt")
    timeline_cues = plan_subtitles_to_cues(baked["edits"]["subtitles"], fps)
    srt_timeline = write_srt(timeline_cues, work / "subtitles.timeline.srt")
    write_fcpxml(baked, BASE, work / "project.fcpxml")

    result: dict = {
        "project": project_name,
        "sources": [{"id": s["id"], "role": s.get("role"), "path": s["path_rel"],
                     "frames": s["duration_frames"]} for s in baked["sources"]],
        "asr": {k: asr[k] for k in ("model", "device", "compute_type", "duration_seconds") if k in asr} or asr,
        "words": len(words),
        "candidates": events["candidates"],
        "redactions": len(vision["redactions"]),
        "subtitles": len(baked["edits"]["subtitles"]),
        "pip": pip_report,
        "expected_seconds": expected_seconds,
        "fcpxml": str(work / "project.fcpxml"),
        "srt": str(srt_timeline),
    }

    if not args.skip_render:
        if args.renderer == "ffmpeg":
            from video_ai.deliver import deliver
            clips = sum(len(track.get("items", [])) for track in baked["timeline"]["tracks"])
            rendered = deliver(baked, BASE, work, encoder=args.encoder,
                               music=Path(args.music).resolve() if args.music else None)
            result["render"] = {"clips": clips, **rendered}
        else:
            from video_ai.adapters.openchatcut import apply_plan
            from video_ai.master_audio import normalize_audio
            from video_ai.music import duck_music
            from video_ai.occ_client import OccClient, export_project
            from video_ai.qc import qc_video
            from video_ai.subtitles import burn_subtitles

            client = OccClient()
            client.initialize()
            applied = apply_plan(client, baked, BASE, project_name=project_name)
            raw = work / "render-raw.mp4"
            export_project(applied["project_id"], raw, DB)
            mastered = normalize_audio(raw, work / "render-master.mp4")
            mixed = mastered
            if args.music:
                mixed = duck_music(mastered, Path(args.music).resolve(), work / "render-music.mp4")
            final = work / "render-final.mp4"
            burn_subtitles(mixed, final, timeline_cues)
            qc = qc_video(final, expected={"width": int(primary["width"]), "height": int(primary["height"]),
                                           "fps": fps, "duration": expected_seconds})
            result["render"] = {"renderer": "occ", "clips": applied.get("clips"),
                                "video": str(final), "qc_ok": qc["ok"],
                                "qc_failed": [c["name"] for c in qc["checks"] if c["critical"] and not c["ok"]]}

    (work / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("render") and not result["render"]["qc_ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
