"""Pruebas del paquete de validación humana revisión por revisión."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def load_module():
    path = REPO_ROOT / "src" / "05b_manual_extraction_review.py"
    spec = importlib.util.spec_from_file_location("manual_extraction_review_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


REVIEW = load_module()


class ManualExtractionReviewTests(unittest.TestCase):
    def test_load_excluded_case_ids_combines_previous_sessions(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "primera.json"
            second = Path(temporary) / "segunda.json"
            first.write_text(
                json.dumps({"cases": [{"case_id": "r1|p1"}, {"case_id": "r2|p1"}]}),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps({"cases": [{"case_id": "r2|p1"}, {"case_id": "r3|p2"}]}),
                encoding="utf-8",
            )
            self.assertEqual(
                REVIEW.load_excluded_case_ids([str(first), str(second)]),
                {"r1|p1", "r2|p1", "r3|p2"},
            )

    def test_group_preserves_original_text_and_evidence_chain(self):
        cases = REVIEW.group_review_cases(
            [{
                "review_id": 1, "product_id": "p1", "rate": 5,
                "content": "Buen sabor y aroma", "relevance": 2, "likes": 1,
                "has_media": False, "content_length": 18,
            }],
            [{
                "review_id": 1, "product_id": "p1", "trust_score": 0.5,
                "base_score": 0.2, "relevance_bonus": 0.3,
                "short_penalty": -0.2,
            }],
            [{
                "id": 7, "review_id": 1, "product_id": "p1", "aspect": "sabor",
                "polarity": "pos", "extraction_confidence": 0.8,
                "sentence_excerpt": "Buen sabor y aroma",
            }],
            {"p1": "Café uno"},
        )
        self.assertEqual(cases[0]["content"], "Buen sabor y aroma")
        self.assertEqual(cases[0]["product_name"], "Café uno")
        self.assertEqual(cases[0]["extractions"][0]["effective_evidence"], 0.4)
        self.assertEqual(cases[0]["trust"]["short_penalty"], -0.2)

    def test_selection_is_reproducible_and_diverse(self):
        cases = [
            {
                "case_id": f"c{index}",
                "has_mixed_polarity": index == 0,
                "is_multi_aspect": index < 4,
                "has_negative": index % 2 == 0,
                "minimum_extraction_confidence": 0.5 if index == 5 else 0.8,
            }
            for index in range(12)
        ]
        first = REVIEW.choose_review_cases(cases, 8, 123)
        second = REVIEW.choose_review_cases(cases, 8, 123)
        self.assertEqual([item["case_id"] for item in first], [item["case_id"] for item in second])
        self.assertIn("c0", {item["case_id"] for item in first})
        self.assertEqual(len(first), 8)

    def test_packet_creates_one_file_per_review_and_preserves_answers(self):
        case = {
            "case_id": "1|p1", "review_id": "1", "product_id": "p1",
            "product_name": "Café uno", "rate": 5, "content": "Buen sabor",
            "review_metadata": {"relevance": 1, "likes": 0, "has_media": False, "content_length": 11},
            "trust": {
                "trust_score": 0.5, "base_score": 0.2, "rate_bonus": 0,
                "relevance_bonus": 0.3, "media_bonus": 0, "likes_bonus": 0,
                "flag_penalty": 0, "short_penalty": 0,
            },
            "extractions": [{
                "extraction_id": 7, "aspect": "sabor", "polarity": "pos",
                "extraction_confidence": 0.8, "sentence_excerpt": "Buen sabor",
                "effective_evidence": 0.4,
            }],
            "selection_reason": "general",
        }
        with tempfile.TemporaryDirectory() as temporary:
            paths = REVIEW.write_review_packet(
                Path(temporary), dataset_key="dataset", cases=[case], seed=123,
            )
            self.assertIn("Buen sabor", Path(paths["case_files"][0]).read_text(encoding="utf-8"))
            answers = json.loads(Path(paths["responses"]).read_text(encoding="utf-8"))
            self.assertEqual(answers["cases"][0]["review_status"], "pending")
            Path(paths["responses"]).write_text('{"preserved": true}', encoding="utf-8")
            REVIEW.write_review_packet(Path(temporary), dataset_key="dataset", cases=[case], seed=123)
            self.assertEqual(json.loads(Path(paths["responses"]).read_text()), {"preserved": True})


if __name__ == "__main__":
    unittest.main()
