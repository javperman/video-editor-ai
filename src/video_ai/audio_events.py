"""Detección local de silencios, muletillas y repeticiones sobre el análisis."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

SILENCE_START = re.compile(r"silence_start:\s*([\d.]+)")
SILENCE_END = re.compile(r"silence_end:\s*([\d.]+)")
FILLERS = {"eh", "em", "mmm", "este", "bueno", "pues", "o sea", "es que", "en plan"}
PUNCTUATION = ".,;:!?¡¿()[]{}\"'\u201c\u201d"


def _duration_seconds(media: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(media)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def detect_silences(media: Path, noise_db: int = -35, min_seconds: float = 0.5) -> list[dict[str, float]]:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(media),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_seconds}", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    starts = [float(match) for match in SILENCE_START.findall(result.stderr)]
    ends = [float(match) for match in SILENCE_END.findall(result.stderr)]
    total = _duration_seconds(media)
    silences = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else total
        silences.append({"start": start, "end": end, "duration": max(0.0, end - start)})
    return silences


def _clean(word: str) -> str:
    return word.strip().strip(PUNCTUATION).lower()


def detect_fillers(words: list[dict[str, Any]], pause_seconds: float = 0.25) -> list[dict[str, Any]]:
    """Detecta muletillas reales, no palabras con función gramatical.

    Una palabra como «este» solo es muletilla si va aislada por una pausa o se
    repite. «Este es un tutorial» **no** se marca. Riesgo `human_review`: nunca
    se corta sin aprobación, porque puede alterar el significado.
    """
    candidates = []
    for index, word in enumerate(words):
        cleaned = _clean(str(word.get("word", "")))
        if cleaned not in FILLERS:
            continue
        previous = words[index - 1] if index > 0 else None
        following = words[index + 1] if index + 1 < len(words) else None
        pause_before = previous is not None and (float(word["start"]) - float(previous["end"])) >= pause_seconds
        pause_after = following is not None and (float(following["start"]) - float(word["end"])) >= pause_seconds
        repeated = (previous is not None and _clean(str(previous.get("word", ""))) in FILLERS) or \
                   (following is not None and _clean(str(following.get("word", ""))) in FILLERS)
        isolated = previous is None and following is None
        if not (pause_before or pause_after or repeated or isolated):
            continue
        candidates.append({
            "kind": "filler",
            "start": float(word["start"]),
            "end": float(word["end"]),
            "reason": f"muletilla aislada: {cleaned!r}",
            "confidence": float(word.get("probability") or 0.5),
            "risk": "human_review",
            "affects_meaning": False,
            "approval": "pending",
            "context_before": _clean(str(previous.get("word", ""))) if previous is not None else "",
            "context_after": _clean(str(following.get("word", ""))) if following is not None else "",
            "evidence": ["transcript"],
        })
    return candidates


def detect_repetitions(words: list[dict[str, Any]], max_n: int = 4) -> list[dict[str, Any]]:
    tokens = [_clean(str(word.get("word", ""))) for word in words]
    candidates = []
    index = 0
    while index < len(tokens):
        matched = False
        for size in range(2, max_n + 1):
            first = tokens[index:index + size]
            second = tokens[index + size:index + 2 * size]
            if len(first) == size and first == second and all(first):
                candidates.append({
                    "kind": "repetition",
                    "start": float(words[index]["start"]),
                    "end": float(words[index + 2 * size - 1]["end"]),
                    "reason": "repetición consecutiva: " + " ".join(first),
                    "confidence": 0.7,
                    "risk": "human_review",
                    "affects_meaning": True,
                    "approval": "pending",
                    "context_before": " ".join(tokens[max(0, index - 3):index]),
                    "context_after": " ".join(tokens[index + 2 * size:index + 2 * size + 3]),
                    "evidence": ["transcript"],
                })
                index += 2 * size
                matched = True
                break
        if not matched:
            index += 1
    return candidates


def analyze_audio(
    media: Path,
    words: list[dict[str, Any]],
    fps: float = 30.0,
    *,
    noise_db: int = -35,
    min_seconds: float = 0.5,
    min_cut: float = 1.2,
    auto_seconds: float = 1.5,
) -> dict[str, Any]:
    silences = detect_silences(media, noise_db=noise_db, min_seconds=min_seconds)
    candidates: list[dict[str, Any]] = []
    for silence in silences:
        if silence["duration"] < min_cut:
            continue
        candidates.append({
            "kind": "silence",
            "start": silence["start"],
            "end": silence["end"],
            "reason": f"silencio de {silence['duration']:.2f}s",
            "confidence": 1.0,
            "risk": "automatic" if silence["duration"] >= auto_seconds else "conservative",
            "affects_meaning": False,
            "approval": "not_required",
            "context_before": "",
            "context_after": "",
            "evidence": ["silencedetect"],
        })
    candidates.extend(detect_fillers(words))
    candidates.extend(detect_repetitions(words))
    for candidate in candidates:
        candidate["start_frame"] = int(round(candidate["start"] * fps))
        candidate["end_frame"] = int(round(candidate["end"] * fps))
    return {"candidates": candidates, "silence_count": len(silences)}
