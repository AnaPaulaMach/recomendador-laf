import json
from unittest.mock import Mock

from django.conf import settings
from django.test import SimpleTestCase

from recommender.domain.contracts import EvaluationRequest
from recommender.repositories.fixture_repository import FixtureRepository
from recommender.services.evaluators import LAFHttpRecommendationEvaluator
from recommender.services.laf1_programs import GeneratedLAF1Program
from recommender.services.laf2_programs import GeneratedLAF2Program
from recommender.services.post_laf_decision import DECISION_MODEL
from recommender.services.laf_api import (
    LAFApiClient,
    LAFGraphPresentationMapper,
    LAFGraphRankingMapper,
    LAFProgramParseError,
    LAFProgramParser,
)


PROGRAM = """
% Caso controlado de integración
basicServices(houseA). {0.50; 0.80}
goodArea(X) :- basicServices(X). {0.40; 1.00}
recomendar(X) :- goodArea(X). {1.00; 1.00}
"""


GRAPH = {
    "nodes": [
        {
            "id": "F1",
            "label": "basicServices(houseA)",
            "type": "FACT",
            "attributes": ["0.5", "0.8"],
            "deltaAttributes": ["0.5", "0.8"],
            "sourceKey": "FACT|basicServices|houseA",
        },
        {
            "id": "F2",
            "label": "recomendar(houseA)",
            "type": "FACT",
            "attributes": ["0.2", "0.8"],
            "deltaAttributes": ["0.2", "0.8"],
        },
    ],
    "edges": [{"from": "F1", "to": "F2", "kind": "SUPPORT"}],
}


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class LAFProgramParserTests(SimpleTestCase):
    def test_translates_program_to_graph_request_contract(self):
        payload = LAFProgramParser().parse(PROGRAM).to_request_payload()

        self.assertEqual(payload["facts"][0]["name"], "basicServices")
        self.assertEqual(payload["facts"][0]["attributes"], ["0.50", "0.80"])
        self.assertEqual(payload["rules"][0]["bodyLiterals"], ["basicServices"])
        self.assertEqual(payload["rules"][1]["headName"], "recomendar")
        self.assertFalse(payload["explainabilityEnabled"])
        self.assertEqual(len(payload["operations"]["labels"]), 2)
        self.assertEqual(
            payload["operations"]["labels"][0]["supportFunction"],
            "X * Y",
        )

    def test_rejects_inconsistent_attribute_arity(self):
        with self.assertRaises(LAFProgramParseError):
            LAFProgramParser().parse(
                "hecho(a). {0.5; 0.8}\nconclusion(X) :- hecho(X). {0.4}"
            )

    def test_accepts_single_label_program_with_only_confidence(self):
        # La API acepta 1 o 2 etiquetas; con una, se manda solo la confianza.
        payload = LAFProgramParser().parse(
            "hecho(a). {0.6}\nconclusion(X) :- hecho(X). {0.85}"
        ).to_request_payload()

        self.assertEqual(len(payload["operations"]["labels"]), 1)
        self.assertEqual(payload["operations"]["labels"][0]["labelName"], "confidence")
        self.assertEqual(payload["facts"][0]["attributes"], ["0.6"])

    def test_two_label_program_still_sends_both_operations(self):
        # Regresión: el comportamiento con dos etiquetas NO cambia (default).
        payload = LAFProgramParser().parse(PROGRAM).to_request_payload()

        labels = [row["labelName"] for row in payload["operations"]["labels"]]
        self.assertEqual(labels, ["confidence", "preference"])

    def test_rejects_three_labels(self):
        with self.assertRaises(LAFProgramParseError):
            LAFProgramParser().parse(
                "hecho(a). {0.5; 0.8; 0.2}\nconclusion(X) :- hecho(X). {0.4; 0.4; 0.4}"
            ).to_request_payload()


class LAFApiClientTests(SimpleTestCase):
    def test_posts_json_and_reads_graph(self):
        calls = []

        def opener(request, timeout):
            calls.append((request, timeout))
            return _Response(GRAPH)

        graph = LAFApiClient(
            "http://laf.test/api/graph",
            timeout_seconds=7,
            opener=opener,
        ).build_graph({"facts": [], "rules": [], "operations": {}})

        self.assertEqual(graph, GRAPH)
        self.assertEqual(calls[0][0].full_url, "http://laf.test/api/graph")
        self.assertEqual(calls[0][0].method, "POST")
        self.assertEqual(calls[0][1], 7)


