"""Composición de la escena: picture-in-picture y posición de capas.

Semántica de `transform` (coherente con el esquema del plan):

- `x`, `y`: esquina superior izquierda en coordenadas normalizadas 0..1 del lienzo.
- `scale`: fracción del ancho del lienzo que ocupa la capa.
- El alto se deduce del aspecto de la fuente para no deformar.

La aplicación de estos transform en el editor se verifica en el adaptador; aquí
se calcula y valida el plan.
"""

from __future__ import annotations

import copy
from typing import Any

POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right", "center")
FOCUS = ("center", "top", "bottom")


def picture_transform(
    *,
    position: str = "bottom-right",
    scale: float = 0.28,
    margin: float = 0.03,
    aspect: float = 9 / 16,
    canvas_aspect: float = 16 / 9,
    max_height: float | None = None,
    fit_aspect: float | None = None,
    focus: str = "center",
) -> dict[str, Any]:
    """Calcula el `transform` de una capa PiP.

    - `scale`: fracción del ancho del lienzo.
    - `aspect`: alto/ancho **de la fuente** (por ejemplo, 16/9 ≈ 1,78 para un móvil
      vertical 9:16). Solo se usa si no se indica `fit_aspect`.
    - `canvas_aspect`: ancho/alto del lienzo (por ejemplo, 16/9).
    - `max_height`: si se indica (fracción de alto del lienzo, 0..1), se reduce
      `scale` lo necesario para que la capa no supere ese alto.
    - `fit_aspect`: alto/ancho **de la caja** visible. Si se indica, la fuente se
      **recorta** a esa proporción (tipo *cover*), en lugar de deformarse: sirve
      para convertir un móvil vertical en un recuadro tipo «talking head» (~4:3).
    - `focus`: dónde anclar el recorte vertical (`center`, `top`, `bottom`).
    - El alto de la capa en fracción del lienzo es `scale * ratio * canvas_aspect`,
      con `ratio` = `fit_aspect` si se indica, si no `aspect`.
    """
    if position not in POSITIONS:
        raise ValueError(f"posición no soportada: {position!r}; usa una de {POSITIONS}")
    if focus not in FOCUS:
        raise ValueError(f"focus no soportado: {focus!r}; usa uno de {FOCUS}")
    if not 0 < scale <= 1:
        raise ValueError("scale debe estar en (0, 1]")
    if not 0 <= margin < 1:
        raise ValueError("margin debe estar en [0, 1)")
    if max_height is not None and not 0 < max_height <= 1:
        raise ValueError("max_height debe estar en (0, 1]")
    if fit_aspect is not None and fit_aspect <= 0:
        raise ValueError("fit_aspect debe ser > 0")
    ratio = fit_aspect if fit_aspect is not None else aspect
    unit_height = ratio * canvas_aspect  # alto por unidad de ancho
    if max_height is not None and scale * unit_height > max_height:
        scale = max_height / unit_height
    width = scale
    height = scale * unit_height
    if width + 2 * margin > 1 or height + 2 * margin > 1:
        raise ValueError("la capa y los márgenes no caben en el lienzo")

    if position == "top-left":
        x, y = margin, margin
    elif position == "top-right":
        x, y = 1 - margin - width, margin
    elif position == "bottom-left":
        x, y = margin, 1 - margin - height
    elif position == "bottom-right":
        x, y = 1 - margin - width, 1 - margin - height
    else:  # center
        x, y = (1 - width) / 2, (1 - height) / 2
    transform: dict[str, Any] = {"x": round(x, 4), "y": round(y, 4),
                                 "scale": round(scale, 4), "opacity": 1.0}
    if fit_aspect is not None:
        transform["fit_aspect"] = round(fit_aspect, 4)
        transform["focus"] = focus
    return transform


def picture_in_picture(
    plan: dict[str, Any],
    overlay_source: str,
    *,
    track_id: str | None = None,
    position: str = "bottom-right",
    scale: float = 0.28,
    margin: float = 0.03,
    aspect: float = 9 / 16,
    canvas_aspect: float | None = None,
    max_height: float | None = None,
    fit_aspect: float | None = None,
    focus: str = "center",
    start_frame: int | None = None,
    end_frame: int | None = None,
) -> dict[str, Any]:
    """Devuelve una copia con la capa superpuesta colocada como PiP.

    Afecta a los `timeline.items` cuya `source` es `overlay_source` (o que están
    en `track_id`) y que caen dentro de `[start_frame, end_frame]` si se indica.
    """
    result = copy.deepcopy(plan)
    if canvas_aspect is None:
        timebase = plan.get("timebase", {})
        canvas_aspect = float(timebase.get("width", 16)) / float(timebase.get("height", 9))
    transform = picture_transform(position=position, scale=scale, margin=margin,
                                  aspect=aspect, canvas_aspect=canvas_aspect,
                                  max_height=max_height, fit_aspect=fit_aspect, focus=focus)
    touched = 0
    for track in result.get("timeline", {}).get("tracks", []):
        if track_id is not None and track["id"] != track_id:
            continue
        for item in track.get("items", []):
            if track_id is None and item["source"] != overlay_source:
                continue
            item_in = int(item["timeline_in"])
            item_out = item_in + int(item.get("duration_frames", 0))
            if start_frame is not None and item_out <= start_frame:
                continue
            if end_frame is not None and item_in >= end_frame:
                continue
            item["transform"] = dict(transform)
            touched += 1
    if touched == 0:
        raise ValueError("no se encontró ninguna capa que colocar como PiP")
    from .plan import validate

    report = validate(result)
    if report["errors"]:
        raise ValueError("plan inválido tras PiP: " + "; ".join(report["errors"]))
    return result
