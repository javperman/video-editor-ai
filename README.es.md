# video-editor-ai

Pipeline de edición automática para tutoriales técnicos, controlado por un
`edit_plan.json` determinista e independiente del editor.

El plan es la fuente de verdad: ingesta, cortes, subtítulos, PiP, máster de audio,
render y QC leen de él. Cada instrucción en lenguaje natural crea una revisión
inmutable nueva; nunca modifica el plan anterior.

[English](README.md) · [Escala y rendimiento](docs/scale.md) · [Spike de OpenChatCut](docs/spike-openchatcut.md)

## Qué hace

- Ingesta pantalla, webcam/móvil y voz con hashes SHA-256 y metadatos `ffprobe`.
- Transcribe en local con `faster-whisper` (GPU por defecto, respaldo a CPU).
- Detecta silencios, muletillas y repeticiones; los cortes que afectan al
  significado requieren aprobación humana explícita.
- Construye un `edit_plan.json` validado, aplica revisiones JSON Patch y conserva
  un historial inmutable.
- Alinea la cámara del móvil como PiP por correlación de audio.
- Quema subtítulos con ASS a la resolución real de salida.
- Renderiza en local con FFmpeg + NVENC, masteriza a −14 LUFS y ejecuta QC.
- Exporta FCPXML para seguir editando.
- Expone un adaptador MCP para OpenChatCut, limitado a `127.0.0.1`.

## Pipeline

```mermaid
flowchart LR
  A[Pantalla / webcam / voz] --> B[Ingesta + hash + ffprobe]
  B --> C[ASR local: faster-whisper]
  C --> D[Constructor + validador de plan]
  D --> E[Revisión inmutable: JSON Patch]
  E --> F[Cortes + subtítulos + PiP]
  F --> G[Render FFmpeg NVENC]
  G --> H[Máster de audio -14 LUFS]
  H --> I[QC: duración, true peak, LUFS, frames]
  I --> J[FCPXML / máster final]
```

OpenChatCut es opcional para trabajo interactivo. El render determinista es la
ruta del máster final.

## Rendimiento medido

Clip real de 30 minutos, 1080p:

| Etapa | Resultado |
|---|---|
| Pipeline completo (ASR + render NVENC + máster + QC) | **~7,6 min** |
| Memoria pico | **2,5 GB** |
| ASR | RTF **0,105** (120 s de audio en 12,6 s) |
| ASR con caché caliente | 13,9 s de audio en 0,65 s (RTF ~0,05) |
| QC | OK: 1800,09 s, true peak −1,0 dBFS, −16,6 LUFS |

Hardware: RTX 3050 Ti (4 GB, NVENC), portátil de 16 GB. Son medidas locales, no
una garantía para otro hardware. Metodología: [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md).

## Inicio rápido

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e '.[asr,vision,providers]'

PYTHONPATH=src python scripts/run_project.py \
  --screen pantalla.mkv --webcam movil.mp4 --voice voz.wav \
  --out-dir data/mi-tutorial --project-name "Mi tutorial"
```

Integración opcional con OpenChatCut:

```bash
./scripts/run-openchatcut.sh          # servidor local en 127.0.0.1:5199
python3 scripts/occ_spike.py          # flujo MCP completo
python3 scripts/occ_export.py <id> data/artifacts/salida.mp4
```

Aplicar una revisión:

```bash
PYTHONPATH=src python -m video_ai.cli show data/mi-tutorial
PYTHONPATH=src python -m video_ai.cli apply data/mi-tutorial "quita los silencios"
```

## Estructura

```text
config/       configuración de proveedores, editor y privacidad
schemas/      esquema versionado del edit plan
src/          ingesta, audio, visión, planificación, adaptadores, QC
scripts/      arranque, spike MCP y export headless
tests/        fixtures y protocolo de pruebas
docs/         arquitectura, ADRs y notas de rendimiento
data/         proyectos y artefactos locales (ignorado por git)
vendor/       binarios y código de terceros (ignorado por git)
```

Cada vídeo vive en su propia carpeta bajo `data/projects/`; ni entradas ni salidas
se versionan.

## Tests

```bash
.venv/bin/python -m pytest -q
```

La suite cubre validación del plan, revisiones JSON Patch, compilación de cortes,
mapeo de subtítulos a timeline, transformaciones PiP, alineado de audio, umbrales
de QC, parser de instrucciones y contratos del adaptador OpenChatCut. Los tests
que dependen de GPU, modelo o fixture de vídeo se saltan cuando falta el recurso.

## Cómo se construyó

El repositorio se desarrolla con un flujo asistido por IA:

- `AGENTS.md` es el contrato para agentes: invariantes, honestidad y verificación.
- `docs/` contiene ADRs, spikes y guías de uso.
- Los tests y los renders reales son el criterio de aceptación; arrancar la app no
  cuenta como prueba superada.
- Cada revisión es inspeccionable e inmutable; la persona revisa el diff y el QC
  final antes de aceptar un cambio.
- Herramientas usadas: OpenCode, Claude Code y Gemini API.

## Demo

[![Demo: asistente de chat que cualifica y agenda una llamada](https://i.ytimg.com/vi/XcZ60adpBms/hqdefault.jpg)](https://youtu.be/XcZ60adpBms)

Demo de Peresotech producida con este pipeline (8:01): pantalla + PiP del móvil, cortes de silencio, subtítulos, máster de audio y QC. Datos sintéticos; no hay sistemas reales conectados.

El vídeo before/after del proceso de edición no está incluido; la demo de arriba es una salida real producida con el pipeline. No se incluye un vídeo simulado en lugar de un render real.

## Límites

- El pipeline es determinista pero opinado: está pensado para tutoriales técnicos,
  no para edición narrativa de cine.
- La calidad del ASR depende del modelo, idioma y audio; la detección de muletillas
  es conservadora y los cortes que cambian significado requieren aprobación.
- OpenChatCut es un componente externo AGPL-3.0; no se incluye. El render local usa
  FFmpeg/NVENC y es independiente.
- NVENC requiere una GPU NVIDIA compatible; el render en CPU es posible pero más lento.
- El esquema cubre las operaciones implementadas; lo que no está soportado se
  rechaza, no se simula.

## Licencia

MIT. Ver [`LICENSE`](LICENSE) y [`THIRD-PARTY.md`](THIRD-PARTY.md).

OpenChatCut, FFmpeg, faster-whisper, Remotion y otros componentes externos conservan
sus licencias. Remotion y el proyecto de motion graphics de ejemplo no se incluyen
en este repositorio.
