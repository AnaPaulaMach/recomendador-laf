"""Decisión multicriterio posterior a LAF para el ranking de productos.

LAF conserva la responsabilidad de evaluar la evidencia y resolver soporte,
agregación y conflicto. Este módulo aplica después la función de preferencia
entre alternativas: combina el resultado LAF de cada aspecto con los pesos
declarados por la persona usuaria.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Iterable

from recommender.domain.contracts import RankingEntry


DECISION_MODEL = "post_laf_multicriteria_v1"


def _number(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(numeric):
        return 0.0
    return max(0.0, min(numeric, 1.0))


def zero_threshold_payload(payload: dict[str, object]) -> dict[str, object]:
    """Quita hechos con preferencia nula antes de ejecutar una vista por aspecto.

    El cero representa el elemento inferior del álgebra de preferencias. No se
    aplica ningún umbral a valores positivos: 0,33 sigue participando.
    """
    transformed = deepcopy(payload)
    transformed["facts"] = [
        fact
        for fact in transformed.get("facts", [])
        if _number((fact.get("attributes") or [0, 0])[1]) > 0
    ]
    return transformed


def normalized_multicriteria_ranking(
    aspect_scores: dict[str, dict[str, float]],
    preferences: dict[str, float],
    entity_names: dict[str, str],
) -> tuple[dict[str, object], ...]:
    """Calcula Σ(peso × resultado LAF del aspecto) / Σ(pesos activos)."""
    active = {
        aspect: _number(weight)
        for aspect, weight in preferences.items()
        if _number(weight) > 0 and aspect in aspect_scores
    }
    denominator = sum(active.values())
    if denominator <= 0:
        return ()
    entity_ids = (
        set().union(*(set(aspect_scores[aspect]) for aspect in active))
        if active
        else set()
    )
    rows = []
    for entity_id in entity_ids:
        score = sum(
            weight * _number(aspect_scores[aspect].get(entity_id, 0.0))
            for aspect, weight in active.items()
        ) / denominator
        rows.append(
            {
                "entity_id": entity_id,
                "entity_name": entity_names.get(entity_id, entity_id),
                "score": score,
            }
        )
    rows.sort(key=lambda row: (-float(row["score"]), str(row["entity_id"]).casefold()))
    return tuple(rows)


@dataclass(frozen=True)
class AspectEvaluation:
    aspect: str
    weight: float
    ranking: tuple[RankingEntry, ...]


def combine_rankings(
    baseline: Iterable[RankingEntry],
    evaluations: Iterable[AspectEvaluation],
    preferences: dict[str, float],
) -> tuple[RankingEntry, ...]:
    """Convierte evaluaciones LAF por aspecto en el contrato estable del ranking."""
    baseline = tuple(baseline)
    evaluations = tuple(evaluations)
    baseline_by_id = {entry.entity_id: entry for entry in baseline}
    aspect_scores = {
        evaluation.aspect: {
            entry.entity_id: entry.confidence for entry in evaluation.ranking  # confianza post-conflicto: final_score=min(conf,pref) colapsa a 0 en aspectos discutidos porque en la corrida por aspecto la pref es 1.0 constante en ambos lados
        }
        for evaluation in evaluations
    }
    entity_names = {entry.entity_id: entry.entity_name for entry in baseline}
    for evaluation in evaluations:
        entity_names.update(
            {entry.entity_id: entry.entity_name for entry in evaluation.ranking}
        )
    rows = normalized_multicriteria_ranking(
        aspect_scores,
        preferences,
        entity_names,
    )
    active = {
        aspect: _number(weight)
        for aspect, weight in preferences.items()
        if _number(weight) > 0 and aspect in aspect_scores
    }
    denominator = sum(active.values())
    entries = []
    for position, row in enumerate(rows, start=1):
        entity_id = str(row["entity_id"])
        source = baseline_by_id.get(entity_id)
        if source is None:
            source = next(
                (
                    entry
                    for evaluation in evaluations
                    for entry in evaluation.ranking
                    if entry.entity_id == entity_id
                ),
                None,
            )
        if source is None:
            continue
        contributions = []
        for aspect, weight in sorted(active.items()):
            laf_score = _number(aspect_scores[aspect].get(entity_id, 0.0))
            normalized_weight = weight / denominator if denominator else 0.0
            contributions.append(
                {
                    "aspect": aspect,
                    "weight": weight,
                    "normalized_weight": normalized_weight,
                    "laf_score": laf_score,
                    "contribution": normalized_weight * laf_score,
                }
            )
        final_score = _number(row["score"])
        metadata = dict(source.metadata)
        metadata.update(
            {
                "decision_model": DECISION_MODEL,
                "score_projection": (
                    "sum(normalized_user_weight * per_aspect_laf_confidence)"
                ),
                "source_laf_confidence": source.confidence,
                "source_laf_preference": source.preference,
                "active_aspects": sorted(active),
                "disabled_aspects": sorted(
                    aspect
                    for aspect, weight in preferences.items()
                    if _number(weight) == 0
                ),
                "aspect_contributions": contributions,
            }
        )
        entries.append(
            RankingEntry(
                entity_id=source.entity_id,
                entity_name=source.entity_name,
                position=position,
                final_score=final_score,
                # Estas dos etiquetas siguen siendo la salida de la corrida LAF
                # completa y se conservan para la traza técnica. No forman una
                # operación min para el orden multicriterio.
                confidence=source.confidence,
                preference=source.preference,
                status="recommended" if final_score > 0 else "not_recommended",
                evidence_count=source.evidence_count,
                arguments_for=source.arguments_for,
                arguments_against=source.arguments_against,
                metadata=metadata,
            )
        )
    return tuple(entries)
