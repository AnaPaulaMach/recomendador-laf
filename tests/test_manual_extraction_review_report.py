"""Pruebas del resumen de validación manual de extracción."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module():
    path = REPO_ROOT / "src" / "05c_manual_extraction_review_report.py"
    spec = importlib.util.spec_from_file_location("manual_extraction_review_report_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


REPORT = load_module()


class ManualExtractionReviewReportTests(unittest.TestCase):
    def test_summary_separates_errors_omissions_and_trust(self):
        payload = {
            "dataset_key": "dataset",
            "cases": [
                {
                    "case_number": 1,
                    "review_status": "reviewed",
                    "extraction_decisions": [
                        {"extraction_id": 1, "verdict": "correct"},
                        {"extraction_id": 2, "verdict": "wrong_polarity"},
                    ],
                    "missing_aspects": [],
                    "trust_verdict": "reasonable",
                    "reviewer": "Ana",
                },
                {
                    "case_number": 2,
                    "review_status": "reviewed",
                    "extraction_decisions": [
                        {"extraction_id": 3, "verdict": "spurious", "note": "fuera de contexto"},
                    ],
                    "missing_aspects": [
                        {"aspect": "sabor", "polarity": "pos", "evidence": "rico"}
                    ],
                    "trust_verdict": "too_high",
                    "reviewer": "Ana",
                },
            ],
        }
        summary = REPORT.summarize_review(payload)
        self.assertEqual(summary["cases_reviewed"], 2)
        self.assertEqual(summary["decisions_total"], 3)
        self.assertEqual(summary["verdict_counts"]["correct"], 1)
        self.assertEqual(summary["strict_decision_accuracy_pct"], 33.33)
        self.assertEqual(summary["aspect_supported_pct"], 66.67)
        self.assertEqual(summary["polarity_accuracy_on_supported_decisions_pct"], 50.0)
        self.assertEqual(summary["missing_aspects_total"], 1)
        self.assertEqual(summary["exact_case_matches"], 0)
        self.assertIn("muestra es determinística", REPORT.build_markdown(summary))


if __name__ == "__main__":
    unittest.main()
