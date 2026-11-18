"""Pruebas de generación de subtítulos, SRT y mapeo a timeline."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.plan_builder import build_plan  # noqa: E402
from video_ai.subtitles import (  # noqa: E402
    Cue,
    build_ass,
    burn_subtitles,
    cues_to_plan_subtitles,
    format_srt,
    segment_words,
)

BASE = Path(__file__).resolve().parents[1]
SCREEN = BASE / "tests" / "fixtures" / "spike" / "screen-voice.mp4"


def words(*spec: tuple[float, float, str]) -> list[dict]:
    return [{"start": start, "end": end, "word": word} for start, end, word in spec]


class SegmentTest(unittest.TestCase):
    def test_gap_splits_cues(self) -> None:
        cues = segment_words(words((0.0, 0.4, " Hola"), (0.4, 0.9, " mundo."),
                                   (2.5, 2.9, " Adiós"), (2.9, 3.3, " mundo")))
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].text, "Hola mundo.")
        self.assertAlmostEqual(cues[0].start, 0.0)
        self.assertAlmostEqual(cues[1].start, 2.5)

    def test_period_ends_cue(self) -> None:
        cues = segment_words(words((0.0, 0.5, " Uno."), (0.5, 1.0, " Dos")))
        self.assertEqual(len(cues), 2)


class SrtTest(unittest.TestCase):
    def test_format(self) -> None:
        text = format_srt([Cue(0.0, 1.5, "Hola"), Cue(2.0, 3.25, "mundo")])
        self.assertIn("1\n00:00:00,000 --> 00:00:01,500\nHola", text)
        self.assertIn("2\n00:00:02,000 --> 00:00:03,250\nmundo", text)


class AssStyleTest(unittest.TestCase):
    def test_header_uses_real_resolution_and_scaled_font(self) -> None:
        ass = build_ass([Cue(0.0, 1.5, "Hola")], 1920, 1080, style="tutorial")
        self.assertIn("PlayResX: 1920", ass)
        self.assertIn("PlayResY: 1080", ass)
        # 1080 * 0.042 = 45 -> el tamaño NO es 36 fijo relativo a 288.
        self.assertIn(",45,", ass)
        self.assertIn("Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,Hola", ass)

    def test_multiline_and_minimal_style(self) -> None:
        ass = build_ass([Cue(0.0, 1.0, "linea1\nlinea2")], 1280, 720, style="minimal")
        self.assertIn("linea1\\Nlinea2", ass)
        self.assertIn("PlayResY: 720", ass)
        self.assertIn(",27,", ass)  # 720 * 0.038 = 27.36 -> 27

    @unittest.skipUnless(SCREEN.is_file(), "falta tests/fixtures/spike/screen-voice.mp4")
    def test_burn_produces_video(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "subs.mp4"
            burn_subtitles(SCREEN, output, [Cue(0.5, 2.0, "Hola mundo")],
                           width=1920, height=1080, style="tutorial", encoder="libx264", quality=28)
            self.assertTrue(output.is_file() and output.stat().st_size > 1000)
            self.assertTrue(output.with_suffix(".ass").is_file())


class TimelineMappingTest(unittest.TestCase):
    def test_basic(self) -> None:
        cues = [Cue(1.0, 2.0, "antes"), Cue(4.0, 4.5, "cortado")]
        subtitles = cues_to_plan_subtitles(cues, self.plan(), "a", fps=30.0)
        self.assertEqual(len(subtitles), 1)
        self.assertEqual(subtitles[0]["text"], "antes")
        self.assertLess(subtitles[0]["timeline_in"], subtitles[0]["timeline_out"])

    def test_shift_after_cut(self) -> None:
        # Un cue tras el corte (t=6s) debe desplazarse 50 frames hacia atrás.
        cues = [Cue(6.0, 6.5, "después")]
        subtitles = cues_to_plan_subtitles(cues, self.plan(), "a", fps=30.0)
        self.assertEqual(len(subtitles), 1)
        self.assertEqual(subtitles[0]["timeline_in"], int(6.0 * 30) - 50)

    @staticmethod
    def plan() -> dict:
        sources = [{"id": "a", "sha256": "0" * 64, "path_rel": "a.mp4", "kind": "video",
                    "role": "screen", "duration_frames": 300}]
        # Corte de 100 a 150 frames (3,33 s a 5 s).
        candidates = [{"kind": "silence", "start_frame": 100, "end_frame": 150, "reason": "silencio",
                       "confidence": 1.0, "risk": "automatic", "affects_meaning": False,
                       "approval": "not_required", "evidence": ["silencedetect"]}]
        return build_plan("subs", sources, candidates, fps=30.0)


if __name__ == "__main__":
    unittest.main()
