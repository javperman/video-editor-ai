# Benchmarks

Local measurements, not a guarantee for other hardware.

## Machine

- NVIDIA RTX 3050 Ti Laptop GPU (4 GB VRAM, NVENC)
- 16 GB RAM class laptop
- `faster-whisper` large-v3-turbo, GPU, `int8_float16`
- FFmpeg with `h264_nvenc`

## 30-minute tutorial

Input: screen recording 1080p60 + phone camera + voice track, total duration
1800 s. Full pipeline:

| Stage | Time |
|---|---:|
| ASR | 64.8 s |
| NVENC render | 134.9 s |
| Audio master | 92.3 s |
| QC | 144.6 s |
| **Total** | **≈ 7.6 min** |

Peak memory: **2.5 GB**. QC result: duration 1800.09 s, true peak −1.0 dBFS,
integrated loudness −16.6 LUFS, status OK.

## ASR throughput

| Run | Audio | Time | RTF |
|---|---:|---:|---:|
| Cold-ish model, 120 s clip | 120 s | 12.6 s | 0.105 |
| Warm model cache, 13.9 s clip | 13.9 s | 0.65 s | ≈ 0.05 |

RTF = processing time / audio duration. Lower is better.

## First real run (short clip)

Screen 1080p60 + phone PiP aligned by audio, 9 silence cuts, 21 subtitles,
QC OK, total ≈ 105 s. This was a short validation run, not the 30-minute
benchmark above.

## Method

- The pipeline is run end to end, including ASR, render, audio master and QC.
- The reported time is wall-clock time for the full command, not a sum of
  isolated micro-benchmarks.
- Memory is the peak reported by the process monitor during the run.
- The source recording and the generated project are local test data; they are
  not part of this repository.

## Caveats

- GPU model, driver, CUDA/cuDNN versions, storage speed and thermal state change
  the result.
- The 30-minute run used a real tutorial recording; its content and the speaker
  are not published.
- These numbers are engineering evidence, not a product SLA.
