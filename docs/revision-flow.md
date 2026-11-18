# Flujo de revisión — 2026-11-09

Ciclo completo verificado **sin OpenChatCut**: visión → redacción → lenguaje
natural → revisión inmutable → horneado → compilación.

Script reproducible: `scripts/run_revision_demo.py` (no necesita servidor).

## Pasos y resultado

```text
fixtures (pantalla con secreto + voz)
  → analyze_audio        → 2 cortes de silencio
  → analyze_vision       → 3 redacciones (api_key, email, password_label)
  → build_plan           → revisión 1 (cortes + redacciones)
  → run_instruction      → "aprueba el corte 1" → revisión 2
  → bake_redactions      → desenfoque horneado en copia → revisión 3
  → compile_timeline     → 317 frames = 10,567 s
```

| Dato | Valor |
|---|---|
| Fuente de pantalla | `secret` (fixture de laboratorio) |
| Candidatos de audio | 2 |
| Redacciones propuestas | 3 |
| Instrucción aplicada | «aprueba el corte 1» |
| Revisiones | r1 plan · r2 instrucción · r3 redacciones horneadas |
| Timeline compilada | 317 frames · 10,567 s |
| Archivos | `data/revision-demo/project/revisions/edit_plan.r000{1,2,3}.json` |

## Horneado de redacciones

`src/video_ai/redact.py` aplica el desenfoque con FFmpeg **sobre una copia**, en
las ventanas temporales indicadas y solo en las cajas marcadas. Nunca se toca el
original (se conserva su SHA-256).

- Se crea un archivo `*-redacted.mp4` por fuente afectada.
- El plan resultante actualiza `path_rel`, `sha256` y añade `redacted_from`.
- La lista `edits.redactions` queda vacía (ya aplicada) y el plan se vuelve a
  validar contra el esquema y las reglas semánticas.
- El original mantiene su hash: comprobado en las pruebas.

Verificación por OCR: tras redactar la caja del token, el OCR **ya no** lee
`sk-ABCDEF…` ni detecta `api_key`. Los otros dos textos (no redactados) siguen
siendo legibles, así que el desenfoque es localizado, no global.

CLI:

```bash
PYTHONPATH=src .venv/bin/python -m video_ai.cli redact plan.json --root . --out plan-redactado.json
```

## Por qué hornear en la fuente y no en el editor

- No depende de que OpenChatCut soporte desenfoque por región o máscaras.
- Conserva las marcas de tiempo de **origen**, sin recalcular a timeline.
- El render final sale limpio aunque cambie el editor.

## Límites

- Si una caja solo es válida en un instante, la redacción cubre toda la ventana
  propuesta (±1,5 s, agrupada hasta 3 s). Es conservador por diseño.
- Horneado requiere recodificar el vídeo (una pasada de `libx264`).

## Subtítulos

`src/video_ai/subtitles.py` agrupa las palabras con tiempos en cues legibles
(corte por pausa > 0,8 s, frase terminada, > 6 s o > 84 caracteres) y genera:

- **SRT** con marcas de tiempo:
  ```bash
  PYTHONPATH=src .venv/bin/python -m video_ai.cli subtitles words.json --out salida.srt
  ```
- **Subtítulos del plan** (`edits.subtitles`) **mapeados a la timeline**: un cue
  que cae en una zona cortada se descarta y uno posterior a un corte se desplaza
  los frames eliminados. Verificado en pruebas: un cue en el segundo 6 con un
  corte de 50 frames queda en el frame 130, no en el 180.
- **Quemado opcional** con `burn_subtitles` (vídeo + SRT → vídeo con subtítulos).

Prueba real sobre la voz de laboratorio: 24 palabras → **5 cues** y SRT
correcto:

```text
1
00:00:00,000 --> 00:00:00,220
¡Hola!

2
00:00:00,640 --> 00:00:03,080
Este es un tutorial técnico de prueba.
```

Los errores de texto en esa prueba son del TTS robótico, no del generador; con
voz humana el punto de partida es la transcripción de Whisper.
