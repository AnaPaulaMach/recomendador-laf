from django.test import SimpleTestCase

from recommender.domain.contracts import RankingEntry
from recommender.services.post_laf_decision import (
    AspectEvaluation,
    DECISION_MODEL,
    combine_rankings,
    normalized_multicriteria_ranking,
    zero_threshold_payload,
)


def _entry(entity_id: str, score: float) -> RankingEntry:
    return RankingEntry(
        entity_id=entity_id,
        entity_name=f"Producto {entity_id}",
        position=1,
        final_score=score,
        confidence=score,
        preference=1.0,
        status="recommended",
        evidence_count=0,
        metadata={"laf_argument": entity_id},
    )


class PostLAFDecisionTests(SimpleTestCase):
    def test_zero_disables_but_low_positive_preference_remains(self):
        payload = {
            "facts": [
                {"label": "cero", "attributes": ["0.9", "0"]},
                {"label": "bajo", "attributes": ["0.9", "0.33"]},
            ],
            "rules": [],
        }

        transformed = zero_threshold_payload(payload)

        self.assertEqual([fact["label"] for fact in transformed["facts"]], ["bajo"])
        self.assertEqual(len(payload["facts"]), 2)

    def test_normalized_average_uses_user_weights(self):
        ranking = normalized_multicriteria_ranking(
            {
                "sabor": {"A": 0.9, "B": 0.2},
                "aroma": {"A": 0.1, "B": 0.8},
            },
            {"sabor": 1.0, "aroma": 0.33, "caducidad": 0.0},
            {"A": "Producto A", "B": "Producto B"},
        )

        self.assertEqual(ranking[0]["entity_id"], "A")
        self.assertAlmostEqual(ranking[0]["score"], (0.9 + 0.33 * 0.1) / 1.33)

    def test_intermediate_weight_changes_score_without_becoming_zero(self):
        scores = {"sabor": {"A": 0.9}, "aroma": {"A": 0.3}}

        low = normalized_multicriteria_ranking(
            scores, {"sabor": 1.0, "aroma": 0.33}, {"A": "A"}
        )[0]["score"]
        medium = normalized_multicriteria_ranking(
            scores, {"sabor": 1.0, "aroma": 0.67}, {"A": "A"}
        )[0]["score"]

        self.assertNotEqual(low, medium)
        self.assertGreater(low, medium)

    def test_combined_ranking_keeps_laf_trace_and_adds_contributions(self):
        baseline = (_entry("A", 0.95), _entry("B", 0.94))
        evaluations = (
            AspectEvaluation("sabor", 1.0, (_entry("A", 0.9), _entry("B", 0.2))),
            AspectEvaluation("aroma", 0.33, (_entry("B", 0.8), _entry("A", 0.1))),
        )

        ranking = combine_rankings(
            baseline,
            evaluations,
            {"sabor": 1.0, "aroma": 0.33, "caducidad": 0.0},
        )

        self.assertEqual([entry.entity_id for entry in ranking], ["A", "B"])
        self.assertEqual(ranking[0].metadata["decision_model"], DECISION_MODEL)
        self.assertEqual(ranking[0].metadata["disabled_aspects"], ["caducidad"])
        self.assertEqual(len(ranking[0].metadata["aspect_contributions"]), 2)
        self.assertEqual(ranking[0].confidence, 0.95)
        self.assertNotEqual(ranking[0].final_score, min(0.95, 1.0))

    def test_contested_aspect_uses_post_conflict_confidence_not_collapsed_min(self):
        # Aspecto DISCUTIDO (resenas positivas Y negativas del mismo aspecto).
        # En la corrida por aspecto ambos lados llevan preferencia 1.0, el
        # conflicto deja la preferencia en 0 y min(conf, pref) colapsa a 0,
        # pero la confianza post-conflicto (0.55) sigue siendo informativa:
        # es la fuerza del argumento ya debilitada por las criticas.
        # El score del aspecto debe ser esa confianza, no 0.
        contested = RankingEntry(
            entity_id="X",
            entity_name="Producto X",
            position=1,
            final_score=0.0,
            confidence=0.55,
            preference=0.0,
            status="not_recommended",
            evidence_count=0,
            metadata={"laf_argument": "X"},
        )
        ranking = combine_rankings(
            (_entry("X", 0.9),),
            (AspectEvaluation("sabor", 1.0, (contested,)),),
            {"sabor": 1.0},
        )

        self.assertEqual(len(ranking), 1)
        self.assertAlmostEqual(ranking[0].final_score, 0.55, places=6)
        self.assertEqual(ranking[0].status, "recommended")

