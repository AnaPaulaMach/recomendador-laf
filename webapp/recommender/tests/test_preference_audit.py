from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from recommender.domain.contracts import EvaluationRequest, EvaluationResult
from recommender.models import RecommendationSession
from recommender.services.preference_audit import (
    BINARY_LEVELS,
    PreferenceAuditRunner,
    iter_profiles,
    projected_case_count,
    summarize,
    write_reports,
)


class PreferenceProfileTests(TestCase):
    def test_profile_counts_cover_every_aspect_and_pair(self):
        aspects = ("sabor", "aroma", "rendimiento")

        self.assertEqual(projected_case_count(aspects, "quick"), 7)
        self.assertEqual(projected_case_count(aspects, "standard"), 19)
        self.assertEqual(projected_case_count(aspects, "pairwise"), 22)
        self.assertEqual(
            projected_case_count(aspects, "exhaustive", BINARY_LEVELS),
            9,
        )
        pairwise = list(iter_profiles(aspects, mode="pairwise"))
        self.assertEqual(len(pairwise), 22)
        self.assertEqual(
            {profile.aspect for profile in pairwise if profile.kind == "one_hot"},
            set(aspects),
        )

    def test_dry_run_reports_cartesian_size_without_evaluating(self):
        flow = RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="cafe_top20_demo_2026",
            strategy="D",
            quality_preferences={"sabor": 0.67, "aroma": 0.67},
        )
        output = StringIO()

        call_command(
            "audit_preferences",
            flow=str(flow.id),
            mode="exhaustive",
            levels="ui",
            dry_run=True,
            stdout=output,
        )

        self.assertIn("16 casos proyectados", output.getvalue())
        self.assertIn("No se ejecutaron evaluaciones", output.getvalue())


class _PreferenceSensitiveEvaluator:
    def evaluate_products(self, request):
        candidates = [
            ("sabor", "Producto sabor", request.preferences.get("sabor", 0)),
            ("aroma", "Producto aroma", request.preferences.get("aroma", 0)),
            ("estable", "Producto estable", 0.4),
        ]
        candidates.sort(key=lambda item: (-item[2], item[0]))
        return EvaluationResult.from_dict(
            {
                "run_id": "audit-test",
                "evaluation_status": "validated",
                "evaluator_version": "test",
                "operator_profile": "test",
                "dataset_key": request.dataset_key,
                "domain": request.domain,
                "strategy": request.strategy,
                "ranking": [
                    {
                        "entity_id": entity_id,
                        "entity_name": name,
                        "position": position,
                        "final_score": score,
                        "confidence": score,
                        "preference": score,
                    }
                    for position, (entity_id, name, score) in enumerate(candidates, start=1)
                ],
            }
        )


class PreferenceAuditRunnerTests(TestCase):
    def test_runner_detects_winner_changes_and_writes_clear_outputs(self):
        profiles = list(
            iter_profiles(
                ("sabor", "aroma"),
                {"sabor": 0.67, "aroma": 0.67},
                mode="quick",
            )
        )
        cases = PreferenceAuditRunner(_PreferenceSensitiveEvaluator()).run(
            EvaluationRequest(
                domain="cafe",
                dataset_key="dataset-test",
                strategy="D",
                preferences={},
            ),
            profiles,
        )
        summary = summarize(cases)

        self.assertGreaterEqual(summary["distinct_winners"], 2)
        self.assertGreater(summary["winner_change_rate"], 0)
        with TemporaryDirectory() as temporary:
            paths = write_reports(
                Path(temporary),
                metadata={
                    "dataset_key": "dataset-test",
                    "strategy": "D",
                    "mode": "quick",
                    "aspects": ("sabor", "aroma"),
                },
                cases=cases,
            )
            self.assertTrue(paths["json"].is_file())
            self.assertTrue(paths["csv"].is_file())
            self.assertIn("Un único aspecto como prioridad", paths["markdown"].read_text(encoding="utf-8"))
