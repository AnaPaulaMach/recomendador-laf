"""Evaluadores intercambiables sin cambios en vistas ni plantillas."""
from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
import logging
import math
from typing import Any

from recommender.domain.contracts import (
    EvaluationRequest,
    EvaluationResult,
    RankingEntry,
)
from recommender.repositories.fixture_repository import FixtureRepository
from recommender.services.laf1_programs import (
    LAF1ProgramGenerationError,
    LAF1ProgramService,
)
from recommender.services.laf2_programs import (
    LAF2ProgramGenerationError,
    LAF2ProgramService,
)
from recommender.services.laf_api import (
    LAFApiClient,
    LAFApiError,
    LAFGraphRankingMapper,
    LAFProgramParseError,
    LAFProgramParser,
)
from recommender.services.post_laf_decision import (
    AspectEvaluation,
    DECISION_MODEL,
    combine_rankings,
    zero_threshold_payload,
)


logger = logging.getLogger(__name__)


class RecommendationEvaluator(ABC):
    evaluator_version = "abstract"
    operator_profile = "budan_2017"

    @abstractmethod
    def evaluate_products(self, request: EvaluationRequest) -> EvaluationResult:
        raise NotImplementedError

    @abstractmethod
    def evaluate_listings(self, request: EvaluationRequest) -> EvaluationResult:
        raise NotImplementedError


class MockRecommendationEvaluator(RecommendationEvaluator):
    """Demo determinista, limitada a los datasets incluidos en los fixtures."""

    evaluator_version = "mock-fixtures-1.0.0"
    generated_at = "2026-07-29T12:00:00-03:00"

    def __init__(self, fixtures: FixtureRepository):
        self.fixtures = fixtures

    def evaluate_products(self, request: EvaluationRequest) -> EvaluationResult:
        if not self._has_fixture_dataset(request):
            return self._pending(request, "laf1")
        data = self.fixtures.load(request.domain)
        return self._result(request, data.get("products", []), "laf1")

    def evaluate_listings(self, request: EvaluationRequest) -> EvaluationResult:
        if not self._has_fixture_dataset(request):
            return self._pending(request, "laf2")
        data = self.fixtures.load(request.domain)
        listings = deepcopy(data.get("listings", []))
        product_name = str(data.get("product_names", {}).get(request.selected_entity_id) or "")
        for index, item in enumerate(listings, start=1):
            item["entity_id"] = f"{request.selected_entity_id or 'producto'}-oferta-{index}"
            if product_name:
                item["entity_name"] = f"{product_name} · {item.get('seller', 'Publicación')}"
            item.setdefault("metadata", {})["product_id"] = request.selected_entity_id
        return self._result(request, listings, "laf2")

    def _has_fixture_dataset(self, request: EvaluationRequest) -> bool:
        return request.dataset_key in self.fixtures.demonstration_dataset_keys(
            request.domain
        )

    def _pending(self, request: EvaluationRequest, stage: str) -> EvaluationResult:
        """No sustituye un catálogo real por productos de demostración."""
        return EvaluationResult.from_dict(
            {
                "run_id": f"{stage}-pending-real-dataset",
                "evaluation_status": "pending",
                "evaluator_version": self.evaluator_version,
                "operator_profile": self.operator_profile,
                "dataset_key": request.dataset_key,
                "domain": request.domain,
                "strategy": request.strategy,
                "generated_at": "pendiente",
                "ranking": [],
            }
        )

    def _result(
        self,
        request: EvaluationRequest,
        ranking: list[dict[str, Any]],
        stage: str,
    ) -> EvaluationResult:
        fingerprint = "|".join(
            [
                request.domain,
                request.dataset_key,
                request.strategy,
                stage,
                request.selected_entity_id,
                ",".join(f"{key}:{request.preferences[key]:.2f}" for key in sorted(request.preferences)),
            ]
        )
        run_id = f"{stage}-mock-{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:12]}"
        return EvaluationResult.from_dict(
            {
                "run_id": run_id,
                "evaluation_status": "mock",
                "evaluator_version": self.evaluator_version,
                "operator_profile": self.operator_profile,
                "dataset_key": request.dataset_key,
                "domain": request.domain,
                "strategy": request.strategy,
                "generated_at": self.generated_at,
                "ranking": ranking,
            }
        )


