"""Lectura coherente del estado persistido de un recorrido."""
from __future__ import annotations

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404

from recommender.domain.contracts import EvaluationResult
from recommender.models import RecommendationSession
from recommender.repositories.fixture_repository import FixtureRepository


def get_flow(flow_id) -> RecommendationSession:
    return get_object_or_404(RecommendationSession, id=flow_id)


def result(raw: dict) -> EvaluationResult:
    if not raw:
        raise Http404("Esta etapa todavía no fue evaluada.")
    return EvaluationResult.from_dict(raw)


def result_for_flow(flow: RecommendationSession, raw: dict) -> EvaluationResult:
    """Evita reutilizar resultados simulados históricos sobre un catálogo real."""
    evaluated = result(raw)
    fixture_keys = FixtureRepository(settings.FIXTURE_DIR).fixture_dataset_keys(
        flow.domain_key
    )
    if evaluated.evaluation_status != "mock" or flow.dataset_key in fixture_keys:
        return evaluated
    return EvaluationResult.from_dict(
        {
            **raw,
            "evaluation_status": "pending",
            "dataset_key": flow.dataset_key,
            "ranking": [],
        }
    )


def explanation_result(
    flow: RecommendationSession,
    entity_id: str = "",
) -> EvaluationResult:
    candidates = []
    if flow.laf2_result:
        candidates.append(result_for_flow(flow, flow.laf2_result))
    if flow.laf1_result:
        candidates.append(result_for_flow(flow, flow.laf1_result))
    if entity_id:
        for evaluated in candidates:
            if any(item.entity_id == entity_id for item in evaluated.ranking):
                return evaluated
    if candidates:
        return candidates[0]
    raise Http404("Esta etapa todavía no fue evaluada.")
