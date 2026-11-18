"""Pruebas de detección local de eventos de audio."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.audio_events import analyze_audio, detect_fillers, detect_silences  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "spike" / "voice-es.wav"


def word(start: float, end: float, text: str) -> dict:
    return {"start": start, "end": end, "word": text, "probability": 0.9}


class FillerTest(unittest.TestCase):
    def test_demonstrative_is_not_filler(self) -> None:
        # «Este es un tutorial»: sin pausas alrededor, no es muletilla.
        words = [word(0.0, 0.3, " Este"), word(0.3, 0.5, " es"), word(0.5, 0.7, " un"),
                 word(0.7, 1.1, " tutorial")]
        self.assertEqual(detect_fillers(words), [])

    def test_isolated_filler_is_flagged_for_review(self) -> None:
        words = [word(0.0, 0.4, " Hola"), word(1.0, 1.3, " este"), word(1.3, 1.6, " bien")]
        candidates = detect_fillers(words)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["risk"], "human_review")
        self.assertEqual(candidates[0]["approval"], "pending")

    def test_repeated_filler_flagged(self) -> None:
        words = [word(0.0, 0.3, " este"), word(0.3, 0.6, " este"), word(0.6, 0.9, " claro")]
        self.assertEqual(len(detect_fillers(words)), 2)


@unittest.skipUnless(FIXTURE.is_file(), "genera el fixture con scripts/make_voice_fixture.sh")
class AudioEventsTest(unittest.TestCase):
    def test_silences_detected(self) -> None:
        silences = detect_silences(FIXTURE)
        self.assertGreaterEqual(len(silences), 1)
        self.assertTrue(any(s["duration"] >= 1.2 for s in silences))

    def test_candidates_risk_levels(self) -> None:
        result = analyze_audio(FIXTURE, words=[])
        kinds = {candidate["kind"] for candidate in result["candidates"]}
        self.assertIn("silence", kinds)
        for candidate in result["candidates"]:
            self.assertIn(candidate["risk"], {"automatic", "conservative", "human_review"})
            self.assertIn("start_frame", candidate)
            self.assertIn("end_frame", candidate)


if __name__ == "__main__":
    unittest.main()