class PythonLAFEvaluator(RecommendationEvaluator):
    """Punto de extensión para la evaluación algebraica validada."""

    evaluator_version = "python-laf-pending-0.1.0"

    def evaluate_products(self, request: EvaluationRequest) -> EvaluationResult:
        return self._pending(request, "laf1")

    def evaluate_listings(self, request: EvaluationRequest) -> EvaluationResult:
        return self._pending(request, "laf2")

    def _pending(self, request: EvaluationRequest, stage: str) -> EvaluationResult:
        return EvaluationResult.from_dict(
            {
                "run_id": f"{stage}-pending",
                "evaluation_status": "pending",
                "evaluator_version": self.evaluator_version,
                "operator_profile": self.operator_profile,
                "dataset_key": request.dataset_key,
                "domain": request.domain,
                "strategy": request.strategy,
                "generated_at": "pendiente",
                "ranking": [],
            }
        )


class LAF1PreparedRecommendationEvaluator(RecommendationEvaluator):
    """Usa el demo sólo para fixtures y prepara 08/10 para datos reales."""

    evaluator_version = "laf-programs-08-10-1.0.0"

    def __init__(
        self,
        fixtures: FixtureRepository,
        laf1_programs: LAF1ProgramService,
        laf2_programs: LAF2ProgramService | None = None,
    ):
        self.fixtures = fixtures
        self.mock = MockRecommendationEvaluator(fixtures)
        self.laf1_programs = laf1_programs
        self.laf2_programs = laf2_programs

    def evaluate_products(self, request: EvaluationRequest) -> EvaluationResult:
        if self._has_fixture_dataset(request):
            return self.mock.evaluate_products(request)
        try:
            generated = self.laf1_programs.generate(request)
        except LAF1ProgramGenerationError:
            logger.warning("No se pudo generar LAF 1 para %s.", request.dataset_key)
            return self._pending(request, "laf1", program_status="failed")
        return self._generated_result(request, generated, "laf1")

    def evaluate_listings(self, request: EvaluationRequest) -> EvaluationResult:
        if self._has_fixture_dataset(request):
            return self.mock.evaluate_listings(request)
        if self.laf2_programs is None:
            return self._pending(request, "laf2")
        try:
            generated = self.laf2_programs.generate(request)
        except LAF2ProgramGenerationError:
            logger.warning("No se pudo generar LAF 2 para %s.", request.dataset_key)
            return self._pending(request, "laf2", program_status="failed")
        return self._generated_result(request, generated, "laf2")

    def _generated_result(self, request, generated, stage: str) -> EvaluationResult:
        return EvaluationResult.from_dict(
            {
                "run_id": generated.run_id,
                "evaluation_status": "pending",
                "evaluator_version": self.evaluator_version,
                "operator_profile": self.operator_profile,
                "dataset_key": request.dataset_key,
                "domain": request.domain,
                "strategy": request.strategy,
                "generated_at": generated.generated_at,
                "ranking": [],
                "program_status": "generated",
                "program_kind": stage,
                "laf_program": generated.text,
                "methodology_sha256": generated.methodology_sha256,
                "products_count": getattr(generated, "products_count", 1),
                "items_count": getattr(generated, "items_count", 0),
                "facts_count": generated.facts_count,
                "rules_count": generated.rules_count,
            }
        )

    def _has_fixture_dataset(self, request: EvaluationRequest) -> bool:
        return request.dataset_key in self.fixtures.fixture_dataset_keys(request.domain)

    def _pending(
        self,
        request: EvaluationRequest,
        stage: str,
        *,
        program_status: str = "not_generated",
    ) -> EvaluationResult:
        return EvaluationResult.from_dict(
            {
                "run_id": f"{stage}-pending-{request.dataset_key}",
                "evaluation_status": "pending",
                "evaluator_version": self.evaluator_version,
                "operator_profile": self.operator_profile,
                "dataset_key": request.dataset_key,
                "domain": request.domain,
                "strategy": request.strategy,
                "generated_at": datetime.now().astimezone().isoformat(),
                "ranking": [],
                "program_status": program_status,
                "program_kind": stage if stage in {"laf1", "laf2"} else "",
            }
        )


