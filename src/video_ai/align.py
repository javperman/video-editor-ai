"""Alineado de pistas de audio (voz grabada aparte) con el vídeo de referencia.

Dos usos:

1. **Correlación**: dada una referencia (el audio del vídeo, aunque sea de peor
   calidad) y la voz grabada aparte, calcula el desfase en segundos.
2. **Palmada**: detecta el instante de un pico fuerte (la palmada) en cada pista
   y devuelve la diferencia.

Se implementa con numpy (FFT para la correlación) y FFmpeg para decodificar, así
que no añade dependencias nuevas.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SAMPLE_RATE = 8000


def decode_mono(path: Path, sample_rate: int = SAMPLE_RATE) -> "object":
    """Decodifica a mono float32 a baja frecuencia (suficiente para alinear)."""
    import numpy as np  # type: ignore

    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-"],
        capture_output=True, check=True,
    )
    return np.frombuffer(result.stdout, dtype=np.float32).astype(np.float64)


def find_offset(
    reference: Path,
    target: Path,
    *,
    max_seconds: float = 60.0,
    sample_rate: int = SAMPLE_RATE,
):
    """Desfase de `target` respecto a `reference`, en segundos.

    Positivo significa que `target` empieza **más tarde** que la referencia (hay
    que recortarle el principio). Devuelve además la calidad (0..1).
    """
    import numpy as np  # type: ignore

    ref = decode_mono(reference, sample_rate)
    tgt = decode_mono(target, sample_rate)
    if len(ref) == 0 or len(tgt) == 0:
        raise ValueError("alguna pista está vacía")
    size = 1 << int(np.ceil(np.log2(len(ref) + len(tgt))))
    correlation = np.fft.irfft(np.fft.rfft(ref, size) * np.conj(np.fft.rfft(tgt, size)), size)
    correlation = np.concatenate((correlation[-(len(tgt) - 1):], correlation[:len(ref)]))
    lags = np.arange(-(len(tgt) - 1), len(ref))
    limit = int(max_seconds * sample_rate)
    mask = np.abs(lags) <= limit
    correlation = correlation[mask]
    lags = lags[mask]
    peak = int(np.argmax(correlation))
    lag = int(lags[peak])
    quality = float(correlation[peak] / (np.sqrt(np.sum(ref ** 2) * np.sum(tgt ** 2)) + 1e-12))
    return -lag / sample_rate, quality


def detect_clap(path: Path, *, sample_rate: int = SAMPLE_RATE):
    """Instante (segundos) del pico de energía más fuerte, típicamente la palmada."""
    import numpy as np  # type: ignore

    audio = decode_mono(path, sample_rate)
    if len(audio) == 0:
        raise ValueError("pista vacía")
    window = int(0.02 * sample_rate)  # 20 ms
    energy = np.convolve(audio ** 2, np.ones(window) / window, mode="same")
    return float(int(np.argmax(energy)) / sample_rate)


def detect_claps(
    path: Path,
    *,
    sample_rate: int = SAMPLE_RATE,
    threshold_ratio: float = 0.5,
    min_gap: float = 0.25,
    max_count: int = 8,
) -> list[float]:
    """Instantes de los picos de energía prominentes (las palmadas), en orden.

    A diferencia de `detect_clap`, devuelve **todas** las palmadas por encima de
    un umbral relativo al pico, no solo la más fuerte. Así se puede usar la
    primera para sincronizar.
    """
    import numpy as np  # type: ignore

    audio = decode_mono(path, sample_rate)
    if len(audio) == 0:
        raise ValueError("pista vacía")
    window = int(0.02 * sample_rate)
    energy = np.convolve(audio ** 2, np.ones(window) / window, mode="same")
    peak = float(energy.max())
    if peak <= 0:
        return []
    threshold = peak * threshold_ratio
    times: list[float] = []
    index = 0
    total = len(energy)
    while index < total and len(times) < max_count:
        if energy[index] >= threshold:
            end = min(total, index + window)
            local = int(np.argmax(energy[index:end])) + index
            times.append(round(local / sample_rate, 4))
            index = local + int(min_gap * sample_rate)
        else:
            index += 1
    return times


def sync_from_first_clap(reference: Path, target: Path, **kwargs) -> float:
    """Desfase (segundos) para alinear `target` con `reference` usando la primera palmada.

    Devuelve `clap_referencia - clap_objetivo`: la posición de la referencia que
    corresponde al inicio (t=0) del objetivo.
    """
    ref_claps = detect_claps(reference, **kwargs)
    tgt_claps = detect_claps(target, **kwargs)
    if not ref_claps or not tgt_claps:
        raise ValueError("no se detectó ninguna palmada")
    return round(ref_claps[0] - tgt_claps[0], 4)


def clap_offset(reference: Path, target: Path) -> float:
    """Diferencia entre la palmada de la referencia y la del objetivo (segundos)."""
    return detect_clap(target) - detect_clap(reference)


def make_time_aligned(source: Path, output: Path, shift_seconds: float,
                      *, encoder: str = "libx264", crf: int = 20) -> Path:
    """Escribe una copia de `source` con el origen temporal alineado.

    Deja una pista `source'` tal que `source'(t) == source(t + shift_seconds)`:

    - `shift_seconds > 0`: `source` va adelantado → se recorta el principio.
    - `shift_seconds < 0`: `source` va retrasado → se rellena el principio con
      negro (vídeo) y silencio (audio).

    Es la forma correcta de alinear una webcam/móvil con la pantalla **antes** de
    aplicar cortes: así el clip comparte el mismo tiempo de origen que la
    referencia y los cortes (definidos en tiempo de pantalla) le afectan bien.
    Manipular el `source_in` del item y cortar después rompe la alineación.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    if shift_seconds > 0:
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{shift_seconds:.6f}", "-i", str(source),
            "-c:v", encoder, "-crf", str(crf), "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "128k", str(output),
        ]
    elif shift_seconds < 0:
        pad = -shift_seconds
        delay_ms = int(round(pad * 1000))
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-vf", f"tpad=start_duration={pad:.6f}:start_mode=add:color=black",
            "-af", f"adelay={delay_ms}|{delay_ms}",
            "-c:v", encoder, "-crf", str(crf), "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "128k", str(output),
        ]
    else:
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                   "-i", str(source), "-c", "copy", str(output)]
    subprocess.run(command, check=True)
    return output


def apply_offset(target: Path, output: Path, offset_seconds: float) -> Path:
    """Corrige el desfase de `target`.

    `offset_seconds` es el valor devuelto por `find_offset`: positivo si `target`
    va con retraso (se le recorta el principio); negativo si va adelantado (se
    retrasa con silencio).
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    if offset_seconds >= 0:
        filter_graph = f"atrim=start={offset_seconds:.6f},asetpts=PTS-STARTPTS"
    else:
        delay_ms = int(round(-offset_seconds * 1000))
        filter_graph = f"adelay={delay_ms}|{delay_ms}"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(target),
         "-af", filter_graph, "-c:a", "pcm_s16le", str(output)],
        check=True,
    )
    return output
