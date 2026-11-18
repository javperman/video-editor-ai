"""Conversión del `transform` del plan a la semántica de OpenChatCut.

Evidencia del motor de render de OpenChatCut (`remotion-bundle/bundle.js`,
`appearanceAt`):

    transform: translate(<x>%, <y>%) rotate(<r>deg) scale(<sx>, <sy>)
    transformOrigin: 50% 50%

Es decir, `x`/`y` son **porcentajes del tamaño propio del elemento** y el origen
es el centro. Nuestro plan usa un `transform` normalizado distinto:

    x, y      esquina superior izquierda en 0..1 del lienzo
    scale     fracción del ancho del lienzo

Suponiendo que el elemento base ocupa el lienzo completo, la esquina visual tras
escalar alrededor del centro es `(1-s)/2`, y el desplazamiento necesario es:

    x% = x - 0.5 + s/2
    y% = y - 0.5 + s/2

**Pendiente de verificación por render:** la suposición «el elemento base ocupa el
lienzo» no está comprobada; la calibración por render quedó inconcluyente (ver
`docs/layouts.md`). No aplicar en el editor sin completar esa verificación.
"""

from __future__ import annotations

from typing import Any


def plan_transform_to_occ(transform: dict[str, Any]) -> dict[str, float]:
    """Convierte un `transform` normalizado del plan a `{x%, y%, scale}` de OCC."""
    scale = float(transform.get("scale", 1.0))
    if scale <= 0:
        raise ValueError("scale debe ser mayor que cero")
    x = float(transform.get("x", 0.0))
    y = float(transform.get("y", 0.0))
    for name, value in (("x", x), ("y", y)):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} debe estar en 0..1")
    occ: dict[str, float] = {
        "x": round((x - 0.5 + scale / 2) * 100, 3),
        "y": round((y - 0.5 + scale / 2) * 100, 3),
        "scale": round(scale, 4),
    }
    rotation = float(transform.get("rotation", 0.0))
    if rotation:
        occ["rotation"] = rotation
    return occ


def occ_transform_to_plan(x_percent: float, y_percent: float, scale: float) -> dict[str, float]:
    """Inversa de `plan_transform_to_occ`, para diagnosticar un render."""
    return {
        "x": round(x_percent / 100 + 0.5 - scale / 2, 4),
        "y": round(y_percent / 100 + 0.5 - scale / 2, 4),
        "scale": round(scale, 4),
    }
