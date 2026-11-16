import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from recommender.domain.contracts import EvaluationRequest, EvaluationResult
from recommender.services.recommendation_quality import (
    RecommendationQualityRunner,
    build_quality_profiles,
    load_expectations,
    summarize_quality,
    write_quality_reports,
)


class _EvidenceEvaluator:
    evidence = {
        "producto_a": {"sabor": (0.90, 0.10), "aroma": (0.40, 0.10)},
        "producto_b": {"sabor": (0.60, 0.10), "aroma": (0.90, 0.10)},
    }

    def evaluate_products(self, request):
        rows = []
        program = []
        for entity_id, by_aspect in self.evidence.items():
            score = 0.0
            arguments_for = []
            arguments_against = []
            for aspect, (positive, negative) in by_aspect.items():
                preference = float(request.preferences.get(aspect, 0.0))
                score += (positive - negative) * preference
                title = aspect.title()
                program.extend(
                    [
                        f"resenaPositiva{title}({entity_id}). {{{positive}; {preference}}}",
                        f"resenaNegativa{title}({entity_id}). {{{negative}; {preference}}}",
                    ]
                )
                arguments_for.append(
                    {
                        "argument_id": f"{entity_id}-{aspect}-pos",
                        "title": aspect,
                        "aspect": aspect,
                        "polarity": "positive",
                        "confidence": positive,
                        "preference": preference,
                        "evidence_count": 10,
                    }
                )
                arguments_against.append(
                    {
                        "argument_id": f"{entity_id}-{aspect}-neg",
                        "title": aspect,
                        "aspect": aspect,
                        "polarity": "negative",
                        "confidence": negative,
                        "preference": preference,
                        "evidence_count": 2,
                    }
                )
            rows.append(
                {
                    "entity_id": entity_id,
                    "entity_name": entity_id.replace("_", " ").title(),
                    "final_score": score / 2,
                    "confidence": min(score / 2, 1),
                    "preference": 1,
                    "arguments_for": arguments_for,
                    "arguments_against": arguments_against,
                    "metadata": {"laf_argument": entity_id},
                }
            )
        rows.sort(key=lambda row: (-row["final_score"], row["entity_id"]))
        for position, row in enumerate(rows, start=1):
            row["position"] = position
        program.append("recomendar(X) :- resenaPositivaSabor(X). {1; 1}")
        return EvaluationResult.from_dict(
            {
                "run_id": "quality-test",
                "evaluation_status": "validated",
                "evaluator_version": "test",
                "operator_profile": "test",
                "dataset_key": request.dataset_key,
                "domain": request.domain,
                "strategy": request.strategy,
                "ranking": rows,
                "program_status": "generated",
                "program_kind": "laf1",
                "laf_program": "\n".join(program),
            }
        )


class RecommendationQualityTests(SimpleTestCase):
    def setUp(self):
        self.profiles = build_quality_profiles(
            {"sabor": "Sabor", "aroma": "Aroma"},
            {
                "sensorial": {
                    "label": "Experiencia sensorial",
                    "aspects": ["sabor", "aroma"],
                }
            },
            {"sabor": 0.67, "aroma": 0.67},
        )
        self.request = EvaluationRequest(
            domain="cafe",
            dataset_key="dataset-test",
            strategy="D",
            preferences={},
        )

    def test_profiles_cover_single_aspects_and_dimensions(self):
        self.assertEqual(len(self.profiles), 4)
        self.assertEqual(
            {profile.name for profile in self.profiles},
            {"neutral", "solo_sabor", "solo_aroma", "dimension_sensorial"},
        )

    def test_runner_compares_laf_with_pre_rule_evidence(self):
        cases = RecommendationQualityRunner(_EvidenceEvaluator()).run(
            self.request,
            self.profiles,
        )
        by_name = {case.name: case for case in cases}

        self.assertEqual(by_name["solo_sabor"].baseline_winner_id, "producto_a")
        self.assertEqual(by_name["solo_sabor"].laf_winner_id, "producto_a")
        self.assertEqual(by_name["solo_aroma"].baseline_winner_id, "producto_b")
        self.assertTrue(by_name["solo_aroma"].baseline_match)
        self.assertTrue(by_name["solo_aroma"].top3_preference_saturated)
        self.assertEqual(by_name["solo_sabor"].assisted_decision, "clear")
        self.assertEqual(by_name["solo_sabor"].assisted_winner_ids, ("producto_a",))
        self.assertEqual(by_name["solo_sabor"].winner_reasons[0]["aspect"], "sabor")

    def test_reports_do_not_claim_accuracy_before_human_review(self):
        cases = RecommendationQualityRunner(_EvidenceEvaluator()).run(
            self.request,
            self.profiles,
        )
        summary = summarize_quality(cases)

        self.assertEqual(summary["reviewed_cases"], 0)
        self.assertIsNone(summary["human_winner_accuracy"])
        with TemporaryDirectory() as temporary:
            paths = write_quality_reports(
                Path(temporary),
                metadata={"dataset_key": "dataset-test", "strategy": "D"},
                cases=cases,
            )
            self.assertIn(
                "La exactitud todavía no está medida",
                paths["markdown"].read_text(encoding="utf-8"),
            )
            review = json.loads(paths["review"].read_text(encoding="utf-8"))
            self.assertTrue(all(row["review_status"] == "pending" for row in review["cases"]))
            self.assertTrue(review["cases"][0]["candidate_options_from_evidence_baseline"])
            self.assertTrue(paths["assisted_markdown"].is_file())
            assisted = json.loads(paths["assisted_json"].read_text(encoding="utf-8"))
            self.assertFalse(assisted["rubric"]["laf_result_used_for_proposal"])
            self.assertEqual(assisted["cases"][1]["review_status"], "pending")

    def test_approved_expectation_enables_human_accuracy(self):
        expectations = {
            "solo_sabor": {
                "review_status": "approved",
                "expected_winner_ids": ["producto_a"],
                "expected_top3_ids": ["producto_a", "producto_b"],
                "rationale": "Producto A tiene la evidencia más fuerte de sabor.",
                "reviewer": "Experta",
                "reviewed_at": "2026-08-29",
            }
        }
        cases = RecommendationQualityRunner(_EvidenceEvaluator()).run(
            self.request,
            self.profiles,
            expectations=expectations,
        )
        summary = summarize_quality(cases)

        self.assertEqual(summary["reviewed_cases"], 1)
        self.assertEqual(summary["human_winner_accuracy"], 1.0)
        with TemporaryDirectory() as temporary:
            paths = write_quality_reports(
                Path(temporary),
                metadata={"dataset_key": "dataset-test", "strategy": "D"},
                cases=cases,
            )
            report = paths["markdown"].read_text(encoding="utf-8")
            csv_report = paths["csv"].read_text(encoding="utf-8-sig")

        self.assertIn("Validación contra la revisión humana asistida", report)
        self.assertIn("Acierto exacto: **1 de 1 (100.0%)**", report)
        self.assertIn("Producto A", report)
        self.assertIn("ganadores_esperados", csv_report)
        self.assertIn("esperado_en_top3_laf", csv_report)

    def test_expectations_file_is_loaded_by_case_name(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "expectations.json"
            path.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "name": "solo_sabor",
                                "review_status": "approved",
                                "expected_winner_ids": ["producto_a"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_expectations(path)

        self.assertEqual(loaded["solo_sabor"]["expected_winner_ids"], ["producto_a"])
