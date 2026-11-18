---
name: Edit plan
description: Usar al crear, revisar o modificar edit_plan.json en video-editor-ai.
---

# Edit plan

`schemas/edit-plan.schema.json` es la fuente de verdad. Las reglas completas
están en `docs/plan-rules.md` (pendiente de redacción) y el esquema actual.

## Reglas duras

- Tiempos en **frames enteros**; una sola regla de redondeo.
- Coordenadas normalizadas `0..1`.
- Inicio siempre anterior al final; sin duraciones negativas.
- Rutas relativas al workspace, sin symlinks ni escapes.
- Assets con `sha256` verificado.
- Cortes no destructivos: ocultan intervalos, no borran fuentes.
- Todo corte lleva motivo, evidencia, confianza, contexto y riesgo.
- Los cortes `human_review` bloquean el render hasta su aprobación.

## Conservación del significado

Nunca eliminar automáticamente una explicación, advertencia, instrucción,
cifra, comando o pausa didáctica. Ante duda, clasificar como `human_review`.

## Flujo

1. Validar contra el esquema.
2. Ejecutar el validador semántico.
3. Crear una revisión nueva e inmutable.
4. Compilar al editor y validar antes de aplicar.
