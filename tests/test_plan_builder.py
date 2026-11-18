"""Pruebas del constructor de plan a partir del análisis local."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.plan import semantic_errors  # noqa: E402
from video_ai.plan_builder import build_plan  # noqa: E402


class PlanBuilderTest(unittest.TestCase):
    def test_build_plan_with_cut(self) -> None:
        sources = [
            {"id": "screen", "sha256": "0" * 64, "path_rel": "screen.mp4", "kind": "video", "role": "screen", "duration_frames": 300},
            {"id": "voice", "sha256": "1" * 64, "path_rel": "voice.wav", "kind": "audio", "role": "voice", "duration_frames": 300},
        ]
        candidates = [
            {"kind": "silence", "start_frame": 100, "end_frame": 145, "reason": "silencio", "confidence": 1.0,
             "risk": "automatic", "affects_meaning": False, "approval": "not_required", "evidence": ["silencedetect"]},
        ]
        plan = build_plan("demo", sources, candidates)
        self.assertEqual([track["id"] for track in plan["timeline"]["tracks"]], ["V1", "A1"])
        self.assertEqual(plan["edits"]["cuts"][0]["targets"], ["screen", "voice"])
        self.assertEqual(semantic_errors(plan), [])


if __name__ == "__main__":
    unittest.main()
