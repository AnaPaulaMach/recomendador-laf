"""Correcciones tras la evaluación heurística de Nielsen (ADR-006).

Cada prueba fija una de las correcciones que la evaluación pidió, para que no
vuelvan a perderse como se perdió la ecuación instanciada. Nada de esto toca el
cálculo: son rótulos, estados vacíos, encabezados de descarga y plantillas.
"""
from django.test import SimpleTestCase, TestCase
from django.template.loader import render_to_string
from pathlib import Path


def io_read(ruta: str) -> str:
    """El texto de una plantilla del repo, para fijar una decisión de copy."""
    return (Path(__file__).resolve().parents[2] / ruta).read_text(encoding="utf-8")

from recommender.domain.contracts import RankingEntry
from recommender.web import presentation


class MarketplaceItemUrlTests(SimpleTestCase):
    """U30: la dirección de la publicación se arma desde su `item_id`."""

    def test_builds_the_article_url_from_the_item_id(self):
        self.assertEqual(
            presentation.marketplace_item_url("MLM2107019722"),
            "https://articulo.mercadolibre.com.mx/MLM-2107019722",
        )

    def test_an_identifier_that_is_not_mlm_gets_no_link(self):
        for value in ("", None, "publicacion-unica", "ABC123", "MLM"):
            with self.subTest(valor=value):
                self.assertEqual(presentation.marketplace_item_url(value), "")

    def test_the_generic_category_destination_is_no_longer_the_first_choice(self):
        result = presentation.EvaluationResult.from_dict(
            {
                "domain": "cafe",
                "dataset_key": "fixture",
                "ranking": [
                    {
                        "entity_id": "MLM2107019722",
                        "entity_name": "Publicación",
                        "position": 1,
                        "final_score": 0.5,
                        "metadata": {"price": 139.0},
                    }
                ],
            }
        )
        salida = presentation.attach_primary_copy(result, include_purchase_links=True)
        entry = salida.ranking[0]
        self.assertEqual(
            entry.metadata["purchase_url"],
            "https://articulo.mercadolibre.com.mx/MLM-2107019722",
        )
        self.assertFalse(entry.metadata["purchase_url_is_fallback"])
        self.assertNotEqual(
            entry.metadata["purchase_url"], presentation.MARKETPLACE_FALLBACK_URL
        )


class ListingTitleTests(SimpleTestCase):
    """U29: el id crudo del vendedor no es el rótulo de la fila."""

    def _ranked(self, position, price):
        return presentation.EvaluationResult.from_dict(
            {
                "domain": "cafe",
                "dataset_key": "fixture",
                "ranking": [
                    {
                        "entity_id": "MLM2528199353",
                        "entity_name": "Publicación",
                        "position": position,
                        "final_score": 0.4,
                        "metadata": {"price": price, "seller": "Vendedor 272093102"},
                    }
                ],
            }
        )

    def test_the_row_is_named_by_position_and_price(self):
        salida = presentation.attach_primary_copy(
            self._ranked(4, 426.55), include_purchase_links=True
        )
        entry = salida.ranking[0]
        self.assertEqual(entry.metadata["listing_title"], "Publicación 4 · $426,55")
        self.assertEqual(entry.metadata["item_id_display"], "MLM2528199353")

    def test_the_raw_seller_id_is_not_the_visible_label(self):
        salida = presentation.attach_primary_copy(
            self._ranked(1, 139.0), include_purchase_links=True
        )
        self.assertNotIn("272093102", salida.ranking[0].metadata["listing_title"])


class AspectLabelTests(SimpleTestCase):
    """U12: `tamano` se escribe como se escribe en el paso 1."""

    def test_every_quality_aspect_has_a_readable_label(self):
        self.assertEqual(presentation.ASPECT_LABELS["tamano"], "tamaño")

    def test_no_label_is_a_technical_key(self):
        for key, label in presentation.ASPECT_LABELS.items():
            with self.subTest(aspecto=key):
                self.assertNotIn("_", label)