class LAFGraphRankingMapperTests(SimpleTestCase):
    def test_maps_original_entity_id_and_keeps_two_labels(self):
        ranking = LAFGraphRankingMapper().map(
            GRAPH,
            (
                {
                    "argument": "houseA",
                    "entity_id": "MCO123",
                    "entity_name": "Café de prueba",
                    "evidence_counts": {"basic_services": {"positive": 4}},
                    "metadata": {"product_id": "MCO123"},
                },
            ),
        )

        self.assertEqual(len(ranking), 1)
        self.assertEqual(ranking[0].entity_id, "MCO123")
        self.assertEqual(ranking[0].confidence, 0.2)
        self.assertEqual(ranking[0].preference, 0.8)
        self.assertEqual(ranking[0].final_score, 0.2)
        self.assertEqual(ranking[0].metadata["laf_argument"], "houseA")
        self.assertEqual(ranking[0].evidence_count, 4)

    def test_orders_by_conservative_projection_and_stable_id(self):
        graph = {
            "nodes": [
                {"id": "1", "label": "recomendar(b)", "type": "FACT", "deltaAttributes": ["0.9", "0.4"]},
                {"id": "2", "label": "recomendar(a)", "type": "FACT", "deltaAttributes": ["0.7", "0.7"]},
            ],
            "edges": [],
        }
        ranking = LAFGraphRankingMapper().map(graph, ())

        self.assertEqual([item.entity_id for item in ranking], ["a", "b"])
        self.assertEqual([item.position for item in ranking], [1, 2])

    def test_classifies_resena_negativa_fact_as_argument_against(self):
        graph = {
            "nodes": [
                {
                    "id": "negative",
                    "label": "resenaNegativaSabor(cafe)",
                    "type": "FACT",
                    "attributes": ["0.35", "1"],
                    "deltaAttributes": ["0.35", "1"],
                    "sourceKey": "FACT|resenaNegativaSabor|cafe",
                },
                {
                    "id": "final",
                    "label": "recomendar(cafe)",
                    "type": "FACT",
                    "deltaAttributes": ["0.65", "1"],
                },
            ],
            "edges": [],
        }

        ranking = LAFGraphRankingMapper().map(
            graph,
            (
                {
                    "argument": "cafe",
                    "entity_id": "MLM1",
                    "entity_name": "Café",
                    "evidence_counts": {"sabor": {"negative": 3}},
                },
            ),
        )

        self.assertEqual(ranking[0].arguments_for, ())
        self.assertEqual(len(ranking[0].arguments_against), 1)
        self.assertEqual(ranking[0].arguments_against[0].polarity, "negative")
        self.assertEqual(ranking[0].arguments_against[0].evidence_count, 3)


class LAFGraphPresentationMapperTests(SimpleTestCase):
    def test_maps_real_graph_to_human_visual_contract(self):
        graph = LAFGraphPresentationMapper().map(
            GRAPH,
            root_id="F2",
            entity_names={"houseA": "Café de prueba"},
        )

        self.assertEqual(graph["root_id"], "F2")
        self.assertEqual(graph["total_nodes"], 2)
        conclusion = next(node for node in graph["nodes"] if node["id"] == "F2")
        self.assertEqual(conclusion["node_type"], "conclusion")
        self.assertEqual(conclusion["label"], "recomendar(houseA)")
        self.assertEqual(conclusion["metadata"]["display_name"], "Recomendar Café de prueba")
        self.assertEqual(conclusion["metadata"]["graph_label"], "Recomendación final")
        self.assertEqual(graph["edges"][0]["edge_type"], "support")

    def test_distinguishes_final_conclusion_from_its_derivations(self):
        graph = LAFGraphPresentationMapper().map(
            {
                "nodes": [
                    {"id": "final", "label": "recomendar(cafe)", "type": "FACT", "deltaAttributes": ["0.8", "0.8"]},
                    {"id": "derivation", "label": "recomendar(cafe)", "type": "FACT", "deltaAttributes": ["0.6", "0.8"]},
                ],
                "edges": [{"from": "derivation", "to": "final", "kind": "SUPPORT"}],
            },
            root_id="final",
        )

        derivation = next(node for node in graph["nodes"] if node["id"] == "derivation")
        self.assertEqual(derivation["node_type"], "fact")
        self.assertEqual(derivation["label"], "recomendar(cafe)")
        self.assertEqual(derivation["metadata"]["graph_label"], "Aporte a la recomendación")

    def test_reconstructs_laf_operators_from_edge_kinds(self):
        graph = LAFGraphPresentationMapper().map(
            {
                "nodes": [
                    {"id": "fact", "label": "saborBueno(cafe)", "type": "FACT", "deltaAttributes": ["0.8", "1"]},
                    {"id": "rule", "label": "recomendar(X) :- saborBueno(X).", "type": "RULE", "deltaAttributes": ["0.9", "1"]},
                    {"id": "derived", "label": "recomendar(cafe)", "type": "FACT", "deltaAttributes": ["0.72", "1"]},
                    {"id": "other", "label": "recomendar(cafe)", "type": "FACT", "deltaAttributes": ["0.4", "1"]},
                    {"id": "final", "label": "recomendar(cafe)", "type": "FACT", "deltaAttributes": ["0.83", "1"]},
                ],
                "edges": [
                    {"from": "fact", "to": "derived", "kind": "SUPPORT"},
                    {"from": "rule", "to": "derived", "kind": "SUPPORT"},
                    {"from": "derived", "to": "final", "kind": "AGGREGATION"},
                    {"from": "other", "to": "final", "kind": "AGGREGATION"},
                ],
            },
            root_id="final",
        )

        operators = {
            node["metadata"].get("operator"): node
            for node in graph["nodes"]
            if node["node_type"] == "operator"
        }
        self.assertEqual(set(operators), {"dMP", "AGG"})
        self.assertEqual(operators["dMP"]["label"], "dMP")
        self.assertEqual(operators["AGG"]["label"], "⊕")
        self.assertFalse(any(edge["source"] == "fact" and edge["target"] == "derived" for edge in graph["edges"]))


