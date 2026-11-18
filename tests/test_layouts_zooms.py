"""Pruebas de composición (PiP) y de zooms desde el cursor."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.layouts import picture_in_picture, picture_transform  # noqa: E402
from video_ai.plan import validate  # noqa: E402
from video_ai.plan_builder import build_plan  # noqa: E402
from video_ai.zooms import attach_zooms, zooms_from_dwells  # noqa: E402


def two_source_plan(cuts: list[dict] | None = None) -> dict:
    sources = [
        {"id": "screen", "sha256": "0" * 64, "path_rel": "screen.mp4", "kind": "video",
         "role": "screen", "duration_frames": 300},
        {"id": "cam", "sha256": "1" * 64, "path_rel": "cam.mp4", "kind": "video",
         "role": "webcam", "duration_frames": 300},
    ]
    return build_plan("comp", sources, cuts or [], fps=30.0, primary_source="screen")


class LayoutTest(unittest.TestCase):
    def test_positions(self) -> None:
        tr = picture_transform(position="bottom-right", scale=0.25, margin=0.02,
                               aspect=9 / 16, canvas_aspect=16 / 9)
        # Con lienzo 16:9 y capa 16:9, el alto en fracción coincide con `scale`.
        self.assertAlmostEqual(tr["x"], 1 - 0.02 - 0.25, places=3)
        self.assertAlmostEqual(tr["y"], 1 - 0.02 - 0.25, places=3)
        self.assertLess(tr["x"] + 0.25, 1.0)
        self.assertLess(tr["y"] + 0.25, 1.0)

    def test_vertical_webcam_is_taller(self) -> None:
        tr = picture_transform(scale=0.25, margin=0.02, aspect=16 / 9, canvas_aspect=16 / 9)
        height_fraction = 1 - 0.02 - tr["y"]
        # Una capa vertical (9:16) ocupa mucho más alto que el 25 % del ancho.
        self.assertGreater(height_fraction, 0.5)

    def test_max_height_caps_scale(self) -> None:
        # Móvil vertical 480x854 en lienzo 1080p: con 16 % de ancho el alto
        # natural supera el 45 %, así que la escala se reduce para respetarlo.
        aspect = 854 / 480
        canvas_aspect = 1920 / 1080
        tr = picture_transform(scale=0.16, margin=0.03, aspect=aspect,
                               canvas_aspect=canvas_aspect, max_height=0.45)
        height_fraction = tr["scale"] * aspect * canvas_aspect
        self.assertAlmostEqual(height_fraction, 0.45, places=3)
        self.assertLess(tr["scale"], 0.16)

    def test_max_height_not_applied_when_smaller(self) -> None:
        # Capa 16:9: a 10 % de ancho el alto es ~10 %, no salta el tope del 45 %.
        tr = picture_transform(scale=0.10, margin=0.03, aspect=9 / 16,
                               canvas_aspect=16 / 9, max_height=0.45)
        self.assertAlmostEqual(tr["scale"], 0.10, places=4)

    def test_max_height_out_of_range(self) -> None:
        with self.assertRaises(ValueError):
            picture_transform(scale=0.2, max_height=1.5)

    def test_fit_aspect_sets_box_and_marks_transform(self) -> None:
        aspect = 854 / 480  # móvil vertical
        canvas_aspect = 1920 / 1080
        tr = picture_transform(scale=0.16, margin=0.03, aspect=aspect,
                               canvas_aspect=canvas_aspect, fit_aspect=4 / 3, focus="top")
        self.assertEqual(tr["focus"], "top")
        self.assertAlmostEqual(tr["fit_aspect"], 4 / 3, places=3)
        # El alto usa la proporción de la caja, no la del móvil.
        self.assertAlmostEqual(tr["scale"] * (4 / 3) * canvas_aspect,
                               0.16 * (4 / 3) * canvas_aspect, places=3)
        self.assertNotAlmostEqual(tr["scale"] * aspect * canvas_aspect,
                                  0.16 * (4 / 3) * canvas_aspect, places=2)

    def test_no_fit_aspect_leaves_transform_minimal(self) -> None:
        self.assertNotIn("fit_aspect", picture_transform(scale=0.16))

    def test_fit_aspect_with_max_height_caps(self) -> None:
        # Caja 4:3 sobre lienzo 16:9: alto por unidad de ancho = 1,33·1,78 ≈ 2,37.
        tr = picture_transform(scale=0.3, fit_aspect=4 / 3, canvas_aspect=16 / 9,
                               max_height=0.45)
        self.assertAlmostEqual(tr["scale"] * (4 / 3) * (16 / 9), 0.45, places=3)

    def test_focus_validated(self) -> None:
        with self.assertRaises(ValueError):
            picture_transform(scale=0.2, focus="middle")

    def test_cannot_fit(self) -> None:
        with self.assertRaises(ValueError):
            picture_transform(scale=0.9, margin=0.2, aspect=9 / 16)

    def test_pip_sets_transform_and_validates(self) -> None:
        plan = two_source_plan()
        result = picture_in_picture(plan, "cam", position="bottom-right", scale=0.3)
        cam_track = next(track for track in result["timeline"]["tracks"] if track["id"] == "V2")
        self.assertTrue(all("transform" in item for item in cam_track["items"]))
        self.assertEqual(validate(result)["errors"], [])
        # El original no se modifica.
        self.assertNotIn("transform", plan["timeline"]["tracks"][1]["items"][0])

    def test_pip_passes_max_height(self) -> None:
        plan = two_source_plan()
        # capa "cam" declarada 9/16 por defecto por `picture_transform`; se pasa
        # un tope de alto inexistente para comprobar que se propaga.
        result = picture_in_picture(plan, "cam", scale=0.4, max_height=0.3, aspect=9 / 16)
        cam_track = next(track for track in result["timeline"]["tracks"] if track["id"] == "V2")
        self.assertLessEqual(cam_track["items"][0]["transform"]["scale"], 0.4)


class ZoomTest(unittest.TestCase):
    def test_zoom_after_cut_is_shifted(self) -> None:
        cut = [{"kind": "silence", "start_frame": 100, "end_frame": 150, "reason": "silencio",
                "confidence": 1.0, "risk": "automatic", "affects_meaning": False,
                "approval": "not_required", "evidence": ["silencedetect"]}]
        plan = two_source_plan(cut)
        dwells = [{"start_frame": 160, "end_frame": 190, "start": 160 / 30, "end": 190 / 30,
                   "x": 0.4, "y": 0.6, "risk": "human_review"}]
        zooms = zooms_from_dwells(plan, dwells, "screen", magnification=1.6, lead_frames=6, tail_frames=18)
        self.assertEqual(len(zooms), 1)
        # 160 -> timeline 110; menos lead 6 = 104.
        self.assertEqual(zooms[0]["timeline_in"], 104)
        self.assertEqual(zooms[0]["target"], "screen-full-s1")
        self.assertEqual(zooms[0]["center_x"], 0.4)

    def test_dwell_inside_cut_is_dropped(self) -> None:
        cut = [{"kind": "silence", "start_frame": 100, "end_frame": 150, "reason": "silencio",
                "confidence": 1.0, "risk": "automatic", "affects_meaning": False,
                "approval": "not_required", "evidence": ["silencedetect"]}]
        plan = two_source_plan(cut)
        dwells = [{"start_frame": 120, "end_frame": 140, "start": 4.0, "end": 4.6, "x": 0.5, "y": 0.5}]
        self.assertEqual(zooms_from_dwells(plan, dwells, "screen"), [])

    def test_attach_validates(self) -> None:
        plan = two_source_plan()
        dwells = [{"start_frame": 10, "end_frame": 40, "start": 10 / 30, "end": 40 / 30, "x": 0.5, "y": 0.5}]
        zooms = zooms_from_dwells(plan, dwells, "screen")
        result = attach_zooms(plan, zooms)
        self.assertEqual(validate(result)["errors"], [])
        self.assertEqual(len(result["edits"]["zooms"]), 1)


if __name__ == "__main__":
    unittest.main()
