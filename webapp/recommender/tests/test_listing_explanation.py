"""La vista «Ver por qué» del ranking de publicaciones (LAF 2).

Los números que muestra tienen que salir del mismo ``EvaluationResult`` que
produjo el orden. Para eso estas pruebas construyen un resultado multicriterio
real -- evaluador de producción con un cliente de API doble, como en
``test_laf_api`` -- y después leen la vista.

Perfil neutro = el valor inicial de cada control del formulario de compra
(``forms.py``: 0,67 en todas las condiciones ofrecidas).
"""
from unittest.mock import Mock

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from recommender.domain.contracts import EvaluationRequest
from recommender.models import RecommendationSession
from recommender.repositories.fixture_repository import FixtureRepository
from recommender.services.evaluators import LAFHttpRecommendationEvaluator
from recommender.services.laf2_programs import (
    GeneratedLAF2Program,
    LAF2ProgramService,
)
from recommender.services.post_laf_decision import DECISION_MODEL
from recommender.web import presentation


NEUTRAL = 0.67

# Publicación -> condiciones que declara, con el hecho que genera el paso 10.
# `garantia` no aparece en ninguna: es el caso "condición activa sin evidencia
# en este producto" (variante C, VALIDACION_MULTICRITERIO_LAF2.md §3.1).
LISTINGS = {
    "a": {
        "precio": "precioBueno",
        "envio": "tieneEnvioGratis",
        "tienda_oficial": "esTiendaOficial",
        "descuento": "tieneDescuento",
    },
    "b": {"precio": "precioBueno", "envio": "tieneEnvioGratis"},
    "c": {"precio": "precioBueno"},
}

ITEM_DATA = {
    "a": {"price": 139.0, "has_free_shipping": True, "is_official_store": True,
          "has_discount": True, "discount_pct": 0.223, "warranty": "No informada"},
    "b": {"price": 299.0, "has_free_shipping": True, "is_official_store": False,
          "has_discount": False, "discount_pct": 0.0, "warranty": "1 mes"},
    "c": {"price": 447.0, "has_free_shipping": False, "is_official_store": False,
          "has_discount": False, "discount_pct": 0.0, "warranty": "No informada"},
}

# Confianza post-conflicto del `recomendar` de cada corrida por condición.
CONDITION_CONFIDENCE = {
    "precio": {"a": 0.727, "b": 0.512, "c": 0.300},
    "envio": {"a": 0.727, "b": 0.727},
    "tienda_oficial": {"a": 0.727},
    "descuento": {"a": 0.727},
}
BASELINE_CONFIDENCE = {"a": 0.940, "b": 0.860, "c": 0.300}


def _program(preferences):
    """Programa LAF 2 de una variante, con el formato que acepta el parser."""
    lines = []
    for item, conditions in LISTINGS.items():
        for condition, predicate in conditions.items():
            weight = float(preferences.get(condition, 0.0))
            lines.append(f"{predicate}({item}). {{0.95; {weight:.2f}}}")
    for predicate in (
        "precioBueno",
        "tieneEnvioGratis",
        "esTiendaOficial",
        "tieneDescuento",
        "tieneGarantiaLarga",
    ):
        lines.append(f"compraBuena(X) :- {predicate}(X). {{0.85; 0.50}}")
    lines.append("recomendar(X) :- compraBuena(X). {0.90; 0.50}")
    return GeneratedLAF2Program(
        run_id="laf2-program-explicacion",
        text="\n".join(lines),
        generated_at="2026-09-10T12:00:00-03:00",
        methodology_sha256="hash-controlado",
        product_id="MLM194336",
        product_name="Café controlado",
        items_count=len(LISTINGS),
        facts_count=sum(len(v) for v in LISTINGS.values()),
        rules_count=6,
        entities=tuple(
            {
                "argument": item,
                "entity_id": item.upper(),
                "entity_name": f"Publicación {item}",
                "metadata": {
                    "product_id": "MLM194336",
                    "seller": f"Vendedor {item}",
                    "installments": "No informadas",
                    "shipping": (
                        "Gratis" if ITEM_DATA[item]["has_free_shipping"]
                        else "No informado"
                    ),
                    **ITEM_DATA[item],
                },
            }
            for item in LISTINGS
        ),
    )


