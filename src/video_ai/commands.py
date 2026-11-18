"""Instrucciones en lenguaje natural → JSON Patch sobre el edit_plan.

Gramática **determinista**: no usa ningún modelo externo. Si una instrucción no
encaja en ningún patrón conocido, se rechaza en lugar de inventar una operación.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .revisions import RevisionStore

_TIME_TOKEN = re.compile(r"(?P<value>\d+(?:[:,.]\d+)?)\s*(?P<unit>s|seg|segs|segundos|sec|secs|seconds|m|min|minutos)?", re.IGNORECASE)
_RANGE = re.compile(
    r"(?:de|desde|entre|from)\s+(?P<a>[0-9:,.]+(?:\s*[a-z]+)?)\s+(?:a|hasta|y|to)\s+(?P<b>[0-9:,.]+(?:\s*[a-z]+)?)",
    re.IGNORECASE,
)
_REF = r"(?:#?(?P<number>\d+)|(?P<id>cut-[0-9A-Za-z_-]+|redact-[0-9A-Za-z_-]+))"


def parse_time(token: str) -> float:
    """Convierte «3», «3,5s», «1:02.5» o «2 minutos» a segundos."""
    raw = token.strip().lower().rstrip(".")
    if ":" in raw:
        minutes, _, seconds = raw.partition(":")
        return int(minutes) * 60 + float(seconds.replace(",", "."))
    match = _TIME_TOKEN.search(raw)
    if not match:
        raise ValueError(f"no entiendo el tiempo: {token!r}")
    value = float(match.group("value").replace(",", "."))
    unit = (match.group("unit") or "s").lower()
    if unit in {"m", "min", "minutos"}:
        return value * 60
    return value


def _find_range(text: str) -> tuple[float, float] | None:
    match = _RANGE.search(text)
    if not match:
        return None
    start, end = parse_time(match.group("a")), parse_time(match.group("b"))
    return (start, end) if start <= end else (end, start)


def _primary_video_source(plan: dict[str, Any]) -> str:
    for source in plan.get("sources", []):
        if source.get("kind") == "video":
            return source["id"]
    return plan["sources"][0]["id"]


def _next_id(plan: dict[str, Any], key: str, prefix: str) -> str:
    numbers = []
    for item in plan.get("edits", {}).get(key, []):
        match = re.search(r"(\d+)$", str(item.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"{prefix}-{max(numbers, default=0) + 1:04d}"


@dataclass
class Intent:
    action: str
    summary: str
    ops: list[dict[str, Any]] = field(default_factory=list)
    risk: str = "human_review"
    affects_meaning: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "summary": self.summary, "ops": self.ops,
                "risk": self.risk, "affects_meaning": self.affects_meaning}


def _select_cuts(plan: dict[str, Any], selector: str) -> list[int]:
    selector = selector.lower()
    indices: list[int] = []
    for index, cut in enumerate(plan.get("edits", {}).get("cuts", [])):
        if selector in {"todos", "all", "todo"}:
            indices.append(index)
        elif selector == "significado" and cut.get("affects_meaning"):
            indices.append(index)
        elif selector == "conservador" and cut.get("risk") == "conservative":
            indices.append(index)
        elif selector == "automatic" and cut.get("risk") == "automatic":
            indices.append(index)
        elif selector == "pendiente" and cut.get("approval") == "pending":
            indices.append(index)
        elif selector == "muletilla" and cut.get("category") == "filler":
            indices.append(index)
        elif selector == "repeticion" and cut.get("category") == "repetition":
            indices.append(index)
        elif selector == "silencio" and cut.get("category") == "silence":
            indices.append(index)
    return indices


def _selector_from(text: str) -> str | None:
    lowered = text.lower()
    if "significado" in lowered:
        return "significado"
    if "muletilla" in lowered or "filler" in lowered:
        return "muletilla"
    if "repetici" in lowered:
        return "repeticion"
    if "silenc" in lowered:
        return "silencio"
    if "conservador" in lowered:
        return "conservador"
    if "automatic" in lowered:
        return "automatic"
    if "pendiente" in lowered:
        return "pendiente"
    if re.search(r"\b(todos|all|todo)\b", lowered) or "corte" in lowered:
        return "todos"
    return None


def _parse_cut_range(text: str, plan: dict[str, Any]) -> Intent | None:
    if not re.search(r"\b(corta|quita|elimina|recorta|remove|cut|delete)\b", text, re.IGNORECASE):
        return None
    span = _find_range(text)
    if span is None:
        return None
    start, end = span
    fps = float(plan["timebase"]["fps"])
    source = _primary_video_source(plan)
    cut_id = _next_id(plan, "cuts", "cut")
    value = {
        "id": cut_id,
        "source": source,
        "targets": [item["id"] for item in plan.get("sources", [])],
        "source_in": int(round(start * fps)),
        "source_out": int(round(end * fps)),
        "reason": f"petición del usuario: {text.strip()}",
        "category": "other",
        "evidence_refs": ["natural_language"],
        "confidence": 1.0,
        "risk": "human_review",
        "affects_meaning": False,
        "approval": "approved",
    }
    return Intent("cut_range", f"añadir corte de {start:.2f}s a {end:.2f}s ({cut_id})",
                  [{"op": "add", "path": "/edits/cuts/-", "value": value}])


def _parse_remove_cut(text: str, plan: dict[str, Any]) -> Intent | None:
    if not re.search(r"\b(quita|elimina|borra|remove|delete)\b.*\bcorte", text, re.IGNORECASE):
        return None
    match = re.search(_REF, text)
    if not match:
        return None
    cuts = plan.get("edits", {}).get("cuts", [])
    target = None
    if match.group("id"):
        target = match.group("id")
    elif match.group("number"):
        position = int(match.group("number")) - 1
        if 0 <= position < len(cuts):
            target = cuts[position]["id"]
    if target is None:
        return None
    index = next((i for i, cut in enumerate(cuts) if cut["id"] == target), None)
    if index is None:
        return None
    return Intent("remove_cut", f"eliminar el corte {target}",
                  [{"op": "remove", "path": f"/edits/cuts/{index}"}])


def _parse_approval(text: str, plan: dict[str, Any]) -> Intent | None:
    match = re.search(r"\b(aprueba|aprobar|accept|rechaza|rechazar|reject)\b(?P<rest>.*)", text, re.IGNORECASE)
    if not match:
        return None
    decision = "approved" if match.group(1).lower().startswith(("aprueba", "aprobar", "accept")) else "rejected"
    rest = match.group("rest").lower()
    cuts = plan.get("edits", {}).get("cuts", [])
    indices: list[int] = []
    ref = re.search(_REF, rest)
    if re.search(r"\b(todos|all)\b", rest):
        indices = _select_cuts(plan, _selector_from(rest) or "todos")
    elif ref and ref.group("id"):
        index = next((i for i, cut in enumerate(cuts) if cut["id"] == ref.group("id")), None)
        indices = [index] if index is not None else []
    elif ref and ref.group("number"):
        position = int(ref.group("number")) - 1
        indices = [position] if 0 <= position < len(cuts) else []
    else:
        selector = _selector_from(rest)
        if selector is None:
            return None
        indices = _select_cuts(plan, selector)
    if not indices:
        return None
    ops = [{"op": "replace", "path": f"/edits/cuts/{index}/approval", "value": decision} for index in indices]
    verb = "aprobar" if decision == "approved" else "rechazar"
    return Intent("approval", f"{verb} {len(indices)} corte(s)", ops,
                  risk="human_review", affects_meaning=any(cuts[i].get("affects_meaning") for i in indices))


def _parse_redact_range(text: str, plan: dict[str, Any]) -> Intent | None:
    if not re.search(r"\b(redacta|oculta|censura|difumina|tapa|blur|redact|hide|censor)\b", text, re.IGNORECASE):
        return None
    span = _find_range(text)
    if span is None:
        return None
    start, end = span
    fps = float(plan["timebase"]["fps"])
    source = _primary_video_source(plan)
    redaction_id = _next_id(plan, "redactions", "redact")
    value = {
        "id": redaction_id,
        "source": source,
        "source_in": int(round(start * fps)),
        "source_out": int(round(end * fps)),
        "method": "blur",
        "reason": f"petición del usuario: {text.strip()}",
        "boxes": [{"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}],
    }
    return Intent("redact_range", f"añadir redacción de {start:.2f}s a {end:.2f}s ({redaction_id})",
                  [{"op": "add", "path": "/edits/redactions/-", "value": value}])


def _parse_remove_redaction(text: str, plan: dict[str, Any]) -> Intent | None:
    if not re.search(r"\b(quita|elimina|borra|remove|delete)\b.*\bredacci", text, re.IGNORECASE):
        return None
    match = re.search(_REF, text)
    if not match:
        return None
    redactions = plan.get("edits", {}).get("redactions", [])
    target = match.group("id")
    index = next((i for i, item in enumerate(redactions) if item["id"] == target), None)
    if index is None:
        return None
    return Intent("remove_redaction", f"eliminar la redacción {target}",
                  [{"op": "remove", "path": f"/edits/redactions/{index}"}])


def _parse_goal(text: str, plan: dict[str, Any]) -> Intent | None:
    match = re.search(r"objetivo\s*(?:es|ser[aá]|:)\s*(?P<goal>.+)", text, re.IGNORECASE)
    if not match:
        return None
    goal = match.group("goal").strip().strip('".')
    return Intent("set_goal", f"cambiar el objetivo a: {goal}",
                  [{"op": "add", "path": "/intent/goal", "value": goal}], risk="automatic")


_PHRASE = re.compile(r"[«\"'\u201c\u201d\u2018\u2019]([^«»\"'\u201c\u201d\u2018\u2019]+)[»\"'\u201c\u201d\u2018\u2019]")
_START_WORDS = r"\b(empieza|empezar|comienza|comenzar|arranca|arrancar|start|begin)\b"
_END_WORDS = r"\b(termina|terminar|acaba|acabar|finaliza|finalizar|end)\b"


def _norm(token: str) -> str:
    return re.sub(r"[^\wáéíóúüñ]+", "", str(token).lower())


def _find_phrase(words: list[dict[str, Any]], phrase: str) -> tuple[float, float] | None:
    """Devuelve (inicio, fin) en segundos de la primera aparición de `phrase`."""
    target = [_norm(token) for token in phrase.split() if _norm(token)]
    if not target:
        return None
    tokens = [_norm(word.get("word", "")) for word in words]
    for index in range(len(tokens) - len(target) + 1):
        if tokens[index:index + len(target)] == target:
            return float(words[index]["start"]), float(words[index + len(target) - 1]["end"])
    return None


def _parse_marker(text: str, plan: dict[str, Any], words: list[dict[str, Any]]) -> Intent | None:
    """«empieza cuando diga X» / «termina tras decir Y» → cortes de introducción/final."""
    wants_start = re.search(_START_WORDS, text, re.IGNORECASE) is not None
    wants_end = re.search(_END_WORDS, text, re.IGNORECASE) is not None
    if not (wants_start or wants_end):
        return None
    phrase_match = _PHRASE.search(text)
    if not phrase_match:
        return None
    phrase = phrase_match.group(1).strip()
    span = _find_phrase(words, phrase)
    if span is None:
        return None
    phrase_start, phrase_end = span
    fps = float(plan["timebase"]["fps"])
    source = _primary_video_source(plan)
    duration = int(next(s for s in plan["sources"] if s["id"] == source)["duration_frames"])
    targets = [item["id"] for item in plan.get("sources", [])]
    counter = int(re.search(r"(\d+)$", _next_id(plan, "cuts", "cut")).group(1))

    def _cut(source_in: int, source_out: int, label: str) -> dict[str, Any]:
        nonlocal counter
        counter += 1
        return {
            "id": f"cut-{counter:04d}", "source": source, "targets": targets,
            "source_in": source_in, "source_out": source_out,
            "reason": f"petición del usuario: {text.strip()}", "category": "other",
            "evidence_refs": ["natural_language"], "confidence": 0.9,
            "risk": "human_review", "affects_meaning": False, "approval": "approved",
        }

    ops: list[dict[str, Any]] = []
    labels: list[str] = []
    if wants_start:
        cut_end = int(round(phrase_start * fps))
        if cut_end > 0:
            ops.append({"op": "add", "path": "/edits/cuts/-",
                        "value": _cut(0, cut_end, "empieza")})
            labels.append(f"empieza en «{phrase}» ({phrase_start:.2f}s)")
    if wants_end:
        cut_start = int(round(phrase_end * fps))
        if cut_start < duration:
            ops.append({"op": "add", "path": "/edits/cuts/-",
                        "value": _cut(cut_start, duration, "termina")})
            labels.append(f"termina en «{phrase}» ({phrase_end:.2f}s)")
    if not ops:
        return None
    return Intent("marker", "; ".join(labels), ops, risk="human_review")


def _overlay_source(plan: dict[str, Any]) -> str | None:
    for source in plan.get("sources", []):
        if source.get("role") in {"webcam", "phone_cam"}:
            return source["id"]
    videos = [source["id"] for source in plan.get("sources", []) if source.get("kind") == "video"]
    return videos[1] if len(videos) > 1 else None


def _parse_layout(text: str, plan: dict[str, Any]) -> Intent | None:
    """«pon la webcam arriba a la izquierda al 30 %» → transform del PiP."""
    lowered = text.lower()
    overlay = _overlay_source(plan)
    if overlay is None:
        return None
    vertical = "top" if re.search(r"arriba|superior", lowered) else (
        "bottom" if re.search(r"abajo|inferior", lowered) else None)
    horizontal = "left" if re.search(r"izquierda", lowered) else (
        "right" if re.search(r"derecha", lowered) else None)
    position = f"{vertical}-{horizontal}" if vertical and horizontal else None
    scale_match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", lowered) or \
        re.search(r"al\s+(\d+(?:[.,]\d+)?)\s*(?:por ciento)?", lowered)
    scale = None
    if scale_match:
        value = float(scale_match.group(1).replace(",", "."))
        scale = value / 100 if value > 1 else value
    # Altura máxima opcional: «sin pasar del 45 % del alto» / «altura máxima 45 %».
    height_match = re.search(r"(?:alto|altura)\D{0,12}(\d+(?:[.,]\d+)?)\s*%", lowered) or \
        re.search(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:del\s+)?(?:alto|altura)", lowered)
    max_height = None
    if height_match:
        height_value = float(height_match.group(1).replace(",", "."))
        max_height = height_value / 100 if height_value > 1 else height_value
    # Proporción de caja (alto/ancho): «recorta a 4:3», «formato cuadrado».
    crop_words = r"rec[oó]rt|encuadre|encuadrar|aspecto|formato|marco|talking|face ?cam|cuadrad[oa]"
    fit_aspect = None
    ratio_match = re.search(r"(\d+)\s*[:x/]\s*(\d+)", lowered)
    if ratio_match and re.search(crop_words, lowered):
        ratio_w, ratio_h = int(ratio_match.group(1)), int(ratio_match.group(2))
        if ratio_w > 0 and ratio_h > 0:
            fit_aspect = ratio_h / ratio_w  # ancho:alto → alto/ancho
    elif re.search(r"cuadrad[oa]|face ?cam", lowered):
        fit_aspect = 1.0
    elif re.search(r"vertical", lowered) and re.search(crop_words, lowered):
        fit_aspect = 4 / 3  # retrato 3:4
    # Anclaje del recorte: «encuadre arriba/abajo/centrado».
    focus = None
    if re.search(r"(?:encuadre|enfoca|rec[oó]rta|ancla)\w*\s+(?:arriba|superior|cara|cabeza)", lowered):
        focus = "top"
    elif re.search(r"(?:encuadre|enfoca|rec[oó]rta|ancla)\w*\s+(?:abajo|inferior)", lowered):
        focus = "bottom"
    elif re.search(r"(?:encuadre|enfoca|rec[oó]rta|ancla)\w*\s+(?:centrado|centro|center)", lowered):
        focus = "center"
    if position is None and scale is None and max_height is None and fit_aspect is None \
            and focus is None:
        return None
    mentions_layer = re.search(r"webcam|m[oó]vil|c[aá]mara|recuadro|pip|inset|miniatura", lowered)
    if not (mentions_layer or re.search(r"\b(pon|coloca|mueve|sit[uú]a|place|move)\b|rec[oó]rta", lowered)):
        return None

    from .layouts import picture_transform

    source = next(s for s in plan["sources"] if s["id"] == overlay)
    existing_transform = next((item.get("transform") for track in plan["timeline"]["tracks"]
                               for item in track["items"]
                               if item["source"] == overlay and item.get("transform")), {}) or {}
    if fit_aspect is None:
        fit_aspect = existing_transform.get("fit_aspect")
    if focus is None:
        focus = existing_transform.get("focus", "center")
    if max_height is not None and fit_aspect is None \
            and not (source.get("width") and source.get("height")):
        raise ValueError(
            "no puedo aplicar el tope de alto: el plan no guarda el tamaño de la "
            "fuente. Regenera el proyecto con run_project (las corridas nuevas sí lo "
            "incluyen), indica una proporción de recorte (p. ej. «recorta a 4:3») o "
            "el tamaño solo por el ancho")
    aspect = float(source.get("height") or 1080) / float(source.get("width") or 1920)
    canvas_aspect = float(plan["timebase"]["width"]) / float(plan["timebase"]["height"])
    if scale is None:
        scale = float(existing_transform.get("scale") or 0.28)
    transform = picture_transform(position=position or "bottom-right", scale=scale,
                                  margin=0.03, aspect=aspect, canvas_aspect=canvas_aspect,
                                  max_height=max_height, fit_aspect=fit_aspect, focus=focus)
    ops: list[dict[str, Any]] = []
    for track_index, track in enumerate(plan["timeline"]["tracks"]):
        for item_index, item in enumerate(track["items"]):
            if item["source"] != overlay:
                continue
            ops.append({"op": "add", "path": f"/timeline/tracks/{track_index}/items/{item_index}/transform",
                        "value": dict(transform)})
    if not ops:
        return None
    summary = f"colocar {overlay} en {position or 'posición actual'} al {scale:.0%}"
    if fit_aspect is not None:
        summary += f", recorte {fit_aspect:.2f}:1 ({focus})"
    if max_height is not None:
        summary += f" (alto máximo {max_height:.0%})"
    return Intent("layout", summary, ops, risk="automatic")


def _parse_audio(text: str, plan: dict[str, Any]) -> Intent | None:
    """«normaliza el audio a -14 LUFS» → audio.normalization.target_lufs."""
    match = re.search(r"(-?\d+(?:[.,]\d+)?)\s*(?:lufs|luf)\b", text, re.IGNORECASE)
    if not match:
        return None
    if not re.search(r"\b(normaliza|normalizar|sube|baja|ajusta|audio|volumen|nivel|loudness|normalize)\b",
                     text, re.IGNORECASE):
        return None
    target = float(match.group(1).replace(",", "."))
    if not (-40.0 <= target <= 0.0):
        return None
    return Intent("audio_normalization", f"normalizar el audio a {target} LUFS",
                  [{"op": "add", "path": "/audio/normalization/target_lufs", "value": target}],
                  risk="automatic")


def _parse_subtitles(text: str, plan: dict[str, Any]) -> Intent | None:
    """«quita los subtítulos» / «subtítulos minimalistas»."""
    lowered = text.lower()
    if not re.search(r"subt[ií]tul", lowered):
        return None
    if re.search(r"\b(quita|quitar|elimina|eliminar|borra|borrar|sin|desactiva|remove|no)\b", lowered):
        return Intent("subtitles_off", "quitar los subtítulos",
                      [{"op": "replace", "path": "/edits/subtitles", "value": []}], risk="automatic")
    style = None
    if re.search(r"minimal", lowered):
        style = "minimal"
    elif re.search(r"tutorial", lowered):
        style = "tutorial"
    if style is None:
        return None
    subtitles = plan.get("edits", {}).get("subtitles", [])
    ops = [{"op": "replace", "path": f"/edits/subtitles/{index}/style", "value": style}
           for index in range(len(subtitles))]
    if not ops:
        return None
    return Intent("subtitles_style", f"estilo de subtítulos: {style}", ops, risk="automatic")


PARSERS = (_parse_cut_range, _parse_remove_cut, _parse_approval, _parse_redact_range,
           _parse_remove_redaction, _parse_goal, _parse_layout, _parse_audio,
           _parse_subtitles)


def parse_instruction(text: str, plan: dict[str, Any], words: list[dict[str, Any]] | None = None) -> Intent:
    if words:
        intent = _parse_marker(text, plan, words)
        if intent is not None and intent.ops:
            return intent
    for parser in PARSERS:
        intent = parser(text, plan)
        if intent is not None and intent.ops:
            return intent
    raise ValueError(f"no entiendo la instrucción: {text!r}")


def run_instruction(store: RevisionStore, text: str, base_revision: int | None = None,
                    words: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Aplica una instrucción sobre la revisión actual y guarda una nueva."""
    current = store.current()
    if current is None:
        raise ValueError("no hay revisión actual en el almacén")
    intent = parse_instruction(text, current, words)
    patched = store.apply_patch(intent.ops, base_revision)
    return {
        "instruction": text,
        "intent": intent.as_dict(),
        "revision": int(patched["revision"]),
        "parent_revision": int(patched["parent_revision"]),
    }
