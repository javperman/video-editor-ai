"""Pruebas de exportación a FCPXML."""

from __future__ import annotations

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.fcpxml import build_fcpxml, write_fcpxml  # noqa: E402
from video_ai.plan_builder import build_plan  # noqa: E402


def plan() -> dict:
    sources = [
        {"id": "screen", "sha256": "0" * 64, "path_rel": "screen.mp4", "kind": "video",
         "role": "screen", "duration_frames": 300},
        {"id": "voice", "sha256": "1" * 64, "path_rel": "voice.wav", "kind": "audio",
         "role": "voice", "duration_frames": 300},
    ]
    cuts = [{"kind": "silence", "start_frame": 100, "end_frame": 150, "reason": "silencio",
             "confidence": 1.0, "risk": "automatic", "affects_meaning": False,
             "approval": "not_required", "evidence": ["silencedetect"]}]
    return build_plan("fcpx", sources, cuts, fps=30.0)


class FcpxmlTest(unittest.TestCase):
    def test_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("screen.mp4", "voice.wav"):
                (root / name).write_bytes(b"x")
            xml = build_fcpxml(plan(), root)
            document = ET.fromstring(xml)
            self.assertEqual(document.tag, "fcpxml")
            self.assertEqual(document.attrib["version"], "1.9")

            resources = document.find("resources")
            formats = resources.findall("format")
            assets = resources.findall("asset")
            self.assertEqual(len(formats), 1)
            self.assertEqual(formats[0].attrib["width"], "1920")
            self.assertEqual(len(assets), 2)

            clips = document.findall(".//asset-clip")
            # Corte 100-150 -> pantalla se parte en dos clips.
            self.assertEqual(len(clips), 2)
            # El segundo clip empieza en el frame 100 (150-50).
            offsets = [c.attrib["offset"] for c in clips]
            self.assertIn("100/30s", offsets)
            refs = {c.attrib["ref"] for c in clips}
            self.assertTrue(refs)  # referencia a assets

            audio = document.findall(".//audio")
            self.assertEqual(len(audio), 2)
            self.assertTrue(all("ref" in a.attrib for a in audio))

    def test_write_and_src_scheme(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "screen.mp4").write_bytes(b"x")
            (root / "voice.wav").write_bytes(b"x")
            out = write_fcpxml(plan(), root, root / "project.fcpxml")
            text = out.read_text(encoding="utf-8")
            self.assertIn("<fcpxml", text)
            self.assertIn("file://", text)
            ET.fromstring(text)


if __name__ == "__main__":
    unittest.main()
