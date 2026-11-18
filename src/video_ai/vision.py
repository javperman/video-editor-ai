"""Visión selectiva: escenas, muestreo adaptativo, OCR y datos sensibles.

Todo el análisis es local. El OCR usa `rapidocr-onnxruntime` si está instalado
en el entorno aislado y, si no, el binario `tesseract` del sistema.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCENE_TIME = re.compile(r"pts_time:([\d.]+)")
SCENE_SCORE = re.compile(r"lavfi\.scd\.score=([\d.]+)")

SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("api_key", re.compile(r"\b(?:sk|pk|rk|api[_-]?key|access[_-]?key|secret|token|bearer)[\s:=_-]*[A-Za-z0-9_\-]{16,}", re.IGNORECASE)),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
    ("long_hex", re.compile(r"\b[0-9a-fA-F]{32,}\b")),
    ("password_label", re.compile(r"\b(?:password|passwd|pwd|contrasena|clave)\b", re.IGNORECASE)),
    ("card_number", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
]


def _fold(text: str) -> str:
    """Quita diacríticos para que «contraseña» y «contrasena» coincidan."""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _duration_seconds(media: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(media)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def detect_scenes(media: Path, threshold: float = 8.0, min_gap: float = 0.4) -> list[dict[str, float]]:
    """Detecta cambios de escena con el filtro `scdet` de FFmpeg.

    `threshold` está en porcentaje (0-100). Los cortes duros suelen superar 50;
    contenido de pantalla con cambios suaves puede quedar por debajo y no
    detectarse, que es un límite conocido del detector.
    """
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(media),
         "-vf", f"scdet=threshold={threshold:g},metadata=mode=print",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    scenes: list[dict[str, float]] = []
    current_time: float | None = None
    for line in result.stderr.splitlines():
        time_match = SCENE_TIME.search(line)
        if time_match:
            current_time = float(time_match.group(1))
            continue
        score_match = SCENE_SCORE.search(line)
        if score_match and current_time is not None:
            score = float(score_match.group(1))
            if score < threshold or score <= 0:
                continue
            if scenes and current_time - scenes[-1]["time"] < min_gap:
                continue
            scenes.append({"time": round(current_time, 3), "score": round(score, 3)})
    return scenes


def adaptive_sample(
    scenes: list[dict[str, float]],
    duration: float,
    *,
    fps: float = 30.0,
    interval: float | None = None,
    min_gap: float = 0.5,
    max_frames: int = 48,
) -> list[dict[str, float]]:
    """Combina cortes de escena con un muestreo periódico determinista."""
    if duration <= 0:
        return []
    step = interval if interval and interval > 0 else max(duration / max_frames, min_gap)
    times: list[float] = [0.0]
    times.extend(scene["time"] for scene in scenes)
    cursor = step
    while cursor < duration:
        times.append(cursor)
        cursor += step
    ordered = sorted({round(value, 3) for value in times if 0.0 <= value < duration})
    selected: list[float] = []
    for value in ordered:
        if not selected or value - selected[-1] >= min_gap:
            selected.append(value)
    return [{"time": value, "frame": int(round(value * fps))} for value in selected[:max_frames]]


def extract_frames(media: Path, times: list[float], out_dir: Path, prefix: str = "frame") -> list[Path]:
    """Extrae un PNG por marca de tiempo con búsqueda rápida (-ss antes de -i)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for value in times:
        output = out_dir / f"{prefix}-{int(round(value * 1000)):09d}.png"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", f"{value:.3f}", "-i", str(media), "-frames:v", "1", str(output)],
            check=True,
        )
        paths.append(output)
    return paths


@dataclass
class OcrWord:
    text: str
    confidence: float
    x: float
    y: float
    width: float
    height: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_ENGINE: Any = None