def _conclusions(confidences):
    """Grafo mínimo: sólo las conclusiones `recomendar` de esa corrida."""
    return {
        "nodes": [
            {
                "id": f"n-{item}",
                "label": f"recomendar({item})",
                "type": "FACT",
                "deltaAttributes": [str(value), "1"],
            }
            for item, value in confidences.items()
        ],
        "edges": [],
    }


def _derivation(condition, predicate, item, confidence):
    """Corrida de una condición con su derivación completa, como la del motor."""
    return {
        "graphId": f"laf2-{condition}",
        "nodes": [
            {"id": f"{condition}-hecho-{item}", "label": f"{predicate}({item})",
             "type": "FACT", "sourceKey": f"FACT|{predicate}|{item}",
             "deltaAttributes": ["0.95"]},
            {"id": f"{condition}-regla-compra",
             "label": f"compraBuena(X) :- {predicate}(X).", "type": "RULE",
             "deltaAttributes": ["0.85"]},
            {"id": f"{condition}-compra-{item}", "label": f"compraBuena({item})",
             "type": "FACT", "deltaAttributes": ["0.8075"]},
            {"id": f"{condition}-regla-rec",
             "label": "recomendar(X) :- compraBuena(X).", "type": "RULE",
             "deltaAttributes": ["0.90"]},
            {"id": f"n-{item}", "label": f"recomendar({item})", "type": "FACT",
             "deltaAttributes": [str(confidence), "1"]},
        ],
        "edges": [
            {"from": f"{condition}-hecho-{item}", "to": f"{condition}-compra-{item}",
             "kind": "SUPPORT"},
            {"from": f"{condition}-regla-compra", "to": f"{condition}-compra-{item}",
             "kind": "SUPPORT"},
            {"from": f"{condition}-compra-{item}", "to": f"n-{item}", "kind": "SUPPORT"},
            {"from": f"{condition}-regla-rec", "to": f"n-{item}", "kind": "SUPPORT"},
        ],
    }