class LAFHttpRecommendationEvaluatorTests(SimpleTestCase):
    def setUp(self):
        self.request = EvaluationRequest(
            domain="cafe",
            dataset_key="mco_catalogo_real",
            strategy="D",
            preferences={"sabor": 1.0},
        )
        self.generated = GeneratedLAF1Program(
            run_id="laf1-program-http",
            text=PROGRAM,
            generated_at="2026-08-27T12:00:00-03:00",
            methodology_sha256="hash-controlado",
            products_count=1,
            facts_count=1,
            rules_count=2,
            entities=(
                {
                    "argument": "houseA",
                    "entity_id": "MCO123",
                    "entity_name": "Café de prueba",
                    "metadata": {"product_id": "MCO123"},
                },
            ),
        )

    def _evaluator(self, *, validated):
        laf1 = Mock()
        laf1.generate.return_value = self.generated
        api = Mock()
        api.build_graph.return_value = GRAPH
        evaluator = LAFHttpRecommendationEvaluator(
            FixtureRepository(settings.FIXTURE_DIR),
            laf1,
            Mock(),
            api,
            results_validated=validated,
        )
        return evaluator, api

    def test_safety_gate_does_not_publish_unvalidated_ranking(self):
        evaluator, api = self._evaluator(validated=False)

        result = evaluator.evaluate_products(self.request)

        self.assertEqual(result.evaluation_status, "pending")
        self.assertEqual(result.ranking, ())
        api.build_graph.assert_called_once()

    def test_publishes_ranking_only_when_validation_gate_is_enabled(self):
        evaluator, _api = self._evaluator(validated=True)

        result = evaluator.evaluate_products(self.request)

        self.assertEqual(result.evaluation_status, "validated")
        self.assertEqual(result.ranking[0].entity_id, "MCO123")
        self.assertEqual(result.ranking[0].final_score, 0.2)
        self.assertEqual(result.laf_graph, GRAPH)

    def test_product_ranking_uses_post_laf_multicriteria_decision(self):
        generated = GeneratedLAF1Program(
            **{
                **self.generated.__dict__,
                "entities": (
                    {"argument": "a", "entity_id": "A", "entity_name": "Producto A"},
                    {"argument": "b", "entity_id": "B", "entity_name": "Producto B"},
                ),
            }
        )
        baseline_graph = {
            "nodes": [
                {"id": "base-a", "label": "recomendar(a)", "type": "FACT", "deltaAttributes": ["0.99", "1"]},
                {"id": "base-b", "label": "recomendar(b)", "type": "FACT", "deltaAttributes": ["0.98", "1"]},
            ],
            "edges": [],
        }
        aroma_graph = {
            "nodes": [
                {"id": "aroma-a", "label": "recomendar(a)", "type": "FACT", "deltaAttributes": ["0.1", "1"]},
                {"id": "aroma-b", "label": "recomendar(b)", "type": "FACT", "deltaAttributes": ["0.8", "1"]},
            ],
            "edges": [],
        }
        sabor_graph = {
            "nodes": [
                {"id": "sabor-a", "label": "recomendar(a)", "type": "FACT", "deltaAttributes": ["0.9", "1"]},
                {"id": "sabor-b", "label": "recomendar(b)", "type": "FACT", "deltaAttributes": ["0.2", "1"]},
            ],
            "edges": [],
        }
        laf1 = Mock()
        laf1.generate.side_effect = [generated, generated, generated]
        api = Mock()
        api.build_graph.side_effect = [baseline_graph, aroma_graph, sabor_graph]
        evaluator = LAFHttpRecommendationEvaluator(
            FixtureRepository(settings.FIXTURE_DIR),
            laf1,
            Mock(),
            api,
            results_validated=True,
            product_decision_model=DECISION_MODEL,
        )
        request = EvaluationRequest(
            domain="cafe",
            dataset_key="mco_catalogo_real",
            strategy="D",
            preferences={"sabor": 1.0, "aroma": 0.33, "caducidad": 0.0},
        )

        result = evaluator.evaluate_products(request)

        self.assertEqual([entry.entity_id for entry in result.ranking], ["A", "B"])
        self.assertAlmostEqual(result.ranking[0].final_score, (0.9 + 0.33 * 0.1) / 1.33)
        self.assertEqual(result.ranking[0].metadata["decision_model"], DECISION_MODEL)
        self.assertEqual(result.ranking[0].metadata["disabled_aspects"], ["caducidad"])
        self.assertEqual(api.build_graph.call_count, 3)
        self.assertEqual(result.laf_graph, baseline_graph)

    # ---- LAF 2 multicriterio (validacion_laf2/VALIDACION_MULTICRITERIO_LAF2.md) ----

    def _laf2_service(self, conditions_by_item):
        """Simula al paso 10: una variante de programa por conjunto de preferencias."""
        def generate(request):
            lines = []
            for item, conditions in conditions_by_item.items():
                for condition, predicate in conditions.items():
                    pref = float(request.preferences.get(condition, 0.0))
                    lines.append(f"{predicate}({item}). {{0.95; {pref:.2f}}}")
            lines.append("compraBuena(X) :- precioBueno(X). {0.85; 0.50}")
            lines.append("compraBuena(X) :- tieneEnvioGratis(X). {0.85; 0.50}")
            lines.append("compraBuena(X) :- tieneCuotas(X). {0.85; 0.50}")
            lines.append("recomendar(X) :- compraBuena(X). {0.90; 0.50}")
            return GeneratedLAF2Program(
                run_id="laf2-program-mc",
                text="\n".join(lines),
                generated_at="2026-09-03T12:00:00-03:00",
                methodology_sha256="hash-controlado",
                product_id="MCO123",
                product_name="Cafe controlado",
                items_count=len(conditions_by_item),
                facts_count=len(lines) - 4,
                rules_count=4,
                entities=tuple(
                    {"argument": item, "entity_id": item.upper(), "entity_name": f"Publicacion {item}", "metadata": {}}
                    for item in conditions_by_item
                ),
            )
        service = Mock()
        service.generate.side_effect = generate
        return service

    @staticmethod
    def _graph(confidences):
        return {
            "nodes": [
                {"id": f"n-{item}", "label": f"recomendar({item})", "type": "FACT", "deltaAttributes": [str(conf), "0.5"]}
                for item, conf in confidences.items()
            ],
            "edges": [],
        }

    def test_listing_ranking_uses_multicriteria_and_skips_conditions_without_facts(self):
        laf2 = self._laf2_service({
            "a": {"precio": "precioBueno", "envio": "tieneEnvioGratis"},
            "b": {"precio": "precioBueno"},
        })
        api = Mock()
        # orden de llamadas: baseline, envio, precio (cuotas no tiene hechos -> no se llama)
        api.build_graph.side_effect = [
            self._graph({"a": 0.9, "b": 0.8}),
            self._graph({"a": 0.8}),
            self._graph({"a": 0.6, "b": 0.9}),
        ]
        evaluator = LAFHttpRecommendationEvaluator(
            FixtureRepository(settings.FIXTURE_DIR), Mock(), laf2, api,
            results_validated=True, product_decision_model=DECISION_MODEL,
        )
        request = EvaluationRequest(
            domain="cafe", dataset_key="mco_catalogo_real", strategy="D",
            selected_entity_id="MCO123", budget_min=None, budget_max=None,
            preferences={"precio": 0.5, "envio": 1.0, "cuotas": 1.0, "factura": 0.0},
        )

        result = evaluator.evaluate_listings(request)

        self.assertEqual(result.evaluation_status, "validated")
        self.assertEqual([e.entity_id for e in result.ranking], ["A", "B"])
        # cuotas sale del denominador (variante C): pesos activos = envio 1.0 + precio 0.5
        self.assertAlmostEqual(result.ranking[0].final_score, (1.0 * 0.8 + 0.5 * 0.6) / 1.5)
        self.assertAlmostEqual(result.ranking[1].final_score, (0.5 * 0.9) / 1.5)
        self.assertEqual(result.ranking[0].metadata["decision_model"], DECISION_MODEL)
        self.assertEqual(result.ranking[0].metadata["conditions_without_evidence"], ["cuotas"])
        self.assertEqual(api.build_graph.call_count, 3)
        self.assertEqual(set(result.aspect_programs), {"envio", "precio"})
        self.assertEqual(set(result.aspect_graphs), {"envio", "precio"})
        self.assertEqual(set(result.execution_payloads), {"envio", "precio"})
        self.assertEqual(result.backup_laf_graph, self._graph({"a": 0.9, "b": 0.8}))
        self.assertEqual(result.laf_graph["graphId"], "laf2-independent-conditions")
        for payload in result.execution_payloads.values():
            self.assertTrue(payload["facts"])
            self.assertTrue(all(float(fact["attributes"][1]) > 0 for fact in payload["facts"]))

    def test_listing_without_any_active_condition_stays_last_with_zero(self):
        laf2 = self._laf2_service({
            "a": {"precio": "precioBueno", "envio": "tieneEnvioGratis"},
            "b": {"precio": "precioBueno"},
        })
        api = Mock()
        api.build_graph.side_effect = [
            self._graph({"a": 0.9, "b": 0.8}),   # baseline
            self._graph({"a": 0.8}),             # envio: b no tiene el hecho
        ]
        evaluator = LAFHttpRecommendationEvaluator(
            FixtureRepository(settings.FIXTURE_DIR), Mock(), laf2, api,
            results_validated=True, product_decision_model=DECISION_MODEL,
        )
        request = EvaluationRequest(
            domain="cafe", dataset_key="mco_catalogo_real", strategy="D",
            selected_entity_id="MCO123", preferences={"precio": 0.0, "envio": 1.0},
        )

        result = evaluator.evaluate_listings(request)

        self.assertEqual([e.entity_id for e in result.ranking], ["A", "B"])
        self.assertEqual(result.ranking[1].final_score, 0.0)
        self.assertEqual(result.ranking[1].status, "not_recommended")
        self.assertEqual(result.ranking[1].position, 2)

    def test_listing_ranking_without_validation_gate_stays_pending(self):
        laf2 = self._laf2_service({"a": {"precio": "precioBueno"}})
        api = Mock()
        api.build_graph.return_value = self._graph({"a": 0.9})
        evaluator = LAFHttpRecommendationEvaluator(
            FixtureRepository(settings.FIXTURE_DIR), Mock(), laf2, api,
            results_validated=False, product_decision_model=DECISION_MODEL,
        )
        request = EvaluationRequest(
            domain="cafe", dataset_key="mco_catalogo_real", strategy="D",
            selected_entity_id="MCO123", preferences={"precio": 1.0},
        )

        result = evaluator.evaluate_listings(request)

        self.assertEqual(result.evaluation_status, "pending")
        self.assertEqual(result.ranking, ())

    def test_listing_ties_are_broken_by_baseline_confidence_not_by_id(self):
        # a y z tienen envio; z es mas barata (mas confianza en el programa
        # completo) pero su id ordena despues: el desempate por id la pondria segunda.
        laf2 = self._laf2_service({
            "a": {"precio": "precioBueno", "envio": "tieneEnvioGratis"},
            "z": {"precio": "precioBueno", "envio": "tieneEnvioGratis"},
        })
        api = Mock()
        api.build_graph.side_effect = [
            self._graph({"a": 0.70, "z": 0.90}),   # baseline: z mas barata
            self._graph({"a": 0.8, "z": 0.8}),     # envio: empate exacto
        ]
        evaluator = LAFHttpRecommendationEvaluator(
            FixtureRepository(settings.FIXTURE_DIR), Mock(), laf2, api,
            results_validated=True, product_decision_model=DECISION_MODEL,
        )
        request = EvaluationRequest(
            domain="cafe", dataset_key="mco_catalogo_real", strategy="D",
            selected_entity_id="MCO123", preferences={"precio": 0.0, "envio": 1.0},
        )

        result = evaluator.evaluate_listings(request)

        self.assertEqual([e.entity_id for e in result.ranking], ["Z", "A"])
        self.assertEqual(result.ranking[0].final_score, result.ranking[1].final_score)
        self.assertEqual([e.position for e in result.ranking], [1, 2])

