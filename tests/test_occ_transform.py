"""Pruebas de la conversión de `transform` plan → OpenChatCut."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.adapters.occ_transform import occ_transform_to_plan, plan_transform_to_occ  # noqa: E402
from video_ai.layouts import picture_transform  # noqa: E402


class OccTransformTest(unittest.TestCase):
    def test_identity(self) -> None:
        self.assertEqual(plan_transform_to_occ({"x": 0.0, "y": 0.0, "scale": 1.0}), {"x": 0.0, "y": 0.0, "scale": 1.0})

    def test_bottom_right_pip(self) -> None:
        transform = picture_transform(position="bottom-right", scale=0.28, margin=0.03, aspect=9 / 16)
        occ = plan_transform_to_occ(transform)
        # Desplazamiento hacia la derecha y hacia abajo.
        self.assertGreater(occ["x"], 0)
        self.assertGreater(occ["y"], 0)
        self.assertEqual(occ["scale"], 0.28)

    def test_round_trip(self) -> None:
        for transform in ({"x": 0.69, "y": 0.8, "scale": 0.3}, {"x": 0.5, "y": 0.5, "scale": 0.5}):
            occ = plan_transform_to_occ(transform)
            back = occ_transform_to_plan(occ["x"], occ["y"], occ["scale"])
            self.assertAlmostEqual(back["x"], transform["x"], places=3)
            self.assertAlmostEqual(back["y"], transform["y"], places=3)

    def test_invalid(self) -> None:
        with self.assertRaises(ValueError):
            plan_transform_to_occ({"x": 1.5, "y": 0.0, "scale": 0.5})
        with self.assertRaises(ValueError):
            plan_transform_to_occ({"x": 0.0, "y": 0.0, "scale": 0.0})


if __name__ == "__main__":
    unittest.main()
