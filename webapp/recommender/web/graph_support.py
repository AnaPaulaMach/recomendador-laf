"""Construcción y filtrado de grafos usados por las vistas y exportaciones."""
from __future__ import annotations

from django.conf import settings

from recommender.domain.contracts import EvaluationResult
from recommender.graph.service import ArgumentGraphService
from recommender.repositories import FixtureRepository
from recommender.services.laf_api import LAFGraphPresentationMapper


def graph_service(
    domain_key: str,
    result: EvaluationResult | None = None,
    entity_id: str = "",
) -> ArgumentGraphService:
    """Crea el servicio de grafo desde una corrida o desde el fixture del dominio."""
    if result and result.laf_graph:
        selected = next(
            (item for item in result.ranking if item.entity_id == entity_id),
            result.ranking[0] if result.ranking else None,
        )
        root_id = str(selected.metadata.get("laf_node_id") or "") if selected else ""
        entity_names = {
            str(item.metadata.get("laf_argument") or item.entity_id): item.entity_name
            for item in result.ranking
        }
        graph = LAFGraphPresentationMapper().map(
            result.laf_graph,
            root_id=root_id,
            entity_names=entity_names,
        )
    else:
        graph = FixtureRepository(settings.FIXTURE_DIR).load(domain_key).get("graph") or {}
    return ArgumentGraphService(graph, settings.GRAPH_VISIBLE_NODE_LIMIT)


def graph_filters(request) -> dict:
    """Normaliza los filtros HTTP aceptados por el servicio de grafos."""
    return {
        "edge_types": request.GET.getlist("edge_type"),
        "node_types": request.GET.getlist("node_type"),
        "polarities": request.GET.getlist("polarity"),
        "min_confidence": request.GET.get("min_confidence", 0),
        "min_preference": request.GET.get("min_preference", 0),
        "query": request.GET.get("q", ""),
    }
