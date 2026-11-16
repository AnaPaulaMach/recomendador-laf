from django.conf import settings
from unittest.mock import Mock

from django.test import SimpleTestCase

from recommender.domain.contracts import EvaluationRequest
from recommender.repositories.fixture_repository import FixtureRepository
from recommender.services.evaluators import (
    LAF1PreparedRecommendationEvaluator,
    MockRecommendationEvaluator,
    PythonLAFEvaluator,
)
from recommender.services.laf1_programs import GeneratedLAF1Program
from recommender.services.laf2_programs import GeneratedLAF2Program


class EvaluatorTests(SimpleTestCase):
    def setUp(self):
        self.request = EvaluationRequest(
            domain="cafe",
            dataset_key="cafe_top20_demo_2026",
            strategy="D",
            preferences={"sabor": 1.0, "aroma": 0.8},
        )

    def test_mock_is_deterministic_and_explicit(self):
        evaluator = MockRecommendationEvaluator(FixtureRepository(settings.FIXTURE_DIR))
        first = evaluator.evaluate_products(self.request)
        second = evaluator.evaluate_products(self.request)
        self.assertEqual(first, second)
        self.assertEqual(first.evaluation_status, "mock")
        self.assertEqual(first.operator_profile, "budan_2017")
        self.assertEqual(first.ranking[0].position, 1)

    def test_mock_never_uses_fixture_products_for_a_real_dataset(self):
        evaluator = MockRecommendationEvaluator(FixtureRepository(settings.FIXTURE_DIR))
        request = EvaluationRequest(
            **{**self.request.__dict__, "dataset_key": "mco_catalogo_real"}
        )

        result = evaluator.evaluate_products(request)

        self.assertEqual(result.evaluation_status, "pending")
        self.assertEqual(result.dataset_key, "mco_catalogo_real")
        self.assertEqual(result.ranking, ())

    def test_historical_source_dataset_keeps_reproducible_demo(self):
        evaluator = MockRecommendationEvaluator(FixtureRepository(settings.FIXTURE_DIR))
        request = EvaluationRequest(
            **{
                **self.request.__dict__,
                "dataset_key": "mlm_mlm194329_20260528_142014",
            }
        )

        result = evaluator.evaluate_products(request)

        self.assertEqual(result.evaluation_status, "mock")
        self.assertEqual(len(result.ranking), 4)
        self.assertEqual(result.dataset_key, "mlm_mlm194329_20260528_142014")

    def test_future_python_evaluator_does_not_claim_validation(self):
        result = PythonLAFEvaluator().evaluate_products(self.request)
        self.assertEqual(result.evaluation_status, "pending")
        self.assertEqual(result.ranking, ())

    def test_listing_ids_are_stable_for_selected_product(self):
        evaluator = MockRecommendationEvaluator(FixtureRepository(settings.FIXTURE_DIR))
        request = EvaluationRequest(
            **{**self.request.__dict__, "selected_entity_id": "producto-1"}
        )
        result = evaluator.evaluate_listings(request)
        self.assertTrue(all(item.entity_id.startswith("producto-1") for item in result.ranking))

    def test_real_dataset_generates_program_without_claiming_ranking(self):
        service = Mock()
        service.generate.return_value = GeneratedLAF1Program(
            run_id="laf1-program-123",
            text="hecho(producto). {0.80; 1.00}",
            generated_at="2026-08-13T12:00:00-03:00",
            methodology_sha256="hash-congelado",
            products_count=15,
            facts_count=1,
            rules_count=0,
        )
        evaluator = LAF1PreparedRecommendationEvaluator(
            FixtureRepository(settings.FIXTURE_DIR),
            service,
        )
        request = EvaluationRequest(
            **{**self.request.__dict__, "dataset_key": "mco_catalogo_real"}
        )

        result = evaluator.evaluate_products(request)

        self.assertEqual(result.evaluation_status, "pending")
        self.assertEqual(result.program_status, "generated")
        self.assertEqual(result.products_count, 15)
        self.assertEqual(result.ranking, ())

    def test_default_router_treats_fixture_source_as_real_dataset(self):
        service = Mock()
        service.generate.return_value = GeneratedLAF1Program(
            run_id="laf1-program-historico",
            text="hecho(producto_real). {0.80; 1.00}",
            generated_at="2026-08-13T12:00:00-03:00",
            methodology_sha256="hash-congelado",
            products_count=20,
            facts_count=1,
            rules_count=0,
        )
        evaluator = LAF1PreparedRecommendationEvaluator(
            FixtureRepository(settings.FIXTURE_DIR),
            service,
        )
        request = EvaluationRequest(
            **{
                **self.request.__dict__,
                "dataset_key": "mlm_mlm194329_20260528_142014",
            }
        )

        result = evaluator.evaluate_products(request)

        self.assertEqual(result.program_status, "generated")
        self.assertEqual(result.evaluation_status, "pending")
        service.generate.assert_called_once_with(request)

    def test_real_purchase_generates_laf2_without_claiming_a_ranking(self):
        laf1_service = Mock()
        laf2_service = Mock()
        laf2_service.generate.return_value = GeneratedLAF2Program(
            run_id="laf2-program-123",
            text="precioBueno(item). {0.95; 1.00}",
            generated_at="2026-08-13T14:00:00-03:00",
            methodology_sha256="hash-congelado",
            product_id="MCO123",
            product_name="Cafe controlado",
            items_count=3,
            facts_count=3,
            rules_count=8,
        )
        evaluator = LAF1PreparedRecommendationEvaluator(
            FixtureRepository(settings.FIXTURE_DIR),
            laf1_service,
            laf2_service,
        )
        request = EvaluationRequest(
            domain="cafe",
            dataset_key="mco_catalogo_real",
            strategy="D",
            selected_entity_id="MCO123",
            budget_min=100,
            budget_max=200,
            preferences={"precio": 1.0},
        )

        result = evaluator.evaluate_listings(request)

        self.assertEqual(result.evaluation_status, "pending")
        self.assertEqual(result.program_status, "generated")
        self.assertEqual(result.program_kind, "laf2")
        self.assertEqual(result.items_count, 3)
        self.assertEqual(result.ranking, ())
        laf2_service.generate.assert_called_once_with(request)
