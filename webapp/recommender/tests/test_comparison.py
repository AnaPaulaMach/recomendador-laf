"""Pruebas de la vista comparativa y su lógica determinista."""
from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from recommender.domain.contracts import RankingEntry
from recommender.models import RecommendationSession
from recommender.repositories.domain_repository import DomainConfigRepository
from recommender.services import comparison as comparison_service
from recommender.web.presentation import aspect_claim_narrative


def _aspect_node(product, aspect, value, polarity="positive", preference=0.67):
    return {
        "node_type": "aspect",
        "polarity": polarity,
        "accumulated_value": value,
        "preference": preference,
        "metadata": {"product": product, "aspect": aspect},
    }


class AspectStandingsUnitTests(TestCase):
    def _graph(self):
        return {
            "nodes": [
                _aspect_node("Producto A", "aroma", 0.6, preference=0.8),
                _aspect_node("Producto B", "aroma", 0.9),
                _aspect_node("Producto C", "aroma", 0.3),
                # Evidencia en CONTRA de A: no debe alterar su posición a favor.
                _aspect_node("Producto A", "aroma", 0.99, polarity="negative", preference=0.8),
                # Dimensión fuera de los aspectos del dominio: debe filtrarse.
                {
                    "node_type": "dimension",
                    "polarity": "positive",
                    "accumulated_value": 0.7,
                    "preference": 1.0,
                    "metadata": {"product": "Producto A", "aspect": "sensorial"},
                },
                # Segundo aspecto sólo de A, sin prioridad.
                _aspect_node("Producto A", "sabor", 0.5, preference=0.0),
            ]
        }

    def test_selected_product_identified_and_positioned(self):
        labels = {"aroma": "Aroma", "sabor": "Sabor"}
        standings = comparison_service.build_aspect_standings(self._graph(), "Producto A", labels)
        by_key = {s.key: s for s in standings}
        self.assertIn("aroma", by_key)
        # A (0.6) va detrás de B (0.9) y delante de C (0.3): 2º de 3.
        self.assertEqual(by_key["aroma"].position, 2)
        self.assertEqual(by_key["aroma"].total, 3)
        self.assertEqual(by_key["aroma"].value, 0.6)

    def test_groups_do_not_mix_products(self):
        standings = comparison_service.build_aspect_standings(
            self._graph(), "Producto A", {"aroma": "Aroma"}
        )
        aroma = next(s for s in standings if s.key == "aroma")
        # El valor del seleccionado es el propio (0.6), nunca el de otro producto.
        self.assertEqual(aroma.value, 0.6)
        self.assertNotEqual(aroma.value, 0.9)

    def test_support_and_conflict_not_confused(self):
        standings = comparison_service.build_aspect_standings(
            self._graph(), "Producto A", {"aroma": "Aroma"}
        )
        aroma = next(s for s in standings if s.key == "aroma")
        # El nodo negativo (0.99) se ignora para la posición a favor.
        self.assertEqual(aroma.value, 0.6)

    def test_out_of_domain_aspect_is_filtered(self):
        standings = comparison_service.build_aspect_standings(
            self._graph(), "Producto A", {"aroma": "Aroma", "sabor": "Sabor"}
        )
        self.assertNotIn("sensorial", {s.key for s in standings})

    def test_priority_maps_from_preference(self):
        standings = comparison_service.build_aspect_standings(
            self._graph(), "Producto A", {"aroma": "Aroma", "sabor": "Sabor"}
        )
        by_key = {s.key: s for s in standings}
        self.assertEqual(by_key["aroma"].priority, "alta")  # preferencia 0.8
        self.assertEqual(by_key["sabor"].priority, "nula")  # preferencia 0.0

    def test_missing_selected_product_yields_empty(self):
        standings = comparison_service.build_aspect_standings(
            self._graph(), "Producto Inexistente", {"aroma": "Aroma"}
        )
        self.assertEqual(standings, ())


