from django.test import SimpleTestCase

from recommender.domain.contracts import EvaluationResult


class ContractTests(SimpleTestCase):
    def test_result_contract_normalizes_missing_values(self):
        result = EvaluationResult.from_dict(
            {
                "evaluation_status": "invalid",
                "ranking": [
                    {
                        "entity_id": None,
                        "entity_name": None,
                        "final_score": None,
                        "confidence": 4,
                        "preference": -2,
                        "arguments_for": None,
                        "arguments_against": [None],
                    }
                ],
            }
        )
        self.assertEqual(result.evaluation_status, "pending")
        self.assertEqual(result.ranking[0].entity_name, "Entidad sin nombre")
        self.assertEqual(result.ranking[0].final_score, 0)
        self.assertEqual(result.ranking[0].confidence, 1)
        self.assertEqual(result.ranking[0].preference, 0)

    def test_contract_round_trip_preserves_required_trace_fields(self):
        result = EvaluationResult.from_dict(
            {
                "run_id": "run-1",
                "evaluation_status": "mock",
                "evaluator_version": "mock-1",
                "operator_profile": "budan_2017",
                "dataset_key": "cafe-demo",
                "domain": "cafe",
                "strategy": "D",
                "generated_at": "2026-07-29T12:00:00-03:00",
                "ranking": [],
            }
        )
        payload = result.to_dict()
        for key in (
            "evaluation_status",
            "evaluator_version",
            "operator_profile",
            "dataset_key",
            "domain",
            "strategy",
            "generated_at",
        ):
            self.assertIn(key, payload)

    def test_contract_preserves_generated_program_trace(self):
        result = EvaluationResult.from_dict(
            {
                "evaluation_status": "pending",
                "program_status": "generated",
                "laf_program": "hecho(producto). {0.80; 1.00}",
                "methodology_sha256": "abc123",
                "products_count": 15,
                "items_count": 4,
                "program_kind": "laf2",
                "facts_count": 28,
                "rules_count": 12,
                "execution_payloads": {"envio": {"facts": [{"id": "f1"}]}},
                "ranking": [],
            }
        )

        self.assertEqual(result.program_status, "generated")
        self.assertEqual(result.products_count, 15)
        self.assertEqual(result.items_count, 4)
        self.assertEqual(result.program_kind, "laf2")
        self.assertIn("hecho(producto)", result.to_dict()["laf_program"])
        self.assertEqual(result.execution_payloads["envio"]["facts"][0]["id"], "f1")
