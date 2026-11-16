import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from recommender.services.blind_review import build_blind_profiles, write_blind_review_packet


class BlindReviewTests(SimpleTestCase):
    def test_profiles_are_mixed_and_do_not_contain_single_aspect_cases(self):
        profiles = build_blind_profiles(
            {"sabor": "Sabor", "aroma": "Aroma", "rendimiento": "Rendimiento"},
            case_count=2,
        )
        self.assertEqual(len(profiles), 2)
        self.assertEqual(set(profiles[0].preferences.values()), {0.33, 0.67, 1.0})
        self.assertEqual(sum(value > 0 for value in profiles[0].preferences.values()), 3)
        self.assertNotEqual(profiles[0].preferences, profiles[1].preferences)

    def test_packet_has_no_laf_results_and_preserves_all_review_texts(self):
        profiles = build_blind_profiles(
            {"sabor": "Sabor", "aroma": "Aroma", "rendimiento": "Rendimiento"},
            case_count=1,
        )
        products = {
            "P1": {"name": "Café uno", "price_min": 100, "price_max": 120, "n_items": 2},
            "P2": {"name": "Café dos", "price_min": 90, "price_max": 90, "n_items": 1},
        }
        rows = [
            {
                "product_id": "P1", "review_id": "R1", "rate": 5,
                "content": "Muy buen sabor", "aspect": "sabor", "polarity": "pos",
                "trust_score": 0.8, "extraction_confidence": 0.9,
            },
            {
                "product_id": "P1", "review_id": "R2", "rate": 2,
                "content": "No tiene aroma", "aspect": "aroma", "polarity": "neg",
                "trust_score": 0.7, "extraction_confidence": 0.8,
            },
        ]
        with TemporaryDirectory() as temporary:
            paths = write_blind_review_packet(
                Path(temporary), metadata={"dataset_key": "dataset"}, products=products,
                aspect_labels={"sabor": "Sabor", "aroma": "Aroma", "rendimiento": "Rendimiento"},
                profiles=profiles, review_rows=rows, samples_per_polarity=1,
                candidates_per_case=2,
            )
            manifest = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
            self.assertFalse(manifest["contains_system_results"])
            self.assertNotIn("winner", json.dumps(manifest).casefold())
            case_text = Path(paths["case_files"][0]).read_text(encoding="utf-8")
            self.assertIn("Muy buen sabor", case_text)
            self.assertIn("No tiene aroma", case_text)
            self.assertNotIn("puntaje post-LAF", case_text)
            with Path(paths["reading_csv"]).open(encoding="utf-8-sig", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual({row["texto_original"] for row in csv_rows}, {"Muy buen sabor", "No tiene aroma"})

    def test_compact_packet_limits_candidates_without_using_ranking_fields(self):
        profiles = build_blind_profiles(
            {"sabor": "Sabor", "aroma": "Aroma", "rendimiento": "Rendimiento"},
            case_count=2,
        )
        products = {f"P{index}": {"name": f"Café {index}"} for index in range(1, 7)}
        rows = [
            {
                "product_id": product_id,
                "review_id": f"{product_id}-{aspect}",
                "rate": 5,
                "content": f"Opinión de {product_id} sobre {aspect}",
                "aspect": aspect,
                "polarity": "pos",
                "trust_score": 0.8,
                "extraction_confidence": 0.8,
            }
            for product_id in products
            for aspect in ("sabor", "aroma", "rendimiento")
        ]
        with TemporaryDirectory() as temporary:
            paths = write_blind_review_packet(
                Path(temporary),
                metadata={"dataset_key": "dataset"},
                products=products,
                aspect_labels={"sabor": "Sabor", "aroma": "Aroma", "rendimiento": "Rendimiento"},
                profiles=profiles,
                review_rows=rows,
                samples_per_polarity=1,
                candidates_per_case=4,
            )
            manifest = json.loads(Path(paths["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(paths["candidate_count"], 4)
            self.assertTrue(all(len(case["candidate_codes"]) == 4 for case in manifest["cases"]))
            self.assertNotIn("ranking", json.dumps(manifest).casefold())
