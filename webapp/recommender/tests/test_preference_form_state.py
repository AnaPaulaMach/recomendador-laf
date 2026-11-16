from unittest.mock import Mock

from django.conf import settings
from django.test import TestCase

from recommender.domain.contracts import EvaluationResult
from recommender.models import RecommendationSession
from recommender.repositories.domain_repository import DomainConfigRepository
from recommender.services.use_cases import RecommendationWorkflow
from recommender.web.forms import QualityPreferencesForm


class PreferenceFormStateTests(TestCase):
    def test_saved_extreme_values_are_checked_when_preferences_are_reopened(self):
        domain = DomainConfigRepository(settings.DOMAIN_CONFIG_DIR).get("cafe")
        form = QualityPreferencesForm(
            domain=domain,
            initial={"sabor": 1.0, "aroma": 0.0},
        )

        self.assertIn('value="1"', str(form["sabor"]))
        self.assertIn('value="1" data-preference-levels="" required id="id_sabor_3" checked', str(form["sabor"]))
        self.assertIn('value="0" data-preference-levels="" required id="id_aroma_0" checked', str(form["aroma"]))


class RecommendationWorkflowStateTests(TestCase):
    def _session_with_downstream_state(self):
        return RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="cafe_top20_demo_2026",
            strategy="D",
            quality_preferences={"sabor": 0.67},
            selected_product_id="producto-a",
            selected_product_name="Producto A",
            purchase_preferences={"envio": 1.0},
            budget_min=100,
            budget_max=300,
            laf1_result={"run_id": "laf1-anterior"},
            laf2_result={"run_id": "laf2-anterior"},
            stage=RecommendationSession.Stage.LISTING_RANKING,
        )

    def test_recalculating_quality_invalidates_every_downstream_decision(self):
        session = self._session_with_downstream_state()
        evaluator = Mock()
        evaluator.evaluate_products.return_value = EvaluationResult.from_dict(
            {
                "run_id": "laf1-nuevo",
                "evaluation_status": "validated",
                "dataset_key": session.dataset_key,
                "domain": session.domain_key,
                "ranking": [],
            }
        )

        RecommendationWorkflow(evaluator).evaluate_quality(session, {"sabor": 1.0})
        session.refresh_from_db()

        self.assertEqual(session.selected_product_id, "")
        self.assertEqual(session.selected_product_name, "")
        self.assertEqual(session.purchase_preferences, {})
        self.assertIsNone(session.budget_min)
        self.assertIsNone(session.budget_max)
        self.assertEqual(session.laf2_result, {})
        self.assertEqual(session.laf1_result["run_id"], "laf1-nuevo")

    def test_changing_product_invalidates_the_previous_purchase_result(self):
        session = self._session_with_downstream_state()

        RecommendationWorkflow(evaluator=Mock()).select_product(
            session,
            "producto-b",
            "Producto B",
        )
        session.refresh_from_db()

        self.assertEqual(session.selected_product_id, "producto-b")
        self.assertEqual(session.purchase_preferences, {})
        self.assertIsNone(session.budget_min)
        self.assertIsNone(session.budget_max)
        self.assertEqual(session.laf2_result, {})

    def test_reselecting_same_product_preserves_purchase_preferences(self):
        session = self._session_with_downstream_state()

        RecommendationWorkflow(evaluator=Mock()).select_product(
            session,
            "producto-a",
            "Producto A actualizado",
        )
        session.refresh_from_db()

        self.assertEqual(session.purchase_preferences, {"envio": 1.0})
        self.assertEqual(session.laf2_result, {"run_id": "laf2-anterior"})