def ocr_backend(prefer: str | None = None) -> str | None:
    """Devuelve el backend de OCR a usar.

    Orden por defecto: `tesseract` si está instalado (mejor para prosa en
    español), si no `rapidocr`. Se puede forzar con `prefer` o con la variable
    de entorno `VIDEO_AI_OCR_BACKEND` (`rapidocr`, `tesseract` o `auto`).
    """
    import os

    choice = (prefer or os.environ.get("VIDEO_AI_OCR_BACKEND") or "auto").lower()

    def has_rapidocr() -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False

    if choice == "rapidocr":
        return "rapidocr" if has_rapidocr() else ("tesseract" if shutil.which("tesseract") else None)
    if choice == "tesseract":
        return "tesseract" if shutil.which("tesseract") else ("rapidocr" if has_rapidocr() else None)
    if shutil.which("tesseract"):
        return "tesseract"
    return "rapidocr" if has_rapidocr() else None


def _rapidocr_engine() -> Any:
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def ocr_image(path: Path, backend: str | None = None) -> list[OcrWord]:
    backend = backend or ocr_backend()
    if backend == "rapidocr":
        return _ocr_rapidocr(path)
    if backend == "tesseract":
        return _ocr_tesseract(path)
    raise RuntimeError("no hay backend de OCR disponible (instala rapidocr-onnxruntime o tesseract)")


def _ocr_rapidocr(path: Path) -> list[OcrWord]:
    result, _ = _rapidocr_engine()(str(path))
    if not result:
        return []
    words: list[OcrWord] = []
    for box, text, score in result:
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        words.append(OcrWord(
            text=str(text).strip(),
            confidence=float(score),
            x=min(xs), y=min(ys),
            width=max(xs) - min(xs), height=max(ys) - min(ys),
        ))
    return words


def _ocr_tesseract(path: Path, languages: str = "spa+eng") -> list[OcrWord]:
    result = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", languages, "tsv"],
        capture_output=True, text=True,
    )
    words: list[OcrWord] = []
    lines = result.stdout.splitlines()
    if not lines:
        return words
    header = lines[0].split("\t")
    index = {name: position for position, name in enumerate(header)}
    for line in lines[1:]:
        columns = line.split("\t")
        if len(columns) <= index.get("text", 0):
            continue
        text = columns[index["text"]].strip()
        confidence = float(columns[index["conf"]] or -1)
        if not text or confidence < 0:
            continue
        words.append(OcrWord(
            text=text,
            confidence=confidence / 100.0,
            x=float(columns[index["left"]]),
            y=float(columns[index["top"]]),
            width=float(columns[index["width"]]),
            height=float(columns[index["height"]]),
        ))
    return words


@dataclass
class SensitiveHit:
    kind: str
    text: str
    x: float
    y: float
    width: float
    height: float


def detect_sensitive(words: list[OcrWord]) -> list[SensitiveHit]:
    hits: list[SensitiveHit] = []
    for word in words:
        folded = _fold(word.text)
        for kind, pattern in SENSITIVE_PATTERNS:
            if pattern.search(folded):
                hits.append(SensitiveHit(kind=kind, text=word.text, x=word.x, y=word.y,
                                         width=word.width, height=word.height))
                break
    return hits


def normalize_box(hit: SensitiveHit, frame_width: float, frame_height: float, margin: float = 0.008) -> dict[str, float]:
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("dimensiones de fotograma inválidas")
    x = max(0.0, hit.x / frame_width - margin)
    y = max(0.0, hit.y / frame_height - margin)
    width = min(1.0 - x, hit.width / frame_width + 2 * margin)
    height = min(1.0 - y, hit.height / frame_height + 2 * margin)
    return {"x": round(x, 4), "y": round(y, 4), "width": round(width, 4), "height": round(height, 4)}


def merge_boxes(boxes: list[dict[str, float]]) -> list[dict[str, float]]:
    remaining = [dict(box) for box in boxes]
    merged: list[dict[str, float]] = []
    while remaining:
        current = remaining.pop(0)
        changed = True
        while changed:
            changed = False
            for other in list(remaining):
                if _overlaps(current, other):
                    current = _union(current, other)
                    remaining.remove(other)
                    changed = True
        merged.append({key: round(value, 4) for key, value in current.items()})
    return merged


