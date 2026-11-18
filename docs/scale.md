# Medición de escala — 2026-11-09

Medición real de las etapas de **análisis** sobre un clip de 180 s a 1080p30
(`scripts/measure_scale.py`). El render de OpenChatCut se mide aparte porque es la
etapa dominante y muy lenta.

> Nota: el máster final no usa el export de OpenChatCut. Usa el render local con
> FFmpeg/NVENC; el benchmark completo de 30 minutos está en
> [`BENCHMARKS.md`](BENCHMARKS.md).

## Etapas medidas (180 s)

| Etapa | Tiempo | Factor vs audio | Memoria pico |
|---|---|---|---|
| Análisis de audio (silencios) | 2,6 s | 0,014× | 20 MB |
| Transcripción (large-v3-turbo, GPU) | 10,6 s | 0,059× | 2,1 GB |
| Visión + OCR a 1 fps (pantalla dinámica) | 128 s | 0,71× | 2,1 GB |
| Visión + OCR a 1 fps (pantalla estática) | 5,2 s | 0,029× | 2,1 GB |

Memoria pico del proceso: **~2,1 GB** (lo aporta el modelo de Whisper, no el OCR).
Muy por debajo de los 16 GB del equipo.

## Extrapolación a 30 minutos (1800 s)

| Etapa | Estimación | Nota |
|---|---|---|
| Análisis de audio | ~26 s | lineal |
| Transcripción GPU | ~2,1 min | RTF ≈ 0,06 |
| Visión + OCR (estática) | ~2,5 min | el caso real de un tutorial |
| Visión + OCR (dinámica) | ~21 min | peor caso, pantalla cambiando cada segundo |
| Render OpenChatCut | ~59 min | medido 180 s → 356 s (1,98×); software |

## Optimización de OCR: análisis por cambio

El OCR era el cuello de botella (≈0,59 s por fotograma con `tesseract`). Se añadió
detección de cambio: antes de hacer OCR se compara una miniatura de 32×18 con la
del fotograma anterior; si apenas cambió, se salta.

Medido sobre **pantalla estática de 60 s**:

| Configuración | Tiempo | Fotogramas analizados | Redacciones |
|---|---|---|---|
| Sin filtro | 32,5 s | 60 | 3 |
| Con filtro | **5,2 s** | 1 | 3 |

Seis veces más rápido y con las mismas redacciones. En contenido totalmente
dinámico el filtro añade ~20 % de sobrecoste (no hay nada que saltar), por lo que
para pantallas de tutorial el balance es claramente favorable.

## Render: medido (180 s) y extrapolado

Render real de un clip de 180 s por OpenChatCut (ruta `POST /export`, H.264
1080p30 por software):

| Medida | Valor |
|---|---|
| Edición MCP del plan | 0,71 s |
| Export/render | 355,7 s |
| Total | 356,5 s |
| Factor | **1,98× tiempo real** |
| Archivo | 233 MB, 1920×1080 |

Extrapolado a 30 minutos: **~59 min de render**. Es el coste dominante con
mucho, y va por software (NVENC no confirmado en el export). Reducirlo es una
optimización pendiente.

### Render local con FFmpeg (mucho más rápido)

`src/video_ai/render.py` renderiza la timeline compilada con el FFmpeg del
sistema. Sobre el mismo clip de 180 s:

| Renderizador | Tiempo | Factor | Nota |
|---|---|---|---|
| OpenChatCut (WebCodecs) | 356 s | 1,98× | software, sin NVENC |
| FFmpeg local `libx264` | 32,5 s | 0,18× | CPU |
| FFmpeg local `h264_nvenc` | **13,3 s** | **0,074×** | GPU |

El render local con NVENC es **~27× más rápido** que el export de OpenChatCut.
Alcance actual del render local: vídeo primario + audio (embebido o de otra
fuente) y subtítulos opcionales; PiP y zooms aún no (están pendientes de
verificación de `transform`).

### Prueba literal de 30 minutos

Ejecutada de verdad sobre un clip de 1800 s a 1080p30 con el render local:

| Etapa | Tiempo | Memoria pico |
|---|---|---|
| Análisis de audio | 22,4 s | 25 MB |
| Transcripción GPU (3120 palabras) | 64,8 s | 2,5 GB |
| Render local `h264_nvenc` | 134,9 s | 2,5 GB |
| Master `loudnorm` + limitador | 92,3 s | 2,5 GB |
| QC (FFprobe + black/freeze + ebur128) | 144,6 s | 2,5 GB |
| **Total** | **≈7,6 min** | **2,5 GB** |

Resultado: QC **OK** (1920×1080, 30 fps, 1800,09 s, true peak −1,0 dBFS,
−16,6 LUFS), 2,3 GB. Frente a los ~59 min estimados con el export de OpenChatCut,
el render local baja el proyecto de 30 min a **~7,6 min** de proceso total.

`loudnorm` en modo lineal puede superar el true peak; se añadió un `alimiter` de
seguridad en `src/video_ai/master_audio.py`.

## Por qué el render va por software

Inspeccionando el código de OpenChatCut: la ruta de export usa **WebCodecs del
navegador** (`VideoEncoder`, `canRenderMediaOnWeb`, «browser export»), no el CLI
de FFmpeg. El mensaje `浏览器编码器不支持此导出规格` («el codificador del navegador
no admite esta exportación») lo confirma.

Consecuencia: la aceleración depende del proceso GPU de Electron/Chromium, que en
este entorno falla en el arranque (`GPU process launch failed`). No se usa NVENC.
De ahí el 1,98× tiempo real.

Opciones para acelerar (pendientes):

1. Habilitar la aceleración de Chromium en el arranque de Electron (VA-API/NVENC
   con flags tipo `--enable-features=VaapiVideoEncoder --ignore-gpu-blocklist`).
2. Usar la ruta de FFmpeg del modo fuente, que sí podría usar `h264_nvenc`.
3. Aceptar el render por software (~59 min para 30 min) y optimizar en otro punto.

## Límites

- La transcripción y el OCR compiten por memoria pero no de forma crítica
  (2,1 GB pico).
- El OCR de pantalla estática es rápido; el de pantalla muy dinámica sigue siendo
  el peor caso.
- El render es ~2× tiempo real y por software; falta comprobar NVENC.
- La extrapolación a 30 min es lineal sobre el análisis y el render medidos, no
  una prueba de 30 min ejecutada.
