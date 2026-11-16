"""Contrato y adaptadores para ejecutar programas en la API HTTP de LAF."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from recommender.domain.contracts import ArgumentEvidence, RankingEntry


class LAFProgramParseError(ValueError):
    """El programa textual no cumple el subconjunto aceptado por la API."""


class LAFApiError(RuntimeError):
    """La API no respondió o devolvió una respuesta inválida."""


# Perfil de dos etiquetas documentado por los generadores 08 y 10.
# El max interior evita una división por cero en el empate X=Y=1 sin alterar
# los demás puntos del dominio [0, 1].
BUDAN_2017_OPERATIONS = (
    {
        "labelName": "confidence",
        "supportFunction": "X * Y",
        "aggregationFunction": "X + Y - X * Y",
        "conflictFunction": "max((X-Y)/max(1-Y,0.000000001),0)",
    },
    {
        "labelName": "preference",
        "supportFunction": "min(X,Y)",
        "aggregationFunction": "min(X+Y,1)",
        "conflictFunction": "max(X-Y,0)",
    },
)


@dataclass(frozen=True)
class ParsedLAFProgram:
    facts: tuple[dict[str, Any], ...]
    rules: tuple[dict[str, Any], ...]
    attribute_count: int

    def to_request_payload(self) -> dict[str, Any]:
        # La API de Javi acepta programas de una etiqueta (solo confianza) o de
        # dos (confianza + preferencia). Se mandan tantas operaciones como
        # atributos tenga el programa; el default sigue siendo dos.
        if self.attribute_count not in (1, len(BUDAN_2017_OPERATIONS)):
            raise LAFProgramParseError(
                "El perfil budan_2017 acepta una o dos etiquetas por atributo."
            )
        operations = [dict(row) for row in BUDAN_2017_OPERATIONS[: self.attribute_count]]
        return {
            "facts": list(self.facts),
            "rules": list(self.rules),
            "explainabilityEnabled": False,
            "operations": {"labels": operations},
        }


class LAFProgramParser:
    """Versión Python del contrato de entrada usado por la UI de LAF."""

    _fact_pattern = re.compile(
        r"^\s*([~]?[A-Za-z][A-Za-z0-9_]*)\s*\(\s*([^)]+?)\s*\)"
        r"\s*\.\s*\{\s*([^}]*)\s*\}\s*$"
    )
    _rule_pattern = re.compile(
        r"^\s*([~]?[A-Za-z][A-Za-z0-9_]*)\s*\(\s*X\s*\)\s*:-\s*(.+)"
        r"\.\s*\{\s*([^}]*)\s*\}\s*$"
    )
    _literal_pattern = re.compile(
        r"^\s*([~]?[A-Za-z][A-Za-z0-9_]*)\s*\(\s*X\s*\)\s*$"
    )
    _interval_pattern = re.compile(
        r"^\[\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*,\s*"
        r"([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*\]$"
    )

    def parse(self, text: str) -> ParsedLAFProgram:
        facts: list[dict[str, Any]] = []
        rules: list[dict[str, Any]] = []
        arities: list[int] = []
        errors: list[str] = []

        for line_number, raw_line in enumerate(str(text or "").splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith(("#", "//", "%")):
                continue

            fact_match = self._fact_pattern.match(line)
            if fact_match:
                attributes, intervals = self._parse_attributes(
                    fact_match.group(3), line_number
                )
                arities.append(len(attributes))
                argument = fact_match.group(2).strip()
                name = fact_match.group(1)
                facts.append(
                    {
                        "name": name,
                        "argument": argument,
                        "attributes": attributes,
                        "attributeIntervals": intervals,
                        "sourceKey": f"FACT|{name}|{argument}",
                    }
                )
                continue

            rule_match = self._rule_pattern.match(line)
            if rule_match:
                body_literals = []
                for piece in rule_match.group(2).split(","):
                    literal_match = self._literal_pattern.match(piece.strip())
                    if literal_match is None:
                        errors.append(
                            f"Línea {line_number}: literal inválido {piece.strip()!r}."
                        )
                    else:
                        body_literals.append(literal_match.group(1))
                attributes, intervals = self._parse_attributes(
                    rule_match.group(3), line_number
                )
                arities.append(len(attributes))
                if body_literals:
                    rules.append(
                        {
                            "headName": rule_match.group(1),
                            "bodyLiterals": body_literals,
                            "attributes": attributes,
                            "attributeIntervals": intervals,
                            "sourceKey": f"RULE|line:{line_number}",
                        }
                    )
                continue

            errors.append(
                f"Línea {line_number}: no coincide con el formato de hecho o regla."
            )

        if not facts:
            errors.append("El programa debe contener al menos un hecho.")
        if not rules:
            errors.append("El programa debe contener al menos una regla.")
        if arities and any(arity != arities[0] for arity in arities):
            errors.append("Todos los hechos y reglas deben tener la misma cantidad de atributos.")
        if errors:
            raise LAFProgramParseError(" ".join(errors))

        return ParsedLAFProgram(
            facts=tuple(facts),
            rules=tuple(rules),
            attribute_count=arities[0],
        )

    def _parse_attributes(
        self,
        raw_attributes: str,
        line_number: int,
    ) -> tuple[list[str], list[list[float] | None]]:
        parts = self._split_attributes(raw_attributes)
        if not parts:
            raise LAFProgramParseError(
                f"Línea {line_number}: el bloque de atributos está vacío."
            )
        attributes: list[str] = []
        intervals: list[list[float] | None] = []
        for part in parts:
            interval_match = self._interval_pattern.match(part)
            if interval_match:
                first = float(interval_match.group(1))
                second = float(interval_match.group(2))
                lower, upper = sorted((first, second))
                attributes.append(self._format_number(lower))
                intervals.append([lower, upper])
            else:
                attributes.append(part)
                intervals.append(None)
        return attributes, intervals

    @staticmethod
    def _split_attributes(raw_attributes: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        bracket_depth = 0
        for character in raw_attributes:
            if character == "[":
                bracket_depth += 1
            elif character == "]":
                bracket_depth -= 1
                if bracket_depth < 0:
                    raise LAFProgramParseError("Intervalo mal cerrado.")
            elif character == ";" and bracket_depth == 0:
                value = "".join(current).strip()
                if not value:
                    raise LAFProgramParseError("Separador de atributos inválido.")
                parts.append(value)
                current = []
                continue
            elif character == "," and bracket_depth == 0:
                raise LAFProgramParseError(
                    "Use punto y coma entre atributos; la coma se reserva para intervalos."
                )
            current.append(character)
        if bracket_depth != 0:
            raise LAFProgramParseError("Intervalo mal cerrado.")
        tail = "".join(current).strip()
        if tail:
            parts.append(tail)
        return parts

    @staticmethod
    def _format_number(value: float) -> str:
        return str(int(value)) if value.is_integer() else str(value)


class LAFApiClient:
    """Cliente servidor-a-servidor para ``POST /api/graph``."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 30.0,
        opener: Callable[..., Any] | None = None,
    ):
        self.endpoint = str(endpoint or "").strip()
        self.timeout_seconds = max(float(timeout_seconds), 0.1)
        self._opener = opener or urlopen

    def build_graph(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.endpoint:
            raise LAFApiError("LAF_API_URL no está configurada.")
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                raw_response = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LAFApiError(
                f"La API LAF respondió HTTP {exc.code}: {detail or exc.reason}."
            ) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise LAFApiError(f"No se pudo conectar con la API LAF: {exc}.") from exc

        try:
            data = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise LAFApiError("La API LAF no devolvió JSON válido.") from exc
        if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
            raise LAFApiError("La respuesta de la API LAF no contiene una lista de nodos.")
        if not isinstance(data.get("edges"), list):
            raise LAFApiError("La respuesta de la API LAF no contiene una lista de aristas.")
        return data


class LAFGraphRankingMapper:
    """Proyecta conclusiones ``recomendar`` al contrato estable de Django."""

    _literal_pattern = re.compile(
        r"^(~?)([A-Za-z][A-Za-z0-9_]*)\(([^)]+)\)$"
    )

    def map(
        self,
        graph: dict[str, Any],
        entities: Iterable[dict[str, object]],
        *,
        conclusion_predicate: str = "recomendar",
    ) -> tuple[RankingEntry, ...]:
        entity_by_argument = {
            str(entity.get("argument") or ""): entity
            for entity in entities
            if str(entity.get("argument") or "")
        }
        nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
        evidence_by_argument: dict[str, list[tuple[dict[str, Any], bool]]] = {}
        conclusions: dict[str, tuple[dict[str, Any], float, float, float]] = {}

        for node in nodes:
            if str(node.get("type") or "").upper() != "FACT":
                continue
            parsed = self._parse_literal(node.get("label"))
            if parsed is None:
                continue
            negated, predicate, argument = parsed
            if predicate == conclusion_predicate:
                if negated:
                    continue
                confidence, preference = self._label_values(node)
                final_score = min(confidence, preference)
                previous = conclusions.get(argument)
                if previous is None or final_score > previous[3]:
                    conclusions[argument] = (
                        node,
                        confidence,
                        preference,
                        final_score,
                    )
                continue
            if str(node.get("sourceKey") or "").startswith("FACT|"):
                is_negative_evidence = negated or predicate.startswith("resenaNegativa")
                evidence_by_argument.setdefault(argument, []).append(
                    (node, is_negative_evidence)
                )

        entries = []
        for argument, (node, confidence, preference, final_score) in conclusions.items():
            entity = entity_by_argument.get(argument)
            if entity_by_argument and entity is None:
                continue
            entity = entity or {
                "entity_id": argument,
                "entity_name": argument.replace("_", " ").strip().title(),
                "metadata": {},
            }
            positive = []
            negative = []
            entity_evidence_counts = dict(entity.get("evidence_counts") or {})
            for evidence_node, negated in evidence_by_argument.get(argument, []):
                item = self._evidence(
                    evidence_node,
                    negated,
                    entity_evidence_counts,
                )
                (negative if negated else positive).append(item)
            metadata = dict(entity.get("metadata") or {})
            label_count = len(node.get("deltaAttributes") or node.get("attributes") or [])
            metadata.update(
                {
                    "laf_argument": argument,
                    "laf_node_id": str(node.get("id") or ""),
                    "confidence": confidence,
                    "preference": preference,
                    "score_projection": "confidence" if label_count == 1 else "min(confidence, preference)",
                    "label_count": label_count,
                }
            )
            entries.append(
                RankingEntry(
                    entity_id=str(entity.get("entity_id") or argument),
                    entity_name=str(entity.get("entity_name") or argument),
                    position=0,
                    final_score=final_score,
                    confidence=confidence,
                    preference=preference,
                    status="recommended" if final_score > 0 else "not_recommended",
                    evidence_count=sum(item.evidence_count for item in positive + negative),
                    arguments_for=tuple(positive),
                    arguments_against=tuple(negative),
                    metadata=metadata,
                )
            )

        entries.sort(
            key=lambda entry: (
                -entry.final_score,
                -entry.confidence,
                -entry.preference,
                entry.entity_id.casefold(),
            )
        )
        return tuple(
            RankingEntry(
                **{
                    **entry.__dict__,
                    "position": position,
                }
            )
            for position, entry in enumerate(entries, start=1)
        )

    def _evidence(
        self,
        node: dict[str, Any],
        negated: bool,
        counts: dict[str, Any],
    ) -> ArgumentEvidence:
        confidence, preference = self._label_values(node)
        parsed = self._parse_literal(node.get("label"))
        predicate = parsed[1] if parsed else "evidencia"
        aspect = self._aspect_from_predicate(predicate)
        polarity = "negative" if negated else "positive"
        aspect_counts = counts.get(aspect) if isinstance(counts.get(aspect), dict) else {}
        return ArgumentEvidence(
            argument_id=str(node.get("id") or node.get("sourceKey") or predicate),
            title=str(node.get("label") or predicate),
            aspect=aspect,
            polarity=polarity,
            confidence=confidence,
            preference=preference,
            evidence_count=max(int(aspect_counts.get(polarity) or 0), 0),
            summary="Derivado del grafo LAF.",
        )

    @classmethod
    def _parse_literal(cls, value: Any) -> tuple[bool, str, str] | None:
        match = cls._literal_pattern.match(str(value or "").strip())
        if match is None:
            return None
        return bool(match.group(1)), match.group(2), match.group(3).strip()

    @staticmethod
    def _label_values(node: dict[str, Any]) -> tuple[float, float]:
        values = node.get("deltaAttributes") or node.get("attributes") or []
        confidence = LAFGraphRankingMapper._number(values[0] if values else 0)
        preference = LAFGraphRankingMapper._number(
            values[1] if len(values) > 1 else confidence
        )
        return confidence, preference

    @staticmethod
    def _number(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(numeric):
            return 0.0
        return max(0.0, min(numeric, 1.0))

    @staticmethod
    def _aspect_from_predicate(predicate: str) -> str:
        value = re.sub(
            r"^(?:resenaPositiva|resenaNegativa|catalogoDeclara)",
            "",
            predicate,
        )
        value = re.sub(r"Bueno$", "", value)
        value = re.sub(r"(?<!^)(?=[A-Z])", "_", value).casefold()
        return value or "sin_aspecto"


class LAFGraphPresentationMapper:
    """Reconstruye una vista LAF legible sin ocultar hechos, reglas u operadores."""

    def map(
        self,
        graph: dict[str, Any],
        *,
        root_id: str = "",
        entity_names: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        entity_names = entity_names or {}
        raw_nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
        nodes = [self._node(node, entity_names) for node in raw_nodes]
        node_ids = {node["id"] for node in nodes}
        if root_id not in node_ids:
            root_id = next(
                (node["id"] for node in nodes if node["node_type"] == "conclusion"),
                nodes[0]["id"] if nodes else "",
            )
        for node in nodes:
            if node["id"] == root_id:
                node["node_type"] = "conclusion"
                node["metadata"]["is_root"] = True

        raw_edges = []
        for index, raw in enumerate(graph.get("edges", []), start=1):
            if not isinstance(raw, dict):
                continue
            source = str(raw.get("from") or raw.get("source") or "")
            target = str(raw.get("to") or raw.get("target") or "")
            if source not in node_ids or target not in node_ids:
                continue
            kind = str(raw.get("kind") or raw.get("edge_type") or "SUPPORT").upper()
            raw_edges.append(
                {
                    "id": str(raw.get("id") or f"laf-edge-{index}-{source}-{target}"),
                    "source": source,
                    "target": target,
                    "edge_type": "conflict" if kind == "CONFLICT" else "support",
                    "label": "",
                    "rule_id": str(raw.get("ruleId") or raw.get("rule_id") or ""),
                    "metadata": {"laf_kind": kind},
                }
            )
        self._decorate_graph_labels(nodes, raw_edges, root_id)
        for node in nodes:
            if node["metadata"].get("aspect_run"):
                parsed = LAFGraphRankingMapper._parse_literal(node["literal"])
                if parsed and parsed[1] == "recomendar":
                    node["metadata"]["graph_label"] = (
                        "Resultado de " + node["metadata"]["aspect_run"]
                    )
        nodes, edges = self._with_operator_nodes(nodes, raw_edges)
        return {
            "graph_id": str(graph.get("graphId") or graph.get("graph_id") or "laf-real"),
            "root_id": root_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "nodes": nodes,
            "edges": edges,
            "available_filters": {
                "edge_types": ["support", "conflict"],
                "node_types": ["fact", "aspect", "dimension", "rule", "operator", "conclusion"],
            },
        }

    def _decorate_graph_labels(
        self,
        nodes: list[dict[str, Any]],
        raw_edges: list[dict[str, Any]],
        root_id: str,
    ) -> None:
        """Da títulos breves a los nodos sin reemplazar sus literales técnicos."""
        by_id = {node["id"]: node for node in nodes}
        incoming: dict[str, list[dict[str, Any]]] = {}
        for edge in raw_edges:
            incoming.setdefault(edge["target"], []).append(edge)

        for node in nodes:
            metadata = node["metadata"]
            if node["id"] == root_id:
                metadata["graph_label"] = "Recomendación final"
                continue
            parsed = LAFGraphRankingMapper._parse_literal(node["literal"])
            if not parsed or parsed[1] != "recomendar":
                metadata["graph_label"] = metadata.get("display_name") or node["label"]
                continue

            sources = [
                by_id.get(edge["source"])
                for edge in incoming.get(node["id"], [])
                if str(edge["metadata"].get("laf_kind") or "") == "SUPPORT"
            ]
            sources = [source for source in sources if source]
            evidence = next(
                (
                    source
                    for source in sources
                    if source["node_type"] in {"dimension", "aspect", "fact"}
                    and not str(source["literal"]).lstrip("~").startswith("recomendar(")
                ),
                None,
            )
            if evidence:
                evidence_name = str(evidence["metadata"].get("display_name") or "evidencia")
                short_name = re.sub(r"^(?:Evaluación de|(?:Opiniones|Menciones) (?:favorables|desfavorables):)\s*", "", evidence_name, flags=re.IGNORECASE)
                metadata["graph_label"] = f"Aporte: {short_name}"
                metadata["display_name"] = f"Aporte de {evidence_name.casefold()}"
            elif any(
                str(edge["metadata"].get("laf_kind") or "") in {"AGGREGATION", "CONFLICT"}
                for edge in incoming.get(node["id"], [])
            ):
                metadata["graph_label"] = "Síntesis de argumentos"
                metadata["display_name"] = "Síntesis de argumentos sobre el producto"
            else:
                metadata["graph_label"] = "Aporte a la recomendación"

    def _with_operator_nodes(
        self,
        nodes: list[dict[str, Any]],
        raw_edges: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Inserta los operadores que el JSON de Java expresa como tipos de arista."""
        node_types = {node["id"]: node["node_type"] for node in nodes}
        incoming: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for edge in raw_edges:
            kind = str(edge["metadata"].get("laf_kind") or "SUPPORT")
            incoming.setdefault((edge["target"], kind), []).append(edge)

        consumed: set[str] = set()
        rendered_edges: list[dict[str, Any]] = []
        operator_nodes: list[dict[str, Any]] = []
        edge_index = 0

        def add_operator(
            target: str,
            grouped_edges: list[dict[str, Any]],
            *,
            operator: str,
            edge_type: str,
        ) -> None:
            nonlocal edge_index
            operator_id = f"OP:{operator}:{target}"
            operator_nodes.append(self._operator_node(operator_id, operator))
            for original in grouped_edges:
                consumed.add(original["id"])
                edge_index += 1
                rendered_edges.append(
                    {
                        "id": f"laf-op-edge-{edge_index}",
                        "source": original["source"],
                        "target": operator_id,
                        "edge_type": edge_type,
                        "label": "",
                        "rule_id": original["rule_id"],
                        "metadata": original["metadata"],
                    }
                )
            edge_index += 1
            rendered_edges.append(
                {
                    "id": f"laf-op-edge-{edge_index}",
                    "source": operator_id,
                    "target": target,
                    "edge_type": edge_type,
                    "label": "",
                    "rule_id": "",
                    "metadata": {"laf_kind": operator},
                }
            )

        for (target, kind), grouped_edges in incoming.items():
            if kind == "AGGREGATION" and len(grouped_edges) > 1:
                add_operator(target, grouped_edges, operator="AGG", edge_type="support")
            elif kind == "CONFLICT":
                add_operator(target, grouped_edges, operator="CA", edge_type="conflict")
            elif kind == "SUPPORT" and any(
                node_types.get(edge["source"]) == "rule" for edge in grouped_edges
            ):
                add_operator(target, grouped_edges, operator="dMP", edge_type="support")

        rendered_edges.extend(
            edge for edge in raw_edges if edge["id"] not in consumed
        )
        return [*nodes, *operator_nodes], rendered_edges

    @staticmethod
    def _operator_node(node_id: str, operator: str) -> dict[str, Any]:
        labels = {"dMP": "dMP", "AGG": "⊕", "CA": "CA"}
        return {
            "id": node_id,
            "label": labels.get(operator, operator),
            "node_type": "operator",
            "literal": operator,
            "polarity": "negative" if operator == "CA" else "neutral",
            "confidence": 0.0,
            "preference": 0.0,
            "accumulated_value": 0.0,
            "weakened_value": 0.0,
            "acceptability_status": "accepted",
            "evidence_count": 0,
            "metadata": {"operator": operator, "source": "Motor LAF"},
        }

    def _node(self, raw: dict[str, Any], entity_names: dict[str, str]) -> dict[str, Any]:
        node_id = str(raw.get("id") or raw.get("sourceKey") or "nodo-sin-id")
        literal = str(raw.get("label") or raw.get("sourceKey") or node_id)
        parsed = LAFGraphRankingMapper._parse_literal(literal)
        raw_type = str(raw.get("type") or "").upper()
        predicate = parsed[1] if parsed else ""
        argument = parsed[2] if parsed else ""
        if raw_type == "RULE":
            node_type = "rule"
            label = literal
            aspect = ""
        elif predicate == "recomendar":
            node_type = "fact"
            label = literal
            aspect = ""
        else:
            aspect = LAFGraphRankingMapper._aspect_from_predicate(predicate) if predicate else ""
            is_source_fact = str(raw.get("sourceKey") or "").startswith("FACT|")
            if predicate in {
                "sensorialBueno",
                "valorBueno",
                "productoBueno",
                "elaboracionBueno",
                "conservacionBueno",
            }:
                node_type = "dimension"
            else:
                node_type = "fact" if is_source_fact else "aspect"
            label = literal
        confidence, preference = LAFGraphRankingMapper._label_values(raw)
        attributes = raw.get("attributes") or []
        accumulated = LAFGraphRankingMapper._number(attributes[0] if attributes else confidence)
        status = "accepted" if min(confidence, preference) > 0 else "rejected"
        return {
            "id": node_id,
            "label": label or literal,
            "node_type": node_type,
            "literal": literal,
            "polarity": "negative" if parsed and parsed[0] else "positive",
            "confidence": confidence,
            "preference": preference,
            "accumulated_value": accumulated,
            "weakened_value": confidence,
            "acceptability_status": status,
            "evidence_count": 0,
            "metadata": {
                "product": entity_names.get(argument, ""),
                "aspect_run": str(raw.get("aspectRun") or ""),
                "hide_preference": len(raw.get("deltaAttributes") or attributes) == 1,
                "aspect": aspect.replace("_", " "),
                "source": str(raw.get("sourceKey") or "Motor LAF"),
                "display_name": (
                    f"Recomendar {entity_names.get(argument, self._human_argument(argument))}"
                    if predicate == "recomendar"
                    else "Regla de inferencia"
                    if raw_type == "RULE"
                    else self._human_predicate(predicate, aspect)
                ),
            },
        }

    @staticmethod
    def _human_argument(value: str) -> str:
        return str(value or "producto").replace("_", " ").strip()

    @staticmethod
    def _human_predicate(predicate: str, aspect: str) -> str:
        labels = {
            "sabor": "Sabor",
            "aroma": "Aroma",
            "caducidad": "Frescura",
            "molienda": "Tipo de molienda",
            "originalidad": "Originalidad",
            "precio": "Precio",
            "garantia": "Garantía",
            "envio": "Envío",
            "cuotas": "Cuotas",
            "tienda_oficial": "Tienda oficial",
        }
        base = labels.get(aspect, aspect.replace("_", " ").strip().capitalize())
        if predicate.startswith("resenaPositiva"):
            return f"Menciones favorables: {base.casefold()}"
        if predicate.startswith("resenaNegativa") or predicate.startswith("~"):
            return f"Menciones desfavorables: {base.casefold()}"
        if predicate.startswith("catalogoDeclara"):
            return f"Información del catálogo: {base.casefold()}"
        if predicate.endswith("Bueno"):
            return f"Evaluación de {base.casefold()}"
        return base or predicate or "Evidencia"
