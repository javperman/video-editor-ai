"""Pruebas del bucle de edición y entrega (deliver / apply)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.deliver import (  # noqa: E402
    apply_and_deliver,
    apply_ops_and_deliver,
    ops_disable_subtitles,
    refresh_subtitles,
    timeline_frames,
)
from video_ai.ingest import inspect  # noqa: E402
from video_ai.plan_builder import build_plan  # noqa: E402
from video_ai.revisions import RevisionStore  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
SCREEN = BASE / "tests" / "fixtures" / "spike" / "screen-voice.mp4"


def _source() -> dict:
    info = inspect(SCREEN)
    info["role"] = "screen"
    info["path_rel"] = str(SCREEN.resolve().relative_to(BASE.resolve()))
    return info


def _filler_candidate() -> dict:
    return {"kind": "filler", "start": 1.0, "end": 1.4, "reason": "muletilla aislada: 'este'",
            "confidence": 0.9, "risk": "human_review", "affects_meaning": False,
            "approval": "pending", "context_before": "y", "context_after": "es",
            "evidence": ["transcript"], "start_frame": 30, "end_frame": 42}


def _words() -> dict:
    return {"words": [
        {"word": "Hola.", "start": 0.0, "end": 0.3, "probability": 0.9},
        {"word": "mundo", "start": 5.0, "end": 5.4, "probability": 0.9},
    ]}


class RefreshSubtitlesTest(unittest.TestCase):
    def test_cut_shifts_later_cue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "transcript.json").write_text(json.dumps(_words()), encoding="utf-8")
            plan = build_plan("subs", [_source()], [], fps=30.0, width=1920, height=1080)
            refresh_subtitles(plan, work)
            self.assertEqual(len(plan["edits"]["subtitles"]), 2)
            without = {s["text"]: s["timeline_in"] for s in plan["edits"]["subtitles"]}
            self.assertEqual(without["mundo"], 150)  # 5.0 s * 30 fps

            plan2 = build_plan("subs", [_source()], [_filler_candidate()], fps=30.0,
                               width=1920, height=1080)
            # El candidato human_review no se aplica sin aprobación: no desplaza.
            refresh_subtitles(plan2, work)
            self.assertEqual({s["text"]: s["timeline_in"] for s in plan2["edits"]["subtitles"]}["mundo"], 150)


class ApplyTest(unittest.TestCase):
    def test_apply_without_render_creates_revision_and_recomputes_subs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            store = RevisionStore(work / "project", BASE)
            plan = build_plan("apply", [_source()], [_filler_candidate()], fps=30.0,
                              width=1920, height=1080)
            store.save(plan)  # revisión 1
            (work / "transcript.json").write_text(json.dumps(_words()), encoding="utf-8")

            result = apply_and_deliver(store, "aprueba el corte 1", work, BASE, render=False)
            self.assertEqual(result["revision"], 2)
            self.assertEqual(result["parent_revision"], 1)
            self.assertNotIn("render", result)

            current = store.current()
            self.assertEqual(current["edits"]["cuts"][0]["approval"], "approved")
            self.assertEqual(len(current["edits"]["subtitles"]), 2)
            # Con el corte (30-42) aplicado, el cue de 5.0 s cae antes: 150 - 12 - 12? No:
            # el corte ocupa 30..42 (12 frames). El cue empieza en 150 -> 150 - 12 = 138.
            self.assertEqual({s["text"]: s["timeline_in"] for s in current["edits"]["subtitles"]}["mundo"], 138)

    def test_unknown_instruction_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            store = RevisionStore(work / "project", BASE)
            store.save(build_plan("apply", [_source()], [], fps=30.0, width=1920, height=1080))
            with self.assertRaises(ValueError):
                apply_and_deliver(store, "hazme un café", work, BASE, render=False)
            self.assertEqual(store.current_revision(), 1)


class ApplyOpsTest(unittest.TestCase):
    def test_explicit_ops_create_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            store = RevisionStore(work / "project", BASE)
            store.save(build_plan("ops", [_source()], [], fps=30.0, width=1920, height=1080))
            ops = [{"op": "add", "path": "/intent/goal", "value": "guía paso a paso"}]
            result = apply_ops_and_deliver(store, ops, work, BASE, render=False)
            self.assertEqual(result["revision"], 2)
            self.assertEqual(store.current()["intent"]["goal"], "guía paso a paso")

    def test_disable_subtitles_detected(self) -> None:
        self.assertTrue(ops_disable_subtitles(
            [{"op": "replace", "path": "/edits/subtitles", "value": []}]))
        self.assertFalse(ops_disable_subtitles(
            [{"op": "add", "path": "/intent/goal", "value": "x"}]))

    def test_ops_emptying_subtitles_are_not_repopulated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            store = RevisionStore(work / "project", BASE)
            plan = build_plan("ops", [_source()], [], fps=30.0, width=1920, height=1080)
            plan["edits"]["subtitles"] = [{"id": "s", "timeline_in": 1, "timeline_out": 2, "text": "x"}]
            store.save(plan)
            (work / "transcript.json").write_text(json.dumps(_words()), encoding="utf-8")
            ops = [{"op": "replace", "path": "/edits/subtitles", "value": []}]
            apply_ops_and_deliver(store, ops, work, BASE, render=False)
            self.assertEqual(store.current()["edits"]["subtitles"], [])


class TimelineFramesTest(unittest.TestCase):
    def test_matches_expected(self) -> None:
        plan = build_plan("t", [_source()], [], fps=30.0, width=1920, height=1080)
        info = inspect(SCREEN)
        self.assertEqual(timeline_frames(plan), int(info["duration_frames"]))


if __name__ == "__main__":
    unittest.main()
