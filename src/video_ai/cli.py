"""Punto de entrada de video-editor-ai."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="video-ai", description="Herramientas de video-editor-ai")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="Inspecciona medios y emite sources[]")
    ingest.add_argument("paths", nargs="+")
    inspect = sub.add_parser("validate", help="Valida un edit_plan.json")
    inspect.add_argument("plan")
    inspect.add_argument("--root", default=None)
    events = sub.add_parser("events", help="Detecta silencios, muletillas y repeticiones")
    events.add_argument("media")
    events.add_argument("--transcript", help="JSON con words[]")
    events.add_argument("--fps", type=float, default=30.0)
    compile_parser = sub.add_parser("compile", help="Aplica cortes a la timeline")
    compile_parser.add_argument("plan")
    compile_parser.add_argument("--out")
    vision = sub.add_parser("vision", help="Escenas, muestreo, OCR y redacciones")
    vision.add_argument("media")
    vision.add_argument("--source-id", default=None)
    vision.add_argument("--fps", type=float, default=30.0)
    vision.add_argument("--threshold", type=float, default=8.0)
    vision.add_argument("--ocr-fps", type=float, default=1.0)
    vision.add_argument("--max-frames", type=int, default=48)
    vision.add_argument("--frames-dir", default=None)
    vision.add_argument("--backend", choices=["rapidocr", "tesseract", "auto"], default=None)
    vision.add_argument("--change-threshold", type=float, default=2.0,
                        help="Diferencia mínima (0-255) para repetir OCR en un fotograma")
    vision.add_argument("--no-redact", action="store_true")
    vision.add_argument("--out")
    cursor = sub.add_parser("cursor", help="Convierte muestras de cursor en candidatas a zoom")
    cursor.add_argument("samples")
    cursor.add_argument("--fps", type=float, default=30.0)
    cursor.add_argument("--plan", default=None, help="Plan para mapear los zooms a la timeline")
    cursor.add_argument("--source-id", default=None)
    cursor.add_argument("--magnification", type=float, default=1.6)
    cursor.add_argument("--zooms-out", default=None)
    cursor.add_argument("--out")
    layout = sub.add_parser("layout", help="Coloca una capa como picture-in-picture")
    layout.add_argument("plan")
    layout.add_argument("overlay_source")
    layout.add_argument("--position", default="bottom-right")
    layout.add_argument("--scale", type=float, default=0.28)
    layout.add_argument("--margin", type=float, default=0.03)
    layout.add_argument("--aspect", type=float, default=9 / 16)
    layout.add_argument("--fit-aspect", type=float, default=None,
                        help="Proporción de la caja (alto/ancho); recorta la capa a ese marco")
    layout.add_argument("--focus", default="center", choices=["center", "top", "bottom"])
    layout.add_argument("--max-height", type=float, default=None,
                        help="Altura máxima del PiP como fracción del alto del lienzo")
    layout.add_argument("--out", default=None)
    instruct = sub.add_parser("instruct", help="Aplica una instrucción en lenguaje natural a un proyecto")
    instruct.add_argument("project_dir")
    instruct.add_argument("instruction")
    instruct.add_argument("--root", default=None)
    instruct.add_argument("--dry-run", action="store_true")
    apply_parser = sub.add_parser("apply", help="Aplica una instrucción o un JSON Patch y re-renderiza")
    apply_parser.add_argument("project_dir")
    apply_parser.add_argument("instruction", nargs="?", default=None)
    apply_parser.add_argument("--ops", default=None,
                              help="Archivo JSON con operaciones JSON Patch (o '-' para stdin)")
    apply_parser.add_argument("--root", default=".")
    apply_parser.add_argument("--encoder", default="h264_nvenc")
    apply_parser.add_argument("--music", default=None)
    apply_parser.add_argument("--quality", type=int, default=21)
    apply_parser.add_argument("--no-render", action="store_true")
    apply_parser.add_argument("--dry-run", action="store_true")
    redact = sub.add_parser("redact", help="Hornea las redacciones en copias de las fuentes")
    redact.add_argument("plan")
    redact.add_argument("--root", required=True)
    redact.add_argument("--out-dir", default=None)
    redact.add_argument("--out", default=None)
    subtitles = sub.add_parser("subtitles", help="Genera SRT y subtítulos del plan desde palabras")
    subtitles.add_argument("words")
    subtitles.add_argument("--out", default=None)
    subtitles.add_argument("--plan", default=None)
    subtitles.add_argument("--source-id", default=None)
    subtitles.add_argument("--fps", type=float, default=30.0)
    subtitles.add_argument("--plan-out", default=None)
    transcribe = sub.add_parser("transcribe", help="Transcribe un medio con faster-whisper")
    transcribe.add_argument("media")
    transcribe.add_argument("--model", default="large-v3-turbo")
    transcribe.add_argument("--device", default="cuda")
    transcribe.add_argument("--compute", default="float16")
    transcribe.add_argument("--language", default="es")
    transcribe.add_argument("--out", default=None, help="Escribe las palabras en JSON")
    transcribe.add_argument("--srt", default=None, help="Escribe además un SRT")
    mix = sub.add_parser("mix", help="Mezcla música con ducking sobre la voz")
    mix.add_argument("voice")
    mix.add_argument("music")
    mix.add_argument("--out", required=True)
    mix.add_argument("--gain", type=float, default=-18.0)
    mix.add_argument("--threshold", type=float, default=0.05)
    mix.add_argument("--ratio", type=float, default=8.0)
    fcpxml = sub.add_parser("fcpxml", help="Exporta el plan a FCPXML para intercambio")
    fcpxml.add_argument("plan")
    fcpxml.add_argument("--root", required=True)
    fcpxml.add_argument("--out", required=True)
    render = sub.add_parser("render", help="Renderiza el plan con FFmpeg (NVENC opcional)")
    render.add_argument("plan")
    render.add_argument("--root", required=True)
    render.add_argument("--out", required=True)
    render.add_argument("--encoder", default="h264_nvenc")
    render.add_argument("--quality", type=int, default=21)
    render.add_argument("--subtitles", default=None)
    align = sub.add_parser("align", help="Alinea una voz grabada aparte con el audio de referencia")
    align.add_argument("reference")
    align.add_argument("target")
    align.add_argument("--out", required=True)
    align.add_argument("--method", choices=["correlation", "clap"], default="correlation")
    args = parser.parse_args(argv)
    if args.command == "ingest":
        from . import ingest as ingest_module
        return ingest_module.main(args.paths)
    if args.command == "validate":
        from . import plan as plan_module
        return plan_module.main([args.plan] + (["--root", args.root] if args.root else []))
    if args.command == "events":
        import json
        from pathlib import Path
        from .audio_events import analyze_audio
        words = []
        if args.transcript:
            words = json.loads(Path(args.transcript).read_text(encoding="utf-8")).get("words", [])
        result = analyze_audio(Path(args.media), words, fps=args.fps)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "compile":
        import json
        from pathlib import Path
        from .compile import compile_timeline
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        compiled = compile_timeline(plan)
        payload = json.dumps(compiled, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0
    if args.command == "vision":
        import json
        from pathlib import Path
        from .vision import analyze_vision
        result = analyze_vision(
            Path(args.media),
            source_id=args.source_id,
            fps=args.fps,
            threshold=args.threshold,
            ocr_fps=args.ocr_fps,
            max_frames=args.max_frames,
            frames_dir=Path(args.frames_dir) if args.frames_dir else None,
            backend=None if args.backend in (None, "auto") else args.backend,
            redact=not args.no_redact,
            change_threshold=args.change_threshold,
        )
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0
    if args.command == "cursor":
        import json
        from pathlib import Path
        from .vision import cursor_activity, load_cursor_samples
        samples = load_cursor_samples(Path(args.samples))
        dwells = cursor_activity(samples, fps=args.fps)
        result = {"samples": len(samples), "dwells": dwells}
        if args.plan and args.source_id:
            from .zooms import attach_zooms, zooms_from_dwells
            plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
            zooms = zooms_from_dwells(plan, dwells, args.source_id, magnification=args.magnification, fps=args.fps)
            result["zooms"] = zooms
            if args.zooms_out:
                Path(args.zooms_out).write_text(json.dumps(zooms, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0
    if args.command == "layout":
        import json
        from pathlib import Path
        from .layouts import picture_in_picture
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        result = picture_in_picture(plan, args.overlay_source, position=args.position,
                                    scale=args.scale, margin=args.margin, aspect=args.aspect,
                                    max_height=args.max_height, fit_aspect=args.fit_aspect,
                                    focus=args.focus)
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0
    if args.command == "instruct":
        import json
        from pathlib import Path
        from .commands import parse_instruction, run_instruction
        from .deliver import load_words
        from .revisions import RevisionStore
        project_dir = Path(args.project_dir).resolve()
        store = RevisionStore(project_dir, Path(args.root) if args.root else None)
        words = load_words(project_dir.parent)
        if args.dry_run:
            current = store.current()
            if current is None:
                print(json.dumps({"error": "no hay revisión actual"}))
                return 1
            intent = parse_instruction(args.instruction, current, words)
            print(json.dumps(intent.as_dict(), ensure_ascii=False, indent=2))
            return 0
        result = run_instruction(store, args.instruction, words=words)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "apply":
        import json
        import sys
        from pathlib import Path
        from .commands import parse_instruction
        from .deliver import apply_and_deliver, apply_ops_and_deliver, load_words, ops_disable_subtitles
        from .revisions import RevisionStore
        root = Path(args.root).resolve()
        project_dir = Path(args.project_dir).resolve()
        store = RevisionStore(project_dir, root)
        work = project_dir.parent

        if args.ops:
            raw = sys.stdin.read() if args.ops == "-" else Path(args.ops).read_text(encoding="utf-8")
            ops = json.loads(raw)
            if isinstance(ops, dict) and "ops" in ops:
                ops = ops["ops"]
            if not isinstance(ops, list):
                print(json.dumps({"error": "--ops debe ser una lista de operaciones JSON Patch"}))
                return 2
            if args.dry_run:
                print(json.dumps(ops, ensure_ascii=False, indent=2))
                return 0
            result = apply_ops_and_deliver(store, ops, work, root, encoder=args.encoder,
                                           music=args.music, quality=args.quality,
                                           render=not args.no_render,
                                           refresh=not ops_disable_subtitles(ops))
            result["ops"] = ops
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result.get("render") and not result["render"]["qc_ok"] else 0

        if not args.instruction:
            print(json.dumps({"error": "falta la instrucción o --ops"}))
            return 2
        if args.dry_run:
            current = store.current()
            if current is None:
                print(json.dumps({"error": "no hay revisión actual"}))
                return 1
            intent = parse_instruction(args.instruction, current, load_words(work))
            print(json.dumps(intent.as_dict(), ensure_ascii=False, indent=2))
            return 0
        result = apply_and_deliver(store, args.instruction, work, root,
                                   encoder=args.encoder, music=args.music,
                                   quality=args.quality, render=not args.no_render)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("render") and not result["render"]["qc_ok"]:
            return 1
        return 0
    if args.command == "redact":
        import json
        from pathlib import Path
        from .redact import bake_redactions
        root = Path(args.root).resolve()
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        out_dir = Path(args.out_dir).resolve() if args.out_dir else root / "baked"
        baked = bake_redactions(plan, root, out_dir)
        payload = json.dumps(baked, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).write_text(payload + "\n", encoding="utf-8")
        print(payload)
        return 0
    if args.command == "subtitles":
        import json
        from pathlib import Path
        from .subtitles import cues_to_plan_subtitles, segment_words, write_srt
        raw = json.loads(Path(args.words).read_text(encoding="utf-8"))
        words = raw.get("words", raw) if isinstance(raw, dict) else raw
        cues = segment_words(words)
        summary: dict[str, object] = {"cues": len(cues)}
        if args.out:
            write_srt(cues, Path(args.out))
            summary["srt"] = str(args.out)
        if args.plan and args.source_id:
            plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
            subtitles = cues_to_plan_subtitles(cues, plan, args.source_id, fps=args.fps)
            summary["plan_subtitles"] = len(subtitles)
            if args.plan_out:
                Path(args.plan_out).write_text(json.dumps(subtitles, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.command == "transcribe":
        import json
        from pathlib import Path
        from .audio import transcribe as run_transcribe
        from .subtitles import segment_words, write_srt
        result = run_transcribe(Path(args.media), model=args.model, device=args.device,
                                compute_type=args.compute, language=args.language, vad=True)
        if args.out:
            Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.srt:
            write_srt(segment_words(result["words"]), Path(args.srt))
        print(json.dumps({
            "model": result["model"], "device": result["device"], "compute_type": result["compute_type"],
            "language": result["language"], "duration_seconds": round(result["duration_seconds"], 2),
            "words": len(result["words"]),
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "mix":
        import json
        from pathlib import Path
        from .music import duck_music
        out = duck_music(Path(args.voice), Path(args.music), Path(args.out),
                         music_gain_db=args.gain, threshold=args.threshold, ratio=args.ratio)
        print(json.dumps({"output": str(out)}, ensure_ascii=False))
        return 0
    if args.command == "fcpxml":
        import json
        from pathlib import Path
        from .fcpxml import write_fcpxml
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        out = write_fcpxml(plan, Path(args.root).resolve(), Path(args.out))
        print(json.dumps({"output": str(out)}, ensure_ascii=False))
        return 0
    if args.command == "render":
        import json
        from pathlib import Path
        from .render import render_plan
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        out = render_plan(plan, Path(args.root).resolve(), Path(args.out), encoder=args.encoder,
                          quality=args.quality, subtitles=Path(args.subtitles) if args.subtitles else None)
        print(json.dumps({"output": str(out), "encoder": args.encoder}, ensure_ascii=False))
        return 0
    if args.command == "align":
        import json
        from pathlib import Path
        from .align import apply_offset, clap_offset, find_offset
        reference, target = Path(args.reference), Path(args.target)
        if args.method == "clap":
            offset = clap_offset(reference, target)
            quality = None
        else:
            offset, quality = find_offset(reference, target)
        out = apply_offset(target, Path(args.out), offset)
        print(json.dumps({"output": str(out), "offset_seconds": round(offset, 4),
                          "quality": round(quality, 4) if quality is not None else None,
                          "method": args.method}, ensure_ascii=False))
        return 0
    parser.error("comando no soportado")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