class ComparisonTableTests(TestCase):
    """U35 y U36: sin filas muertas y sin afirmar hechos negativos."""

    def _render(self, official_store):
        entry = RankingEntry.from_dict(
            {
                "entity_id": "MLM2528199353",
                "entity_name": "Publicación",
                "position": 1,
                "final_score": 0.4,
                "metadata": {
                    "listing_title": "Publicación 1 · $139,00",
                    "price_label": "$139,00",
                    "match_label": "Mejor opción para vos",
                    "warranty": "No informada",
                    "shipping": "Gratis",
                    "official_store": official_store,
                    "seller": "Vendedor 272093102",
                    "purchase_url": "https://articulo.mercadolibre.com.mx/MLM-2528199353",
                    "purchase_url_is_fallback": False,
                },
            }
        )
        return render_to_string(
            "recommender/partials/listing_comparison.html",
            {"listings": [entry], "show_installments": True},
        )

    def test_the_dead_conditions_have_no_fixed_rows(self):
        html = self._render(True)
        self.assertNotIn("Factura", html)
        self.assertNotIn("Cuotas", html)

    def test_a_missing_condition_is_not_shown_as_a_no(self):
        html = self._render(False)
        self.assertIn("no informado", html)
        self.assertNotIn("— No", html)

    def test_the_plus_minus_row_is_gone(self):
        html = self._render(True)
        self.assertNotIn("Lo mejor y lo que conviene mirar", html)


class EmptyListingStatesTests(TestCase):
    """U33: los dos vacíos del paso 4 nombran su causa y su salida."""

    def _flow(self, *, preferences, budget_min=None, budget_max=None):
        from recommender.models import RecommendationSession

        return RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="mlm_dataset_real",
            strategy="D",
            stage=RecommendationSession.Stage.LISTING_RANKING,
            selected_product_id="MLM194336",
            selected_product_name="Café controlado",
            purchase_preferences=preferences,
            budget_min=budget_min,
            budget_max=budget_max,
            laf2_result={
                "domain": "cafe",
                "dataset_key": "mlm_dataset_real",
                "ranking": [],
                "program_status": "pending",
            },
        )

    def _render(self, flow, **extra):
        from recommender.domain.contracts import EvaluationResult

        contexto = {
            "flow": flow,
            "result": EvaluationResult.from_dict(flow.laf2_result),
            "show_installments": False,
            "has_marketplace_links": False,
            "no_purchase_preferences": False,
            "budget_left_nothing": False,
            "budget_min_label": "",
            "budget_max_label": "",
        }
        contexto.update(extra)
        return render_to_string("recommender/listing_ranking.html", contexto)

    def test_all_conditions_in_no_me_importa_has_its_own_message(self):
        flow = self._flow(preferences={"precio": 0.0, "envio": 0.0})
        html = self._render(flow, no_purchase_preferences=True)
        self.assertIn("No elegiste ninguna condición de compra", html)
        self.assertIn("No me importa", html)
        self.assertNotIn("la configuración del generador", html)

    def test_a_budget_that_leaves_nothing_names_the_range_and_the_way_out(self):
        flow = self._flow(preferences={"precio": 0.67}, budget_min=10, budget_max=20)
        html = self._render(
            flow,
            budget_left_nothing=True,
            budget_min_label="$10,00",
            budget_max_label="$20,00",
        )
        self.assertIn("Ninguna publicación entra en tu presupuesto", html)
        self.assertIn("$10,00", html)
        self.assertIn("$20,00", html)
        self.assertIn("Cambiar el presupuesto", html)
        self.assertNotIn("la configuración del generador", html)

    def test_the_two_states_no_longer_share_one_message(self):
        flow = self._flow(preferences={"precio": 0.0})
        sin_condiciones = self._render(flow, no_purchase_preferences=True)
        sin_presupuesto = self._render(flow, budget_left_nothing=True)
        self.assertNotEqual(sin_condiciones, sin_presupuesto)


class ScoreStoryTests(SimpleTestCase):
    """U09: con una sola característica elegida no se dice «a todas»."""

    def _rows(self, n):
        return [
            {"label": f"Aspecto {i}", "laf_score": 0.6 + i / 100, "weight": 1.0,
             "mentions": 10 + i}
            for i in range(n)
        ]

    def test_one_chosen_aspect_does_not_talk_about_all_of_them(self):
        from recommender.services import comparison

        texto = comparison.build_score_story(1, 18, self._rows(1))
        self.assertIn("La única característica que elegiste", texto)
        self.assertIn("El orden lo decidió ese único resultado.", texto)
        self.assertNotIn("mismo peso a todas", texto)

    def test_several_aspects_with_the_same_weight_keep_the_old_sentence(self):
        from recommender.services import comparison

        texto = comparison.build_score_story(1, 18, self._rows(3))
        self.assertIn("Les diste el mismo peso a todas", texto)
        self.assertNotIn("La única característica que elegiste", texto)


