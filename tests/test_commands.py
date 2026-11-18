"""Pruebas de instrucciones en lenguaje natural → JSON Patch."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.commands import parse_instruction, parse_time, run_instruction  # noqa: E402
from video_ai.plan_builder import build_plan  # noqa: E402
from video_ai.revisions import RevisionStore  # noqa: E402


def base_plan() -> dict:
    sources = [
        {"id": "screen", "sha256": "0" * 64, "path_rel": "screen.mp4", "kind": "video",
         "role": "screen", "duration_frames": 900},
    ]
    candidates = [
        {"kind": "silence", "start_frame": 100, "end_frame": 150, "reason": "silencio",
         "confidence": 1.0, "risk": "automatic", "affects_meaning": False,
         "approval": "not_required", "evidence": ["silencedetect"]},
        {"kind": "repetition", "start_frame": 300, "end_frame": 360, "reason": "repetición",
         "confidence": 0.7, "risk": "human_review", "affects_meaning": True,
         "approval": "approved", "evidence": ["transcript"]},
    ]
    return build_plan("nl", sources, candidates)


class ParseTimeTest(unittest.TestCase):
    def test_variants(self) -> None:
        self.assertEqual(parse_time("3"), 3.0)
        self.assertEqual(parse_time("3,5s"), 3.5)
        self.assertEqual(parse_time("1:02.5"), 62.5)
        self.assertEqual(parse_time("2 minutos"), 120.0)


class ParseInstructionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = base_plan()

    def test_cut_range(self) -> None:
        intent = parse_instruction("corta de 3 a 5 segundos", self.plan)
        self.assertEqual(intent.action, "cut_range")
        value = intent.ops[0]["value"]
        self.assertEqual((value["source_in"], value["source_out"]), (90, 150))
        self.assertEqual(value["approval"], "approved")
        self.assertEqual(value["targets"], ["screen"])

    def test_remove_cut_by_number(self) -> None:
        intent = parse_instruction("quita el corte 2", self.plan)
        self.assertEqual(intent.ops[0]["path"], "/edits/cuts/1")
        self.assertEqual(intent.ops[0]["op"], "remove")

    def test_approve_single(self) -> None:
        intent = parse_instruction("aprueba el corte 2", self.plan)
        self.assertEqual(intent.ops[0]["value"], "approved")
        self.assertEqual(intent.ops[0]["path"], "/edits/cuts/1/approval")
        self.assertTrue(intent.affects_meaning)

    def test_reject_by_meaning(self) -> None:
        intent = parse_instruction("rechaza todos los cortes que afectan al significado", self.plan)
        self.assertEqual(len(intent.ops), 1)
        self.assertEqual(intent.ops[0]["value"], "rejected")

    def test_approve_by_category(self) -> None:
        intent = parse_instruction("aprueba las repeticiones", self.plan)
        self.assertEqual(intent.ops[0]["path"], "/edits/cuts/1/approval")
        self.assertEqual(intent.ops[0]["value"], "approved")

    def test_approve_muletillas(self) -> None:
        sources = [{"id": "screen", "sha256": "0" * 64, "path_rel": "screen.mp4",
                    "kind": "video", "role": "screen", "duration_frames": 900}]
        candidates = [{"kind": "filler", "start_frame": 10, "end_frame": 20, "reason": "muletilla",
                       "confidence": 0.9, "risk": "human_review", "affects_meaning": False,
                       "approval": "pending", "evidence": ["transcript"]}]
        plan = build_plan("f", sources, candidates)
        intent = parse_instruction("aprueba las muletillas", plan)
        self.assertEqual(intent.ops[0]["value"], "approved")

    def test_redact_range(self) -> None:
        intent = parse_instruction("difumina de 10 a 12 segundos", self.plan)
        self.assertEqual(intent.action, "redact_range")
        value = intent.ops[0]["value"]
        self.assertEqual((value["source_in"], value["source_out"]), (300, 360))
        self.assertEqual(value["method"], "blur")

    def test_set_goal(self) -> None:
        intent = parse_instruction("el objetivo es aprender a usar la terminal", self.plan)
        self.assertEqual(intent.ops[0]["path"], "/intent/goal")
        self.assertEqual(intent.ops[0]["value"], "aprender a usar la terminal")

    def test_unknown_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_instruction("hazme un café", self.plan)


def marker_words() -> list[dict]:
    # Habla con "vamos alla" y "adios" en tiempos conocidos (fps=30).
    return [
        {"word": "bueno", "start": 0.0, "end": 0.4},
        {"word": "vamos", "start": 2.0, "end": 2.3},
        {"word": "allá,", "start": 2.3, "end": 2.6},
        {"word": "contenido", "start": 4.0, "end": 4.5},
        {"word": "adiós.", "start": 20.0, "end": 20.4},
    ]


class MarkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = base_plan()
        self.words = marker_words()

    def test_start_by_phrase(self) -> None:
        intent = parse_instruction('empieza cuando diga "vamos allá"', self.plan, self.words)
        self.assertEqual(intent.action, "marker")
        value = intent.ops[0]["value"]
        self.assertEqual(value["source_in"], 0)
        self.assertEqual(value["source_out"], int(2.0 * 30))  # empieza en la frase
        self.assertEqual(value["approval"], "approved")

    def test_end_by_phrase(self) -> None:
        intent = parse_instruction('termina tras decir "adiós"', self.plan, self.words)
        value = intent.ops[0]["value"]
        self.assertEqual(value["source_in"], int(20.4 * 30))
        self.assertEqual(value["source_out"], 900)  # hasta el final

    def test_phrase_not_in_transcript_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_instruction('empieza cuando diga "nunca lo dije"', self.plan, self.words)

    def test_marker_needs_words(self) -> None:
        with self.assertRaises(ValueError):
            parse_instruction('empieza cuando diga "vamos allá"', self.plan)


class CatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        sources = [
            {"id": "screen", "sha256": "0" * 64, "path_rel": "screen.mp4", "kind": "video",
             "role": "screen", "duration_frames": 900, "width": 1920, "height": 1080},
            {"id": "webcam", "sha256": "1" * 64, "path_rel": "cam.mp4", "kind": "video",
             "role": "webcam", "duration_frames": 900, "width": 1920, "height": 1080},
        ]
        self.plan = build_plan("cat", sources, [])
        self.plan["edits"]["subtitles"] = [
            {"id": "sub-0001", "timeline_in": 10, "timeline_out": 40, "text": "Hola", "style": "tutorial"}]

    def test_layout_top_left(self) -> None:
        intent = parse_instruction("pon la webcam arriba a la izquierda al 30%", self.plan)
        self.assertEqual(intent.action, "layout")
        value = intent.ops[0]["value"]
        self.assertAlmostEqual(value["x"], 0.03, places=3)
        self.assertAlmostEqual(value["y"], 0.03, places=3)
        self.assertAlmostEqual(value["scale"], 0.30, places=3)
        self.assertIn("/timeline/tracks/1/items/0/transform", intent.ops[0]["path"])

    def test_layout_max_height_caps_scale(self) -> None:
        intent = parse_instruction(
            "pon la webcam arriba a la izquierda al 60% sin pasar del 45% del alto", self.plan)
        self.assertEqual(intent.action, "layout")
        self.assertAlmostEqual(intent.ops[0]["value"]["scale"], 0.45, places=3)
        self.assertIn("alto máximo", intent.summary)

    def test_layout_crop_ratio(self) -> None:
        intent = parse_instruction("recorta la webcam a 3:4", self.plan)
        self.assertEqual(intent.action, "layout")
        self.assertAlmostEqual(intent.ops[0]["value"]["fit_aspect"], 4 / 3, places=3)
        self.assertEqual(intent.ops[0]["value"]["focus"], "center")

    def test_layout_square(self) -> None:
        intent = parse_instruction("pon el recuadro en formato cuadrado", self.plan)
        self.assertAlmostEqual(intent.ops[0]["value"]["fit_aspect"], 1.0, places=3)

    def test_layout_crop_focus(self) -> None:
        intent = parse_instruction("recorta la webcam a 3:4 con encuadre arriba", self.plan)
        self.assertEqual(intent.ops[0]["value"]["focus"], "top")

    def test_layout_max_height_needs_dimensions(self) -> None:
        sources = [
            {"id": "screen", "sha256": "0" * 64, "path_rel": "screen.mp4", "kind": "video",
             "role": "screen", "duration_frames": 900},
            {"id": "webcam", "sha256": "1" * 64, "path_rel": "cam.mp4", "kind": "video",
             "role": "webcam", "duration_frames": 900},
        ]
        plan = build_plan("nodim", sources, [])
        with self.assertRaises(ValueError):
            parse_instruction("pon la webcam al 16% sin pasar del 45% del alto", plan)

    def test_audio_normalization(self) -> None:
        intent = parse_instruction("normaliza el audio a -14 LUFS", self.plan)
        self.assertEqual(intent.action, "audio_normalization")
        self.assertEqual(intent.ops[0]["path"], "/audio/normalization/target_lufs")
        self.assertEqual(intent.ops[0]["value"], -14.0)

    def test_subtitles_off(self) -> None:
        plan = base_plan()
        plan["edits"]["subtitles"] = [{"id": "s", "timeline_in": 1, "timeline_out": 2, "text": "x"}]
        intent = parse_instruction("quita los subtítulos", plan)
        self.assertEqual(intent.action, "subtitles_off")
        self.assertEqual(intent.ops[0]["value"], [])

    def test_subtitles_style(self) -> None:
        intent = parse_instruction("subtítulos minimalistas", self.plan)
        self.assertEqual(intent.action, "subtitles_style")
        self.assertEqual(intent.ops[0]["path"], "/edits/subtitles/0/style")
        self.assertEqual(intent.ops[0]["value"], "minimal")


class RunInstructionTest(unittest.TestCase):
    def test_saves_new_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RevisionStore(Path(tmp))
            store.save(base_plan())
            result = run_instruction(store, "corta de 3 a 5 segundos")
            self.assertEqual(result["revision"], 2)
            self.assertEqual(result["parent_revision"], 1)
            latest = store.current()
            self.assertEqual(latest["revision"], 2)
            self.assertEqual(len(latest["edits"]["cuts"]), 3)

    def test_conflict_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RevisionStore(Path(tmp))
            store.save(base_plan())
            run_instruction(store, "corta de 3 a 5 segundos")
            with self.assertRaises(ValueError):
                run_instruction(store, "corta de 6 a 7 segundos", base_revision=1)


if __name__ == "__main__":
    unittest.main()
