"""Contrato tolerante a nulos para fragmentos argumentativos."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def safe_text(*values: Any, fallback: str = "Sin etiqueta") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return fallback


def safe_score(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class GraphNode:
    id: str
    label: str
    node_type: str
    literal: str
    polarity: str
    confidence: float
    preference: float
    accumulated_value: float
    weakened_value: float
    acceptability_status: str
    evidence_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphNode":
        node_id = safe_text(data.get("id"), fallback="nodo-sin-id")
        literal = safe_text(data.get("literal"), node_id)
        return cls(
            id=node_id,
            label=safe_text(data.get("label"), literal, node_id),
            node_type=safe_text(data.get("node_type"), fallback="unknown"),
            literal=literal,
            polarity=safe_text(data.get("polarity"), fallback="neutral"),
            confidence=safe_score(data.get("confidence")),
            preference=safe_score(data.get("preference")),
            accumulated_value=safe_score(data.get("accumulated_value")),
            weakened_value=safe_score(data.get("weakened_value")),
            acceptability_status=safe_text(
                data.get("acceptability_status"), fallback="undetermined"
            ),
            evidence_count=max(int(data.get("evidence_count") or 0), 0),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class GraphEdge:
    id: str
    source: str
    target: str
    edge_type: str
    label: str
    rule_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphEdge":
        source = safe_text(data.get("source"), fallback="origen-sin-id")
        target = safe_text(data.get("target"), fallback="destino-sin-id")
        return cls(
            id=safe_text(data.get("id"), f"{source}-{target}"),
            source=source,
            target=target,
            edge_type=safe_text(data.get("edge_type"), fallback="support"),
            label=safe_text(data.get("label"), data.get("edge_type"), fallback="relación"),
            rule_id=safe_text(data.get("rule_id"), fallback="regla-sin-id"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class GraphFragment:
    graph_id: str
    root_id: str
    total_nodes: int
    total_edges: int
    visible_nodes: int
    visible_edges: int
    truncated: bool
    depth: int
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    available_filters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