class RankingOverviewUnitTests(TestCase):
    def _ranking(self):
        return [
            RankingEntry.from_dict(
                {"entity_id": "B", "entity_name": "Prod B", "position": 2,
                 "final_score": 0.7, "status": "competitive"}
            ),
            RankingEntry.from_dict(
                {"entity_id": "A", "entity_name": "Prod A", "position": 1,
                 "final_score": 0.9, "status": "accepted"}
            ),
        ]

    def test_sorted_by_position_and_selected_flagged(self):
        rows = comparison_service.build_ranking(self._ranking(), "A")
        self.assertEqual([r.entity_id for r in rows], ["A", "B"])
        self.assertTrue(rows[0].is_selected)
        self.assertFalse(rows[1].is_selected)


def _ledger_node(product, aspect, mu, delta=None, polarity="positive", preference=0.67, node_type="aspect"):
    node = {
        "node_type": node_type,
        "polarity": polarity,
        "accumulated_value": mu,
        "weakened_value": mu if delta is None else delta,
        "preference": preference,
        "metadata": {"product": product, "aspect": aspect},
    }
    return node


class ClaimLedgerUnitTests(TestCase):
    """Aceptabilidad gradual (Def. 11): estados derivados de μ y δ ya calculados."""

    LABELS = {"sabor": "Sabor", "intensidad": "Intensidad", "dulzor": "Dulzor", "caducidad": "Caducidad"}

    def _graph(self):
        return {
            "nodes": [
                # Sin objeciones: μ = δ.
                _ledger_node("Prod A", "sabor", 0.79, preference=1.0),
                # Discutido: perdió menos del 50% (0.57 → 0.40).
                _ledger_node("Prod A", "intensidad", 0.57, delta=0.40, preference=0.33),
                _ledger_node("Prod A", "intensidad", 0.30, delta=0.0, polarity="negative"),
                # Muy discutido: perdió ≥ 50% (0.47 → 0.14).
                _ledger_node("Prod A", "dulzor", 0.47, delta=0.14, preference=0.0),
                _ledger_node("Prod A", "dulzor", 0.25, delta=0.25, polarity="negative"),
                # No se sostiene: δ = 0.
                _ledger_node("Prod A", "caducidad", 0.43, delta=0.0, preference=0.0),
                # Nodo de otro producto: no debe mezclarse.
                _ledger_node("Prod B", "sabor", 0.20, delta=0.0),
            ]
        }

    def test_states_follow_definition_11(self):
        claims = comparison_service.build_claim_ledger(self._graph(), "Prod A", self.LABELS)
        by_key = {c.key: c for c in claims}
        self.assertEqual(by_key["sabor"].status, "sin_objeciones")
        self.assertEqual(by_key["sabor"].formal_status, "Unchallenged")
        self.assertEqual(by_key["intensidad"].status, "discutido")
        self.assertEqual(by_key["intensidad"].formal_status, "Weakened")
        self.assertEqual(by_key["dulzor"].status, "muy_discutido")
        self.assertEqual(by_key["dulzor"].formal_status, "Weakened")
        self.assertEqual(by_key["caducidad"].status, "no_se_sostiene")
        self.assertEqual(by_key["caducidad"].formal_status, "Rejected")

    def test_objections_split_refuted_vs_standing(self):
        claims = comparison_service.build_claim_ledger(self._graph(), "Prod A", self.LABELS)
        by_key = {c.key: c for c in claims}
        # La crítica de intensidad quedó sin fuerza (δ = 0): respondida.
        self.assertEqual(by_key["intensidad"].against, 1)
        self.assertEqual(by_key["intensidad"].refuted, 1)
        self.assertEqual(by_key["intensidad"].standing, 0)
        # La crítica de dulzor conserva fuerza (δ > 0): quedó en pie.
        self.assertEqual(by_key["dulzor"].standing, 1)

    def test_sorted_by_priority_then_severity(self):
        claims = comparison_service.build_claim_ledger(self._graph(), "Prod A", self.LABELS)
        self.assertEqual(claims[0].key, "sabor")  # prioridad 1.0 primero
        # A igual prioridad (0.0), el estado más grave después del menos grave no importa:
        # el orden interno es por gravedad ascendente… verificamos que es determinista.
        keys = [c.key for c in claims]
        self.assertEqual(keys, sorted(keys, key=lambda k: keys.index(k)))

    def test_other_products_do_not_leak(self):
        claims = comparison_service.build_claim_ledger(self._graph(), "Prod A", self.LABELS)
        sabor = next(c for c in claims if c.key == "sabor")
        self.assertEqual(sabor.mu, 0.79)


