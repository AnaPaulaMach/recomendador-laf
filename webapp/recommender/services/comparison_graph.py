"""Proyección resumida de un grafo LAF para la comparación visual."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

_DIMENSION_LABELS = {
    "sensorial": "Sensorial",
    "producto": "Producto",
    "valor": "Valor",
    "elaboracion": "Elaboración",
    "conservacion": "Conservación",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class CollapsedAspect:
    key: str
    label: str
    favor: int
    against: int


@dataclass(frozen=True)
class CollapsedDimension:
    key: str
    label: str
    favor: int
    against: int
    aspects: tuple[CollapsedAspect, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CollapsedGraph:
    product_name: str
    favor: int
    against: int
    dimensions: tuple[CollapsedDimension, ...]


def build_collapsed_graph(
    graph: dict[str, Any] | None,
    selected_name: str,
    aspect_labels: dict[str, str] | None = None,
) -> CollapsedGraph | None:
    """Colapsa el grafo real a conclusión, dimensión y aspecto."""
    graph = graph or {}
    selected_name = _clean(selected_name)
    labels = aspect_labels or {}
    nodes = {
        _clean(node.get("id")): node
        for node in graph.get("nodes") or []
        if isinstance(node, dict)
    }
    if not nodes:
        return None

    def is_mine(node: dict[str, Any]) -> bool:
        return _clean((node.get("metadata") or {}).get("product")) == selected_name

    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = _clean(edge.get("source"))
        target = _clean(edge.get("target"))
        if source and target:
            incoming[target].append(source)

    aspect_favor: dict[str, int] = defaultdict(int)
    aspect_against: dict[str, int] = defaultdict(int)
    for node in nodes.values():
        if node.get("node_type") not in ("aspect", "fact") or not is_mine(node):
            continue
        key = _clean((node.get("metadata") or {}).get("aspect")).replace(" ", "_")
        if not key:
            continue
        if node.get("polarity") == "positive":
            aspect_favor[key] += 1
        elif node.get("polarity") == "negative":
            aspect_against[key] += 1

    aspect_to_dimension: dict[str, str] = {}
    for node in nodes.values():
        if node.get("node_type") != "dimension" or not is_mine(node):
            continue
        dimension_key = _clean((node.get("metadata") or {}).get("aspect")).replace(" ", "_")
        if not dimension_key:
            continue
        node_id = _clean(node.get("id"))
        seen = {node_id}
        queue = deque([node_id])
        hops = 0
        while queue and hops < 5:
            for _ in range(len(queue)):
                current = queue.popleft()
                for source in incoming.get(current, []):
                    if source in seen:
                        continue
                    seen.add(source)
                    source_node = nodes.get(source)
                    if not source_node:
                        continue
                    if source_node.get("node_type") == "aspect" and is_mine(source_node):
                        aspect_key = _clean(
                            (source_node.get("metadata") or {}).get("aspect")
                        ).replace(" ", "_")
                        if aspect_key and aspect_key not in aspect_to_dimension:
                            aspect_to_dimension[aspect_key] = dimension_key
                    else:
                        queue.append(source)
            hops += 1

    grouped: dict[str, list[CollapsedAspect]] = defaultdict(list)
    for aspect_key in sorted(set(aspect_favor) | set(aspect_against)):
        dimension_key = aspect_to_dimension.get(aspect_key)
        if not dimension_key:
            continue
        grouped[dimension_key].append(
            CollapsedAspect(
                key=aspect_key,
                label=labels.get(aspect_key, aspect_key.replace("_", " ").capitalize()),
                favor=aspect_favor.get(aspect_key, 0),
                against=aspect_against.get(aspect_key, 0),
            )
        )

    dimensions: list[CollapsedDimension] = []
    for dimension_key, aspects in grouped.items():
        aspects.sort(key=lambda aspect: (-aspect.favor, aspect.against, aspect.key))
        dimensions.append(
            CollapsedDimension(
                key=dimension_key,
                label=_DIMENSION_LABELS.get(
                    dimension_key,
                    dimension_key.replace("_", " ").capitalize(),
                ),
                favor=sum(aspect.favor for aspect in aspects),
                against=sum(aspect.against for aspect in aspects),
                aspects=tuple(aspects),
            )
        )
    if not dimensions:
        return None
    dimensions.sort(key=lambda dimension: (-(dimension.favor + dimension.against), dimension.key))
    return CollapsedGraph(
        product_name=selected_name,
        favor=sum(dimension.favor for dimension in dimensions),
        against=sum(dimension.against for dimension in dimensions),
        dimensions=tuple(dimensions),
    )