def _overlaps(a: dict[str, float], b: dict[str, float]) -> bool:
    return not (a["x"] + a["width"] < b["x"] or b["x"] + b["width"] < a["x"]
                or a["y"] + a["height"] < b["y"] or b["y"] + b["height"] < a["y"])


def _union(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    x = min(a["x"], b["x"])
    y = min(a["y"], b["y"])
    return {
        "x": x,
        "y": y,
        "width": max(a["x"] + a["width"], b["x"] + b["width"]) - x,
        "height": max(a["y"] + a["height"], b["y"] + b["height"]) - y,
    }


def build_redactions(
    hits: list[dict[str, Any]],
    *,
    source_id: str,
    fps: float = 30.0,
    pad_seconds: float = 1.5,
    merge_gap_seconds: float = 3.0,
    method: str = "blur",
) -> list[dict[str, Any]]:
    """Agrupa hallazgos sensibles en redacciones con ventana temporal y cajas.

    Cada elemento de `hits` debe incluir `kind`, `time`, `frame`, `width`,
    `height` y `box` (normalizado).
    """
    ordered = sorted(hits, key=lambda hit: (hit["kind"], hit["time"]))
    groups: list[dict[str, Any]] = []
    for hit in ordered:
        if groups:
            last = groups[-1]
            if last["kind"] == hit["kind"] and hit["time"] - last["last_time"] <= merge_gap_seconds:
                last["last_time"] = hit["time"]
                last["boxes"].append(hit["box"])
                continue
        groups.append({"kind": hit["kind"], "first_time": hit["time"], "last_time": hit["time"], "boxes": [hit["box"]]})

    redactions: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        start = max(0.0, group["first_time"] - pad_seconds)
        end = group["last_time"] + pad_seconds
        redactions.append({
            "id": f"redact-{index:04d}",
            "source": source_id,
            "source_in": int(round(start * fps)),
            "source_out": int(round(end * fps)),
            "method": method,
            "reason": f"texto sensible detectado: {group['kind']}",
            "boxes": merge_boxes(group["boxes"]),
        })
    return redactions


def analyze_vision(
    media: Path,
    *,
    source_id: str | None = None,
    fps: float = 30.0,
    threshold: float = 8.0,
    ocr_fps: float = 1.0,
    max_frames: int = 48,
    frames_dir: Path | None = None,
    backend: str | None = None,
    redact: bool = True,
    change_threshold: float = 2.0,
) -> dict[str, Any]:
    """Analiza escenas, muestrea fotogramas, aplica OCR y propone redacciones.

    `change_threshold` evita repetir OCR en fotogramas casi idénticos al anterior
    (diferencia media en escala 0-255 sobre una miniatura). Con pantalla estática
    reduce el coste de OCR drásticamente.
    """
    duration = _duration_seconds(media)
    scenes = detect_scenes(media, threshold=threshold)
    samples = adaptive_sample(scenes, duration, fps=fps, max_frames=max_frames)

    ocr_times: list[float] = []
    step = 1.0 / ocr_fps if ocr_fps > 0 else duration or 1.0
    cursor = 0.0
    while cursor < duration:
        ocr_times.append(round(cursor, 3))
        cursor += step
    if not ocr_times:
        ocr_times = [0.0]

    working_dir = frames_dir or (media.parent / f"{media.stem}-frames")
    backend = backend or ocr_backend()
    hits: list[dict[str, Any]] = []
    frame_reports: list[dict[str, Any]] = []
    skipped = 0
    previous_thumb: bytes | None = None
    for value in ocr_times:
        thumb = _gray_thumb(media, value)
        if previous_thumb is not None and change_threshold > 0 and _mean_abs_diff(previous_thumb, thumb) < change_threshold:
            skipped += 1
            continue
        previous_thumb = thumb
        frame_path = extract_frames(media, [value], working_dir)[0]
        words = ocr_image(frame_path, backend=backend)
        frame_hits = detect_sensitive(words)
        frame_reports.append({
            "time": value,
            "path": str(frame_path),
            "words": [word.as_dict() for word in words],
            "sensitive": [hit.kind for hit in frame_hits],
        })
        if not frame_hits:
            continue
        frame_width, frame_height = _image_size(frame_path)
        for hit in frame_hits:
            hits.append({
                "kind": hit.kind,
                "text": hit.text,
                "time": value,
                "frame": int(round(value * fps)),
                "box": normalize_box(hit, frame_width, frame_height),
            })

    redactions: list[dict[str, Any]] = []
    if redact and hits and source_id:
        redactions = build_redactions(hits, source_id=source_id, fps=fps)
    return {
        "media": str(media),
        "source_id": source_id,
        "duration_seconds": round(duration, 3),
        "fps": fps,
        "backend": backend,
        "scenes": scenes,
        "samples": samples,
        "ocr_frames_analyzed": len(frame_reports),
        "ocr_frames_skipped": skipped,
        "ocr_frames": frame_reports,
        "sensitive": [{"kind": hit["kind"], "text": hit["text"], "time": hit["time"]} for hit in hits],
        "redactions": redactions,
    }


def _gray_thumb(media: Path, time: float, width: int = 32, height: int = 18) -> bytes:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{time:.3f}", "-i", str(media),
         "-frames:v", "1", "-vf", f"scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
    )
    return result.stdout