class ListingExplanationTests(TestCase):
    """Contrato de la explicación: los números son los del ranking."""

    def setUp(self):
        self.preferences = {
            key: NEUTRAL
            for key in ("precio", "descuento", "garantia", "tienda_oficial", "envio")
        }
        self.preferences["cuotas"] = 0.0  # la persona la puso en «No me importa»
        self.result = self._evaluate(self.preferences)
        self.flow = RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="mlm_dataset_real",
            strategy="D",
            stage=RecommendationSession.Stage.LISTING_RANKING,
            selected_product_id="MLM194336",
            selected_product_name="Café controlado",
            purchase_preferences=self.preferences,
            laf2_result=self.result.to_dict(),
        )

    def _evaluate(self, preferences):
        service = Mock()
        service.generate.side_effect = lambda request: _program(request.preferences)
        api = Mock()
        # Orden de llamadas: baseline y después las condiciones activas ordenadas
        # alfabéticamente. `garantia` no tiene hechos, así que no se la llama.
        graphs = [_conclusions(BASELINE_CONFIDENCE)]
        for condition in sorted(
            key for key, weight in preferences.items() if float(weight) > 0
        ):
            scores = CONDITION_CONFIDENCE.get(condition)
            if not scores:
                continue
            if len(scores) == 1:
                item, confidence = next(iter(scores.items()))
                predicate = LISTINGS[item][condition]
                graphs.append(_derivation(condition, predicate, item, confidence))
            else:
                graphs.append(_conclusions(scores))
        api.build_graph.side_effect = graphs
        evaluator = LAFHttpRecommendationEvaluator(
            FixtureRepository(settings.FIXTURE_DIR),
            Mock(),
            service,
            api,
            results_validated=True,
            product_decision_model=DECISION_MODEL,
        )
        return evaluator.evaluate_listings(
            EvaluationRequest(
                domain="cafe",
                dataset_key="mlm_dataset_real",
                strategy="D",
                selected_entity_id="MLM194336",
                preferences=preferences,
            )
        )

    def _explanation(self, entity_id):
        response = self.client.get(
            reverse("recommender:explanation", args=[self.flow.id]),
            {"entity_id": entity_id},
        )
        self.assertEqual(response.status_code, 200)
        return response

    # -- la fórmula mostrada reproduce el puntaje del ranking ------------------

    def test_shown_formula_reproduces_the_ranking_score_of_every_listing(self):
        self.assertEqual(self.result.evaluation_status, "validated")
        self.assertTrue(self.result.ranking)
        for entry in self.result.ranking:
            with self.subTest(publicacion=entry.entity_id):
                breakdown = self._explanation(entry.entity_id).context["breakdown"]
                self.assertTrue(breakdown.is_multicriteria)
                self.assertTrue(breakdown.weights_total > 0)
                # Σ(peso × resultado LAF) ÷ Σpesos == el puntaje que ordenó.
                # La cuenta se hace con los valores tal como se muestran (peso
                # con 2 decimales, resultado LAF con 3), así que reproduce el
                # puntaje a esa precisión; el valor exacto es el de la fila
                # «Puntaje», que viene del ranking. Medido sobre datos reales en
                # `validacion_laf2/explicacion_web_real.py` (desvío ≤ 0,000225).
                self.assertAlmostEqual(
                    breakdown.weighted_total / breakdown.weights_total,
                    entry.final_score,
                    delta=5e-4,
                )
                self.assertEqual(breakdown.final_score, round(entry.final_score, 3))

    def test_the_written_equation_closes_with_the_ranking_score(self):
        for entry in self.result.ranking:
            with self.subTest(publicacion=entry.entity_id):
                response = self._explanation(entry.entity_id)
                equation = response.context["score_equation"]
                esperado = f"{entry.final_score:.2f}".replace(".", ",")
                self.assertTrue(equation.startswith("Puntaje = ["))
                self.assertTrue(
                    equation.endswith(f"= {esperado}"),
                    f"la fórmula termina en otro valor: {equation}",
                )
                self.assertContains(response, "Puntaje = [")

    # -- ninguna condición con peso 0 entra en la fórmula ---------------------

    def test_zero_weight_conditions_are_listed_but_never_enter_the_formula(self):
        response = self._explanation(self.result.ranking[0].entity_id)
        breakdown = response.context["breakdown"]
        rows = response.context["reason_rows"]

        self.assertNotIn("cuotas", [row.key for row in breakdown.contributions])
        for row in breakdown.contributions:
            self.assertGreater(row.weight, 0)
        disabled = [row for row in rows if row["state"] == "no_me_importa"]
        self.assertEqual([row["key"] for row in disabled], ["cuotas"])
        for row in disabled:
            self.assertEqual(row["weight"], 0.0)
            self.assertIsNone(row["laf_score"])
        # Se ve, con su nivel legible, pero no aparece entre los términos.
        self.assertContains(response, "No me importa")
        self.assertNotIn(
            "cuotas",
            [row["key"] for row in rows if row["state"] == "participa"],
        )
        # El divisor es exactamente la suma de los pesos que participaron.
        self.assertAlmostEqual(
            breakdown.weights_total,
            sum(row["weight"] for row in rows if row["state"] == "participa"),
            places=9,
        )

    def test_a_condition_without_evidence_in_the_product_leaves_the_divisor(self):
        response = self._explanation(self.result.ranking[0].entity_id)
        rows = response.context["reason_rows"]
        sin_evidencia = [row for row in rows if row["state"] == "sin_evidencia"]

        self.assertEqual([row["key"] for row in sin_evidencia], ["garantia"])
        self.assertEqual(
            self.result.ranking[0].metadata["conditions_without_evidence"],
            ["garantia"],
        )
        self.assertNotIn(
            "garantia",
            [row.key for row in response.context["breakdown"].contributions],
        )
        self.assertContains(response, "ninguna publicación de este producto la informa")

    # -- el dato de la publicación, sin ceros que parezcan medidas ------------

    def test_a_condition_the_listing_does_not_declare_never_shows_zero(self):
        # La publicación C sólo declara precio.
        response = self._explanation("C")
        rows = {row["key"]: row for row in response.context["reason_rows"]}

        self.assertEqual(rows["envio"]["laf_score"], 0.0)
        self.assertEqual(
            rows["envio"]["laf_display"],
            presentation.LISTING_CONDITION_MISSING,
        )
        self.assertContains(response, "sin información en la publicación")
        self.assertEqual(rows["precio"]["laf_display"], "0,300")
        # El dato mostrado es el que declara la publicación, no un adjetivo.
        self.assertEqual(rows["precio"]["value"], "$447")
        self.assertEqual(rows["envio"]["value"], "No informado")
        self.assertEqual(rows["tienda_oficial"]["value"], "No informado")

    def test_declared_values_come_from_the_listing_row(self):
        rows = {
            row["key"]: row
            for row in self._explanation("A").context["reason_rows"]
        }

        self.assertEqual(rows["precio"]["value"], "$139")
        self.assertEqual(rows["envio"]["value"], "Gratis")
        self.assertEqual(rows["tienda_oficial"]["value"], "Sí")
        self.assertEqual(rows["descuento"]["value"], "Sí, 22 %")

    def test_the_three_steps_carry_the_real_values(self):
        response = self._explanation("A")
        steps = response.context["process_steps"]

        self.assertEqual(steps["listings"], len(self.result.ranking))
        self.assertEqual(steps["position"], 1)
        self.assertEqual(steps["conditions"], 4)
        self.assertEqual(
            steps["condition_names"].split(", ").sort(),
            ["descuento", "envío", "precio", "tienda oficial"].sort(),
        )
        self.assertContains(response, "Partimos de 3 publicaciones del producto")
        self.assertContains(response, "Miramos las condiciones que te importan")
        self.assertContains(response, "Quedó 1º de 3")

    def test_the_closing_sentence_never_claims_a_single_condition_when_there_are_four(self):
        # Con el perfil neutro las cuatro condiciones dan el mismo resultado:
        # la frase de productos diría «la única característica que elegiste».
        # La frase cita el resultado LAF (el número que muestra cada fila del
        # panel), no el aporte peso × resultado, que el panel sólo agrega por
        # nivel de importancia: antes decía «0,487 cada una», un valor que no
        # aparecía en ninguna fila (corregido el 2026-09-10).
        empatadas = self._explanation("A").context["score_story"]
        self.assertEqual(
            empatadas,
            "Quedó 1º de 3. Las 4 condiciones que elegiste dieron el mismo "
            "resultado LAF (0,727), así que el puntaje es ese mismo valor: "
            "cuando todas coinciden, los pesos no cambian el promedio.",
        )
        distintas = self._explanation("C").context["score_story"]
        self.assertIn("El resultado LAF más alto es el de precio (0,300)", distintas)
        self.assertNotIn("única condición", distintas)

    # -- desempate declarado --------------------------------------------------

    def test_the_tie_break_is_declared_only_when_there_is_a_tie(self):
        solo_envio = self._evaluate(
            {**{key: 0.0 for key in self.preferences}, "envio": 1.0}
        )
        self.flow.laf2_result = solo_envio.to_dict()
        self.flow.purchase_preferences = {
            **{key: 0.0 for key in self.preferences},
            "envio": 1.0,
        }
        self.flow.save()

        empatada = self._explanation("A")
        self.assertEqual(solo_envio.ranking[0].final_score, solo_envio.ranking[1].final_score)
        self.assertIn("Empata en puntaje", empatada.context["tie_note"])
        self.assertContains(empatada, "confianza del programa completo")
        # A igual puntaje, primero la de mayor confianza del programa completo.
        self.assertEqual(
            [entry.entity_id for entry in solo_envio.ranking[:2]],
            ["A", "B"],
        )

        self.flow.laf2_result = self.result.to_dict()
        self.flow.purchase_preferences = self.preferences
        self.flow.save()
        self.assertEqual(self._explanation("A").context["tie_note"], "")

    # -- grafo por condición: la corrida guardada, sin recalcular -------------

    def test_the_condition_graph_returns_the_stored_run_of_that_condition(self):
        response = self.client.get(
            reverse("recommender:listing-condition-graph", args=[self.flow.id]),
            {"entity_id": "A", "aspect": "descuento"},
        )
        payload = response.json()
        literals = [node["literal"] for node in payload["nodes"]]

        self.assertEqual(payload["source"], "stored_evaluation")
        self.assertEqual(payload["aspect"], "descuento")
        self.assertIn("tieneDescuento(a)", literals)
        self.assertIn("recomendar(a)", literals)
        # La raíz es el mismo nodo que aportó el número de la fila.
        self.assertEqual(
            payload["root_id"],
            self.result.ranking[0].metadata["condition_node_ids"]["descuento"],
        )
        etiquetas = {
            node["literal"]: node["metadata"].get("graph_label")
            for node in payload["nodes"]
        }
        self.assertEqual(etiquetas["tieneDescuento(a)"], "Tiene descuento")
        self.assertEqual(etiquetas["recomendar(a)"], "Resultado de esta condición")

    def test_the_condition_graph_is_empty_when_there_is_no_stored_run(self):
        for parametros in (
            {"entity_id": "A", "aspect": "garantia"},
            {"entity_id": "A", "aspect": ""},
            {"entity_id": "no-existe", "aspect": "descuento"},
        ):
            with self.subTest(**parametros):
                payload = self.client.get(
                    reverse(
                        "recommender:listing-condition-graph", args=[self.flow.id]
                    ),
                    parametros,
                ).json()
                self.assertEqual(payload["nodes"], [])
                self.assertEqual(payload["total_nodes"], 0)

    def test_only_conditions_with_a_stored_run_open_their_graph(self):
        response = self._explanation("A")
        rows = {row["key"]: row for row in response.context["reason_rows"]}

        self.assertTrue(rows["descuento"]["node_id"])
        self.assertEqual(rows["garantia"]["node_id"], "")
        self.assertEqual(rows["cuotas"]["node_id"], "")
        self.assertContains(response, 'data-aspect-key="descuento"')
        self.assertNotContains(response, 'data-aspect-key="cuotas"')
        # Reutiliza el componente y la leyenda de productos.
        self.assertContains(response, "data-aspect-panel")
        self.assertContains(response, "data-aspect-graph-url")
        for pieza in ("<strong>Hecho</strong>", "<strong>Regla</strong>",
                      "<strong>dMP</strong>", "<strong>CA</strong>"):
            self.assertContains(response, pieza)

    # -- la explicación no altera el orden -----------------------------------

    def test_the_listing_order_is_the_one_the_evaluator_produced(self):
        stored = [entry.entity_id for entry in self.result.ranking]
        ranking_view = self.client.get(
            reverse("recommender:listing-ranking", args=[self.flow.id])
        )
        comparison = self._explanation("A").context["ranking"]

        self.assertEqual(
            [item.entity_id for item in ranking_view.context["result"].ranking],
            stored,
        )
        self.assertEqual([row.entity_id for row in comparison], stored)
        self.assertEqual(stored, ["A", "B", "C"])
        self.assertEqual(
            [entry.position for entry in self.result.ranking], [1, 2, 3]
        )


class ListingConditionCatalogueTests(TestCase):
    """Las condiciones que nombra la presentación son las del generador."""

    def test_presentation_and_program_service_share_the_condition_keys(self):
        self.assertEqual(
            set(presentation.LISTING_CONDITION_FLAGS),
            set(LAF2ProgramService.CONDITION_FLAGS),
        )
        self.assertEqual(
            presentation.LISTING_CONDITION_FLAGS,
            LAF2ProgramService.CONDITION_FLAGS,
        )
        self.assertEqual(
            set(presentation.LISTING_CONDITION_SHORT),
            set(LAF2ProgramService.CONDITION_FLAGS),
        )
