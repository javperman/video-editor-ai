# ADR 0001 — Editor principal

- **Fecha:** 2026-11-09
- **Estado:** aceptada provisionalmente

## Contexto

Se compararon OpenChatCut, Kdenlive, Velorn, NodeTool, Remotion, Blender VSE
y alternativas menores para editar automáticamente tutoriales técnicos a 1080p
en Arch Linux/Wayland con 16 GB de RAM y una RTX 3050 Ti de 4 GB.

## Decisión

Usar **OpenChatCut OSS v0.2.17** como editor principal, con:

- AppImage verificada y entorno HOME/XDG aislados.
- `edit_plan.json` como fuente de verdad independiente.
- Render headless mediante `POST /export` o el CLI de fuente.
- Remotion/FFmpeg como motor auxiliar.
- Kdenlive como respaldo no instalado.

## Justificación

- Persistencia probada al reabrir el proyecto en otro transporte y tras
  reiniciar la aplicación.
- Edición estructurada por MCP con borradores, validación atómica y snapshots.
- PiP, split, texto y zoom validados.
- Render 1080p con audio correcto y QC sin clipping.
- Su motor Remotion interno evita un segundo proyecto y un round-trip frágil.

## Consecuencias

- Hay que mitigar las sesiones MCP huérfanas.
- El render/export no está en el MCP offline: se automatiza por HTTP interno.
- Queda pendiente validar memoria y estabilidad con material real de 30 min.
- Si aparece un fallo crítico de persistencia o render, se revisa la decisión
  y se activa Kdenlive.
