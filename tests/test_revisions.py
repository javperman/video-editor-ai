"""Pruebas de revisiones y patch, sin dependencias externas de red."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.revisions import RevisionStore  # noqa: E402


def base_plan() -> dict:
    return {
        "schema_version": "1.0.0",
        "project_id": "test",
        "revision": 1,
        "parent_revision": None,
        "timebase": {"fps": 30, "width": 1920, "height": 1080},
        "sources": [
            {
                "id": "a",
                "sha256": "0" * 64,
                "path_rel": "a.mp4",
                "kind": "video",
                "duration_frames": 300,
            }
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
        "edits": {"cuts": [], "layouts": [], "zooms": [], "annotations": [], "subtitles": [], "redactions": []},
        "audio": {},
        "render": {"codec": "h264", "container": "mp4"},
    }


class RevisionStoreTest(unittest.TestCase):
    def test_save_and_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RevisionStore(Path(temporary))
            store.save(base_plan())
            self.assertEqual(store.current_revision(), 1)
            patched = store.apply_patch([
                {"op": "add", "path": "/intent", "value": {"goal": "demo"}}
            ])
            self.assertEqual(patched["revision"], 2)
            self.assertEqual(patched["parent_revision"], 1)
            self.assertEqual(store.current_revision(), 2)

    def test_revision_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RevisionStore(Path(temporary))
            store.save(base_plan())
            with self.assertRaises(ValueError):
                store.apply_patch([{"op": "add", "path": "/intent", "value": {}}], base_revision=99)

    def test_existing_revision_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = RevisionStore(Path(temporary))
            store.save(base_plan())
            with self.assertRaises(FileExistsError):
                store.save(base_plan())


if __name__ == "__main__":
    unittest.main()
