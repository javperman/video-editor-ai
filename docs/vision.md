# Visión selectiva — 2026-11-09

Análisis local de la imagen para proponer cortes, zooms y **redacciones de datos
sensibles**. Todo ocurre en la máquina; no se sube ningún fotograma a un servicio
externo.

Módulo: `src/video_ai/vision.py`. CLI: `video-ai vision`, `video-ai cursor`.

## Qué hace

| Función | Método | Notas |
|---|---|---|
| Cambios de escena | filtro `scdet` de FFmpeg | porcentaje 0-100 |
| Muestreo adaptativo | cortes + rejilla periódica | determinista |
| Extracción de fotogramas | FFmpeg (`-ss` rápido) | PNG por marca |
| OCR | `rapidocr-onnxruntime` o `tesseract` | local, con cajas |
| Datos sensibles | patrones + plegado de acentos | propone redacciones |
| Cursor | muestras grabadas en captura | paradas → candidatas a zoom |

## OCR sin dependencias del sistema

El OCR usa `rapidocr-onnxruntime`, instalado dentro del entorno aislado
(`.venv`), así que **no requiere `sudo`** ni paquetes globales. Si se prefiere
`tesseract` (mejor para prosa en español), se instala aparte y el módulo lo
detecta automáticamente:

```bash
sudo pacman -S tesseract tesseract-data-spa tesseract-data-eng
```

El backend efectivo se informa en el campo `backend` del resultado.

## Uso

```bash
# Análisis: escenas, OCR y redacciones propuestas
PYTHONPATH=src .venv/bin/python -m video_ai.cli vision captura.mp4 \
  --source-id screen --ocr-fps 1 --out vision.json

# Cursor: convierte las muestras de captura en candidatas a zoom
PYTHONPATH=src .venv/bin/python -m video_ai.cli cursor cursor.jsonl --fps 30 --out zooms.json
```

Las redacciones salen con este formato, listo para `edits.redactions` del plan:

```json
{
  "id": "redact-0001",
  "source": "screen",
  "source_in": 0,
  "source_out": 105,
  "method": "blur",
  "reason": "texto sensible detectado: api_key",
  "boxes": [{ "x": 0.023, "y": 0.067, "width": 0.697, "height": 0.163 }]
}
```

## Prueba ejecutada

Fixture sintética (`scripts/make_vision_fixture.sh`) con una imagen que contiene
un token, un correo y la palabra «contraseña»:

- Se detectaron los tres tipos (`api_key`, `email`, `password_label`).
- Se propusieron 3 redacciones con cajas normalizadas válidas.
- El plan con esas redacciones pasa el esquema y la validación semántica.
- Alias con acentos: «contraseña» detecta igual que «contrasena».

## Límites conocidos

1. **Cambios de escena en contenido de pantalla**: `scdet` detecta bien cortes
   duros (negro/blanco) pero **no** cambios suaves de interfaz. Para pantalla,
   el muestreo periódico es más fiable que la detección de escena.
2. **Granularidad del OCR**: se muestrea a `--ocr-fps` (1 por segundo por
   defecto). Un dato visible menos tiempo que el intervalo puede no detectarse;
   sube `--ocr-fps` para el barrido de datos sensibles.
3. **Ventana de redacción**: se amplía ±1,5 s y se agrupan hallazgos próximos
   (hasta 3 s). Es una propuesta conservadora, no una garantía.
4. **Cursor**: la detección *a posteriori* es poco fiable, así que se graba la
   posición real durante la captura con `scripts/record_cursor.sh` (Hyprland).
   Sin esas muestras no hay candidatas a zoom.
5. **Falsos positivos**: patrones como `long_hex` o `card_number` pueden marcar
   contenido legítimo; las redacciones se revisan antes de aplicarlas.
