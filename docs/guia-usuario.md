# Guía de usuario — video-editor-ai

Guía práctica para convertir tus grabaciones en un tutorial editado. Escrita para
usarse sin conocer el código: primero qué hace, luego el flujo paso a paso, el
catálogo de instrucciones, lo que **no** se puede hacer y la solución de problemas.

> Índice
> 1. [Qué es y qué no es](#1-qué-es-y-qué-no-es)
> 2. [Requisitos](#2-requisitos)
> 3. [Estructura de carpetas](#3-estructura-de-carpetas)
> 4. [Paso 1 — Grabar](#4-paso-1--grabar)
> 5. [Paso 2 — Primer montaje](#5-paso-2--primer-montaje)
> 6. [Paso 3 — Editar por instrucciones](#6-paso-3--editar-por-instrucciones)
> 7. [Catálogo de instrucciones](#7-catálogo-de-instrucciones)
> 8. [Revisar el resultado](#8-revisar-el-resultado)
> 9. [Entregar y editar fuera](#9-entregar-y-editar-fuera)
> 10. [Límites: lo que NO se puede](#10-límites-lo-que-no-se-puede)
> 11. [Solución de problemas](#11-solución-de-problemas)
> 12. [Referencia de comandos](#12-referencia-de-comandos)

---

## 1. Qué es y qué no es

**Es** un motor de montaje **determinista y local**: recorta silencios, alinea el
móvil como *picture-in-picture*, transcribe, subtitula, masteriza el audio,
renderiza en 1080p (o más) y pasa control de calidad. Todo con FFmpeg, Whisper
local y reglas fijas. **Nada sale de tu máquina**; no usa APIs externas.

**No es** un editor con retoque píxel a píxel (no hay *tracking*, *color grading*
fino ni transiciones complejas). Las ediciones se expresan como operaciones sobre
un **plan** (`edit_plan.json`), versionado y reversible.

Dos formas de usarlo:

- **Terminal**: ejecutando los comandos que verás aquí.
- **Agente (OpenCode)**: hablándole en lenguaje natural; él traduce a los mismos
  comandos. Sigue valiendo la regla: si algo no está en el catálogo, te lo dirá.

Principio importante: **los originales nunca se tocan**. Se trabaja sobre copias y
se verifica el hash.

## 2. Requisitos

- Linux (Arch) con **FFmpeg**, **ffprobe** y **GPU NVIDIA** (NVENC) para el render rápido.
- El entorno del proyecto: `.venv` con las dependencias (`faster-whisper`, etc.).
- Los comandos se ejecutan **desde la raíz del repositorio** (`video-editor-ai`).

Todos los ejemplos asumen que estás en la raíz del repo.

## 3. Estructura de carpetas

La convención es **una carpeta por vídeo** bajo `data/proyectos/`, con `input/`
(tus grabaciones) y `output/` (lo que genera el pipeline) separados:

```text
data/proyectos/
└─ mi-tutorial/
    ├─ input/            ← tus grabaciones originales (ignorado por Git)
    │   ├─ pantalla.mp4
    │   ├─ movil.mp4
    │   └─ (opcional) voz.wav
    └─ output/           ← salida del proyecto (el `--out-dir`)
        ├─ render-final.mp4          vídeo final con subtítulos
        ├─ render-master.mp4         sin subtítulos (máster de audio)
        ├─ subtitles.timeline.srt    subtítulos
        ├─ project.fcpxml            para abrir en DaVinci/Kdenlive
        ├─ report.json               informe (cortes, QC…)
        ├─ transcript.json           transcripción (palabras con tiempos)
        └─ project/                  plan versionado (revisiones r1, r2, …)
```

Cada vídeo nuevo estrena su propia carpeta (`data/proyectos/<nombre>/`), así no hay
colisiones entre grabaciones. `data/` está **ignorado por Git**: tus vídeos y salidas
no se suben a ningún sitio.

## 4. Paso 1 — Grabar

- Pantalla con **OBS** (MP4 vale; MKV solo aguanta mejor un corte inesperado).
- Móvil o webcam como cámara (vertical u horizontal, da igual).
- Si grabas la voz con otro micrófono, guárdala en un fichero aparte.
- **Da una palmada** al principio (sirve de referencia de sincronía).
- Opcional, para zooms automáticos más adelante: deja el cursor con
  `scripts/record_cursor.sh` mientras grabas.

Crea la carpeta del proyecto y deja ahí los ficheros:

```bash
mkdir -p data/proyectos/mi-tutorial/input
# copia pantalla.mp4, movil.mp4 (y voz.wav si la tienes) a esa carpeta
```

No recortes ni reexportes: dame el original.

## 5. Paso 2 — Primer montaje

Un solo comando hace todo el primer montaje:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_project.py \
  --screen data/proyectos/mi-tutorial/input/pantalla.mp4 \
  --webcam data/proyectos/mi-tutorial/input/movil.mp4 \
  --out-dir data/proyectos/mi-tutorial/output --project-name "Mi tutorial" \
  --renderer ffmpeg --encoder h264_nvenc
```

Qué hace, en orden: alinea el móvil con la pantalla (por audio) y lo coloca como
PiP → transcribe (GPU) → detecta silencios, muletillas y repeticiones → propone
redacciones de datos sensibles (OCR) → construye el plan → genera los subtítulos
→ guarda las revisiones → exporta FCPXML → renderiza → masteriza el audio → quema
los subtítulos → control de calidad → escribe `report.json`.

Opciones útiles:

| Opción | Para qué |
|---|---|
| `--voice voz.wav --align` | Si grabaste la voz aparte: la alinea con la pantalla |
| `--no-pip` | No montar el móvil como PiP |
| `--pip-scale 0.16` | Tamaño del PiP: fracción del **ancho** (por defecto `0.16`) |
| `--pip-aspect 1.33` | Proporción de la caja (**alto/ancho**). Recorta el móvil a ese marco: `1.33` = retrato 3:4 tipo *talking head* |
| `--pip-focus center` | Anclaje del recorte: `center`, `top` (cara/cabeza) o `bottom` |
| `--pip-max-height 0.45` | Altura máxima del PiP: fracción del **alto** (por defecto `0.45`) |
| `--subtitle-style minimal` | Estilo de subtítulos (`tutorial` por defecto) |
| `--silence-min-cut 2.0` | Solo cortar silencios de más de 2 s |
| `--skip-render` | Solo análisis y plan, sin render |
| `--music musica.mp3` | Música de fondo con *ducking* |

> **Sobre el tamaño del PiP**: un móvil es vertical, así que un ancho pequeño ya
> ocupa mucho alto (con 22 % de ancho llegaba al ~70 % del alto). Por eso el
> defecto es `0.16` de ancho y, además, la cámara se **recorta a un marco 3:4**
> (`--pip-aspect 1.33`), tipo *talking head*, en lugar de mostrarse como una
> franja alargada. Resultado por defecto: ~16 % de ancho × ~38 % de alto. Puedes
> ajustarlo en el primer montaje o después con `apply`:
>
> ```bash
> # mover, encoger y recortar a 3:4 centrado
> apply "pon la webcam abajo a la derecha al 14% y recórtala a 3:4"
> # recorte cuadrado, anclado a la cabeza
> apply "haz la webcam cuadrada con encuadre arriba"
> ```

> `--out-dir` debe estar **dentro** del repositorio (las rutas del plan se resuelven
> contra él). Si quieres otro disco, usa un enlace simbólico dentro de `data/`.

## 6. Paso 3 — Editar por instrucciones

Cada instrucción crea una **revisión nueva** (no destruye la anterior) y, si no
usas `--no-render`, **regenera el vídeo final** con QC.

```bash
# Aplica y re-renderiza (por defecto)
PYTHONPATH=src .venv/bin/python -m video_ai.cli apply \
  data/proyectos/mi-tutorial/output/project "aprueba las muletillas" --root .

# Solo ver qué haría, sin aplicarlo
PYTHONPATH=src .venv/bin/python -m video_ai.cli apply \
  data/proyectos/mi-tutorial/output/project "corta de 1:20 a 1:35" --root . --dry-run

# Aplicar sin re-renderizar (rápido, para encadenar varias)
PYTHONPATH=src .venv/bin/python -m video_ai.cli apply \
  data/proyectos/mi-tutorial/output/project "quita los subtítulos" --root . --no-render
```

También puedes hacerlo desde **OpenCode**, simplemente diciendo lo que quieres. El
agente traduce la frase a estas operaciones y ejecuta el comando.

Para operaciones no habituales, el agente (o tú) puede enviar un **JSON Patch**
directo, que pasa por la misma validación y revisión:

```bash
PYTHONPATH=src .venv/bin/python -m video_ai.cli apply \
  data/proyectos/mi-tutorial/output/project --ops patch.json --root .
```

El ciclo queda así:

```text
run_project  ──►  primer montaje + render + QC
      │
      ▼   repetir hasta que te guste
apply "instrucción"  ──►  revisión nueva + render + QC
      │
      ▼
render-final.mp4 / subtitles.timeline.srt / project.fcpxml
```

## 7. Catálogo de instrucciones

Estas son las instrucciones que el sistema entiende **hoy**. Se aceptan en
español (y varias en inglés). Una frase fuera del catálogo se **rechaza** con un
mensaje claro; no se inventa nada.

| Quiero… | Instrucción (ejemplo) |
|---|---|
| Cortar un tramo | `corta de 1:20 a 1:35` |
| Quitar un corte propuesto | `quita el corte 3` |
| Aprobar/rechazar cortes | `aprueba el corte 2` · `rechaza los cortes que afectan al significado` |
| Aprobar por categoría | `aprueba las muletillas` · `aprueba las repeticiones` · `aprueba los silencios` |
| Empezar el vídeo en una frase | `empieza cuando diga "vamos allá"` |
| Terminar el vídeo en una frase | `termina tras decir "y esto es todo"` |
| Mover el PiP | `pon la webcam arriba a la izquierda al 30%` |
| Recortar el PiP a un marco | `recorta la webcam a 3:4` · `haz la webcam cuadrada` |
| Anclaje del recorte | `recorta la webcam a 3:4 con encuadre arriba` |
| Tope de alto del PiP | `pon la webcam abajo a la derecha al 16% sin pasar del 45% del alto` |
| Nivel de audio | `normaliza el audio a -14 LUFS` |
| Quitar subtítulos | `quita los subtítulos` |
| Cambiar estilo de subtítulos | `subtítulos minimalistas` |
| Ocultar datos sensibles | `difumina de 2:00 a 2:05` · `quita la redacción 1` |
| Cambiar el objetivo | `el objetivo es aprender a usar la terminal` |

Detalles finos:

- **Silencios**: se cortan solos a partir de 1,2 s (configurable con
  `--silence-min-cut`). Los de 1,2–1,5 s van como «conservadores»; el resto
  «automáticos». Ambos se aplican.
- **Muletillas y repeticiones**: siempre quedan **pendientes de tu aprobación**
  (pueden cambiar el significado). Por eso `run_project` las propone y no las corta.
- **Inicio/fin por frase** usa la transcripción: si la frase no aparece, se rechaza.
  «Empieza» corta lo anterior; «termina» corta lo posterior.

## 8. Revisar el resultado

- **`report.json`**: resumen con `words`, `subtitles`, `candidates` (los cortes),
  `pip` (alineación) y `render.qc_ok`.
- **Control de calidad (QC)**: comprueba resolución, fps, duración, audio, negros,
  congelados, *true peak* y volumen. Si algo crítico falla, el comando devuelve
  error y lo dice.
- **Previsualizaciones**: puedes extraer fotogramas con FFmpeg, o abrir
  `render-final.mp4` directamente.

## 9. Entregar y editar fuera

- Para publicar: `render-final.mp4` (1080p, H.264 + AAC con subtítulos quemados).
- Subtítulos aparte: `subtitles.timeline.srt`.
- Proyecto para otro editor: `project.fcpxml` (DaVinci Resolve, Kdenlive…).
- El plan editable está en `project/` (cada revisión es un `edit_plan.rNNNN.json`).

## 10. Límites: lo que NO se puede

Regla explícita: si no está en el catálogo o en el esquema del plan, el sistema
**lo dice** («según las capacidades deterministas actuales, esto no es posible») y
**propone alternativas**, en vez de intentarlo o inventar.

No se puede (por ahora):

- Retoque píxel a píxel, *tracking*, *color grading* fino, transiciones complejas.
- Rótulos/callouts dibujados sobre la pantalla (están previstos en el esquema, sin
  implementar; pídelo y se valora).
- Zooms «a mano» por instrucción (los automáticos dependen del cursor grabado).
- **Insertar medios externos** (una captura, imagen o vídeo nuevo) en un instante
  concreto: no existe todavía. Añadirlo es un cambio de esquema + render.
- **Generar animaciones** (p. ej. un gráfico de barras tipo Remotion) e
  incrustarlas: es un proyecto en sí (requiere Node/Remotion y una plantilla).
- Publicar, subir o enviar contenido; comprar; borrar originales.
- Que algo que **cambie el significado** se aplique sin tu aprobación.
- Frases que el catálogo no reconoce (se rechazan con aviso).

> Lo que **sí** está resuelto para esos casos futuros: **localizar el instante por
> frase** («tras mostrar el paso 2…, cuando digo "…"»), que es la base de cualquier
> inserción. Insertar medios y animaciones generadas quedan apuntados como backlog.

Alternativas que el agente puede proponer: aproximar con lo existente (p. ej. un
corte por rango), implementarlo (cambio de código), o pedirte aprobación.

## 11. Solución de problemas

| Síntoma | Causa probable / solución |
|---|---|
| `--out-dir debe estar dentro del repositorio` | Usa una ruta bajo `data/` |
| `la revisión N ya existe` | No re-ejecutes `run_project` sobre el mismo `--out-dir`; usa `apply` para editar |
| La voz no cuadra con los labios | Revisa que no haya **dos** audios (OBS + móvil) sin querer; el móvil se alinea automáticamente |
| Subtítulos enormes | Ya corregido; si usas un proyecto antiguo, re-renderiza con `apply` para regenerarlos |
| QC falla en `true_peak` | El máster incluye limitador; si persiste, revisa la fuente |
| El render tarda mucho | Usa `--encoder h264_nvenc` (GPU). El export de OpenChatCut es lento; el render local es el recomendado |
| `no entiendo la instrucción` | No está en el catálogo (ver sección 7) o está mal escrita |

## 12. Referencia de comandos

**Orquestador**

```bash
PYTHONPATH=src .venv/bin/python scripts/run_project.py --help
```

**CLI (`video-ai`)**

```bash
PYTHONPATH=src .venv/bin/python -m video_ai.cli --help
```

Subcomandos: `ingest`, `validate`, `events`, `compile`, `vision`, `cursor`,
`layout`, `instruct`, `apply`, `redact`, `subtitles`, `transcribe`, `mix`,
`fcpxml`, `render`, `align`.

Los más usados en el día a día:

| Comando | Para qué |
|---|---|
| `apply <proyecto> "<frase>" --root .` | Aplicar una edición y re-renderizar |
| `apply <proyecto> "<frase>" --root . --dry-run` | Ver qué haría, sin aplicarlo |
| `apply <proyecto> --ops patch.json --root .` | Aplicar un JSON Patch directo |
| `transcribe <medio> --srt salida.srt` | Solo transcribir |
| `vision <medio>` | OCR y redacciones propuestas |
| `render <plan.json> --root . --out vid.mp4` | Renderizar un plan concreto |
| `fcpxml <plan.json> --root . --out p.fcpxml` | Exportar a FCPXML |

Para dudas sobre qué es posible, pídele al agente que consulte este catálogo; te
dirá si algo no está soportado y qué alternativas hay.
