"""Recorte por vecindad del grafo de argumentos para la interfaz."""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .contracts import GraphEdge, GraphFragment, GraphNode


class ArgumentGraphService:
    """Recorta por BFS; nunca entrega el grafo completo automáticamente."""

    def __init__(self, graph_data: dict[str, Any], maximum_limit: int = 250):
        self.data = graph_data
        self.maximum_limit = min(max(int(maximum_limit), 1), 250)
        self.nodes = {
            node.id: node
            for node in (
                GraphNode.from_dict(raw)
                for raw in graph_data.get("nodes", [])
                if isinstance(raw, dict)
            )
        }
        self.edges = tuple(
            GraphEdge.from_dict(raw)
            for raw in graph_data.get("edges", [])
            if isinstance(raw, dict)
        )

    def fragment(
        self,
        root_id: str | None = None,
        depth: int = 2,
        limit: int = 250,
        filters: dict[str, Any] | None = None,
    ) -> GraphFragment:
        filters = filters or {}
        root_id = root_id if root_id in self.nodes else str(self.data.get("root_id") or "")
        depth = min(max(int(depth), 0), 6)
        limit = min(max(int(limit), 1), self.maximum_limit)

        edges = tuple(edge for edge in self.edges if self._edge_matches(edge, filters))
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            adjacency[edge.target].append(edge.source)
            adjacency[edge.source].append(edge.target)

        selected: list[str] = []
        queued = {root_id}
        queue = deque([(root_id, 0)])
        while queue and len(selected) < limit:
            node_id, distance = queue.popleft()
            node = self.nodes.get(node_id)
            if node is None:
                continue
            if self._node_matches(node, filters) or node_id == root_id:
                selected.append(node_id)
            if distance >= depth:
                continue
            for neighbour in adjacency.get(node_id, []):
                if neighbour not in queued:
                    queued.add(neighbour)
                    queue.append((neighbour, distance + 1))

        node_set = set(selected)
        visible_edges = tuple(
            edge for edge in edges if edge.source in node_set and edge.target in node_set
        )
        total_nodes = max(int(self.data.get("total_nodes") or len(self.nodes)), len(self.nodes))
        total_edges = max(int(self.data.get("total_edges") or len(self.edges)), len(self.edges))
        return GraphFragment(
            graph_id=str(self.data.get("graph_id") or "grafo-sin-id"),
            root_id=root_id,
            total_nodes=total_nodes,
            total_edges=total_edges,
            visible_nodes=len(selected),
            visible_edges=len(visible_edges),
            truncated=len(selected) < total_nodes,
            depth=depth,
            nodes=tuple(self.nodes[node_id] for node_id in selected),
            edges=visible_edges,
            available_filters=dict(self.data.get("available_filters") or {}),
        )

    @staticmethod
    def _edge_matches(edge: GraphEdge, filters: dict[str, Any]) -> bool:
        edge_types = set(filters.get("edge_types") or [])
        return not edge_types or edge.edge_type in edge_types

    @staticmethod
    def _node_matches(node: GraphNode, filters: dict[str, Any]) -> bool:
        node_types = set(filters.get("node_types") or [])
        polarities = set(filters.get("polarities") or [])
        query = str(filters.get("query") or "").strip().casefold()
        if node_types and node.node_type not in node_types:
            return False
        if polarities and node.polarity not in polarities:
            return False
        if node.node_type != "operator":
            if node.confidence < float(filters.get("min_confidence") or 0):
                return False
            if node.preference < float(filters.get("min_preference") or 0):
                return False
        if query:
            haystack = " ".join(
                [
                    node.label,
                    node.literal,
                    str(node.metadata.get("product") or ""),
                    str(node.metadata.get("aspect") or ""),
                ]
            ).casefold()
            if query not in haystack:
                return False
        return True