class LAFHttpRecommendationEvaluator(RecommendationEvaluator):
    """Ejecuta los programas 08/10 en la API LAF sin acoplar las vistas."""

    evaluator_version = "laf-http-api-post-laf-1.1.0"

    def __init__(
        self,
        fixtures: FixtureRepository,
        laf1_programs: LAF1ProgramService,
        laf2_programs: LAF2ProgramService,
        api_client: LAFApiClient,
        *,
        results_validated: bool = False,
        product_decision_model: str = DECISION_MODEL,
        parser: LAFProgramParser | None = None,
        ranking_mapper: LAFGraphRankingMapper | None = None,
    ):
        self.fixtures = fixtures
        self.mock = MockRecommendationEvaluator(fixtures)
        self.laf1_programs = laf1_programs
        self.laf2_programs = laf2_programs
        self.api_client = api_client
        self.results_validated = bool(results_validated)
        self.product_decision_model = str(product_decision_model or "legacy_min")
        self.parser = parser or LAFProgramParser()
        self.ranking_mapper = ranking_mapper or LAFGraphRankingMapper()

    def evaluate_products(self, request: EvaluationRequest) -> EvaluationResult:
        if self._has_fixture_dataset(request):
            return self.mock.evaluate_products(request)
        if self.results_validated and self.product_decision_model == DECISION_MODEL:
            return self._evaluate_products_multicriteria(request)
        try:
            generated = self.laf1_programs.generate(request)
        except LAF1ProgramGenerationError:
            logger.warning("No se pudo generar LAF 1 para %s.", request.dataset_key)
            return self._pending_without_program(request, "laf1")
        return self._execute(request, generated, "laf1")

    def _evaluate_products_multicriteria(
        self,
        request: EvaluationRequest,
    ) -> EvaluationResult:
        # Adaptadores anteriores conservan su protocolo; el servicio real genera
        # programas separados. La referencia permanece disponible para comparar.
        if not callable(getattr(type(self.laf1_programs), "generate_aspects", None)):
            return self._evaluate_products_multicriteria_reference(request)
        try:
            backup, programs = self.laf1_programs.generate_aspects(request)
        except LAF1ProgramGenerationError:
            logger.exception("No se pudieron generar programas independientes de LAF 1.")
            return self._pending_without_program(request, "laf1")
        graphs = {}
        backup_graph = {}
        evaluations = []
        try:
            if not programs:
                return self._result(request, backup, "laf1", ranking=(), graph={})
            # Se conserva la baseline histórica sin filtrar, para compatibilidad
            # de metadatos y comparación. No decide el puntaje multicriterio.
            backup_graph = self.api_client.build_graph(
                self.parser.parse(backup.text).to_request_payload()
            )
            baseline = self.ranking_mapper.map(backup_graph, backup.entities)
            if not baseline:
                raise LAFApiError("El respaldo completo no contiene conclusiones recomendar.")
            for aspect, generated in programs.items():
                parsed = self.parser.parse(generated.text)
                if parsed.attribute_count != 1:
                    raise LAFProgramParseError("LAF1 por aspecto requiere solo confianza.")
                raw = self.api_client.build_graph(parsed.to_request_payload())
                graphs[aspect] = raw
                aspect_ranking = self.ranking_mapper.map(raw, generated.entities)
                if not aspect_ranking:
                    raise LAFApiError(f"El aspecto {aspect!r} no produjo ranking.")
                evaluations.append(AspectEvaluation(aspect, request.preferences[aspect], aspect_ranking))
            ranking = combine_rankings(baseline, evaluations, request.preferences)
            if not ranking:
                raise LAFApiError("La decisión multicriterio no produjo ranking.")
            # Evidencia y nodos de explicación pertenecen a las mismas corridas
            # que aportaron la confianza. Los pesos siguen siendo externos.
            traced = []
            for entry in ranking:
                sources = [
                    (evaluation.aspect, item)
                    for evaluation in evaluations for item in evaluation.ranking
                    if item.entity_id == entry.entity_id
                ]
                positive = tuple(
                    replace(argument, argument_id=f"{aspect}:{argument.argument_id}")
                    for aspect, item in sources for argument in item.arguments_for
                )
                negative = tuple(
                    replace(argument, argument_id=f"{aspect}:{argument.argument_id}")
                    for aspect, item in sources for argument in item.arguments_against
                )
                metadata = dict(entry.metadata)
                metadata.update({
                    "explanation_source": "stored_single_label_aspect_runs",
                    "label_count": 1,
                    "laf_node_id": f"{sources[0][0]}:{sources[0][1].metadata.get('laf_node_id', '')}",
                    "aspect_node_ids": {
                        aspect: item.metadata.get("laf_node_id", "") for aspect, item in sources
                    },
                })
                traced.append(replace(entry, arguments_for=positive, arguments_against=negative,
                                      evidence_count=sum(a.evidence_count for a in positive + negative),
                                      metadata=metadata))
            result = self._result(request, backup, "laf1", ranking=tuple(traced),
                                  graph=self._merge_aspect_graphs(graphs))
        except (LAFProgramParseError, LAFApiError):
            logger.exception("La evaluación independiente de LAF1 falló.")
            result = self._result(request, backup, "laf1", ranking=(), graph={})
        return replace(result, run_id=backup.run_id + "-confidence-only-v1",
                       evaluator_version="laf-http-api-single-label-laf1-2.0.0",
                       aspect_programs={aspect: program.text for aspect, program in programs.items()},
                       aspect_graphs=graphs, backup_laf_graph=backup_graph)

    @staticmethod
    def _merge_aspect_graphs(graphs):
        """Unión disjunta para presentación: no hay agregación LAF entre aspectos."""
        return LAFHttpRecommendationEvaluator._merge_component_graphs(
            graphs,
            graph_id="laf1-independent-aspects",
        )

    @staticmethod
    def _merge_component_graphs(graphs, *, graph_id):
        """Une corridas independientes sin inventar aristas entre ellas."""
        merged = {"nodes": [], "edges": [], "graphId": graph_id}
        for aspect, graph in graphs.items():
            for raw in graph.get("nodes", []):
                node = deepcopy(raw)
                node["id"] = f"{aspect}:{raw['id']}"
                node["aspectRun"] = aspect
                merged["nodes"].append(node)
            for index, raw in enumerate(graph.get("edges", [])):
                edge = deepcopy(raw)
                edge["id"] = f"{aspect}:{raw.get('id', index)}"
                for key in ("from", "to", "source", "target", "ruleId", "rule_id"):
                    if edge.get(key) is not None:
                        edge[key] = f"{aspect}:{edge[key]}"
                merged["edges"].append(edge)
        return merged

    def _evaluate_products_multicriteria_reference(
        self,
        request: EvaluationRequest,
    ) -> EvaluationResult:
        active_aspects = tuple(
            sorted(
                aspect
                for aspect, weight in request.preferences.items()
                if self._positive_number(weight)
            )
        )
        preference_sets = [dict(request.preferences)] + [
            {aspect: 1.0} for aspect in active_aspects
        ]
        try:
            generate_many = getattr(type(self.laf1_programs), "generate_many", None)
            if callable(generate_many):
                generated_variants = self.laf1_programs.generate_many(
                    request,
                    preference_sets,
                )
            else:
                generated_variants = tuple(
                    self.laf1_programs.generate(
                        EvaluationRequest(
                            domain=request.domain,
                            dataset_key=request.dataset_key,
                            strategy=request.strategy,
                            preferences=preferences,
                        )
                    )
                    for preferences in preference_sets
                )
        except LAF1ProgramGenerationError:
            logger.warning("No se pudieron generar variantes LAF 1 para %s.", request.dataset_key)
            return self._pending_without_program(request, "laf1")
        baseline_generated = generated_variants[0]
        if not active_aspects:
            return self._result(
                request,
                baseline_generated,
                "laf1",
                ranking=(),
                graph={},
            )
        graph: dict[str, Any] = {}
        try:
            baseline_payload = self.parser.parse(
                baseline_generated.text
            ).to_request_payload()
            graph = self.api_client.build_graph(baseline_payload)
            baseline_ranking = self.ranking_mapper.map(
                graph,
                baseline_generated.entities,
            )
            if not baseline_ranking:
                raise LAFApiError(
                    "La corrida completa no contiene conclusiones recomendar."
                )
            evaluations = []
            for aspect, generated in zip(
                active_aspects,
                generated_variants[1:],
                strict=True,
            ):
                payload = zero_threshold_payload(
                    self.parser.parse(generated.text).to_request_payload()
                )
                aspect_graph = self.api_client.build_graph(payload)
                aspect_ranking = self.ranking_mapper.map(
                    aspect_graph,
                    generated.entities,
                )
                if not aspect_ranking:
                    raise LAFApiError(
                        f"La corrida del aspecto {aspect!r} no produjo ranking."
                    )
                evaluations.append(
                    AspectEvaluation(
                        aspect=aspect,
                        weight=float(request.preferences[aspect]),
                        ranking=aspect_ranking,
                    )
                )
            ranking = combine_rankings(
                baseline_ranking,
                evaluations,
                request.preferences,
            )
            if not ranking:
                raise LAFApiError("La decisión multicriterio no produjo ranking.")
        except (LAFProgramParseError, LAFApiError):
            logger.exception("La decisión multicriterio post-LAF falló.")
            return self._result(
                request,
                baseline_generated,
                "laf1",
                ranking=(),
                graph=graph,
            )
        return self._result(
            request,
            baseline_generated,
            "laf1",
            ranking=ranking,
            graph=graph,
        )

    @staticmethod
    def _positive_number(value: object) -> bool:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(numeric) and numeric > 0

    def evaluate_listings(self, request: EvaluationRequest) -> EvaluationResult:
        if self._has_fixture_dataset(request):
            return self.mock.evaluate_listings(request)
        if self.results_validated and self.product_decision_model == DECISION_MODEL:
            return self._evaluate_listings_multicriteria(request)
        try:
            generated = self.laf2_programs.generate(request)
        except LAF2ProgramGenerationError:
            logger.warning("No se pudo generar LAF 2 para %s.", request.dataset_key)
            return self._pending_without_program(request, "laf2")
        return self._execute(request, generated, "laf2")

    def _evaluate_listings_multicriteria(
        self,
        request: EvaluationRequest,
    ) -> EvaluationResult:
        """Misma decisión multicriterio que productos, aplicada a publicaciones.

        Diferencias respecto de ``_evaluate_products_multicriteria``, medidas en
        ``validacion_laf2/VALIDACION_MULTICRITERIO_LAF2.md``:

        * una condición activa puede no tener ningún hecho en el producto (por
          ejemplo cuotas en café). El payload queda sin hechos y la API responde
          HTTP 400, así que no se la llama: la condición sale del denominador y
          se informa en ``metadata["conditions_without_evidence"]``;
        * una publicación que no cumple ninguna condición activa no aparece en
          ninguna corrida por condición. Se la conserva al final del ranking con
          puntaje 0 (``not_recommended``) a partir del baseline, que siempre la
          incluye porque ``precioBueno`` existe para todas.
        """
        active_conditions = tuple(
            sorted(
                condition
                for condition, weight in request.preferences.items()
                if self._positive_number(weight)
            )
        )

        def variant(preferences: dict[str, float]) -> EvaluationRequest:
            return EvaluationRequest(
                domain=request.domain,
                dataset_key=request.dataset_key,
                strategy=request.strategy,
                preferences=preferences,
                selected_entity_id=request.selected_entity_id,
                budget_min=request.budget_min,
                budget_max=request.budget_max,
            )

        preference_sets = [dict(request.preferences)] + [
            {key: (1.0 if key == condition else 0.0) for key in request.preferences}
            for condition in active_conditions
        ]
        # Selección explícita por condición y una sola etiqueta (ADR-007), igual
        # que LAF 1 por aspecto (ADR-002). Los adaptadores que no la implementan
        # conservan la máscara de preferencias y las dos etiquetas.
        single_label = callable(
            getattr(type(self.laf2_programs), "generate_conditions", None)
        )
        try:
            if single_label:
                baseline_generated, by_condition = (
                    self.laf2_programs.generate_conditions(request)
                )
                condition_variants = tuple(
                    by_condition[condition] for condition in active_conditions
                )
            else:
                generate_many = getattr(type(self.laf2_programs), "generate_many", None)
                if callable(generate_many):
                    generated_variants = self.laf2_programs.generate_many(
                        request,
                        preference_sets,
                    )
                else:
                    generated_variants = tuple(
                        self.laf2_programs.generate(variant(preferences))
                        for preferences in preference_sets
                    )
                baseline_generated = generated_variants[0]
                condition_variants = tuple(generated_variants[1:])
        except (LAF2ProgramGenerationError, KeyError):
            logger.warning("No se pudo generar LAF 2 para %s.", request.dataset_key)
            return self._pending_without_program(request, "laf2")
        if not active_conditions:
            return self._result(request, baseline_generated, "laf2", ranking=(), graph={})

        graph: dict[str, Any] = {}
        condition_graphs: dict[str, dict[str, Any]] = {}
        condition_programs: dict[str, str] = {}
        execution_payloads: dict[str, dict[str, Any]] = {}
        try:
            baseline_payload = self.parser.parse(
                baseline_generated.text
            ).to_request_payload()
            graph = self.api_client.build_graph(baseline_payload)
            baseline_ranking = self.ranking_mapper.map(
                graph,
                baseline_generated.entities,
            )
            if not baseline_ranking:
                raise LAFApiError(
                    "La corrida completa no contiene conclusiones recomendar."
                )
            evaluations = []
            without_evidence: list[str] = []
            for condition, generated in zip(
                active_conditions,
                condition_variants,
                strict=True,
            ):
                if single_label:
                    # Sin hechos el programa no es parseable: la condición no
                    # tiene evidencia en este producto y sale del denominador.
                    if not generated.facts_count:
                        without_evidence.append(condition)
                        continue
                    parsed = self.parser.parse(generated.text)
                    if parsed.attribute_count != 1:
                        raise LAFProgramParseError(
                            "LAF2 por condición requiere solo confianza."
                        )
                    payload = parsed.to_request_payload()
                else:
                    payload = zero_threshold_payload(
                        self.parser.parse(generated.text).to_request_payload()
                    )
                if not payload.get("facts"):
                    without_evidence.append(condition)
                    continue
                condition_graph = self.api_client.build_graph(payload)
                condition_ranking = self.ranking_mapper.map(
                    condition_graph,
                    generated.entities,
                )
                if not condition_ranking:
                    without_evidence.append(condition)
                    continue
                condition_graphs[condition] = condition_graph
                condition_programs[condition] = generated.text
                execution_payloads[condition] = payload
                evaluations.append(
                    AspectEvaluation(
                        aspect=condition,
                        weight=float(request.preferences[condition]),
                        ranking=condition_ranking,
                    )
                )
            effective_preferences = {
                condition: (
                    0.0 if condition in without_evidence else weight
                )
                for condition, weight in request.preferences.items()
            }
            ranking = combine_rankings(
                baseline_ranking,
                evaluations,
                effective_preferences,
            )
            ranking = self._complete_with_baseline(
                ranking,
                baseline_ranking,
                without_evidence,
            )
            if not ranking:
                raise LAFApiError("La decisión multicriterio no produjo ranking.")

            # La explicación y los argumentos deben provenir de las mismas
            # corridas por condición que determinaron el puntaje mostrado.
            traced = []
            for entry in ranking:
                sources = [
                    (evaluation.aspect, item)
                    for evaluation in evaluations
                    for item in evaluation.ranking
                    if item.entity_id == entry.entity_id
                ]
                positive = tuple(
                    replace(argument, argument_id=f"{condition}:{argument.argument_id}")
                    for condition, item in sources
                    for argument in item.arguments_for
                )
                negative = tuple(
                    replace(argument, argument_id=f"{condition}:{argument.argument_id}")
                    for condition, item in sources
                    for argument in item.arguments_against
                )
                metadata = dict(entry.metadata)
                metadata.update(
                    {
                        "explanation_source": "stored_laf2_condition_runs",
                        # Cuántas etiquetas trajo la corrida que dio el número.
                        "label_count": 1 if single_label else 2,
                        "laf_node_id": (
                            f"{sources[0][0]}:{sources[0][1].metadata.get('laf_node_id', '')}"
                            if sources
                            else ""
                        ),
                        "condition_node_ids": {
                            condition: item.metadata.get("laf_node_id", "")
                            for condition, item in sources
                        },
                    }
                )
                traced.append(
                    replace(
                        entry,
                        arguments_for=positive,
                        arguments_against=negative,
                        evidence_count=sum(
                            argument.evidence_count
                            for argument in positive + negative
                        ),
                        metadata=metadata,
                    )
                )
            ranking = tuple(traced)
        except (LAFProgramParseError, LAFApiError):
            logger.exception("La decisión multicriterio de publicaciones falló.")
            return self._result(
                request,
                baseline_generated,
                "laf2",
                ranking=(),
                graph=graph,
            )
        result = self._result(
            request,
            baseline_generated,
            "laf2",
            ranking=ranking,
            graph=self._merge_component_graphs(
                condition_graphs,
                graph_id="laf2-independent-conditions",
            ),
        )
        return replace(
            result,
            run_id=(
                baseline_generated.run_id + "-confidence-only-v1"
                if single_label
                else result.run_id
            ),
            evaluator_version=(
                "laf-http-api-single-label-laf2-3.0.0"
                if single_label
                else "laf-http-api-laf2-traceable-2.0.0"
            ),
            aspect_programs=condition_programs,
            aspect_graphs=condition_graphs,
            execution_payloads=execution_payloads,
            backup_laf_graph=graph,
        )

    @staticmethod
    def _complete_with_baseline(
        ranking: tuple[RankingEntry, ...],
        baseline: tuple[RankingEntry, ...],
        without_evidence: list[str],
    ) -> tuple[RankingEntry, ...]:
        """Agrega al final, con 0, las publicaciones sin ninguna condición activa."""
        present = {entry.entity_id for entry in ranking}
        entries = list(ranking)
        for source in baseline:
            if source.entity_id in present:
                continue
            metadata = dict(source.metadata)
            metadata.update(
                {
                    "decision_model": DECISION_MODEL,
                    "score_projection": (
                        "sum(normalized_user_weight * per_aspect_laf_confidence)"
                    ),
                    "source_laf_confidence": source.confidence,
                    "source_laf_preference": source.preference,
                    "aspect_contributions": [],
                }
            )
            entries.append(
                RankingEntry(
                    **{
                        **source.__dict__,
                        "final_score": 0.0,
                        "status": "not_recommended",
                        "metadata": metadata,
                    }
                )
            )
        # Desempate: a igual puntaje en lo que pidió la persona, primero la de
        # mayor confianza del programa completo (que ya incorpora el precio:
        # más barata, más confianza). Sin esto el empate se resolvía por id.
        entries.sort(
            key=lambda entry: (
                -entry.final_score,
                -entry.confidence,
                entry.entity_id.casefold(),
            )
        )
        completed = []
        for position, entry in enumerate(entries, start=1):
            metadata = dict(entry.metadata)
            metadata["conditions_without_evidence"] = sorted(without_evidence)
            completed.append(
                RankingEntry(
                    **{**entry.__dict__, "position": position, "metadata": metadata}
                )
            )
        return tuple(completed)

    def _execute(self, request, generated, stage: str) -> EvaluationResult:
        graph: dict[str, Any] = {}
        try:
            payload = self.parser.parse(generated.text).to_request_payload()
            graph = self.api_client.build_graph(payload)
            ranking = self.ranking_mapper.map(graph, generated.entities)
            if not ranking:
                raise LAFApiError(
                    "La respuesta no contiene conclusiones recomendar para los candidatos."
                )
        except (LAFProgramParseError, LAFApiError):
            logger.exception("La ejecución HTTP de %s falló.", stage)
            return self._result(request, generated, stage, ranking=(), graph=graph)
        return self._result(
            request,
            generated,
            stage,
            ranking=ranking if self.results_validated else (),
            graph=graph,
        )

    def _result(self, request, generated, stage: str, *, ranking, graph=None) -> EvaluationResult:
        return EvaluationResult.from_dict(
            {
                "run_id": generated.run_id,
                "evaluation_status": (
                    "validated" if self.results_validated and ranking else "pending"
                ),
                "evaluator_version": self.evaluator_version,
                "operator_profile": self.operator_profile,
                "dataset_key": request.dataset_key,
                "domain": request.domain,
                "strategy": request.strategy,
                "generated_at": generated.generated_at,
                "ranking": [asdict(entry) for entry in ranking],
                "program_status": "generated",
                "program_kind": stage,
                "laf_program": generated.text,
                "methodology_sha256": generated.methodology_sha256,
                "products_count": getattr(generated, "products_count", 1),
                "items_count": getattr(generated, "items_count", 0),
                "facts_count": generated.facts_count,
                "rules_count": generated.rules_count,
                "laf_graph": graph or {},
            }
        )

    def _pending_without_program(
        self,
        request: EvaluationRequest,
        stage: str,
    ) -> EvaluationResult:
        return EvaluationResult.from_dict(
            {
                "run_id": f"{stage}-pending-{request.dataset_key}",
                "evaluation_status": "pending",
                "evaluator_version": self.evaluator_version,
                "operator_profile": self.operator_profile,
                "dataset_key": request.dataset_key,
                "domain": request.domain,
                "strategy": request.strategy,
                "generated_at": datetime.now().astimezone().isoformat(),
                "ranking": [],
                "program_status": "failed",
                "program_kind": stage,
            }
        )

    def _has_fixture_dataset(self, request: EvaluationRequest) -> bool:
        return request.dataset_key in self.fixtures.fixture_dataset_keys(request.domain)
