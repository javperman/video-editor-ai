"""Pruebas de compilación de cortes."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.compile import compile_timeline  # noqa: E402


def plan_with_cuts(cuts: list[dict]) -> dict:
    return {
        "schema_version": "1.0.0",
        "project_id": "cuts",
        "revision": 1,
        "parent_revision": None,
        "timebase": {"fps": 30, "width": 1920, "height": 1080},
        "sources": [
            {"id": "a", "sha256": "0" * 64, "path_rel": "a.mp4", "kind": "video", "duration_frames": 300}
        ],
        "timeline": {
            "tracks": [
                {
                    "id": "V1",
                    "kind": "video",
                    "items": [
                        {
                            "id": "i1",
                            "source": "a",
                            "source_in": 0,
                            "source_out": 300,
                            "timeline_in": 0,
                            "duration_frames": 300,
                        }
                    ],
                }
            ]
        },
        "edits": {"cuts": cuts, "layouts": [], "zooms": [], "annotations": [], "subtitles": [], "redactions": []},
        "audio": {},
        "render": {"codec": "h264", "container": "mp4"},
    }


def cut(identifier: str, start: int, end: int, risk: str, approval: str, targets: list[str] | None = None) -> dict:
    payload = {
        "id": identifier,
        "source": "a",
        "source_in": start,
        "source_out": end,
        "reason": "prueba",
        "confidence": 1.0,
        "risk": risk,
        "approval": approval,
    }
    if targets is not None:
        payload["targets"] = targets
    return payload


class CompileTest(unittest.TestCase):
    def test_automatic_cut_applied(self) -> None:
        compiled = compile_timeline(plan_with_cuts([
            cut("auto", 100, 150, "automatic", "not_required"),
            cut("review", 200, 220, "human_review", "pending"),
            cut("rejected", 50, 60, "automatic", "rejected"),
        ]))
        items = compiled["timeline"]["tracks"][0]["items"]
        self.assertEqual([(i["source_in"], i["source_out"], i["timeline_in"]) for i in items],
                         [(0, 100, 0), (150, 300, 100)])

    def test_human_review_needs_approval(self) -> None:
        compiled = compile_timeline(plan_with_cuts([
            cut("review", 200, 220, "human_review", "approved"),
        ]))
        items = compiled["timeline"]["tracks"][0]["items"]
        self.assertEqual([(i["source_in"], i["source_out"]) for i in items],
                         [(0, 200), (220, 300)])


if __name__ == "__main__":
    unittest.main()
