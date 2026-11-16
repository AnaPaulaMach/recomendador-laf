"""Casos de uso del recorrido: elige el evaluador y encadena los pasos.

``get_evaluator`` arma el adaptador que indica ``settings.RECOMMENDATION_EVALUATOR``
y ``RecommendationWorkflow`` aplica las reglas de invalidacion en cascada
(preferencias -> LAF1 -> producto elegido -> compra -> LAF2).
"""
from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

from recommender.domain.contracts import EvaluationRequest, EvaluationResult
from recommender.models import RecommendationSession
from recommender.repositories.fixture_repository import FixtureRepository
from recommender.repositories.supabase_repository import SupabaseRepository
from recommender.services.laf1_programs import LAF1ProgramService
from recommender.services.laf2_programs import LAF2ProgramService
from recommender.services.laf_api import LAFApiClient


def get_evaluator():
    evaluator_class = import_string(settings.RECOMMENDATION_EVALUATOR)
    if evaluator_class.__name__ == "MockRecommendationEvaluator":
        return evaluator_class(FixtureRepository(settings.FIXTURE_DIR))
    if evaluator_class.__name__ in {
        "LAF1PreparedRecommendationEvaluator",
        "LAFHttpRecommendationEvaluator",
    }:
        fixtures = FixtureRepository(settings.FIXTURE_DIR)
        repository = SupabaseRepository(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        arguments = [
            fixtures,
            LAF1ProgramService(
                repository,
                settings.REPOSITORY_ROOT,
            ),
            LAF2ProgramService(
                repository,
                settings.REPOSITORY_ROOT,
            ),
        ]
        if evaluator_class.__name__ == "LAFHttpRecommendationEvaluator":
            arguments.append(
                LAFApiClient(
                    settings.LAF_API_URL,
                    timeout_seconds=settings.LAF_API_TIMEOUT_SECONDS,
                )
            )
            return evaluator_class(
                *arguments,
                results_validated=settings.LAF_API_RESULTS_VALIDATED,
                product_decision_model=settings.LAF_PRODUCT_DECISION_MODEL,
            )
        return evaluator_class(*arguments)
    return evaluator_class()


class RecommendationWorkflow:
    def __init__(self, evaluator=None):
        self.evaluator = evaluator or get_evaluator()

    def evaluate_quality(
        self,
        session: RecommendationSession,
        preferences: dict[str, float],
    ) -> EvaluationResult:
        result = self.evaluator.evaluate_products(
            EvaluationRequest(
                domain=session.domain_key,
                dataset_key=session.dataset_key,
                strategy=session.strategy,
                preferences=preferences,
            )
        )
        session.quality_preferences = preferences
        session.laf1_result = result.to_dict()
        # Todo lo posterior depende del ranking recién calculado. Conservar una
        # selección o un LAF2 anterior mezclaría dos recorridos incompatibles.
        session.selected_product_id = ""
        session.selected_product_name = ""
        session.purchase_preferences = {}
        session.budget_min = None
        session.budget_max = None
        session.laf2_result = {}
        session.stage = RecommendationSession.Stage.PRODUCT_RANKING
        session.save(
            update_fields=[
                "quality_preferences",
                "laf1_result",
                "selected_product_id",
                "selected_product_name",
                "purchase_preferences",
                "budget_min",
                "budget_max",
                "laf2_result",
                "stage",
                "updated_at",
            ]
        )
        return result

    def select_product(
        self,
        session: RecommendationSession,
        product_id: str,
        product_name: str,
    ) -> None:
        product_changed = session.selected_product_id != product_id
        session.selected_product_id = product_id
        session.selected_product_name = product_name
        update_fields = ["selected_product_id", "selected_product_name"]
        if product_changed:
            session.purchase_preferences = {}
            session.budget_min = None
            session.budget_max = None
            session.laf2_result = {}
            update_fields.extend(
                ["purchase_preferences", "budget_min", "budget_max", "laf2_result"]
            )
        session.stage = RecommendationSession.Stage.PURCHASE
        update_fields.extend(["stage", "updated_at"])
        session.save(
            update_fields=update_fields
        )

    def evaluate_purchase(
        self,
        session: RecommendationSession,
        preferences: dict[str, float],
        budget_min: float | None,
        budget_max: float | None,
    ) -> EvaluationResult:
        result = self.evaluator.evaluate_listings(
            EvaluationRequest(
                domain=session.domain_key,
                dataset_key=session.dataset_key,
                strategy=session.strategy,
                preferences=preferences,
                selected_entity_id=session.selected_product_id,
                budget_min=budget_min,
                budget_max=budget_max,
            )
        )
        session.purchase_preferences = preferences
        session.budget_min = budget_min
        session.budget_max = budget_max
        session.laf2_result = result.to_dict()
        session.stage = RecommendationSession.Stage.LISTING_RANKING
        session.save(
            update_fields=[
                "purchase_preferences",
                "budget_min",
                "budget_max",
                "laf2_result",
                "stage",
                "updated_at",
            ]
        )
        return result