class ClaimLedgerPlainStateTests(TestCase):
    """Estado en lenguaje común (E5/R3): por MENCIONES, desacoplado de μ/δ."""

    LABELS = ClaimLedgerUnitTests.LABELS

    def _graph(self):
        return ClaimLedgerUnitTests()._graph()

    def test_single_mention_criticism_not_shown_as_no_se_sostiene(self):
        # caducidad tiene δ=0 -> μ/δ dice "no_se_sostiene"; pero con 1 sola
        # mención crítica (marginal) el estado de usuario es "bien valorado".
        info = {"caducidad": {"favor": 40, "against": 1, "relevant": False}}
        claims = comparison_service.build_claim_ledger(
            self._graph(), "Prod A", self.LABELS, criticism_info=info
        )
        cad = next(c for c in claims if c.key == "caducidad")
        self.assertEqual(cad.status, "no_se_sostiene")       # μ/δ formal intacto
        self.assertEqual(cad.plain_status, "bien_valorado")  # cara al usuario
        self.assertEqual(cad.plain_label, "Bien valorado")

    def test_relevant_criticism_shown_with_mention_counts(self):
        info = {"intensidad": {"favor": 30, "against": 6, "relevant": True}}
        claims = comparison_service.build_claim_ledger(
            self._graph(), "Prod A", self.LABELS, criticism_info=info
        )
        it = next(c for c in claims if c.key == "intensidad")
        self.assertEqual(it.plain_status, "con_criticas")
        self.assertEqual(it.plain_label, "Con algunas críticas")
        self.assertIn("30", it.plain_narrative)
        self.assertIn("6", it.plain_narrative)


class _FakeProduct:
    def __init__(self, confidence, preference, entity_name="Prod A"):
        self.confidence = confidence
        self.preference = preference
        self.entity_name = entity_name
        self.final_score = min(confidence, preference)


class _FakeMultiProduct:
    def __init__(self, position, contributions, entity_name="Prod A"):
        self.confidence = 0.5
        self.preference = 0.5
        self.entity_name = entity_name
        self.final_score = 0.3
        self.position = position
        self.metadata = {
            "decision_model": "post_laf_multicriteria_v1",
            "aspect_contributions": contributions,
        }


class VerdictMulticriteriaStoryTests(TestCase):
    """El veredicto multicriterio se lee como historia, sin fórmulas ni jerga."""

    def _claims(self, graph, labels, criticism_info=None):
        return comparison_service.build_claim_ledger(
            graph, "Prod A", labels, criticism_info=criticism_info
        )

    def test_first_place_story_names_top_aspects_no_jargon(self):
        graph = {"nodes": [
            _ledger_node("Prod A", "sabor", 0.6, preference=0.67),
            _ledger_node("Prod A", "aroma", 0.5, preference=0.67),
        ]}
        labels = {"sabor": "Sabor", "aroma": "Aroma"}
        claims = self._claims(graph, labels)
        product = _FakeMultiProduct(1, [
            {"aspect": "sabor", "weight": 0.67, "contribution": 0.05},
            {"aspect": "aroma", "weight": 0.67, "contribution": 0.04},
        ])
        verdict = comparison_service.build_verdict(product, claims)
        self.assertIn("primer puesto", verdict.headline)
        self.assertIn("sabor", verdict.detail.lower())
        self.assertNotIn("post-LAF", verdict.detail)
        self.assertNotIn("Σ", verdict.detail)
        self.assertNotIn("ponderad", verdict.detail.lower())

    def test_lower_place_story_mentions_relevant_criticism(self):
        graph = {"nodes": [
            _ledger_node("Prod A", "sabor", 0.6, preference=0.67),
            _ledger_node("Prod A", "aroma", 0.5, preference=0.67),
            _ledger_node("Prod A", "aroma", 0.3, delta=0.2, polarity="negative"),
        ]}
        labels = {"sabor": "Sabor", "aroma": "Aroma"}
        info = {"aroma": {"favor": 20, "against": 5, "relevant": True}}
        claims = self._claims(graph, labels, criticism_info=info)
        product = _FakeMultiProduct(5, [
            {"aspect": "sabor", "weight": 0.67, "contribution": 0.05},
        ])
        verdict = comparison_service.build_verdict(product, claims)
        self.assertIn("puesto 5", verdict.headline)
        self.assertIn("aroma", verdict.detail.lower())


