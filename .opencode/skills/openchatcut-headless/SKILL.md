---
name: OpenChatCut headless
description: Usar al arrancar, automatizar, editar por MCP o exportar OpenChatCut en video-editor-ai sin navegador ni UI.
---

# OpenChatCut headless

## Arranque

```bash
./scripts/run-openchatcut.sh
```

Deja el servidor en `http://127.0.0.1:5199`. El `HOME` y los XDG están
aislados en `data/`. El token MCP se lee de `.openchatcut/mcp-token` dentro de
ese HOME aislado.

## Flujo MCP obligatorio

1. `target_project` sobre un proyecto sin dueño.
2. `begin_edit_session` con `approvalMode: "auto"`.
3. Operaciones con `editSessionId`.
4. `review_edit_session` para confirmar o `discard_edit_session` para cancelar.

**Nunca** dejes un draft abierto al terminar el proceso: el proyecto queda
bloqueado como "active browser or offline editor" y el MCP empaquetado no
ofrece recuperación. Si ocurre, crea un proyecto nuevo.

## Reglas conocidas

- `import_assets` exige rutas absolutas.
- El MCP offline no expone render/export (`browserRequiredFor`).
- `validateOnly: true` valida sin publicar; úsalo antes de un lote grande.
- Añadir media: `edit_item` con `{type, assetId, track, fromFrame, durationInFrames}`.
- PiP: `edit_item` update con `transform: {scale, x, y}`.
- Zoom: `edit_item` add `{type:"effect", targetItemId, assetId:"builtin:zoom"}`.
- Texto: `edit_item` add `{type:"text", text, track, fromFrame, durationInFrames}`.

## Export headless

El MCP no exporta. Usa la ruta interna:

```bash
python3 scripts/occ_export.py <project-id> data/artifacts/salida.mp4
```

Equivale a `POST /export` con `{state, project, timelineId, format, codec,
resolution, fps}`. Tarda ~0,57× del tiempo real en material simple; mide
siempre antes de extrapolar.
