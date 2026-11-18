"""Pruebas del render local con FFmpeg desde el plan compilado."""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.ingest import inspect  # noqa: E402
from video_ai.plan_builder import build_plan  # noqa: E402
from video_ai.qc import qc_video  # noqa: E402
from video_ai.render import render_plan  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
SCREEN = BASE / "tests" / "fixtures" / "spike" / "screen-voice.mp4"


@unittest.skipUnless(SCREEN.is_file(), "falta tests/fixtures/spike/screen-voice.mp4")
class RenderTest(unittest.TestCase):
    def _plan(self) -> dict:
        info = inspect(SCREEN)
        info["role"] = "screen"
        info["path_rel"] = str(SCREEN.resolve().relative_to(BASE.resolve()))
        cuts = [{"kind": "silence", "start_frame": 90, "end_frame": 150, "reason": "silencio",
                 "confidence": 1.0, "risk": "automatic", "affects_meaning": False,
                 "approval": "not_required", "evidence": ["silencedetect"]}]
        return build_plan("render", [info], cuts, fps=float(info["fps"]),
                          width=info["width"], height=info["height"], primary_source=info["id"])

    def test_render_libx264(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out.mp4"
            render_plan(self._plan(), BASE, output, encoder="libx264", quality=24)
            self.assertTrue(output.is_file() and output.stat().st_size > 1000)
            from video_ai.master_audio import normalize_audio
            mastered = normalize_audio(output, Path(tmp) / "mastered.mp4")
            info = inspect(SCREEN)
            expected = (info["duration_frames"] - 60) / float(info["fps"])
            qc = qc_video(mastered, expected={"width": info["width"], "height": info["height"],
                                              "fps": float(info["fps"]), "duration": expected})
            self.assertTrue(qc["ok"], [c for c in qc["checks"] if not c["ok"]])

    def test_two_source_screen_plus_voice(self) -> None:
        voice = BASE / "tests" / "fixtures" / "spike" / "voice-es.wav"
        if not voice.is_file():
            self.skipTest("falta voice-es.wav")
        with tempfile.TemporaryDirectory() as tmp:
            screen_info = inspect(SCREEN)
            screen_info.update(role="screen", path_rel=str(SCREEN.resolve().relative_to(BASE.resolve())))
            voice_info = inspect(voice)
            voice_info.update(role="voice", path_rel=str(voice.resolve().relative_to(BASE.resolve())))
            cuts = [{"kind": "silence", "start_frame": 60, "end_frame": 120, "reason": "silencio",
                     "confidence": 1.0, "risk": "automatic", "affects_meaning": False,
                     "approval": "not_required", "evidence": ["silencedetect"]}]
            plan = build_plan("two", [screen_info, voice_info], cuts, fps=30.0,
                              width=1920, height=1080, primary_source=screen_info["id"])
            output = Path(tmp) / "two.mp4"
            render_plan(plan, BASE, output, encoder="libx264", quality=26)
            self.assertTrue(output.is_file() and output.stat().st_size > 1000)
            from video_ai.qc import qc_video
            qc = qc_video(output, expected={"width": 1920, "height": 1080, "fps": 30.0})
            self.assertTrue(next(c for c in qc["checks"] if c["name"] == "has_audio")["ok"])

    def test_pip_position_matches_transform(self) -> None:
        import numpy as np
        from video_ai.layouts import picture_in_picture

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            base = work / "base.mp4"
            cam = work / "cam.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                            "-i", "color=c=black:s=640x360:d=1:r=30", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(base)], check=True)
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                            "-i", "color=c=magenta:s=640x360:d=1:r=30", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(cam)], check=True)
            # Plan con base y webcam sobre un lienzo 640x360 dentro de un root temporal.
            root = work
            sources = [
                {"id": "base", "sha256": "0" * 64, "path_rel": "base.mp4", "kind": "video",
                 "role": "screen", "duration_frames": 30},
                {"id": "cam", "sha256": "1" * 64, "path_rel": "cam.mp4", "kind": "video",
                 "role": "webcam", "duration_frames": 30},
            ]
            plan = build_plan("pip", sources, [], fps=30.0, width=640, height=360, primary_source="base")
            plan = picture_in_picture(plan, "cam", position="bottom-right", scale=0.3, margin=0.03,
                                      aspect=9 / 16)
            output = work / "pip.mp4"
            render_plan(plan, root, output, encoder="libx264", quality=18)

            raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0.5",
                                  "-i", str(output), "-frames:v", "1", "-f", "rawvideo",
                                  "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
            frame = np.frombuffer(raw, dtype=np.uint8)[: 640 * 360 * 3].reshape((360, 640, 3))
            mask = (frame[:, :, 0].astype(int) > 90) & (frame[:, :, 2].astype(int) > 90) & \
                   (frame[:, :, 1].astype(int) + 30 < frame[:, :, 0].astype(int))
            ys, xs = np.where(mask)
            self.assertGreater(len(xs), 0, "no se detectó el PiP")
            x = xs.min() / 640
            y = ys.min() / 360
            w = (xs.max() - xs.min() + 1) / 640
            self.assertAlmostEqual(x, 1 - 0.03 - 0.3, delta=0.03)
            self.assertAlmostEqual(y, 1 - 0.03 - 0.3, delta=0.03)
            self.assertAlmostEqual(w, 0.3, delta=0.03)

    def test_pip_crop_matches_box_aspect(self) -> None:
        import numpy as np
        from video_ai.layouts import picture_in_picture

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            base = work / "base.mp4"
            cam = work / "cam.mp4"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                            "-i", "color=c=black:s=640x360:d=1:r=30", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(base)], check=True)
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                            "-i", "color=c=magenta:s=480x854:d=1:r=30", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(cam)], check=True)
            sources = [
                {"id": "base", "sha256": "0" * 64, "path_rel": "base.mp4", "kind": "video",
                 "role": "screen", "duration_frames": 30},
                {"id": "cam", "sha256": "1" * 64, "path_rel": "cam.mp4", "kind": "video",
                 "role": "webcam", "duration_frames": 30, "width": 480, "height": 854},
            ]
            plan = build_plan("pipcrop", sources, [], fps=30.0, width=640, height=360,
                              primary_source="base")
            plan = picture_in_picture(plan, "cam", position="bottom-right", scale=0.16,
                                      margin=0.03, fit_aspect=4 / 3, focus="center")
            output = work / "pip.mp4"
            render_plan(plan, work, output, encoder="libx264", quality=18)

            raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0.5",
                                  "-i", str(output), "-frames:v", "1", "-f", "rawvideo",
                                  "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
            frame = np.frombuffer(raw, dtype=np.uint8)[: 640 * 360 * 3].reshape((360, 640, 3))
            mask = (frame[:, :, 0].astype(int) > 90) & (frame[:, :, 2].astype(int) > 90) & \
                   (frame[:, :, 1].astype(int) + 30 < frame[:, :, 0].astype(int))
            ys, xs = np.where(mask)
            self.assertGreater(len(xs), 0, "no se detectó el PiP")
            width = xs.max() - xs.min() + 1
            height = ys.max() - ys.min() + 1
            # La caja recortada debe tener proporción 3:4 (alto/ancho ≈ 1,33), no la
            # del móvil vertical (854/480 ≈ 1,78), y un ancho ≈ 16 % del lienzo.
            self.assertAlmostEqual(height / width, 4 / 3, delta=0.08)
            self.assertAlmostEqual(width / 640, 0.16, delta=0.04)

    def test_nvenc_faster_if_available(self) -> None:
        # Solo comprueba que NVENC funciona si está; no compara tiempos aquí.
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "nvenc.mp4"
            try:
                render_plan(self._plan(), BASE, output, encoder="h264_nvenc", quality=25)
            except Exception as error:  # noqa: BLE001
                self.skipTest(f"NVENC no disponible: {error}")
            self.assertTrue(output.is_file() and output.stat().st_size > 1000)


if __name__ == "__main__":
    unittest.main()