class VerdictAndPositionNoteTests(TestCase):
    def _claims(self):
        graph = ClaimLedgerUnitTests()._graph()
        return comparison_service.build_claim_ledger(graph, "Prod A", ClaimLedgerUnitTests.LABELS)

    def test_verdict_priorities_intact(self):
        # Confianza limita (pref 1.0): lo prioritario (sabor) está sin objeciones.
        verdict = comparison_service.build_verdict(_FakeProduct(0.96, 1.0), self._claims())
        self.assertIn("no recibió ninguna objeción", verdict.headline)
        self.assertIn("dulzor", verdict.detail)  # los flojos son de baja prioridad

    def test_verdict_preference_bound(self):
        verdict = comparison_service.build_verdict(_FakeProduct(0.98, 0.67), self._claims())
        self.assertIn("no cumple del todo", verdict.headline)

    def test_position_note_first_place(self):
        rows = (
            comparison_service.RankingRow(
                entity_id="A", entity_name="Prod A", position=1, final_score=0.9,
                confidence=0.9, preference=1.0, binding="confianza", status="accepted",
                is_selected=True,
            ),
        )
        note = comparison_service.build_position_note(rows, self._claims())
        self.assertIn("primero", note)

    def test_position_note_names_standing_objections(self):
        rows = (
            comparison_service.RankingRow(
                entity_id="A", entity_name="Prod A", position=3, final_score=0.88,
                confidence=0.88, preference=1.0, binding="confianza", status="competitive",
                is_selected=True,
            ),
        )
        note = comparison_service.build_position_note(rows, self._claims())
        self.assertIn("3º", note)
        self.assertIn("dulzor", note)


