import json
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from recommender.domain.contracts import EvaluationRequest
from recommender.models import RecommendationSession
from recommender.repositories.domain_repository import DomainConfigRepository
from recommender.repositories.fixture_repository import FixtureRepository
from recommender.repositories.supabase_repository import SupabaseRepository
from recommender.services.evaluators import MockRecommendationEvaluator
from recommender.services.laf1_programs import GeneratedLAF1Program
from recommender.services.laf2_programs import GeneratedLAF2Program
from recommender.services.use_cases import RecommendationWorkflow


@override_settings(SUPABASE_URL="", SUPABASE_KEY="")
class FullFlowTests(TestCase):
    def setUp(self):
        self.domain = DomainConfigRepository(settings.DOMAIN_CONFIG_DIR).get("cafe")

    def _start(self):
        response = self.client.post(
            reverse("recommender:start"),
            {
                "domain": "cafe",
                "dataset_key": "cafe_top20_demo_2026",
                "strategy": "D",
            },
        )
        self.assertEqual(response.status_code, 302)
        return RecommendationSession.objects.get()

    def _quality(self, flow):
        response = self.client.post(
            reverse("recommender:quality", args=[flow.id]),
            {aspect.key: "0.67" for aspect in self.domain.quality_aspects},
        )
        self.assertRedirects(
            response,
            reverse("recommender:product-ranking", args=[flow.id]),
            fetch_redirect_response=False,
        )
        flow.refresh_from_db()
        return flow.laf1_result["ranking"][0]

    def test_laf1_selection_laf2_flow(self):
        flow = self._start()
        product = self._quality(flow)
        response = self.client.post(
            reverse("recommender:select-product", args=[flow.id, product["entity_id"]])
        )
        self.assertEqual(response.status_code, 302)
        flow.refresh_from_db()
        self.assertEqual(flow.stage, RecommendationSession.Stage.PURCHASE)

        purchase_data = {
            "budget_min": "200",
            "budget_max": "500",
            **{aspect.key: "0.67" for aspect in self.domain.purchase_aspects},
        }
        response = self.client.post(
            reverse("recommender:purchase", args=[flow.id]), purchase_data
        )
        self.assertEqual(response.status_code, 302)
        flow.refresh_from_db()
        self.assertEqual(flow.stage, RecommendationSession.Stage.LISTING_RANKING)
        self.assertEqual(flow.laf2_result["evaluation_status"], "mock")
        self.assertEqual(len(flow.laf2_result["ranking"]), 3)

    def test_htmx_preference_summary_and_comparison(self):
        flow = self._start()
        product = self._quality(flow)
        summary = self.client.post(
            reverse("recommender:preference-summary", args=[flow.id]),
            {"stage": "quality", "sabor": "1", "aroma": "0.8"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(summary.status_code, 200)
        self.assertContains(summary, "Sabor")

        self.client.post(
            reverse("recommender:select-product", args=[flow.id, product["entity_id"]])
        )
        self.client.post(
            reverse("recommender:purchase", args=[flow.id]),
            {
                "budget_min": "100",
                "budget_max": "600",
                **{aspect.key: "0.67" for aspect in self.domain.purchase_aspects},
            },
        )
        comparison = self.client.get(
            reverse("recommender:compare-listings", args=[flow.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(comparison.status_code, 200)
        self.assertContains(comparison, "Resultado")

    def test_graph_endpoint_never_exceeds_limit_and_handles_null_fixture(self):
        flow = self._start()
        self._quality(flow)
        response = self.client.get(
            reverse("recommender:graph-fragment", args=[flow.id]),
            {"depth": 6, "limit": 999},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertLessEqual(data["visible_nodes"], 250)
        self.assertTrue(all(node["label"] for node in data["nodes"]))

    def test_full_graph_download_is_explicitly_different_from_visible_fragment(self):
        flow = self._start()
        product = self._quality(flow)
        response = self.client.get(
            reverse("recommender:export-graph-json", args=[flow.id]),
            {"entity_id": product["entity_id"], "full": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="grafo-laf-completo.json"',
        )
        self.assertIn("nodes", json.loads(response.content))

    @override_settings(SUPABASE_URL="", SUPABASE_KEY="", ALLOW_DEMO_FIXTURE=True)
    def test_application_works_without_supabase(self):
        response = self.client.get(reverse("recommender:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "¿Qué producto estás buscando?")
        self.assertContains(response, 'role="combobox"')
        self.assertNotContains(response, "Por ahora hay 1 categoría disponible.")
        self.assertNotContains(response, "Buscar otro producto")
        self.assertContains(response, "Café")
        self.assertContains(response, f'action="{reverse("recommender:start")}"')
        self.assertContains(response, 'name="dataset_key" value="cafe_top20_demo_2026"')
        self.assertNotContains(response, reverse("recommender:start") + "?domain=cafe")
        flow = self._start()
        self.assertEqual(flow.dataset_key, "cafe_top20_demo_2026")
        self.assertFalse(SupabaseRepository("", "").is_configured)

    @override_settings(SUPABASE_URL="", SUPABASE_KEY="", ALLOW_DEMO_FIXTURE=False)
    def test_without_database_and_without_fixture_flag_shows_error(self):
        response = self.client.get(reverse("recommender:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se pudo conectar con la base de datos")
        self.assertNotContains(response, 'value="cafe_top20_demo_2026"')
        self.assertNotContains(response, "Todavía no hay un snapshot completamente procesado")
        submitted = self.client.post(
            reverse("recommender:start"),
            {"domain": "cafe", "dataset_key": "cafe_top20_demo_2026", "strategy": "D"},
        )
        self.assertRedirects(submitted, reverse("recommender:home"))
        self.assertFalse(RecommendationSession.objects.exists())

    @override_settings(
        SUPABASE_URL="https://proyecto.supabase.co",
        SUPABASE_KEY="clave-de-prueba",
        ALLOW_DEMO_FIXTURE=False,
    )
    @patch(
        "recommender.web.views.SupabaseRepository.datasets",
        side_effect=RuntimeError("caída simulada"),
    )
    def test_database_failure_does_not_fall_back_to_fixture_silently(self, _datasets):
        with self.assertLogs("recommender.web.views", level="ERROR"):
            response = self.client.get(reverse("recommender:home"))
        self.assertContains(response, "No se pudo conectar con la base de datos")
        self.assertNotContains(response, 'value="cafe_top20_demo_2026"')

    @override_settings(
        SUPABASE_URL="https://proyecto.supabase.co",
        SUPABASE_KEY="clave-de-prueba",
        ALLOW_DEMO_FIXTURE=True,
    )
    @patch(
        "recommender.web.views.SupabaseRepository.datasets",
        side_effect=RuntimeError("caída simulada"),
    )
    def test_database_failure_uses_fixture_only_when_enabled(self, _datasets):
        with self.assertLogs("recommender.web.views", level="ERROR"):
            response = self.client.get(reverse("recommender:home"))
        self.assertNotContains(response, "No se pudo conectar con la base de datos")
        self.assertContains(response, 'name="dataset_key" value="cafe_top20_demo_2026"')

    def test_catalog_market_can_change_without_mixing_country_data(self):
        colombia = self.client.get(reverse("recommender:home"), {"market": "co"})
        self.assertEqual(colombia.status_code, 200)
        self.assertEqual(self.client.session["catalog_market"], "co")
        self.assertContains(colombia, "El catálogo de Colombia todavía no está disponible")
        self.assertContains(colombia, "Todavía no hay productos para Colombia")
        self.assertNotContains(colombia, 'data-search="Café"')

        mexico = self.client.get(reverse("recommender:home"), {"market": "mx"})
        self.assertEqual(mexico.status_code, 200)
        self.assertEqual(self.client.session["catalog_market"], "mx")
        self.assertContains(mexico, 'data-search="Café ')

    @patch("recommender.web.views._datasets")
    def test_colombia_catalog_is_selected_on_home_and_skips_technical_screen(
        self,
        datasets,
    ):
        datasets.return_value = (
            {
                "key": "mco_mco409413_20260805_184739",
                "label": "Cafe en granos y molido · Colombia · 05/08/2026",
                "category_label": "Cafe en granos y molido",
                "site_id": "MCO",
                "captured_at": "05/08/2026",
            },
        )

        response = self.client.get(reverse("recommender:home"), {"market": "co"})

        self.assertContains(response, "Café en grano o molido")
        self.assertContains(response, "Colombia · relevado el 05/08/2026")
        self.assertContains(
            response,
            'name="dataset_key" value="mco_mco409413_20260805_184739"',
        )
        self.assertNotContains(response, "Configuración avanzada")

        start_get = self.client.get(reverse("recommender:start"))
        self.assertRedirects(start_get, reverse("recommender:home"))

        submitted = self.client.post(
            reverse("recommender:start"),
            {
                "domain": "cafe",
                "dataset_key": "mco_mco409413_20260805_184739",
                "strategy": "D",
            },
        )
        flow = RecommendationSession.objects.get()
        self.assertRedirects(
            submitted,
            reverse("recommender:quality", args=[flow.id]),
            fetch_redirect_response=False,
        )
        self.assertEqual(flow.dataset_key, "mco_mco409413_20260805_184739")

        quality = self.client.post(
            reverse("recommender:quality", args=[flow.id]),
            {aspect.key: "0.67" for aspect in self.domain.quality_aspects},
        )
        self.assertRedirects(
            quality,
            reverse("recommender:product-ranking", args=[flow.id]),
            fetch_redirect_response=False,
        )
        flow.refresh_from_db()
        self.assertEqual(flow.laf1_result["evaluation_status"], "pending")
        self.assertEqual(flow.laf1_result["ranking"], [])

        ranking = self.client.get(
            reverse("recommender:product-ranking", args=[flow.id])
        )
        self.assertContains(ranking, "Todavía no podemos ordenar este catálogo")
        self.assertNotContains(ranking, "Nescafé Reserva Xiapan")

    def test_historical_mock_for_real_dataset_is_not_rendered(self):
        flow = RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="mco_catalogo_real",
            strategy="D",
            quality_preferences={"sabor": 1.0},
            laf1_result={
                "run_id": "laf1-mock-antiguo",
                "evaluation_status": "mock",
                "evaluator_version": "mock-fixtures-1.0.0",
                "operator_profile": "budan_2017",
                "dataset_key": "mco_catalogo_real",
                "domain": "cafe",
                "strategy": "D",
                "generated_at": "2026-08-12",
                "ranking": [
                    {
                        "entity_id": "producto_mexicano",
                        "entity_name": "Producto mexicano de prueba",
                        "position": 1,
                    }
                ],
            },
        )

        response = self.client.get(
            reverse("recommender:product-ranking", args=[flow.id])
        )

        self.assertContains(response, "Todavía no podemos ordenar este catálogo")
        self.assertNotContains(response, "Producto mexicano de prueba")

    def test_preference_page_uses_plain_language_levels(self):
        flow = self._start()
        response = self.client.get(reverse("recommender:quality", args=[flow.id]))
        self.assertEqual(response.status_code, 200)
        for label in ("No me importa", "Poco", "Bastante", "Es prioridad"):
            self.assertContains(response, label)
        self.assertContains(response, "Paso 1 de 4")
        self.assertContains(response, "Qué te importa")
        self.assertContains(response, "Cómo usamos lo que elegiste")
        self.assertContains(response, "Revisamos cada característica")
        self.assertContains(response, "Cuanto más importante sea una característica para vos")
        self.assertNotContains(response, "LAF1")
        self.assertNotContains(response, "una única etiqueta")
        self.assertNotContains(response, "programa independiente")
        self.assertNotContains(response, "Tus prioridades")

    @override_settings(
        SUPABASE_URL="https://proyecto.supabase.co",
        SUPABASE_KEY="clave-de-prueba",
        LAF_PRODUCT_DECISION_MODEL="legacy_min",
    )
    @patch.object(
        SupabaseRepository,
        "available_quality_aspect_keys",
        return_value=("sabor", "tueste"),
    )
    def test_preference_page_only_shows_aspects_supported_by_dataset(
        self,
        available_quality_aspect_keys,
    ):
        flow = RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="mlm_dataset_real",
            strategy="D",
        )

        response = self.client.get(reverse("recommender:quality", args=[flow.id]))

        self.assertContains(response, "Sabor")
        self.assertContains(response, "Calidad del tueste")
        self.assertNotContains(response, "Aroma y olor")
        self.assertContains(
            response,
            "Solo mostramos las características con menciones en las reseñas",
        )
        available_quality_aspect_keys.assert_called_once_with(flow.dataset_key, "D")

        submitted = self.client.post(
            reverse("recommender:quality", args=[flow.id]),
            {"sabor": "1", "tueste": "0.67"},
        )
        self.assertRedirects(
            submitted,
            reverse("recommender:product-ranking", args=[flow.id]),
            fetch_redirect_response=False,
        )
        flow.refresh_from_db()
        self.assertEqual(flow.quality_preferences, {"sabor": 1.0, "tueste": 0.67})
        available_quality_aspect_keys.assert_called_once()

    @override_settings(
        SUPABASE_URL="https://proyecto.supabase.co",
        SUPABASE_KEY="clave-de-prueba",
        LAF_PRODUCT_DECISION_MODEL="legacy_min",
    )
    @patch.object(
        SupabaseRepository,
        "available_quality_aspect_keys",
        return_value=(),
    )
    def test_preference_page_blocks_catalog_without_comparable_evidence(
        self,
        available_quality_aspect_keys,
    ):
        flow = RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="dataset_sin_evidencia",
            strategy="D",
        )

        response = self.client.get(reverse("recommender:quality", args=[flow.id]))
        self.assertContains(
            response,
            "No encontramos información suficiente para comparar características",
        )
        self.assertNotContains(response, "Ver productos recomendados")

        submitted = self.client.post(
            reverse("recommender:quality", args=[flow.id]),
            {"sabor": "1"},
        )
        self.assertEqual(submitted.status_code, 200)
        flow.refresh_from_db()
        self.assertEqual(flow.quality_preferences, {})
        self.assertEqual(flow.laf1_result, {})

    @override_settings(
        SUPABASE_URL="https://proyecto.supabase.co",
        SUPABASE_KEY="clave-de-prueba",
        LAF_PRODUCT_DECISION_MODEL="legacy_min",
    )
    @patch.object(
        SupabaseRepository,
        "available_quality_aspect_keys",
        return_value=("sabor",),
    )
    @patch("recommender.services.laf1_programs.LAF1ProgramService.generate")
    def test_real_preferences_generate_and_export_step_08_program(
        self,
        generate,
        available_quality_aspect_keys,
    ):
        generate.return_value = GeneratedLAF1Program(
            run_id="laf1-program-web",
            text=(
                "% Dataset key: mco_catalogo_real\n"
                "resenaPositivaSabor(producto). {0.80; 1.00}"
            ),
            generated_at="2026-08-13T12:00:00-03:00",
            methodology_sha256="hash-congelado",
            products_count=15,
            facts_count=1,
            rules_count=0,
        )
        flow = RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="mco_catalogo_real",
            strategy="D",
        )

        submitted = self.client.post(
            reverse("recommender:quality", args=[flow.id]),
            {"sabor": "1"},
        )

        self.assertRedirects(
            submitted,
            reverse("recommender:product-ranking", args=[flow.id]),
            fetch_redirect_response=False,
        )
        flow.refresh_from_db()
        self.assertEqual(flow.laf1_result["program_status"], "generated")
        self.assertEqual(flow.laf1_result["products_count"], 15)
        ranking = self.client.get(
            reverse("recommender:product-ranking", args=[flow.id])
        )
        # U21 (ADR-006): el estado sin ranking nombra la causa y ofrece la acción,
        # y ya no habla de «ejecutar el motor algebraico».
        self.assertContains(ranking, "No pudimos ordenar los cafés ahora")
        self.assertContains(ranking, "Volver a intentar")
        self.assertNotContains(ranking, "motor algebraico")
        self.assertNotContains(ranking, "Nescafé Reserva Xiapan")

        exported = self.client.get(
            reverse("recommender:export-laf1-program", args=[flow.id])
        )
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn(b"mco_catalogo_real", exported.content)
        generate.assert_called_once()

        flow.quality_preferences = {
            "sabor": 1.0,
            "tueste": 0.67,
            "acidez": 0.33,
            "aroma": 0.0,
        }
        flow.save(update_fields=["quality_preferences", "updated_at"])
        traceability = self.client.get(
            reverse("recommender:traceability", args=[flow.id])
        )
        self.assertContains(traceability, "13 de agosto de 2026, 12:00 h")
        self.assertContains(traceability, "Hora de Argentina")
        self.assertContains(traceability, "Cómo se combinan los valores")
        self.assertContains(traceability, "Es prioridad")
        self.assertContains(traceability, "Bastante")
        self.assertContains(traceability, "Poco")
        self.assertContains(traceability, "No me importa")
        self.assertContains(traceability, 'class="preference-meter-track"')
        self.assertContains(traceability, 'class="operator-formula"')
        # El "grafo completo por producto" se retiró de Trazabilidad
        # (2026-09-10): ese grafo no es la traza del ranking. La trazabilidad
        # queda en los programas descargables y en el grafo por aspecto.
        self.assertNotContains(traceability, "Grafo completo por producto")
        self.assertNotContains(traceability, "trace-graph-links")

    def test_the_combined_graph_per_product_is_gone(self):
        from django.urls import NoReverseMatch

        with self.assertRaises(NoReverseMatch):
            reverse("recommender:product-graph", args=["x", "y"])

    def test_product_ranking_allows_direct_selection(self):
        flow = self._start()
        self._quality(flow)
        response = self.client.get(reverse("recommender:product-ranking", args=[flow.id]))

        self.assertContains(response, "Elegir producto", count=4)
        self.assertContains(response, "Ver por qué lo recomendamos", count=4)
        self.assertContains(response, "Mejor opción para vos")
        self.assertContains(response, "Buena coincidencia")
        self.assertNotContains(response, "82%")
        # La tarjeta informa menciones por característica, sin adjetivos (E3, 09/09).
        self.assertContains(response, "Sabor: 181 de 184 menciones favorables")
        self.assertContains(response, "Aroma: 61 de 61 menciones favorables")
        self.assertNotContains(response, "La mayoría valora su sabor")

    def test_a_tied_head_shares_the_label_and_the_detail_says_so(self):
        # Resguardo del rótulo (validacion_robustez/RESULTADOS.md §3): con el 1.º
        # y el 2.º a menos de 0,01 de puntaje la interfaz no declara un único
        # mejor. Se fuerza el empate sobre el ranking ya calculado; el orden y
        # los puestos no se tocan.
        flow = self._start()
        self._quality(flow)
        flow.refresh_from_db()
        ranking = flow.laf1_result["ranking"]
        ranking[1]["final_score"] = round(ranking[0]["final_score"] - 0.0009, 4)
        flow.save(update_fields=["laf1_result"])

        listado = self.client.get(reverse("recommender:product-ranking", args=[flow.id]))
        self.assertContains(listado, "Entre las mejores opciones para vos", count=2)
        self.assertNotContains(listado, "Mejor opción para vos")

        detalle = self.client.get(
            reverse("recommender:product-detail", args=[flow.id, ranking[0]["entity_id"]])
        )
        self.assertContains(
            detalle,
            "Las 2 primeras opciones quedaron a menos de 0,01 de puntaje: "
            "el orden entre ellas no es concluyente",
        )

    def test_ranking_when_no_preference_selected(self):
        # Con el motor real, poner todo en "No me importa" (peso 0) hace que
        # min(confianza, 0) = 0 rechace todos los productos y el ranking quede
        # vacio. Reproducimos ese resultado directamente.
        flow = RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="mco_catalogo_real",
            strategy="D",
            quality_preferences={"sabor": 0.0, "aroma": 0.0},
            laf1_result={
                "run_id": "laf1-sin-preferencias",
                "evaluation_status": "validated",
                "evaluator_version": "laf-programs-08-10-1.0.0",
                "operator_profile": "budan_2017",
                "dataset_key": "mco_catalogo_real",
                "domain": "cafe",
                "strategy": "D",
                "generated_at": "2026-08-13T12:00:00-03:00",
                "ranking": [],
                "program_status": "generated",
                "program_kind": "laf1",
                "laf_program": "hecho(producto). {0.8; 1.0}",
                "products_count": 18,
            },
            stage=RecommendationSession.Stage.PRODUCT_RANKING,
        )
        response = self.client.get(
            reverse("recommender:product-ranking", args=[flow.id])
        )
        self.assertContains(response, "Todavía no elegiste qué te importa")
        self.assertContains(response, "No seleccionaste ninguna preferencia")
        self.assertContains(response, "Elegir qué me importa")
        self.assertNotContains(response, "productos ordenados para vos")
        self.assertNotContains(response, "El catálogo real ya fue preparado")

    @override_settings(
        DEBUG=True,
        SUPABASE_URL="https://proyecto.supabase.co",
        SUPABASE_KEY="clave-de-prueba",
    )
    @patch(
        "recommender.services.laf2_programs.LAF2ProgramService.available_purchase_condition_keys",
        return_value=("precio", "descuento", "cuotas", "garantia", "tienda_oficial", "factura", "envio"),
    )
    @patch("recommender.services.laf2_programs.LAF2ProgramService.generate_conditions")
    @patch.object(
        SupabaseRepository,
        "listing_price_range",
        return_value=(100.0, 300.0, 3),
    )
    @patch.object(
        SupabaseRepository,
        "laf2_audit_products",
        return_value=(
            {
                "product_id": "MCO123",
                "name": "Cafe controlado",
                "position": 1,
                "price_min": 100.0,
                "price_max": 300.0,
                "items_count": 3,
            },
        ),
    )
    def test_local_audit_generates_and_exports_laf2_program(
        self,
        audit_products,
        listing_price_range,
        generate_conditions,
        available_conditions,
    ):
        generated = GeneratedLAF2Program(
            run_id="laf2-program-web",
            text=(
                "% Dataset key: mco_catalogo_real\n"
                "% Product ID: MCO123\n"
                "precioBueno(mco_item_1). {0.95; 1.00}"
            ),
            generated_at="2026-08-13T14:30:00-03:00",
            methodology_sha256="hash-congelado",
            product_id="MCO123",
            product_name="Cafe controlado",
            items_count=3,
            facts_count=3,
            rules_count=8,
        )
        # ADR-007: el evaluador pide un respaldo completo y un programa por
        # condición activa en una sola carga, igual que LAF 1 por aspecto.
        generate_conditions.side_effect = lambda request: (
            generated,
            {
                condition: generated
                for condition, weight in request.preferences.items()
                if float(weight) > 0
            },
        )
        flow = RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="mco_catalogo_real",
            strategy="D",
            quality_preferences={"sabor": 1.0},
            laf1_result={
                "run_id": "laf1-program-web",
                "evaluation_status": "pending",
                "evaluator_version": "laf-programs-08-10-1.0.0",
                "operator_profile": "budan_2017",
                "dataset_key": "mco_catalogo_real",
                "domain": "cafe",
                "strategy": "D",
                "generated_at": "2026-08-13T12:00:00-03:00",
                "ranking": [],
                "program_status": "generated",
                "program_kind": "laf1",
                "laf_program": "hecho(producto). {0.8; 1.0}",
                "products_count": 15,
            },
            stage=RecommendationSession.Stage.PRODUCT_RANKING,
        )

        ranking = self.client.get(
            reverse("recommender:product-ranking", args=[flow.id])
        )
        self.assertContains(ranking, "Probar LAF2 con un producto controlado")

        audit = self.client.get(
            reverse("recommender:audit-laf2-product", args=[flow.id])
        )
        self.assertContains(audit, "Modo de auditor")
        self.assertContains(audit, "Cafe controlado")
        selected = self.client.post(
            reverse("recommender:audit-laf2-product", args=[flow.id]),
            {"product_id": "MCO123"},
        )
        self.assertRedirects(
            selected,
            reverse("recommender:purchase", args=[flow.id]),
            fetch_redirect_response=False,
        )

        purchase = self.client.get(reverse("recommender:purchase", args=[flow.id]))
        self.assertContains(purchase, "Este producto fue elegido para probar 09/10")
        self.assertContains(purchase, "Cómo comparamos las opciones de compra")
        self.assertContains(purchase, "Cuanto más importante sea una condición para vos")
        self.assertContains(purchase, "no altere injustamente el resultado")
        self.assertContains(purchase, "aparecen al final")
        self.assertNotContains(purchase, "compraBuena")
        self.assertNotContains(purchase, "confianza 0,85")
        submitted = self.client.post(
            reverse("recommender:purchase", args=[flow.id]),
            {
                "budget_min": "100",
                "budget_max": "300",
                **{aspect.key: "0.67" for aspect in self.domain.purchase_aspects},
            },
        )
        self.assertRedirects(
            submitted,
            reverse("recommender:listing-ranking", args=[flow.id]),
            fetch_redirect_response=False,
        )
        flow.refresh_from_db()
        self.assertEqual(flow.laf2_result["program_kind"], "laf2")
        self.assertEqual(flow.laf2_result["items_count"], 3)
        self.assertEqual(flow.laf2_result["ranking"], [])

        result_page = self.client.get(
            reverse("recommender:listing-ranking", args=[flow.id])
        )
        # U21 (ADR-006): sin «el programa 10» ni «LAF Studio» en la pantalla.
        self.assertContains(result_page, "No pudimos ordenar las publicaciones ahora")
        self.assertContains(result_page, "Volver a intentar")
        self.assertNotContains(result_page, "LAF Studio")
        self.assertContains(result_page, "Descargar programa LAF 2")
        exported = self.client.get(
            reverse("recommender:export-laf2-program", args=[flow.id])
        )
        self.assertEqual(exported.status_code, 200)
        self.assertIn(b"MCO123", exported.content)
        # Multicriterio de publicaciones: una sola carga de Supabase para el
        # respaldo completo más un programa por condición con peso > 0
        # (validacion_laf2/VALIDACION_MULTICRITERIO_LAF2.md, ADR-007).
        generate_conditions.assert_called_once()
        self.assertEqual(
            len(generate_conditions.call_args.args[0].preferences),
            len(self.domain.purchase_aspects),
        )
        available_conditions.assert_called_with(
            flow.dataset_key,
            "cafe",
            product_id="MCO123",
        )
        self.assertEqual(audit_products.call_count, 2)
        audit_products.assert_called_with(flow.dataset_key)
        self.assertEqual(listing_price_range.call_count, 2)

    @override_settings(DEBUG=False)
    def test_laf2_audit_route_is_not_available_in_production(self):
        flow = RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="mco_catalogo_real",
            strategy="D",
        )

        response = self.client.get(
            reverse("recommender:audit-laf2-product", args=[flow.id])
        )

        self.assertEqual(response.status_code, 404)

    def test_unavailable_stages_redirect_to_the_latest_completed_step(self):
        flow = self._start()

        for view_name in (
            "recommender:product-ranking",
            "recommender:listing-ranking",
            "recommender:compare-listings",
        ):
            response = self.client.get(reverse(view_name, args=[flow.id]))
            self.assertRedirects(
                response,
                reverse("recommender:quality", args=[flow.id]),
                fetch_redirect_response=False,
            )

        product = self._quality(flow)
        response = self.client.get(
            reverse("recommender:listing-ranking", args=[flow.id])
        )
        self.assertRedirects(
            response,
            reverse("recommender:product-ranking", args=[flow.id]),
            fetch_redirect_response=False,
        )

        self.client.post(
            reverse("recommender:select-product", args=[flow.id, product["entity_id"]])
        )
        response = self.client.get(
            reverse("recommender:listing-ranking", args=[flow.id])
        )
        self.assertRedirects(
            response,
            reverse("recommender:purchase", args=[flow.id]),
            fetch_redirect_response=False,
        )

    def test_purchase_results_have_a_provisional_marketplace_exit(self):
        flow = self._start()
        product = self._quality(flow)
        self.client.post(
            reverse("recommender:select-product", args=[flow.id, product["entity_id"]])
        )
        self.client.post(
            reverse("recommender:purchase", args=[flow.id]),
            {
                "budget_min": "121,22",
                "budget_max": "410",
                **{aspect.key: "0.67" for aspect in self.domain.purchase_aspects},
            },
        )

        fallback_url = "https://www.mercadolibre.com.mx/mas-vendidos/MLM194336"
        ranking = self.client.get(
            reverse("recommender:listing-ranking", args=[flow.id])
        )
        comparison = self.client.get(
            reverse("recommender:compare-listings", args=[flow.id])
        )
        flow.refresh_from_db()

        self.assertContains(ranking, fallback_url, count=3)
        self.assertContains(ranking, "Ver opciones en Mercado Libre", count=3)
        self.assertContains(ranking, "Ver por qué lo recomendamos", count=3)
        for item in flow.laf2_result["ranking"]:
            self.assertContains(
                ranking,
                f"?entity_id={item['entity_id']}",
            )
        self.assertContains(comparison, fallback_url, count=3)
        self.assertNotContains(ranking, "84%")

        explained_id = flow.laf2_result["ranking"][1]["entity_id"]
        explanation_url = reverse("recommender:explanation", args=[flow.id])
        explanation = self.client.get(
            explanation_url,
            {"entity_id": explained_id},
        )

        # La explicación de publicaciones no abre con una oración sobre el
        # puesto: el paso 3 y la tabla ya lo dicen (2026-09-10).
        self.assertNotContains(explanation, "Por qué está en este lugar")
        self.assertNotContains(explanation, "mejor combina las condiciones que elegiste")
        self.assertContains(explanation, "Qué encontramos en esta publicación")
        self.assertContains(explanation, "Comparar con las demás")
        # La explicación de publicaciones ya no ofrece el grafo técnico
        # (?technical=1) ni la plantilla technical_explanation.html (2026-09-18).
        self.assertNotContains(explanation, "Ver razonamiento técnico")
        self.assertNotContains(explanation, "Abrir grafo y reglas")
        self.assertNotContains(explanation, 'id="argument-graph"')
        self.assertContains(explanation, "Ver datos utilizados")
        technical = self.client.get(
            explanation_url,
            {"entity_id": explained_id, "technical": "1"},
        )
        self.assertNotContains(technical, "Filtros del grafo")
        self.assertNotContains(technical, 'id="argument-graph"')

    @override_settings(
        SUPABASE_URL="https://proyecto.supabase.co",
        SUPABASE_KEY="clave-de-prueba",
    )
    def test_single_purchase_option_skips_preferences_and_laf2(self):
        result = MockRecommendationEvaluator(
            FixtureRepository(settings.FIXTURE_DIR)
        ).evaluate_products(
            EvaluationRequest(
                domain="cafe",
                dataset_key="cafe_top20_demo_2026",
                strategy="D",
                preferences={"sabor": 1.0},
            )
        )
        product = result.ranking[0]
        flow = RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="cafe_top20_demo_2026",
            strategy="D",
            quality_preferences={"sabor": 1.0},
            selected_product_id=product.entity_id,
            selected_product_name=product.entity_name,
            laf1_result=result.to_dict(),
            stage=RecommendationSession.Stage.PURCHASE,
        )
        only_item = (
            {"product_id": product.entity_id, "name": product.entity_name},
            [
                {
                    "item_id": "MLM-UNICA",
                    "price": "249.00",
                    "seller_id": 7,
                    "tags": [],
                    "sale_terms": [],
                    "shipping_free_shipping": True,
                }
            ],
        )

        with (
            patch.object(SupabaseRepository, "product_images", return_value={}),
            patch.object(
                SupabaseRepository,
                "listing_price_range",
                return_value=(249.0, 249.0, 1),
            ),
            patch.object(
                SupabaseRepository,
                "laf2_generation_items",
                return_value=only_item,
            ),
            patch.object(
                RecommendationWorkflow,
                "evaluate_purchase",
            ) as evaluate_purchase,
        ):
            response = self.client.get(
                reverse("recommender:purchase", args=[flow.id])
            )
            submitted = self.client.post(
                reverse("recommender:purchase", args=[flow.id]),
                {},
            )

        for page in (response, submitted):
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "Encontramos una sola opción de compra")
            self.assertContains(page, "se vende en una sola publicación")
            self.assertNotContains(page, "LAF 2")
            self.assertContains(page, "$249")
            self.assertNotContains(page, "Importancia de las condiciones")
        evaluate_purchase.assert_not_called()
        flow.refresh_from_db()
        self.assertEqual(flow.laf2_result, {})

    def test_product_detail_shows_comparison_not_raw_contributions(self):
        flow = self._start()
        product = self._quality(flow)
        response = self.client.get(
            reverse("recommender:product-detail", args=[flow.id, product["entity_id"]])
        )

        # El "Resumen" ahora abre con la frase-historia y la comparación.
        self.assertContains(response, "Por qué está en este lugar")
        self.assertContains(response, "Comparar con los demás")
        self.assertNotContains(response, "Hay algunas críticas al sabor")

    def test_raw_argument_contributions_are_no_longer_rendered(self):
        flow = self._start()
        product = self._quality(flow)
        response = self.client.get(
            reverse("recommender:product-detail", args=[flow.id, product["entity_id"]])
        )

        self.assertNotContains(response, "La mayoría valora su sabor")
        self.assertNotContains(response, "Qué inclinó la recomendación")
        self.assertNotContains(response, 'class="argument-grid')
        # Las líneas de menciones son de la tarjeta; la explicación usa la comparación.
        self.assertNotContains(response, "Sabor: 181 de 184 menciones favorables")

    def test_laf1_product_and_explanation_share_one_page(self):
        flow = self._start()
        product = self._quality(flow)
        detail_url = reverse(
            "recommender:product-detail",
            args=[flow.id, product["entity_id"]],
        )

        detail = self.client.get(detail_url)
        legacy_explanation = self.client.get(
            reverse("recommender:explanation", args=[flow.id]),
            {"entity_id": product["entity_id"]},
        )

        self.assertContains(detail, 'id="explicacion"')
        self.assertContains(detail, "Cómo llegamos a esta recomendación")
        self.assertContains(detail, "Por qué está en este lugar")
        self.assertContains(detail, "Comparar con los demás")
        # La pestaña del grafo técnico completo se retiró (2026-09-10): el grafo
        # real vive en el panel de cada característica y el programa se descarga.
        self.assertNotContains(detail, "El razonamiento completo")
        self.assertNotContains(detail, 'id="argument-graph"')
        self.assertContains(detail, "data-summary-figure")
        self.assertContains(detail, "Descargar programas LAF")
        self.assertContains(detail, "?used=1")
        self.assertNotContains(detail, "JSON completo")
        self.assertNotContains(detail, ">CSV")
        self.assertNotContains(detail, "Controles avanzados de auditoría")
        self.assertNotContains(detail, "Un dato importante")
        self.assertRedirects(
            legacy_explanation,
            f"{detail_url}#explicacion",
            fetch_redirect_response=False,
        )

    def test_product_pages_show_image_fallback_without_supabase(self):
        flow = self._start()
        product = self._quality(flow)
        ranking = self.client.get(reverse("recommender:product-ranking", args=[flow.id]))
        detail = self.client.get(
            reverse("recommender:product-detail", args=[flow.id, product["entity_id"]])
        )

        self.assertContains(ranking, "Imagen no disponible")
        self.assertContains(detail, "Imagen no disponible")

    @override_settings(
        SUPABASE_URL="https://proyecto.supabase.co",
        SUPABASE_KEY="clave-de-prueba",
    )
    @patch.object(
        SupabaseRepository,
        "product_images",
        return_value={
            "MLM16207894": "https://http2.mlstatic.com/D_NQ_NP_producto-F.jpg"
        },
    )
    def test_product_pages_use_catalog_image_from_supabase(
        self,
        product_images,
    ):
        flow = RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="mlm_mlm194329_20260528_142014",
            strategy="D",
        )
        demo_result = MockRecommendationEvaluator(
            FixtureRepository(settings.FIXTURE_DIR)
        ).evaluate_products(
            EvaluationRequest(
                domain="cafe",
                dataset_key="cafe_top20_demo_2026",
                strategy="D",
                preferences={"sabor": 1.0},
            )
        ).to_dict()
        demo_result["evaluation_status"] = "validated"
        demo_result["dataset_key"] = flow.dataset_key
        flow.quality_preferences = {"sabor": 1.0}
        flow.laf1_result = demo_result
        flow.stage = RecommendationSession.Stage.PRODUCT_RANKING
        flow.save(
            update_fields=["quality_preferences", "laf1_result", "stage", "updated_at"]
        )
        product = demo_result["ranking"][0]

        ranking = self.client.get(reverse("recommender:product-ranking", args=[flow.id]))
        detail = self.client.get(
            reverse("recommender:product-detail", args=[flow.id, product["entity_id"]])
        )

        image_url = "https://http2.mlstatic.com/D_NQ_NP_producto-F.jpg"
        self.assertContains(ranking, image_url)
        self.assertContains(detail, image_url)
        product_images.assert_called()
