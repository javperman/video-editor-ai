# Demo de pipeline completo — 2026-11-09

Flujo ejecutado por `scripts/run_pipeline_demo.py` (requiere OpenChatCut
arrancado con `scripts/run-openchatcut.sh`):

```text
fixtures (pantalla+voz 1080p, móvil, voz)
  → transcripción real (faster-whisper large-v3-turbo, GPU float16)
  → análisis de audio: silencios + muletillas + repeticiones
  → plan: cortes + subtítulos mapeados a la timeline
  → adaptador MCP de OpenChatCut
  → export headless
  → normalización loudnorm de dos pasadas (master de audio)
  → quemado de subtítulos
  → informe QC
```

## Resultado

| Campo | Valor |
|---|---|
| ASR | `large-v3-turbo`, CUDA float16 |
| Palabras transcritas | 24 |
| Candidatos de audio | 3 (2 silencios + 1 muletilla) |
| Subtítulos en el plan | 5 |
| Clips colocados en OCC | 9 |
| Duración esperada | 317 frames = 10,567 s |
| Duración medida | ≈10,6 s (delta < 100 ms) |
| Resolución/FPS | 1920×1080 / 30 |
| Audio | AAC; true peak y loudness dentro de rango |
| blackdetect / freezedetect | limpio |
| QC final | **OK** |
| Tiempo total | ~36 s (incluye ASR en GPU y render) |

## Corrección importante: muletillas

En una primera ejecución el detector marcó «Este» como muletilla en frases
legítimas («Este es un tutorial…», «Este paso es importante…»). Como el riesgo
era `conservative`, el compilador las **cortó automáticamente** (317 → 290
frames), alterando el significado.

Arreglado en `detect_fillers`:

- Una palabra del diccionario de muletillas solo se marca si va **aislada por una
  pausa**, se **repite** o es una emisión suelta.
- Su riesgo pasa a `human_review`: **nunca** se corta sin aprobación explícita.

Tras el arreglo el pipeline vuelve a 317 frames y solo propone la muletilla para
revisión, sin aplicarla.

## Artefactos

- `data/artifacts/pipeline-demo.mp4` (export directo de OpenChatCut)
- `data/artifacts/pipeline-demo-final.mp4` (master con loudnorm)
- `data/artifacts/pipeline-demo-subtitled.mp4` (**entrega final con subtítulos quemados**)
- `data/artifacts/pipeline-demo.source.srt` (subtítulos en tiempo de origen)
- `data/artifacts/pipeline-demo.srt` (subtítulos en tiempo de timeline)
- `data/artifacts/pipeline-demo-report.json` (informe completo)

Los artefactos están ignorados por Git.
