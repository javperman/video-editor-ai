# Spike real de OpenChatCut — 2026-11-09

## Resultado

**Apto como editor principal del sistema**, con reservas documentadas.
No se instaló nada en el sistema: se usó la AppImage oficial extraída y un
HOME/XDG aislados dentro del proyecto.

## Artefacto probado

| Campo | Valor |
|---|---|
| Versión | OpenChatCut OSS v0.2.17 |
| AppImage | `OpenChatCut-0.2.17-x86_64.AppImage` |
| SHA-256 | `1ce151fc2821cd3eecd074c3fb074a9e1f37320c65a1c1cc2c59f82a4dea8f13` |
| Verificación | SHA256SUMS oficial + digest de la API de GitHub: coinciden |
| Fuente | GitHub `0xsline/OpenChatCut`, tag `v0.2.17`, commit `72ddb330` |

## Pruebas superadas

| Prueba | Resultado |
|---|---|
| Arranque en Hyprland/Wayland | Correcto; servidor embebido en `127.0.0.1:5199` |
| Arranque con `--ozone-platform=wayland` | Correcto |
| Arranque con `--disable-gpu` | Correcto |
| Smoke interno `CC_SMOKE=1 CC_SMOKE_RENDER=1` | `SMOKE-OK`, render-still Remotion correcto |
| MCP HTTP con Bearer | 44 herramientas, initialize correcto |
| Crear proyecto | Correcto |
| Importar pantalla, móvil y voz | Correcto (rutas absolutas obligatorias) |
| Crear pistas V2, V3 y A1 | Correcto |
| Edición inválida | Rechazada atómicamente |
| Añadir tres medios y audio | Correcto |
| PiP de webcam con `transform` | Correcto (`scale 0.28`, `x 60`, `y -60`) |
| Split y ripple delete | Correcto |
| Texto superpuesto | Correcto |
| Validación de zoom | Correcto (`builtin:zoom`, magnificación 1.5) |
| Commit de sesión offline | 9 operaciones aplicadas atómicamente |
| Reapertura en otro transporte MCP | Correcto |
| Reapertura tras reiniciar la aplicación | Correcto |
| Render H.264 1080p30 con audio | Correcto por la ruta interna `POST /export` |
| QC FFprobe | 1920x1080, 30 fps, 360 frames, H.264 + AAC, 12,05 s |
| blackdetect | Sin negros |
| freezedetect | Un intervalo estático detectado (material sintético) |
| Loudness | −15,8 LUFS integrado; true peak −11,2 dBFS; sin clipping |
| Tiempo de render | ~21 s para 12 s (0,57× tiempo real) |

## Limitaciones y hallazgos

1. **El MCP offline no expone render/export.** `browserRequiredFor` incluye
   render y export. La vía headless real es `POST /export` con el documento de
   proyecto y el `timelineId`; el CLI de fuente es la alternativa oficial.
2. **Sesiones huérfanas.** Si el transporte MCP no confirma ni descarta una
   sesión, el proyecto queda bloqueado como "active browser or offline editor"
   y el MCP empaquetado no ofrece recuperarla. Mitigación: cada transacción
   debe abrirse, aplicarse y cerrarse en el mismo proceso; ante un fallo,
   recrear el proyecto.
3. **Acumulación de proyectos de prueba.** Cada ejecución creó un proyecto
   nuevo. Se limpiarán en la siguiente iteración.
4. **Sin verificación de aceleración H.264 real.** Con el FFmpeg empaquetado el
   log muestra fallback a `libx264`. Con `OPENCHATCUT_FFMPEG=/usr/bin/ffmpeg`
   el render funcionó, pero no se confirmó que NVENC se usara realmente.
5. **GPU del proceso Electron.** Aparecen fallos `GPU process launch failed`
   en el arranque por defecto; los renders de prueba funcionan por software.
6. **No probado aún:** transcripción local dentro del editor, captions,
   transiciones con su assetId real, render de 30 minutos, memoria pico,
   export FCPXML y muchos efectos WebGL.

## Decisión

OpenChatCut queda como **editor principal**, porque supera las pruebas
críticas de persistencia y render que eran el riesgo principal. Kdenlive no se
instala mientras no aparezca un fallo crítico en las pruebas ampliadas.
