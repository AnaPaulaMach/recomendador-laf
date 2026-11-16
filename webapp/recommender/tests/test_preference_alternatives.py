import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from recommender.services.preference_alternatives import (
    AlternativeCase,
    build_weight_sweep_profiles,
    normalized_multicriteria_ranking,
    summarize_alternatives,
    summarize_weight_sweep,
    weighted_confidence_payload,
    write_alternative_reports,
    zero_threshold_payload,
)


def _payload():
    return {
        "facts": [
            {
                "name": "activo",
                "argument": "producto_a",
                "attributes": ["0.9", "0.33"],
                "attributeIntervals": [None, None],
            },
            {
                "name": "inactivo",
                "argument": "producto_a",
                "attributes": ["0.8", "0"],
                "attributeIntervals": [None, None],
            },
        ],
        "rules": [{"headName": "recomendar", "attributes": ["0.8", "1"]}],
        "operations": {"labels": []},
    }


def _case(model, *, winner="producto_a", exact=True, top3=True, score=0.8):
    return AlternativeCase(
        model=model,
        profile_name="solo_sabor",
        profile_title="Sólo sabor",
        profile_kind="single_aspect",
        focused_aspects=("sabor",),
        preferences={"sabor": 1.0, "aroma": 0.0},
        expected_winner_ids=("producto_a",),
        winner_id=winner,
        winner_name=winner.replace("_", " ").title(),
        winner_score=score,
        runner_up_score=0.6,
        margin=score - 0.6,
        top3_ids=(winner, "producto_b"),
        top3_names=(winner, "producto_b"),
        exact_match=exact,
        expected_in_top3=top3,
        high_score=score >= 0.95,
    )


class PreferenceAlternativeTests(SimpleTestCase):
    def test_zero_threshold_removes_inactive_facts_without_mutating_input(self):
        payload = _payload()

        transformed = zero_threshold_payload(payload)

        self.assertEqual([fact["name"] for fact in transformed["facts"]], ["activo"])
        self.assertEqual(len(payload["facts"]), 2)
        self.assertEqual(transformed["rules"], payload["rules"])

    def test_weighted_confidence_scales_low_importance_and_neutralizes_beta(self):
        transformed = weighted_confidence_payload(_payload())

        self.assertEqual(len(transformed["facts"]), 1)
        self.assertAlmostEqual(float(transformed["facts"][0]["attributes"][0]), 0.297)
        self.assertEqual(transformed["facts"][0]["attributes"][1], "1")

    def test_multicriteria_zero_weight_is_invariant(self):
        scores = {
            "sabor": {"a": 0.9, "b": 0.3},
            "aroma": {"a": 0.2, "b": 0.9},
        }
        changed_inactive = {
            **scores,
            "aroma": {"a": 1.0, "b": 0.0},
        }

        first = normalized_multicriteria_ranking(
            scores, {"sabor": 1.0, "aroma": 0.0}, {"a": "A", "b": "B"}
        )
        second = normalized_multicriteria_ranking(
            changed_inactive,
            {"sabor": 1.0, "aroma": 0.0},
            {"a": "A", "b": "B"},
        )

        self.assertEqual(first, second)
        self.assertEqual(first[0]["entity_id"], "a")

    def test_multicriteria_intermediate_weight_changes_influence_gradually(self):
        scores = {
            "sabor": {"a": 0.9, "b": 0.3},
            "aroma": {"a": 0.2, "b": 0.9},
        }
        names = {"a": "A", "b": "B"}

        low = normalized_multicriteria_ranking(
            scores, {"sabor": 1.0, "aroma": 0.33}, names
        )
        medium = normalized_multicriteria_ranking(
            scores, {"sabor": 1.0, "aroma": 0.67}, names
        )
        equal = normalized_multicriteria_ranking(
            scores, {"sabor": 1.0, "aroma": 1.0}, names
        )

        low_gap = float(low[0]["score"]) - float(low[1]["score"])
        medium_gap = float(medium[0]["score"]) - float(medium[1]["score"])
        self.assertGreater(low_gap, medium_gap)
        self.assertEqual(low[0]["entity_id"], "a")
        self.assertEqual(medium[0]["entity_id"], "a")
        self.assertEqual(equal[0]["entity_id"], "b")

    def test_multicriteria_normalization_is_invariant_to_common_scale(self):
        scores = {
            "sabor": {"a": 0.8, "b": 0.4},
            "aroma": {"a": 0.2, "b": 0.9},
        }
        names = {"a": "A", "b": "B"}

        first = normalized_multicriteria_ranking(
            scores, {"sabor": 0.33, "aroma": 0.67}, names
        )
        second = normalized_multicriteria_ranking(
            scores, {"sabor": 0.165, "aroma": 0.335}, names
        )

        self.assertEqual(
            [row["entity_id"] for row in first],
            [row["entity_id"] for row in second],
        )
        for left, right in zip(first, second, strict=True):
            self.assertAlmostEqual(float(left["score"]), float(right["score"]))

    def test_weight_sweep_covers_intermediate_levels_against_neutral_background(self):
        profiles = build_weight_sweep_profiles({"sabor": "Sabor", "aroma": "Aroma"})

        self.assertEqual(len(profiles), 6)
        flavor = [profile for profile in profiles if profile.focused_aspects == ("sabor",)]
        self.assertEqual(
            [profile.preferences["sabor"] for profile in flavor],
            [0.33, 0.67, 1.0],
        )
        self.assertTrue(all(profile.preferences["aroma"] == 0.67 for profile in flavor))

    def test_weight_sweep_summary_detects_winner_and_top3_changes(self):
        base = replace(
            _case("actual"),
            profile_kind="weight_sweep",
            preferences={"sabor": 0.33, "aroma": 0.67},
            expected_winner_ids=(),
            exact_match=None,
            expected_in_top3=None,
        )
        middle = replace(
            base,
            preferences={"sabor": 0.67, "aroma": 0.67},
        )
        high = replace(
            base,
            preferences={"sabor": 1.0, "aroma": 0.67},
            winner_id="producto_b",
            winner_name="Producto B",
            top3_ids=("producto_b", "producto_c"),
            top3_names=("Producto B", "Producto C"),
        )

        summary = summarize_weight_sweep([base, middle, high])["actual"]

        self.assertEqual(summary["aspects"], 1)
        self.assertEqual(summary["winner_changed_aspects"], 1)
        self.assertEqual(summary["top3_changed_aspects"], 1)
        self.assertEqual(summary["score_changed_aspects"], 0)

    def test_summary_and_reports_expose_comparable_metrics_and_caveat(self):
        models = (
            "actual",
            "zero_threshold",
            "weighted_confidence",
            "post_laf_multicriteria",
        )
        cases = [_case(model) for model in models]

        summary = summarize_alternatives(cases)

        self.assertEqual(summary["actual"]["exact_accuracy"], 1.0)
        self.assertEqual(summary["actual"]["dominant_winner_share"], 1.0)
        with TemporaryDirectory() as temporary:
            paths = write_alternative_reports(
                Path(temporary),
                metadata={
                    "dataset_key": "dataset-test",
                    "strategy": "D",
                    "approved_cases": 1,
                },
                cases=cases,
            )
            report = paths["markdown"].read_text(encoding="utf-8")
            data = json.loads(paths["json"].read_text(encoding="utf-8"))

        self.assertIn("no constituyen una evaluación ciega", report)
        self.assertIn("0,33 influye menos", report)
        self.assertEqual(len(data["cases"]), 4)