class SupportNoteTests(SimpleTestCase):
    """U08: la nota que se calculaba ahora se muestra."""

    def test_the_note_is_computed_for_a_product_with_little_support(self):
        result = presentation.EvaluationResult.from_dict(
            {
                "domain": "cafe",
                "dataset_key": "fixture",
                "ranking": [
                    {"entity_id": "A", "entity_name": "Muchas menciones",
                     "position": 1, "final_score": 0.5, "evidence_count": 100},
                    {"entity_id": "B", "entity_name": "Menciones al medio",
                     "position": 2, "final_score": 0.4, "evidence_count": 100},
                    {"entity_id": "C", "entity_name": "Pocas menciones",
                     "position": 3, "final_score": 0.2, "evidence_count": 12},
                ],
            }
        )
        salida = presentation.attach_primary_copy(result)
        notas = {e.entity_id: e.metadata.get("support_note") for e in salida.ranking}
        self.assertEqual(notas["C"], presentation.LOW_SUPPORT_NOTE)
        self.assertIsNone(notas["A"])

    def test_the_card_template_renders_it(self):
        # La tarjeta vive dentro de `product_ranking.html`, que necesita el
        # recorrido completo: acá se fija que la plantilla la nombra, que es lo
        # que faltaba (se calculaba y no se renderizaba).
        plantilla = io_read("recommender/templates/recommender/product_ranking.html")
        self.assertIn("item.metadata.support_note", plantilla)
        self.assertIn("ranking-support-note", plantilla)


class ScoreNoteTests(SimpleTestCase):
    """U18, segunda pasada: la nota habla de corchetes, que es lo que se ve."""

    def test_the_note_names_the_brackets_the_equation_actually_uses(self):
        for ruta in (
            "recommender/templates/recommender/explanation.html",
            "recommender/templates/recommender/partials/argument_graph.html",
        ):
            with self.subTest(plantilla=ruta):
                plantilla = io_read(ruta)
                self.assertIn("adentro de los corchetes", plantilla)
                self.assertNotIn("adentro del paréntesis", plantilla)

    def test_the_written_equation_uses_brackets(self):
        from recommender.services import comparison

        class _Fila:
            def __init__(self):
                self.weight = 0.67
                self.laf_score = 0.5
                self.aspect = "sabor"
                self.label = "sabor"
                self.priority_label = "importante"
                self.contribution = 0.335

        class _Breakdown:
            contributions = (_Fila(),)
            weighted_total = 0.335
            weights_total = 0.67
            final_score = 0.5

        self.assertIn("[", presentation.listing_score_equation(_Breakdown()))
        self.assertIn("]", comparison.build_score_equation(_Breakdown()))


class BudgetErrorTests(SimpleTestCase):
    """U32: el error se ve donde está el error."""

    def test_both_budget_fields_are_marked_when_the_range_is_impossible(self):
        from django.conf import settings

        from recommender.repositories.domain_repository import DomainConfigRepository
        from recommender.web.forms import PurchasePreferencesForm

        domain = DomainConfigRepository(settings.DOMAIN_CONFIG_DIR).get("cafe")
        form = PurchasePreferencesForm(
            data={
                "budget_min": "500",
                "budget_max": "300",
                **{aspect.key: "0.67" for aspect in domain.purchase_aspects},
            },
            domain=domain,
        )
        self.assertFalse(form.is_valid())
        for nombre in ("budget_min", "budget_max"):
            with self.subTest(campo=nombre):
                attrs = form.fields[nombre].widget.attrs
                self.assertIn("input-error", attrs.get("class", ""))
                self.assertEqual(attrs.get("aria-invalid"), "true")

    def test_the_message_is_rendered_inside_the_budget_panel(self):
        plantilla = io_read("recommender/templates/recommender/purchase.html")
        antes, _, despues = plantilla.partition("Rango de presupuesto")
        self.assertNotIn("form.non_field_errors", antes)
        panel, _, _ = despues.partition("Importancia de las condiciones")
        self.assertIn("form.non_field_errors", panel)