def _mean_abs_diff(a: bytes, b: bytes) -> float:
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


_SIZE_CACHE: dict[str, tuple[int, int]] = {}


def _image_size(path: Path) -> tuple[int, int]:
    key = str(path)
    if key not in _SIZE_CACHE:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
             "-of", "csv=s=x:p=0", str(path)],
            capture_output=True, text=True, check=True,
        )
        width, height = result.stdout.strip().split("x")
        _SIZE_CACHE[key] = (int(width), int(height))
    return _SIZE_CACHE[key]


def load_cursor_samples(path: Path) -> list[dict[str, float]]:
    """Carga muestras de cursor grabadas en captura (JSON Lines con t, x, y, w, h).

    Devuelve posiciones normalizadas (0..1) para mapearlas a fotogramas.
    """
    import json

    samples: list[dict[str, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        width = float(record.get("w") or 1)
        height = float(record.get("h") or 1)
        samples.append({
            "time": float(record["t"]),
            "x": float(record["x"]) / width,
            "y": float(record["y"]) / height,
        })
    return samples


def cursor_activity(
    samples: list[dict[str, float]],
    *,
    fps: float = 30.0,
    dwell_seconds: float = 1.2,
    move_threshold: float = 0.02,
) -> list[dict[str, Any]]:
    """Detecta paradas del cursor útiles como candidatas a zoom.

    Una «parada» es una racha en la que el cursor se mueve menos de
    `move_threshold` (en coordenadas normalizadas) durante al menos
    `dwell_seconds`. Se marca `risk: human_review` porque un zoom nunca es
    100 % inocuo para el significado.
    """
    dwells: list[dict[str, Any]] = []
    if not samples:
        return dwells
    start = samples[0]
    anchor = samples[0]
    for sample in samples[1:]:
        moved = abs(sample["x"] - anchor["x"]) + abs(sample["y"] - anchor["y"])
        if moved > move_threshold:
            duration = anchor["time"] - start["time"]
            if duration >= dwell_seconds:
                dwells.append(_dwell(start, anchor, duration, fps))
            start = sample
            anchor = sample
        else:
            anchor = sample
    duration = anchor["time"] - start["time"]
    if duration >= dwell_seconds:
        dwells.append(_dwell(start, anchor, duration, fps))
    return dwells


def _dwell(start: dict[str, float], end: dict[str, float], duration: float, fps: float) -> dict[str, Any]:
    return {
        "kind": "cursor_dwell",
        "start": round(start["time"], 3),
        "end": round(end["time"], 3),
        "duration": round(duration, 3),
        "x": round((start["x"] + end["x"]) / 2, 4),
        "y": round((start["y"] + end["y"]) / 2, 4),
        "start_frame": int(round(start["time"] * fps)),
        "end_frame": int(round(end["time"] * fps)),
        "risk": "human_review",
        "affects_meaning": False,
        "reason": f"cursor detenido {duration:.2f}s",
    }
