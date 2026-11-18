"""Transcripción local con faster-whisper (import diferido)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "large-v3-turbo"
DEFAULT_COMPUTE = "int8_float16"
SAMPLE_RATE = 16000


def _decode_pcm(media: Path, sample_rate: int = SAMPLE_RATE) -> "Any":
    """Decodifica con el FFmpeg del sistema para evitar incompatibilidades de PyAV."""
    import numpy as np  # type: ignore

    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(media),
            "-vn", "-ac", "1", "-ar", str(sample_rate),
            "-f", "f32le", "-",
        ],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, dtype=np.float32).copy()


def available() -> bool:
    try:
        import faster_whisper  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def _preload_cuda_libs() -> list[str]:
    """Carga cuBLAS y cuDNN de las ruedas `nvidia-*-cu12` del entorno aislado.

    ctranslate2 busca `libcublas.so.12` en el cargador del sistema; cargándolas
    aquí con ruta absoluta evitamos depender de `LD_LIBRARY_PATH` o de paquetes
    globales.
    """
    import ctypes
    import glob
    import importlib.util

    loaded: list[str] = []
    for package in ("nvidia.cublas", "nvidia.cudnn"):
        spec = importlib.util.find_spec(package)
        if spec is None:
            continue
        libdir = Path(spec.submodule_search_locations[0]) / "lib"
        for library in sorted(glob.glob(str(libdir / "*.so*"))):
            try:
                ctypes.CDLL(library, mode=ctypes.RTLD_GLOBAL)
                loaded.append(Path(library).name)
            except OSError:
                continue
    return loaded


_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}


def _load_model(model: str, device: str, compute_type: str) -> tuple[Any, str, str]:
    """Carga el modelo una sola vez por (modelo, device, compute).

    Reutilizar el modelo caliente evita el coste de carga en llamadas repetidas,
    la misma idea que un servicio de STT en marcha.
    """
    from faster_whisper import WhisperModel  # type: ignore

    key = (model, device, compute_type)
    if device.startswith("cuda") and key not in _MODEL_CACHE:
        _preload_cuda_libs()
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key], device, compute_type
    try:
        instance = WhisperModel(model, device=device, compute_type=compute_type)
    except Exception:  # noqa: BLE001
        if not device.startswith("cuda"):
            raise
        device, compute_type = "cpu", "int8"
        key = (model, device, compute_type)
        if key not in _MODEL_CACHE:
            _MODEL_CACHE[key] = WhisperModel(model, device=device, compute_type=compute_type)
        return _MODEL_CACHE[key], device, compute_type
    _MODEL_CACHE[key] = instance
    return instance, device, compute_type


def warm(model: str = DEFAULT_MODEL, device: str = "cuda", compute_type: str = DEFAULT_COMPUTE) -> dict[str, str]:
    """Carga el modelo por adelantado y devuelve el device/compute efectivos."""
    _, effective_device, effective_compute = _load_model(model, device, compute_type)
    return {"model": model, "device": effective_device, "compute_type": effective_compute}


def release_models() -> None:
    _MODEL_CACHE.clear()


def transcribe(
    media: Path,
    *,
    model: str = DEFAULT_MODEL,
    device: str = "cuda",
    compute_type: str = DEFAULT_COMPUTE,
    language: str = "es",
    vad: bool = True,
) -> dict[str, Any]:
    """Transcribe con timestamps por palabra.

    Si se pide CUDA y no está disponible, cae a CPU con `int8`. El modelo se
    reutiliza entre llamadas. Lanza un error claro si faster-whisper no está
    instalado.
    """
    try:
        import faster_whisper  # type: ignore  # noqa: F401
    except ImportError as error:
        raise RuntimeError(
            "faster-whisper no está instalado; usa un venv aparte con `[asr]`"
        ) from error

    whisper, device, compute_type = _load_model(model, device, compute_type)

    audio = _decode_pcm(media)
    segments, info = whisper.transcribe(
        audio,
        language=language,
        task="transcribe",
        word_timestamps=True,
        vad_filter=vad,
        beam_size=5,
    )
    words = [
        {"start": word.start, "end": word.end, "word": word.word, "probability": word.probability}
        for segment in segments
        for word in (segment.words or [])
    ]
    return {
        "model": model,
        "device": device,
        "compute_type": compute_type,
        "language": info.language,
        "duration_seconds": info.duration,
        "words": words,
    }
