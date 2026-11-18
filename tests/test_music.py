"""Pruebas del ducking de música."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from video_ai.music import duck_music, duck_music_only, mean_volume_db  # noqa: E402


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True)


def _voice_and_music(work: Path) -> tuple[Path, Path]:
    """Voz: tono 1 kHz de 0-1 s y silencio de 1-4 s. Música: tono constante 440 Hz."""
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
          "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "4",
          "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[out]", "-map", "[out]",
          "-c:a", "pcm_s16le", str(work / "voice.wav")])
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:a", "pcm_s16le", str(work / "music.wav")])
    return work / "voice.wav", work / "music.wav"


class DuckingTest(unittest.TestCase):
    def test_music_louder_when_no_voice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            voice, music = _voice_and_music(work)
            ducked = duck_music_only(voice, music, work / "ducked.wav",
                                     music_gain_db=-6.0, threshold=0.05, ratio=8.0, release_ms=200.0)
            with_voice = mean_volume_db(ducked, 0.1, 0.8)   # voz activa -> música atenuada
            without_voice = mean_volume_db(ducked, 2.0, 1.5)  # silencio -> música al nivel
            self.assertGreater(without_voice, with_voice + 2.0,
                               f"no se atenuó: con voz {with_voice}, sin voz {without_voice}")

    def test_mix_keeps_voice_and_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            voice, music = _voice_and_music(work)
            out = duck_music(voice, music, work / "mixed.wav", music_gain_db=-6.0)
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(out)],
                capture_output=True, text=True, check=True)
            self.assertGreater(float(result.stdout.strip()), 3.5)


if __name__ == "__main__":
    unittest.main()
