"""Pruebas de regresion para la auditoria before/after de aspectos."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def load_audit_module():
    """Importa 05a sin ejecutar su pipeline ni requerir credenciales."""
    path = REPO_ROOT / "src" / "05a_aspect_audit.py"
    spec = importlib.util.spec_from_file_location("aspect_audit_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = load_audit_module()


class AspectAuditTests(unittest.TestCase):
    def test_import_does_not_initialize_credentials_or_domain(self):
        self.assertEqual(AUDIT.SUPABASE_URL, "")
        self.assertEqual(AUDIT.DATASET_KEY, "")
        self.assertEqual(AUDIT.DOMAIN, {})

    def test_positive_int_rejects_zero_and_negative_values(self):
        self.assertEqual(AUDIT.positive_int("3"), 3)
        with self.assertRaises(Exception):
            AUDIT.positive_int("0")
        with self.assertRaises(Exception):
            AUDIT.positive_int("-1")

    def test_fetch_all_uses_last_id_as_cursor(self):
        calls = []

        def loader(last_id, page_size):
            calls.append((last_id, page_size))
            if last_id == 0:
                return [{"id": 1}, {"id": 2}]
            if last_id == 2:
                return [{"id": 5}]
            return []

        rows = AUDIT.fetch_all(loader, page_size=2)

        self.assertEqual(rows, [{"id": 1}, {"id": 2}, {"id": 5}])
        self.assertEqual(calls, [(0, 2), (2, 2)])

    def test_selection_is_reproducible_and_keeps_all_mixed_groups(self):
        groups = [
            {
                "group_id": "mixed",
                "review_id": 1,
                "excerpt": "a",
                "is_multi_aspect": True,
                "is_mixed_signal_candidate": True,
            },
            *[
                {
                    "group_id": f"regular-{index}",
                    "review_id": index + 2,
                    "excerpt": str(index),
                    "is_multi_aspect": True,
                    "is_mixed_signal_candidate": False,
                }
                for index in range(5)
            ],
        ]

        first = AUDIT.choose_audit_groups(groups, 2, 123)
        second = AUDIT.choose_audit_groups(groups, 2, 123)

        self.assertEqual(
            [group["group_id"] for group in first],
            [group["group_id"] for group in second],
        )
        self.assertIn("mixed", {group["group_id"] for group in first})
        self.assertEqual(len(first), 3)

    def test_false_positive_prevents_exact_group_accuracy(self):
        selected = [
            {
                "group_id": "g1",
                "aspects": ["sabor"],
                "current_predictions": {
                    "sabor": ["pos"],
                    "ruido": ["neg"],
                },
            }
        ]
        decisions = {
            "g1": {
                "decision_status": "included",
                "expected": {"sabor": ["pos"]},
            }
        }

        rows, metrics = AUDIT.evaluate_decisions(selected, decisions)

        ruido = next(row for row in rows if row["aspect"] == "ruido")
        self.assertTrue(ruido["is_labeled"])
        self.assertFalse(ruido["is_correct"])
        self.assertEqual(metrics["groups_labeled"], 1)
        self.assertEqual(metrics["groups_exact"], 0)
        self.assertEqual(metrics["aspect_accuracy"], 0.5)

    def test_optional_delta_accepts_missing_accuracy(self):
        self.assertIsNone(AUDIT.optional_delta(None, 0.8))
        self.assertIsNone(AUDIT.optional_delta(0.8, None))
        self.assertEqual(AUDIT.optional_delta(0.9, 0.8), 0.1)

    def test_report_signatures_must_match(self):
        signature = {
            "dataset_key": "d1",
            "domain_key": "cafe",
            "included_products_hash": "a",
            "preferences_hash": "b",
        }
        AUDIT.validate_comparable_reports(
            {"run_signature": signature},
            {"run_signature": dict(signature)},
        )
        with self.assertRaisesRegex(RuntimeError, "dataset_key"):
            AUDIT.validate_comparable_reports(
                {"run_signature": signature},
                {"run_signature": {**signature, "dataset_key": "d2"}},
            )

    def test_strategies_are_discovered_from_data(self):
        before = [
            {
                "strategy": "F",
                "product_id": "p1",
                "aspect": "sabor",
                "polarity": "pos",
                "agg_confidence": 0.5,
                "n_reviews": 1,
                "n_mentions": 1,
                "coverage_ratio": 1.0,
                "from_catalog": False,
            }
        ]
        after = [{**before[0], "agg_confidence": 0.7}]

        _changes, summary = AUDIT.compare_facts(before, after)

        self.assertIn("F", summary)
        self.assertEqual(summary["F"]["changed"], 1)

    def test_fact_comparison_detects_uncertainty_without_changing_proxy(self):
        before = [
            {
                "strategy": "D",
                "product_id": "p1",
                "aspect": "sabor",
                "polarity": "pos",
                "agg_confidence": 0.5,
                "evidence_weight": 0.2,
                "total_evidence_weight": 0.4,
                "belief_mass": 0.01923077,
                "uncertainty": 0.96153846,
                "n_reviews": 1,
                "n_mentions": 1,
                "coverage_ratio": 1.0,
                "from_catalog": False,
            }
        ]
        after = [
            {
                **before[0],
                "evidence_weight": 50.0,
                "total_evidence_weight": 100.0,
                "belief_mass": 0.45454545,
                "uncertainty": 0.09090909,
            }
        ]

        changes, summary = AUDIT.compare_facts(before, after)

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["change_type"], "changed")
        self.assertEqual(changes[0]["confidence_delta"], 0.0)
        self.assertAlmostEqual(changes[0]["uncertainty_delta"], -0.870629)
        self.assertEqual(summary["D"]["changed"], 1)

        before_ranking = AUDIT.evidence_proxy_ranking(
            before,
            {"sabor": 1},
            {"p1": "Uno"},
        )
        after_ranking = AUDIT.evidence_proxy_ranking(
            after,
            {"sabor": 1},
            {"p1": "Uno"},
        )
        self.assertEqual(before_ranking, after_ranking)

    def test_proxy_ranking_keeps_products_without_strategy_d_facts(self):
        facts = [
            {
                "strategy": "D",
                "product_id": "p1",
                "aspect": "sabor",
                "polarity": "pos",
                "agg_confidence": 0.8,
            }
        ]
        ranking = AUDIT.evidence_proxy_ranking(
            facts,
            {"sabor": 1},
            {"p1": "Uno", "p2": "Dos"},
        )

        self.assertEqual([row["product_id"] for row in ranking], ["p1", "p2"])
        self.assertEqual(ranking[1]["proxy_score"], 0.0)

    def test_json_and_csv_writes_are_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_path = root / "report.json"
            csv_path = root / "audit.csv"

            AUDIT.write_json_atomic(json_path, {"ok": True})
            AUDIT.write_csv(
                csv_path,
                [{"group_id": "g1", "signals": [{"polarity": "pos"}]}],
            )

            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), {"ok": True})
            self.assertIn("group_id", csv_path.read_text(encoding="utf-8-sig"))
            self.assertFalse(list(root.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