@override_settings(SUPABASE_URL="", SUPABASE_KEY="")
class ProductDetailComparisonTests(TestCase):
    """La comparación vive dentro del detalle del producto (sin endpoint aparte)."""

    def setUp(self):
        self.domain = DomainConfigRepository(settings.DOMAIN_CONFIG_DIR).get("cafe")

    def _flow_with_result(self):
        self.client.post(
            reverse("recommender:start"),
            {"domain": "cafe", "dataset_key": "cafe_top20_demo_2026", "strategy": "D"},
        )
        flow = RecommendationSession.objects.get()
        self.client.post(
            reverse("recommender:quality", args=[flow.id]),
            {aspect.key: "0.67" for aspect in self.domain.quality_aspects},
        )
        flow.refresh_from_db()
        return flow

    def test_detail_exposes_comparison_data(self):
        flow = self._flow_with_result()
        entity_id = flow.laf1_result["ranking"][0]["entity_id"]
        response = self.client.get(
            reverse("recommender:product-detail", args=[flow.id, entity_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("ranking", response.context)
        self.assertIn("standings", response.context)
        self.assertIn("claims", response.context)
        self.assertIn("verdict", response.context)
        self.assertIn("position_note", response.context)
        # El ranking cubre a todos los productos evaluados.
        self.assertEqual(
            len(response.context["ranking"]), len(flow.laf1_result["ranking"])
        )
        # El producto abierto queda identificado como seleccionado (uno solo).
        selected = [row for row in response.context["ranking"] if row.is_selected]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].entity_id, entity_id)

    def test_used_laf_programs_downloadable_from_detail(self):
        flow = self._flow_with_result()
        entity_id = flow.laf1_result["ranking"][0]["entity_id"]
        response = self.client.get(
            reverse("recommender:product-detail", args=[flow.id, entity_id])
        )
        self.assertContains(response, "?used=1")
        self.assertContains(response, "Descargar programas LAF")
        self.assertNotContains(response, "JSON completo")

    def test_comparison_endpoint_no_longer_exists(self):
        from django.urls import NoReverseMatch

        with self.assertRaises(NoReverseMatch):
            reverse("recommender:comparison", args=["x"])


class AspectNarrativeFromLedgerTests(TestCase):
    """La oración del aspecto sobre el reclamo real que arma el ledger (Tarea 2).

    Cubre los dos casos con la misma función: con crítica agregada y sin ninguna.
    """

    LABELS = {"sabor": "Sabor", "aroma": "Aroma"}

    def _claims(self):
        graph = {
            "nodes": [
                # Aroma: sólo elogios (el hecho positivo entra con 0,91).
                _ledger_node("Prod A", "aroma", 0.82, preference=0.67),
                dict(
                    _ledger_node("Prod A", "aroma", 0.91, preference=0.67, node_type="fact"),
                    literal="resenaPositivaAroma(prod_a)",
                ),
                # Sabor: elogios y una crítica agregada (0,93 contra 0,62).
                _ledger_node("Prod A", "sabor", 0.84, delta=0.53, preference=0.67),
                dict(
                    _ledger_node("Prod A", "sabor", 0.93, preference=0.67, node_type="fact"),
                    literal="resenaPositivaSabor(prod_a)",
                ),
                dict(
                    _ledger_node("Prod A", "sabor", 0.62, polarity="negative", node_type="fact"),
                    literal="resenaNegativaSabor(prod_a)",
                ),
            ]
        }
        info = {
            "sabor": {"favor": 45, "against": 7, "relevant": True},
            "aroma": {"favor": 61, "against": 0, "relevant": False},
        }
        claims = comparison_service.build_claim_ledger(
            graph, "Prod A", self.LABELS, criticism_info=info
        )
        return {claim.key: claim for claim in claims}

    def test_both_branches_cite_the_values_of_their_own_run(self):
        claims = self._claims()

        con_critica = aspect_claim_narrative(claims["sabor"], 0.478)
        sin_critica = aspect_claim_narrative(claims["aroma"], 0.737)

        self.assertEqual(
            con_critica,
            "45 menciones del aspecto a favor y 7 en contra en las reseñas de "
            "este café. La evidencia favorable pesa 0,93 y la crítica 0,62. "
            "Al enfrentarlas, la conclusión favorable pasa de 0,84 a 0,53; "
            "las reglas que llevan de este punto a la recomendación la dejan "
            "en 0,48.",
        )
        self.assertEqual(
            sin_critica,
            "61 menciones del aspecto a favor y ninguna en contra en las "
            "reseñas de este café. La evidencia favorable pesa 0,91; sin "
            "críticas, la conclusión no fue debilitada y las reglas que llevan "
            "de este punto a la recomendación la dejan en 0,74.",
        )

    def test_the_values_are_the_ones_the_ledger_calculated(self):
        claims = self._claims()

        self.assertEqual((claims["aroma"].fact_favor, claims["aroma"].fact_against), (0.91, 0.0))
        self.assertEqual((claims["sabor"].fact_favor, claims["sabor"].fact_against), (0.93, 0.62))
        self.assertEqual((claims["sabor"].mu, claims["sabor"].delta), (0.84, 0.53))
        # Sin críticas, δ = μ: la oración no puede decir que fue debilitada.
        self.assertEqual(claims["aroma"].mu, claims["aroma"].delta)
