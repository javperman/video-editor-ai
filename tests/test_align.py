"""Pruebas de alineado de audio (voz aparte)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.align import apply_offset, clap_offset, detect_clap, find_offset, make_time_aligned  # noqa: E402

ESPEAK = Path("/usr/bin/espeak-ng")


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True)


@unittest.skipUnless(ESPEAK.is_file(), "falta espeak-ng")
class AlignTest(unittest.TestCase):
    def _speech(self, path: Path) -> None:
        _run([str(ESPEAK), "-v", "es", "-s", "150", "-w", str(path),
              "Uno dos tres cuatro cinco seis siete ocho nueve diez."])

    def _av(self, path: Path, speech: Path) -> None:
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
              "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25:duration=3",
              "-i", str(speech), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
              "-c:a", "aac", str(path)])

    def _wav(self, media: Path, out: Path) -> None:
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(media),
              "-vn", "-ac", "1", "-ar", "16000", str(out)])

    def test_make_time_aligned_trims_late_webcam(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            speech = work / "s.wav"
            self._speech(speech)
            base = work / "base.mp4"
            self._av(base, speech)
            delay = 0.6
            delayed = work / "delayed.mp4"
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(base),
                  "-vf", f"tpad=start_duration={delay}:start_mode=add:color=black",
                  "-af", f"adelay={int(delay*1000)}|{int(delay*1000)}",
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(delayed)])
            self._wav(base, work / "b.wav")
            self._wav(delayed, work / "d.wav")
            offset, _ = find_offset(work / "b.wav", work / "d.wav")
            self.assertAlmostEqual(offset, delay, delta=0.08)
            aligned = make_time_aligned(delayed, work / "aligned.mp4", offset)
            self._wav(aligned, work / "a.wav")
            residual, _ = find_offset(work / "b.wav", work / "a.wav")
            self.assertLess(abs(residual), 0.08)

    def test_make_time_aligned_pads_early_webcam(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            speech = work / "s.wav"
            self._speech(speech)
            base = work / "base.mp4"
            self._av(base, speech)
            lead = 0.6
            advanced = work / "advanced.mp4"
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                  "-ss", str(lead), "-i", str(base),
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(advanced)])
            self._wav(base, work / "b.wav")
            self._wav(advanced, work / "d.wav")
            offset, _ = find_offset(work / "b.wav", work / "d.wav")
            self.assertAlmostEqual(offset, -lead, delta=0.08)
            aligned = make_time_aligned(advanced, work / "aligned.mp4", offset)
            self._wav(aligned, work / "a.wav")
            residual, _ = find_offset(work / "b.wav", work / "a.wav")
            self.assertLess(abs(residual), 0.08)

    def test_find_offset_recovers_delay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            reference = work / "ref.wav"
            self._speech(reference)
            delayed = work / "delayed.wav"
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(reference),
                  "-af", "adelay=1300|1300", "-c:a", "pcm_s16le", str(delayed)])
            offset, quality = find_offset(reference, delayed)
            self.assertAlmostEqual(offset, 1.3, delta=0.05)
            self.assertGreater(quality, 0.2)

    def test_apply_offset_then_aligned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            reference = work / "ref.wav"
            self._speech(reference)
            delayed = work / "delayed.wav"
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(reference),
                  "-af", "adelay=800|800", "-c:a", "pcm_s16le", str(delayed)])
            offset, _ = find_offset(reference, delayed)
            fixed = apply_offset(delayed, work / "fixed.wav", offset)
            residual, _ = find_offset(reference, fixed)
            self.assertLess(abs(residual), 0.05)

    def test_clap_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            silence = work / "sil.wav"
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                  "-i", "anullsrc=r=22050:cl=mono", "-t", "0.5", "-c:a", "pcm_s16le", str(silence)])
            click = work / "click.wav"
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                  "-i", "sine=frequency=2000:duration=0.05", "-c:a", "pcm_s16le", str(click)])
            tail = work / "tail.wav"
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                  "-i", "anullsrc=r=22050:cl=mono", "-t", "1.0", "-c:a", "pcm_s16le", str(tail)])
            clap = work / "clap.wav"
            (work / "list.txt").write_text(
                f"file '{silence}'\nfile '{click}'\nfile '{tail}'\n", encoding="utf-8")
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                  "-i", str(work / "list.txt"), "-c:a", "pcm_s16le", str(clap)])
            at = detect_clap(clap)
            self.assertAlmostEqual(at, 0.5, delta=0.05)
            # Otra pista con 1 s de silencio delante: su palmada va 1 s después.
            other = work / "other.wav"
            (work / "list2.txt").write_text(
                f"file '{tail}'\nfile '{clap}'\n", encoding="utf-8")
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                  "-i", str(work / "list2.txt"), "-c:a", "pcm_s16le", str(other)])
            self.assertAlmostEqual(clap_offset(clap, other), 1.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
