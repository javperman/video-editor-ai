"""Pruebas de visión selectiva: escenas, muestreo, OCR y redacciones."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.plan import semantic_errors, validate  # noqa: E402
from video_ai.plan_builder import build_plan  # noqa: E402
from video_ai.vision import (  # noqa: E402
    OcrWord,
    adaptive_sample,
    analyze_vision,
    build_redactions,
    cursor_activity,
    detect_scenes,
    detect_sensitive,
    load_cursor_samples,
    merge_boxes,
    normalize_box,
    ocr_backend,
    ocr_image,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "vision"
CUTS = FIXTURES / "cuts.mp4"
SECRET = FIXTURES / "secret.mp4"


class SamplingTest(unittest.TestCase):
    def test_scenes_and_periodic_sample(self) -> None:
        samples = adaptive_sample([{"time": 2.0, "score": 80.0}], 6.0, fps=30.0, interval=2.0, max_frames=10)
        times = [sample["time"] for sample in samples]
        self.assertEqual(times[0], 0.0)
        self.assertIn(2.0, times)
        self.assertEqual(samples[1]["frame"], 60)
        self.assertEqual(times, sorted(times))

    def test_empty_for_zero_duration(self) -> None:
        self.assertEqual(adaptive_sample([], 0.0), [])


class SensitiveTest(unittest.TestCase):
    def test_patterns(self) -> None:
        words = [
            OcrWord("sk-ABCDEF1234567890XYZ", 0.9, 10, 10, 100, 20),
            OcrWord("ana@example.com", 0.9, 10, 40, 100, 20),
            OcrWord("normal", 0.9, 10, 70, 40, 20),
            OcrWord("contraseña", 0.9, 10, 100, 60, 20),
        ]
        kinds = {hit.kind for hit in detect_sensitive(words)}
        self.assertIn("api_key", kinds)
        self.assertIn("email", kinds)
        self.assertIn("password_label", kinds)
        self.assertEqual(len(detect_sensitive([words[2]])), 0)

    def test_normalize_clamps(self) -> None:
        hit = detect_sensitive([OcrWord("ana@example.com", 0.9, 990, 310, 40, 20)])[0]
        box = normalize_box(hit, 1000, 320)
        self.assertGreaterEqual(box["x"], 0.0)
        self.assertLessEqual(box["x"] + box["width"], 1.0)
        self.assertLessEqual(box["y"] + box["height"], 1.0)

    def test_merge_overlapping(self) -> None:
        merged = merge_boxes([
            {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1},
            {"x": 0.25, "y": 0.12, "width": 0.2, "height": 0.1},
            {"x": 0.8, "y": 0.8, "width": 0.1, "height": 0.1},
        ])
        self.assertEqual(len(merged), 2)

    def test_build_redactions_groups(self) -> None:
        hits = [
            {"kind": "api_key", "time": 1.0, "frame": 30, "box": {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1}},
            {"kind": "api_key", "time": 2.0, "frame": 60, "box": {"x": 0.12, "y": 0.1, "width": 0.2, "height": 0.1}},
            {"kind": "email", "time": 2.0, "frame": 60, "box": {"x": 0.1, "y": 0.5, "width": 0.3, "height": 0.1}},
        ]
        redactions = build_redactions(hits, source_id="src", fps=30.0)
        self.assertEqual(len(redactions), 2)
        self.assertEqual(redactions[0]["source"], "src")
        self.assertLess(redactions[0]["source_in"], redactions[0]["source_out"])


class CursorTest(unittest.TestCase):
    def test_load_and_dwell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cursor.jsonl"
            lines = []
            for step in range(0, 100):
                t = step / 30.0
                x = 500 if step < 60 else 100 + step
                y = 400
                lines.append(json.dumps({"t": round(t, 4), "x": x, "y": y, "w": 1000, "h": 800}))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            samples = load_cursor_samples(path)
            self.assertEqual(len(samples), 100)
            self.assertAlmostEqual(samples[0]["x"], 0.5)
            dwells = cursor_activity(samples, fps=30.0, dwell_seconds=1.0)
            self.assertGreaterEqual(len(dwells), 1)
            self.assertEqual(dwells[0]["risk"], "human_review")


@unittest.skipUnless(CUTS.is_file(), "genera las fixtures con scripts/make_vision_fixture.sh")
class SceneTest(unittest.TestCase):
    def test_detects_hard_cuts(self) -> None:
        scenes = detect_scenes(CUTS, threshold=20.0)
        times = [scene["time"] for scene in scenes]
        self.assertTrue(any(abs(value - 2.0) < 0.4 for value in times), times)
        self.assertTrue(any(abs(value - 4.0) < 0.4 for value in times), times)


@unittest.skipUnless(SECRET.is_file(), "genera las fixtures con scripts/make_vision_fixture.sh")
class OcrTest(unittest.TestCase):
    def test_backend_available(self) -> None:
        self.assertIsNotNone(ocr_backend(), "sin backend de OCR (rapidocr o tesseract)")
        self.assertIn(ocr_backend("tesseract"), {"tesseract", "rapidocr"})
        self.assertIn(ocr_backend("rapidocr"), {"rapidocr", "tesseract"})

    def test_ocr_reads_text(self) -> None:
        words = ocr_image(FIXTURES / "text.png")
        text = " ".join(word.text for word in words)
        self.assertIn("api_key", text)

    def test_analyze_produces_valid_redactions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = analyze_vision(SECRET, source_id="secret", fps=30.0, ocr_fps=1.0, frames_dir=Path(tmp) / "frames")
            self.assertGreaterEqual(len(result["redactions"]), 1)
            # Vídeo estático: solo se hace OCR del primer fotograma que cambia.
            self.assertEqual(result["ocr_frames_analyzed"], 1)
            self.assertGreaterEqual(result["ocr_frames_skipped"], 1)
        for redaction in result["redactions"]:
            self.assertEqual(redaction["source"], "secret")
            self.assertTrue(redaction["boxes"])
            for box in redaction["boxes"]:
                self.assertGreaterEqual(box["x"], 0.0)
                self.assertLessEqual(box["x"] + box["width"], 1.0001)
                self.assertLessEqual(box["y"] + box["height"], 1.0001)

        sources = [{"id": "secret", "sha256": "0" * 64, "path_rel": "secret.mp4",
                    "kind": "video", "role": "screen", "duration_frames": 90}]
        plan = build_plan("vision", sources, [], redactions=result["redactions"])
        self.assertEqual(validate(plan)["errors"], [])
        self.assertEqual(semantic_errors(plan), [])


if __name__ == "__main__":
    unittest.main()
