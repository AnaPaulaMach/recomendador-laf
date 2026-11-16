"""Comparación entre productos a partir de resultados LAF ya calculados.

Este módulo NO ejecuta ni modifica el razonador: sólo lee valores que el
evaluador LAF ya produjo (grafo y ranking) y los reorganiza para explicar
por qué se recomendó un producto frente a los demás. Todas las operaciones
son deterministas (orden canónico, sin muestreo ni truncamientos).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import statistics
from typing import Any

from .comparison_graph import (
    CollapsedAspect,
    CollapsedDimension,
    CollapsedGraph,
    build_collapsed_graph,
)


def _num(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _clean(value: Any) -> str:
    return str(value or "").strip()


_PREFERENCE_LEVELS = (
    (1.0, "Es prioridad"),
    (0.67, "Bastante"),
    (0.33, "Poco"),
    (0.0, "No me importa"),
)


def _level_label(preference: float) -> str:
    """Etiqueta del nivel más cercano a la preferencia (los 4 que elige el usuario)."""
    return min(_PREFERENCE_LEVELS, key=lambda level: abs(level[0] - preference))[1]


_LEVEL_KEYS = (
    (1.0, "alta"),
    (0.67, "bastante"),
    (0.33, "poco"),
    (0.0, "nula"),
)


def _level_key(preference: float) -> str:
    """Slug del nivel para estilar el chip de prioridad (alta/bastante/poco/nula)."""
    return min(_LEVEL_KEYS, key=lambda level: abs(level[0] - preference))[1]


@dataclass(frozen=True)
class AspectStanding:
    """Posición del producto seleccionado en un aspecto frente al resto."""

    key: str
    label: str
    position: int
    total: int
    value: float
    field_median: float
    preference: float
    tier: str  # "fuerte" | "medio" | "flojo"
    priority: str  # "alta" | "media" | "nula"
    priority_label: str  # "No me importa" | "Poco" | "Bastante" | "Es prioridad"
    priority_key: str  # slug para el chip: "alta" | "bastante" | "poco" | "nula"


@dataclass(frozen=True)
class RankingRow:
    entity_id: str
    entity_name: str
    position: int
    final_score: float
    confidence: float
    preference: float
    binding: str  # "confianza" | "preferencia" | "empate" | "multicriterio"
    status: str
    is_selected: bool
    decision_model: str = ""

    @property
    def conf_pct(self) -> int:
        return round(self.confidence * 100)

    @property
    def pref_pct(self) -> int:
        return round(self.preference * 100)


def build_aspect_standings(
    graph: dict[str, Any] | None,
    selected_name: str,
    aspect_labels: dict[str, str] | None = None,
    preference_overrides: dict[str, float] | None = None,
) -> tuple[AspectStanding, ...]:
    """Para cada aspecto, ubica al producto seleccionado entre todos los productos.

    Usa el máximo `accumulated_value` positivo por (producto, aspecto) del grafo.
    Un nodo sólo cuenta para el producto indicado en su `metadata.product`, por lo
    que los grupos nunca mezclan productos.
    """
    nodes = (graph or {}).get("nodes") or []
    selected_name = _clean(selected_name)
    labels = aspect_labels or {}
    overrides = preference_overrides or {}

    field: dict[str, dict[str, float]] = {}
    preferences: dict[str, float] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("node_type") not in ("aspect", "dimension"):
            continue
        if node.get("polarity") != "positive":
            continue
        meta = node.get("metadata") or {}
        product = _clean(meta.get("product"))
        aspect = _clean(meta.get("aspect"))
        if not product or not aspect:
            continue
        # Sólo aspectos que el usuario pudo priorizar (los del dominio), si se pasan.
        if labels and aspect not in labels:
            continue
        value = _num(node.get("accumulated_value"))
        bucket = field.setdefault(aspect, {})
        if value > bucket.get(product, -1.0):
            bucket[product] = value
        if product == selected_name:
            pref = _num(node.get("preference"))
            if pref > preferences.get(aspect, -1.0):
                preferences[aspect] = pref

    standings: list[AspectStanding] = []
    for aspect in field:
        products = field[aspect]
        if selected_name not in products:
            continue
        selected_value = products[selected_name]
        ordered = sorted(products.values(), reverse=True)
        position = 1 + sum(1 for value in ordered if value > selected_value)
        total = len(products)
        median = statistics.median(ordered) if ordered else 0.0
        preference = _num(overrides.get(aspect, preferences.get(aspect, 0.0)))
        ratio = (total - position + 1) / total if total else 0.0
        tier = "fuerte" if ratio >= 0.66 else ("flojo" if ratio < 0.34 else "medio")
        priority = "alta" if preference >= 0.8 else ("nula" if preference <= 0.01 else "media")
        standings.append(
            AspectStanding(
                key=aspect,
                label=labels.get(aspect, aspect.replace("_", " ").capitalize()),
                position=position,
                total=total,
                value=round(selected_value, 3),
                field_median=round(median, 3),
                preference=round(preference, 2),
                tier=tier,
                priority=priority,
                priority_label=_level_label(preference),
                priority_key=_level_key(preference),
            )
        )

    standings.sort(key=lambda s: (-s.preference, s.position, s.key))
    return tuple(standings)


def _binding(confidence: float, preference: float) -> str:
    """Qué etiqueta define el puntaje = min(confianza, preferencia)."""
    if preference < confidence - 1e-6:
        return "preferencia"
    if confidence < preference - 1e-6:
        return "confianza"
    return "empate"


def build_ranking(ranking: Any, selected_entity_id: str) -> tuple[RankingRow, ...]:
    """Ordena el ranking completo por posición y marca el producto seleccionado."""
    selected_entity_id = _clean(selected_entity_id)
    rows = []
    for entry in ranking:
        decision_model = _clean(getattr(entry, "metadata", {}).get("decision_model"))
        rows.append(RankingRow(
            entity_id=entry.entity_id,
            entity_name=entry.entity_name,
            position=entry.position,
            final_score=round(float(entry.final_score), 3),
            confidence=round(_num(entry.confidence), 3),
            preference=round(_num(entry.preference), 3),
            binding=(
                "multicriterio"
                if decision_model.startswith("post_laf_multicriteria")
                else _binding(_num(entry.confidence), _num(entry.preference))
            ),
            decision_model=decision_model,
            status=entry.status,
            is_selected=entry.entity_id == selected_entity_id,
        ))
    rows.sort(key=lambda r: (r.position or 10_000, r.entity_name))
    return tuple(rows)


@dataclass(frozen=True)
class AspectContributionRow:
    key: str
    label: str
    weight: float
    normalized_weight: float
    laf_score: float
    contribution: float
    has_evidence: bool = True  # False: el producto no tiene hechos de este aspecto (E2)


@dataclass(frozen=True)
class ScoreBreakdown:
    """Desglose del puntaje publicado y de las etiquetas LAF de trazabilidad."""

    confidence: float
    preference: float
    final_score: float
    binding: str  # "confianza" | "preferencia" | "empate" | "multicriterio"
    decision_model: str
    contributions: tuple[AspectContributionRow, ...]
    favor: int
    against: int

    @property
    def weighted_total(self) -> float:
        """Numerador de la suma ponderada: Σ (peso × resultado LAF del aspecto).

        Sólo para mostrar la cuenta en pantalla; el puntaje publicado lo calcula
        ``post_laf_decision`` y no se recalcula acá.
        """
        return sum(row.weight * row.laf_score for row in self.contributions)

    @property
    def weights_total(self) -> float:
        """Denominador de la suma ponderada: Σ de los pesos que participan.

        Sólo para mostrar la cuenta real en pantalla; el puntaje ya viene
        calculado por ``post_laf_decision`` y no se recalcula acá.
        """
        return sum(row.weight for row in self.contributions)

    @property
    def conf_pct(self) -> int:
        return round(self.confidence * 100)

    @property
    def pref_pct(self) -> int:
        return round(self.preference * 100)

    @property
    def against_pct(self) -> int:
        total = self.favor + self.against
        return round(self.against / total * 100) if total else 0

    @property
    def is_multicriteria(self) -> bool:
        return self.binding == "multicriterio"


def build_score_breakdown(
    product: Any,
    graph: dict[str, Any] | None,
    aspect_labels: dict[str, str] | None = None,
) -> ScoreBreakdown | None:
    """Explica el puntaje y cuenta señales a favor/en contra.

    Lee valores ya calculados por LAF; no recalcula nada.
    """
    if product is None:
        return None
    confidence = _num(getattr(product, "confidence", 0.0))
    preference = _num(getattr(product, "preference", 0.0))
    final_score = _num(getattr(product, "final_score", min(confidence, preference)))
    metadata = getattr(product, "metadata", {}) or {}
    decision_model = _clean(metadata.get("decision_model"))
    is_multicriteria = decision_model.startswith("post_laf_multicriteria")
    labels = aspect_labels or {}
    evidenced_aspects = {
        _clean(getattr(argument, "aspect", "")).casefold()
        for argument in (
            *(getattr(product, "arguments_for", ()) or ()),
            *(getattr(product, "arguments_against", ()) or ()),
        )
        if _clean(getattr(argument, "aspect", ""))
    }
    contributions = tuple(
        sorted(
            (
                AspectContributionRow(
                    key=_clean(item.get("aspect")),
                    label=labels.get(
                        _clean(item.get("aspect")),
                        _clean(item.get("aspect")).replace("_", " ").capitalize(),
                    ),
                    weight=round(_num(item.get("weight")), 2),
                    normalized_weight=round(_num(item.get("normalized_weight")), 4),
                    laf_score=round(_num(item.get("laf_score")), 3),
                    contribution=round(_num(item.get("contribution")), 4),
                    has_evidence=(
                        not evidenced_aspects
                        or _clean(item.get("aspect")).casefold() in evidenced_aspects
                    ),
                )
                for item in metadata.get("aspect_contributions", [])
                if isinstance(item, dict)
            ),
            key=lambda item: (-item.contribution, -item.weight, item.key),
        )
    )
    name = _clean(getattr(product, "entity_name", ""))
    favor = against = 0
    for node in (graph or {}).get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("node_type") not in ("aspect", "dimension", "fact"):
            continue
        meta = node.get("metadata") or {}
        if _clean(meta.get("product")) != name:
            continue
        polarity = node.get("polarity")
        if polarity == "positive":
            favor += 1
        elif polarity == "negative":
            against += 1
    return ScoreBreakdown(
        confidence=round(confidence, 3),
        preference=round(preference, 3),
        final_score=round(final_score, 3),
        binding="multicriterio" if is_multicriteria else _binding(confidence, preference),
        decision_model=decision_model,
        contributions=contributions,
        favor=favor,
        against=against,
    )


# --- Mapa de todos los productos (confianza × preferencia) --------------------

def _svg_len(value: float) -> str:
    """Longitud SVG como texto con punto decimal, inmune al locale (USE_L10N
    renderiza los float con coma en es-AR y el navegador rechaza `cx="452,3"`)."""
    return f"{value:.1f}"


@dataclass(frozen=True)
class ScoreMapPoint:
    entity_id: str
    entity_name: str
    position: int
    cx: str
    cy: str
    binding: str
    is_selected: bool


@dataclass(frozen=True)
class ScoreMap:
    """Geometría lista para dibujar el mapa confianza×preferencia en un SVG.

    Las coordenadas son strings ya formateadas con punto decimal (ver _svg_len).
    """

    width: int
    height: int
    x0: str
    y0: str
    x1: str
    y1: str
    plot_w: str
    plot_h: str
    lo: float
    band_y: str
    points: tuple[ScoreMapPoint, ...]
    x_ticks: tuple[dict[str, Any], ...]
    y_ticks: tuple[dict[str, Any], ...]


def build_score_map(
    ranking: Any,
    *,
    width: int = 660,
    height: int = 380,
) -> ScoreMap | None:
    """Ubica cada producto en el plano confianza (x) × preferencia (y)."""
    entries = list(ranking or [])
    if not entries:
        return None
    if any(getattr(entry, "binding", "") == "multicriterio" for entry in entries):
        return None
    x0, y0 = 96.0, 44.0            # esquina sup-izq del área de trazado
    x1, y1 = float(width - 40), float(height - 64)  # esquina inf-der
    values = []
    for e in entries:
        values.append(_num(getattr(e, "confidence", 0.0)))
        values.append(_num(getattr(e, "preference", 0.0)))
    raw_lo = min(values) if values else 0.0
    lo = math.floor(raw_lo / 0.05) * 0.05
    lo = min(lo, 0.6)              # el eje muestra al menos [0.6, 1.0]
    hi = 1.0
    span = hi - lo or 1.0

    def to_x(v: float) -> str:
        return _svg_len(x0 + (v - lo) / span * (x1 - x0))

    def to_y(v: float) -> str:  # preferencia alta = arriba
        return _svg_len(y0 + (hi - v) / span * (y1 - y0))

    points = []
    for e in entries:
        conf = _num(getattr(e, "confidence", 0.0))
        pref = _num(getattr(e, "preference", 0.0))
        points.append(
            ScoreMapPoint(
                entity_id=_clean(getattr(e, "entity_id", "")),
                entity_name=_clean(getattr(e, "entity_name", "")),
                position=int(getattr(e, "position", 0) or 0),
                cx=to_x(conf),
                cy=to_y(pref),
                binding=_binding(conf, pref),
                is_selected=bool(getattr(e, "is_selected", False)),
            )
        )
    ticks: list[float] = []
    tick = round(math.ceil(round(lo / 0.1, 6)) * 0.1, 1)  # primer múltiplo de 0.1 ≥ lo
    while tick <= hi + 1e-9:
        ticks.append(round(tick, 1))
        tick = round(tick + 0.1, 1)
    x_ticks = tuple({"x": to_x(t), "label": f"{t:.1f}"} for t in ticks)
    y_ticks = tuple({"y": to_y(t), "label": f"{t:.1f}"} for t in ticks)
    return ScoreMap(
        width=width,
        height=height,
        x0=_svg_len(x0),
        y0=_svg_len(y0),
        x1=_svg_len(x1),
        y1=_svg_len(y1),
        plot_w=_svg_len(x1 - x0),
        plot_h=_svg_len(y1 - y0),
        lo=round(lo, 2),
        band_y=to_y(1.0),
        points=tuple(points),
        x_ticks=x_ticks,
        y_ticks=y_ticks,
    )


# --- Libro de reclamos: aceptabilidad gradual (Def. 11, Budán et al. 2017) ----
#
# Cada reclamo positivo del producto («buen sabor», «buena intensidad»…) se
# clasifica comparando su fuerza acumulada μ (accumulated_value) con su fuerza
# tras el debate δ (weakened_value), ambas ya calculadas por el evaluador LAF:
#   μ = δ ≠ 0  → sin objeciones   (Unchallenged)
#   0 < δ < μ  → discutido        (Weakened; «muy discutido» si perdió ≥ 50%)
#   δ = 0      → no se sostiene   (Rejected)
#   δ = 1      → asegurado        (Assured)
# El corte del 50% para «muy discutido» es una decisión de presentación; el
# estado formal de la Def. 11 se conserva en `formal_status`.

_CLAIM_SEVERITY = {
    "asegurado": 0,
    "sin_objeciones": 1,
    "discutido": 2,
    "muy_discutido": 3,
    "no_se_sostiene": 4,
}

_CLAIM_LABELS = {
    "asegurado": "Sin ninguna duda",
    "sin_objeciones": "Sin objeciones",
    "discutido": "Discutido",
    "muy_discutido": "Muy discutido",
    "no_se_sostiene": "No se sostiene",
}

_FORMAL_STATUS = {
    "asegurado": "Assured",
    "sin_objeciones": "Unchallenged",
    "discutido": "Weakened",
    "muy_discutido": "Weakened",
    "no_se_sostiene": "Rejected",
}


@dataclass(frozen=True)
class ClaimRow:
    """Un reclamo del producto con su estado de aceptabilidad gradual."""

    key: str
    label: str
    status: str  # slug de _CLAIM_LABELS
    status_label: str
    formal_status: str  # estado de la Def. 11 (Assured/Unchallenged/Weakened/Rejected)
    mu: float  # fuerza acumulada del reclamo (accumulated_value)
    delta: float  # fuerza tras el debate (weakened_value)
    favor: int  # menciones a favor del aspecto
    against: int  # objeciones (menciones en contra)
    refuted: int  # objeciones que quedaron sin fuerza (δ = 0)
    standing: int  # objeciones que sobrevivieron al debate (δ > 0)
    preference: float
    priority_label: str
    priority_key: str
    narrative: str  # oración determinista que resume el debate del aspecto
    # Estado de cara al usuario, derivado de las MENCIONES (mismo criterio E3 que
    # la tarjeta del ranking), no de μ/δ. Evita que una crítica de una sola
    # mención muestre "No se sostiene" (chequeo humano 2026-09-03, E3/E5/R3).
    plain_status: str = "bien_valorado"  # "bien_valorado" | "con_criticas"
    plain_label: str = "Bien valorado"
    plain_narrative: str = ""
    mentions_favor: int = 0
    mentions_against: int = 0
    node_id: str = ""  # id del nodo-aspecto positivo, para enraizar su subgrafo real
    # Confianza de los hechos que entran al aspecto, tal como los devuelve el
    # motor: el elogio agregado y la crítica agregada. Sirven para mostrar el
    # conflicto con sus valores reales; no se recalcula nada.
    fact_favor: float = 0.0
    fact_against: float = 0.0


def _claim_status(mu: float, delta: float) -> str:
    if delta >= 1.0 - 1e-9:
        return "asegurado"
    if delta <= 1e-9:
        return "no_se_sostiene"
    if abs(mu - delta) <= 1e-9:
        return "sin_objeciones"
    return "muy_discutido" if (mu - delta) / mu >= 0.5 else "discutido"


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _claim_narrative(status: str, favor: int, against: int, refuted: int, standing: int) -> str:
    if status in ("asegurado", "sin_objeciones"):
        if favor:
            return f"{favor} {_plural(favor, 'mención lo respalda', 'menciones lo respaldan')} y ninguna lo discute."
        return "Ninguna reseña lo discute."
    parts: list[str] = []
    if against:
        parts.append(f"{against} {_plural(against, 'crítica', 'críticas')}")
        if refuted:
            parts.append(
                f"{refuted} {_plural(refuted, 'fue respondida por el resto de las reseñas', 'fueron respondidas por el resto de las reseñas')}"
            )
        if standing:
            parts.append(f"{standing} {_plural(standing, 'quedó en pie', 'quedaron en pie')}")
    detail = "; ".join(parts) + "." if parts else ""
    if status == "no_se_sostiene":
        return (detail + " Las críticas ganaron el debate: este punto no se sostiene.").strip()
    if status == "muy_discutido":
        return (detail + " Las críticas pesaron más que la defensa.").strip()
    if against and not standing:
        return (detail + " Aun respondida, la crítica debilitó en parte el respaldo de este punto.").strip()
    return (detail + " El punto quedó parcialmente en duda.").strip()


def _plain_state(
    aspect: str,
    favor_nodes: int,
    against_nodes: int,
    criticism_info: dict[str, dict[str, Any]] | None,
) -> tuple[str, str, str, int, int]:
    """Estado del aspecto para el usuario, basado en MENCIONES (criterio E3).

    Devuelve (plain_status, plain_label, plain_narrative, menciones_favor,
    menciones_contra). Con ``criticism_info`` (provisto por la capa de
    presentación desde los argumentos) usa las menciones reales y el umbral E3
    ya aprobado; sin él, cae a los conteos de nodos del grafo (uso en tests).
    """
    info = (criticism_info or {}).get(aspect) or (criticism_info or {}).get(aspect.casefold())
    if info is not None:
        relevant = bool(info.get("relevant"))
        fav = int(info.get("favor", 0) or 0)
        against = int(info.get("against", 0) or 0)
    else:
        fav = int(favor_nodes or 0)
        against = int(against_nodes or 0)
        relevant = against >= 1
    if relevant:
        crit_word = "crítica" if against == 1 else "críticas"
        val_word = "mención lo respalda" if fav == 1 else "menciones lo respaldan"
        narrative = (
            f"{fav} {val_word} y {against} {crit_word} lo señalan."
            if fav
            else f"{against} {crit_word} sobre este punto."
        )
        return "con_criticas", "Con algunas críticas", narrative, fav, against
    return "bien_valorado", "Bien valorado", "", fav, against


def build_score_groups(breakdown) -> tuple[dict[str, Any], ...]:
    """Agrupa la suma ponderada por nivel de importancia, para mostrarla.

    Devuelve, por cada peso distinto, los resultados LAF que lo comparten y su
    subtotal (peso × suma). Es la misma cuenta que ya hizo
    ``post_laf_decision``, reordenada para leerla; no recalcula el puntaje.
    """
    if not breakdown or not getattr(breakdown, "contributions", ()):  # pragma: no cover
        return ()
    grouped: dict[float, list[Any]] = {}
    for row in breakdown.contributions:
        grouped.setdefault(round(float(row.weight), 2), []).append(row)
    salida = []
    for weight in sorted(grouped, reverse=True):
        rows = grouped[weight]
        total = sum(float(row.laf_score) for row in rows)
        salida.append(
            {
                "weight": weight,
                "level": _level_label(weight),
                "rows": tuple(rows),
                "scores": tuple(round(float(row.laf_score), 3) for row in rows),
                "total": round(total, 3),
                "subtotal": round(weight * total, 3),
            }
        )
    aportes = sum(row["subtotal"] for row in salida)
    for row in salida:
        row["share"] = round(row["subtotal"] / aportes * 100) if aportes else 0
    return tuple(salida)


def build_score_equation(breakdown) -> str:
    """La formula instanciada con los valores que dieron el puntaje mostrado.

    Escribe la misma cuenta que el panel, agrupada por nivel de importancia:
    por cada nivel, ``peso x (suma de resultados LAF de ese nivel)``. Se agrupa
    en lugar de expandir un termino por aspecto porque un producto puede tener
    los 14 aspectos activos y la linea quedaria ilegible; ademas los sumandos
    por nivel son los que el panel ya rotula ("suma 5,080 x 0,67").

    No recalcula nada: el numerador, el divisor y el puntaje salen de
    ``breakdown``, que a su vez los toma del ranking que publico
    ``post_laf_decision``.
    """
    groups = build_score_groups(breakdown)
    if not groups:
        return ""

    def _n(value: float, decimals: int = 2) -> str:
        return f"{float(value):.{decimals}f}".replace(".", ",")

    terminos = " + ".join(
        f"{_n(group['weight'])} × {_n(group['total'], 3)}" for group in groups
    )
    pesos = " + ".join(
        _n(group["weight"])
        if len(group["rows"]) == 1
        else f"{len(group['rows'])} × {_n(group['weight'])}"
        for group in groups
    )
    return (
        f"Puntaje = [{terminos}] ÷ [{pesos}] = "
        f"{_n(breakdown.weighted_total)} ÷ {_n(breakdown.weights_total)} = "
        f"{_n(breakdown.final_score)}"
    )


def build_score_story(
    position: int,
    total: int,
    rows: "list[dict[str, Any]]",
) -> str:
    """Cierra la explicación con los tres valores que decidieron el puesto.

    Plantilla fija completada con lo que ya está en la tabla: el aspecto que más
    aportó, el que menos, y qué hicieron los pesos. No calcula nada nuevo ni
    genera texto con un modelo.
    """
    scored = [row for row in rows if row.get("laf_score") is not None]
    if not scored or not position:
        return ""
    best = max(scored, key=lambda row: row["laf_score"])
    worst = min(scored, key=lambda row: row["laf_score"])
    def _n(value: float) -> str:
        return f"{value:.2f}".replace(".", ",")
    partes = [f"Quedó {position}º de {total}."]
    if best is worst:
        partes.append(
            f"La única característica que elegiste es {best['label'].lower()}, "
            f"con {_n(best['laf_score'])}."
        )
    else:
        mentions = int(worst.get("mentions") or 0)
        detalle = (
            f", con {mentions} mención" if mentions == 1
            else f", con {mentions} menciones" if mentions else ""
        )
        # Sin adjetivos sobre el producto: el número dice cuánto lo respaldan las
        # reseñas, no si el punto es bueno o malo.
        partes.append(
            f"El punto con más respaldo en las reseñas es {best['label'].lower()} "
            f"({_n(best['laf_score'])}); el de menos, {worst['label'].lower()} "
            f"({_n(worst['laf_score'])}){detalle}."
        )
    pesos = {round(float(row.get("weight") or 0.0), 2) for row in scored}
    if len(scored) == 1:
        # U09: con una sola característica elegida, "les diste el mismo peso a
        # todas" contradice la oración anterior, que dice que es la única.
        partes.append("El orden lo decidió ese único resultado.")
    elif len(pesos) == 1:
        # Con pesos distintos no se nombra a ninguno: señalar "el de mayor peso"
        # sugiere que ese decidió el orden, y el orden lo decide la suma entera.
        partes.append(
            "Les diste el mismo peso a todas, así que el orden lo decidieron esos resultados."
        )
    return " ".join(partes)


def build_claim_ledger(
    graph: dict[str, Any] | None,
    selected_name: str,
    aspect_labels: dict[str, str] | None = None,
    preference_overrides: dict[str, float] | None = None,
    criticism_info: dict[str, dict[str, Any]] | None = None,
) -> tuple[ClaimRow, ...]:
    """Clasifica cada reclamo del producto según la aceptabilidad gradual (Def. 11).

    Sólo lee μ (accumulated_value) y δ (weakened_value) ya calculados por el
    evaluador; no recalcula LAF. Ordena por prioridad del usuario y, dentro de
    la misma prioridad, por gravedad del estado.
    """
    nodes = (graph or {}).get("nodes") or []
    selected_name = _clean(selected_name)
    labels = aspect_labels or {}
    overrides = preference_overrides or {}

    best: dict[str, dict[str, Any]] = {}  # aspecto → nodo positivo con mayor μ
    preferences: dict[str, float] = {}
    favor: dict[str, int] = defaultdict(int)
    against: dict[str, int] = defaultdict(int)
    refuted: dict[str, int] = defaultdict(int)
    standing: dict[str, int] = defaultdict(int)
    fact_favor: dict[str, float] = defaultdict(float)
    fact_against: dict[str, float] = defaultdict(float)

    for node in nodes:
        if not isinstance(node, dict):
            continue
        meta = node.get("metadata") or {}
        if _clean(meta.get("product")) != selected_name:
            continue
        aspect = _clean(meta.get("aspect"))
        if not aspect or (labels and aspect not in labels):
            continue
        node_type = node.get("node_type")
        polarity = node.get("polarity")
        if node_type == "fact":
            literal = _clean(node.get("literal") or node.get("label"))
            value = _num(node.get("accumulated_value"))
            # El lado lo dice el literal: resenaNegativaX es un hecho afirmado
            # sobre una crítica, no un literal negado.
            if literal.startswith("resenaNegativa"):
                fact_against[aspect] = max(fact_against[aspect], value)
            elif literal.startswith("resenaPositiva"):
                fact_favor[aspect] = max(fact_favor[aspect], value)
        if node_type in ("aspect", "fact"):
            if polarity == "positive":
                favor[aspect] += 1
            elif polarity == "negative":
                against[aspect] += 1
                weakened = node.get("weakened_value")
                delta = _num(weakened if weakened is not None else node.get("accumulated_value"))
                if delta <= 1e-9:
                    refuted[aspect] += 1
                else:
                    standing[aspect] += 1
        if node_type == "aspect" and polarity == "positive":
            mu = _num(node.get("accumulated_value"))
            if mu > _num((best.get(aspect) or {}).get("accumulated_value")):
                best[aspect] = node
            pref = _num(node.get("preference"))
            if pref > preferences.get(aspect, -1.0):
                preferences[aspect] = pref

    rows: list[ClaimRow] = []
    for aspect, node in best.items():
        mu = _num(node.get("accumulated_value"))
        weakened = node.get("weakened_value")
        delta = _num(weakened if weakened is not None else mu)
        status = _claim_status(mu, delta)
        preference = _num(overrides.get(aspect, preferences.get(aspect, 0.0)))
        plain_status, plain_label, plain_narrative, m_favor, m_against = _plain_state(
            aspect,
            favor.get(aspect, 0),
            against.get(aspect, 0),
            criticism_info,
        )
        rows.append(
            ClaimRow(
                key=aspect,
                label=labels.get(aspect, aspect.replace("_", " ").capitalize()),
                status=status,
                status_label=_CLAIM_LABELS[status],
                formal_status=_FORMAL_STATUS[status],
                mu=round(mu, 3),
                delta=round(delta, 3),
                favor=favor.get(aspect, 0),
                against=against.get(aspect, 0),
                refuted=refuted.get(aspect, 0),
                standing=standing.get(aspect, 0),
                preference=round(preference, 2),
                priority_label=_level_label(preference),
                priority_key=_level_key(preference),
                narrative=_claim_narrative(
                    status,
                    favor.get(aspect, 0),
                    against.get(aspect, 0),
                    refuted.get(aspect, 0),
                    standing.get(aspect, 0),
                ),
                plain_status=plain_status,
                plain_label=plain_label,
                plain_narrative=plain_narrative,
                mentions_favor=m_favor,
                mentions_against=m_against,
                node_id=_clean(node.get("id")),
                fact_favor=round(fact_favor.get(aspect, 0.0), 2),
                fact_against=round(fact_against.get(aspect, 0.0), 2),
            )
        )
    rows.sort(key=lambda r: (-r.preference, _CLAIM_SEVERITY[r.status], r.key))
    return tuple(rows)


_WEAK_STATES = ("muy_discutido", "no_se_sostiene")
_DISCUSSED_STATES = ("discutido",) + _WEAK_STATES


def join_es(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " y " + items[-1]


@dataclass(frozen=True)
class Verdict:
    headline: str
    detail: str


def build_verdict(product: Any, claims: tuple[ClaimRow, ...]) -> Verdict | None:
    """Veredicto en dos oraciones, generado por plantillas sobre valores ya calculados."""
    if product is None:
        return None
    confidence = _num(getattr(product, "confidence", 0.0))
    preference = _num(getattr(product, "preference", 0.0))
    metadata = getattr(product, "metadata", {}) or {}
    if _clean(metadata.get("decision_model")).startswith("post_laf_multicriteria"):
        # Frase-historia para el usuario común: lugar en la lista + qué lo
        # respalda + qué le juega en contra. Sin fórmulas ni "post-LAF".
        labels = {claim.key: claim.label.lower() for claim in claims}
        # Críticas relevantes = las que la capa de menciones marcó "con_criticas"
        # (mismo umbral E3 que la tarjeta; nunca una crítica de una sola mención).
        crit_keys = {
            c.key for c in claims if getattr(c, "plain_status", "") == "con_criticas"
        }
        crit = [
            c.label.lower()
            for c in claims
            if getattr(c, "plain_status", "") == "con_criticas"
        ]
        # Un aspecto con críticas relevantes no se repite en la lista de elogios:
        # queda nombrado en la parte de críticas para no leerse contradictorio.
        leading = sorted(
            (
                item
                for item in metadata.get("aspect_contributions", [])
                if isinstance(item, dict)
                and _num(item.get("weight")) > 0
                and _num(item.get("contribution")) > 0
                and _clean(item.get("aspect")) not in crit_keys
            ),
            key=lambda item: -_num(item.get("contribution")),
        )[:3]
        names = [
            labels.get(
                _clean(item.get("aspect")),
                _clean(item.get("aspect")).replace("_", " "),
            )
            for item in leading
        ]
        position = int(getattr(product, "position", 0) or 0)
        if position == 1:
            headline = "Quedó en el primer puesto."
        elif position:
            headline = f"Quedó en el puesto {position}."
        else:
            headline = "Así se explica su lugar en la lista."
        parts: list[str] = []
        if names:
            parts.append(f"Muchas menciones valoran su {join_es(names)}.")
        else:
            parts.append("Las reseñas no dejaron señales claras a favor en lo que priorizaste.")
        if crit:
            parts.append(f"Recibió algunas críticas sobre {join_es(crit)}.")
        elif position and position > 1:
            parts.append("Quedó por debajo de opciones que reunieron más menciones a favor.")
        return Verdict(headline=headline, detail=" ".join(parts))
    high = [c for c in claims if c.preference >= 0.8]
    high_weak = [c for c in high if c.status in _DISCUSSED_STATES]
    low_weak = [c for c in claims if c.preference < 0.8 and c.status in _WEAK_STATES]
    low_discussed = [c for c in claims if c.preference < 0.8 and c.status in _DISCUSSED_STATES]

    if preference < confidence - 1e-6:
        headline = "Las reseñas lo respaldan, pero no cumple del todo lo que priorizaste."
        if high_weak:
            detail = (
                f"El punto flojo está en {join_es([c.label.lower() for c in high_weak])}, "
                "que marcaste como importante. Eso le pone un techo al puntaje."
            )
        else:
            detail = "Su límite no son las reseñas sino el ajuste con tus prioridades."
        return Verdict(headline=headline, detail=detail)

    if high and not high_weak:
        headline = "Lo que más te importa no recibió ninguna objeción."
        if low_discussed:
            detail = (
                f"Hubo críticas sobre {join_es([c.label.lower() for c in low_discussed])}, "
                "pero son puntos a los que les diste poca o ninguna prioridad."
            )
        else:
            detail = "Tampoco quedaron críticas en pie en el resto de los aspectos."
        return Verdict(headline=headline, detail=detail)

    if high_weak:
        headline = "La mayor parte de lo que priorizaste está respaldado por las reseñas."
        detail = (
            f"Quedó en discusión {join_es([c.label.lower() for c in high_weak])}: "
            "abrí ese punto para ver qué dijeron las críticas."
        )
        return Verdict(headline=headline, detail=detail)

    headline = "Es una de las opciones con menos objeciones sin responder."
    if low_weak:
        detail = f"Las críticas que quedaron en pie hablan de {join_es([c.label.lower() for c in low_weak])}."
    else:
        detail = "Ninguna crítica quedó sin responder en el debate de reseñas."
    return Verdict(headline=headline, detail=detail)


def build_position_note(
    ranking_rows: tuple[RankingRow, ...],
    claims: tuple[ClaimRow, ...],
) -> str:
    """Una oración determinista que responde «¿por qué no está más arriba?»."""
    selected = next((r for r in ranking_rows if r.is_selected), None)
    if selected is None:
        return ""
    if selected.position == 1:
        if selected.binding == "multicriterio":
            return (
                "Quedó primero: es el café que más respaldan las reseñas en el "
                "conjunto de lo que marcaste como importante."
            )
        return (
            "Quedó primero: es la opción con menos objeciones sin responder "
            "entre las que mejor cumplen tus preferencias."
        )
    if selected.binding == "multicriterio":
        return (
            f"Está {selected.position}º porque, sumando todo lo que te importa, las "
            "reseñas lo respaldan un poco menos que a los cafés de arriba."
        )
    weak = [c for c in claims if c.standing > 0 or c.status in _WEAK_STATES]
    if selected.binding == "preferencia":
        note = (
            f"Está {selected.position}º aunque sus reseñas lo respaldan: "
            "el límite es que no cumple del todo lo que priorizaste."
        )
        high_weak = [c for c in weak if c.preference >= 0.8]
        if high_weak:
            note += f" El desajuste está en {join_es([c.label.lower() for c in high_weak])}."
        return note
    if weak:
        return (
            f"Está {selected.position}º porque las críticas sobre "
            f"{join_es([c.label.lower() for c in weak])} quedaron en pie "
            "y le restan confianza frente a los de arriba."
        )
    discussed = [c for c in claims if c.status in _DISCUSSED_STATES]
    if discussed:
        return (
            f"Está {selected.position}º: las críticas sobre "
            f"{join_es([c.label.lower() for c in discussed])} fueron respondidas, "
            "pero debilitaron su respaldo frente a los de arriba."
        )
    return (
        f"Está {selected.position}º por diferencias mínimas de confianza "
        "con los de arriba; ninguna crítica quedó sin responder."
    )


# Se reexporta para mantener estable la API pública histórica de este módulo.
__all__ = [
    "CollapsedAspect",
    "CollapsedDimension",
    "CollapsedGraph",
    "build_aspect_standings",
    "build_claim_ledger",
    "build_collapsed_graph",
    "build_position_note",
    "build_ranking",
    "build_score_breakdown",
    "build_score_groups",
    "build_score_map",
    "build_score_story",
    "build_verdict",
]

