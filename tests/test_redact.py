"""Pruebas del horneado de redacciones en copias de la fuente."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.ingest import sha256_file  # noqa: E402
from video_ai.plan import semantic_errors, validate  # noqa: E402
from video_ai.plan_builder import build_plan  # noqa: E402
from video_ai.redact import apply_box_redactions, bake_redactions  # noqa: E402
from video_ai.vision import detect_sensitive, ocr_backend, ocr_image  # noqa: E402

SECRET = Path(__file__).resolve().parent / "fixtures" / "vision" / "secret.mp4"
API_KEY_BOX = {"x": 0.023, "y": 0.067, "width": 0.697, "height": 0.163}


@unittest.skipUnless(SECRET.is_file(), "genera las fixtures con scripts/make_vision_fixture.sh")
class RedactTest(unittest.TestCase):
    def test_bake_updates_source_and_clears_redactions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy(SECRET, root / "secret.mp4")
            sources = [{"id": "secret", "sha256": sha256_file(root / "secret.mp4"),
                        "path_rel": "secret.mp4", "kind": "video", "role": "screen",
                        "duration_frames": 90}]
            plan = build_plan("redact", sources, [], fps=30.0, width=1000, height=320,
                              redactions=[{"id": "redact-0001", "source": "secret", "source_in": 0,
                                           "source_out": 90, "method": "blur", "boxes": [API_KEY_BOX]}])
            self.assertEqual(plan["edits"]["redactions"][0]["source"], "secret")
            baked = bake_redactions(plan, root, root / "baked")
            self.assertEqual(baked["edits"]["redactions"], [])
            self.assertEqual(baked["sources"][0]["sha256"], sha256_file(root / "baked" / "secret-redacted.mp4"))
            self.assertEqual(baked["sources"][0]["redacted_from"], "secret.mp4")
            self.assertEqual(validate(baked, root)["errors"], [])
            self.assertEqual(semantic_errors(baked, root), [])
            # El original no se ha tocado.
            self.assertEqual(sha256_file(root / "secret.mp4"), sources[0]["sha256"])


@unittest.skipUnless(SECRET.is_file(), "genera las fixtures con scripts/make_vision_fixture.sh")
class RedactOcrTest(unittest.TestCase):
    @unittest.skipUnless(ocr_backend() is not None, "sin backend de OCR")
    def test_secret_not_readable_after_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "redacted.mp4"
            apply_box_redactions(
                SECRET,
                [{"source_in": 0, "source_out": 90, "boxes": [API_KEY_BOX]}],
                out, fps=30.0,
            )
            frame = Path(tmp) / "frame.png"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-ss", "0.5", "-i", str(out), "-frames:v", "1", str(frame)], check=True)
            words = ocr_image(frame)
            kinds = {hit.kind for hit in detect_sensitive(words)}
            self.assertNotIn("api_key", kinds)
            self.assertNotIn("sk-ABCDEF", " ".join(word.text for word in words))


if __name__ == "__main__":
    unittest.main()
