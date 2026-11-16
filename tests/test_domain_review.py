"""Pruebas de la lógica pura usada por el panel de revisión del dominio."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))


def load_module():
    path = SRC_DIR / "04_domain_review.py"
    spec = importlib.util.spec_from_file_location("domain_review_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


REVIEW = load_module()


def sample_report():
    return {
        "dataset": {"dataset_key": "cafe-dataset", "category_label": "Cafe"},
        "candidates": [
            {
                "term": "sabor",
                "aspect_key_sugerido": "sabor",
                "reviews_mencion": 10,
                "oraciones_mencion": 12,
                "polaridad_neta": 0.2,
                "examples": ["buen sabor"],
            },
            {
                "term": "aroma",
                "aspect_key_sugerido": "aroma",
                "reviews_mencion": 8,
                "oraciones_mencion": 9,
                "polaridad_neta": 0.1,
                "examples": ["aroma intenso"],
            },
        ],
    }


class DomainReviewStateTests(unittest.TestCase):
    def test_search_filters_view_without_deleting_hidden_rows(self):
        complete = pd.DataFrame([
            {"termino": "sabor", "accion": "dudoso", "grupo": "", "ejemplos": "rico", "motivo_llm": ""},
            {"termino": "aroma", "accion": "dudoso", "grupo": "", "ejemplos": "intenso", "motivo_llm": ""},
        ])
        visible = REVIEW.filter_candidate_rows(complete, "sabor")
        visible.loc[:, "accion"] = "aspecto"
        visible.loc[:, "grupo"] = "sabor"

        merged = REVIEW.merge_visible_edits(complete, visible)

        self.assertEqual(len(merged), 2)
        self.assertEqual(
            merged.set_index("termino").loc["sabor", "accion"],
            "aspecto",
        )
        self.assertEqual(
            merged.set_index("termino").loc["aroma", "accion"],
            "dudoso",
        )

    def test_domain_rule_has_priority_over_global_rule(self):
        global_rules = {"term_actions": [{
            "terms": ["cuerpo"], "action": "descartar", "reason": "global"
        }]}
        domain_rules = {"term_actions": [{
            "terms": ["cuerpo"], "action": "aspecto", "group": "cuerpo", "reason": "dominio"
        }]}
        report = sample_report()
        report["candidates"] = [{
            "term": "cuerpo", "reviews_mencion": 5, "oraciones_mencion": 5
        }]

        rows = REVIEW.rows_from_report(
            report,
            1,
            {},
            global_rules,
            domain_rules,
        )

        self.assertEqual(rows.iloc[0]["accion"], "aspecto")
        self.assertEqual(rows.iloc[0]["alcance_regla"], "dominio")


class DomainReviewArtifactTests(unittest.TestCase):
    def test_llm_payload_must_match_domain_report_and_status(self):
        report = sample_report()
        payload = {
            "domain_key": "cafe",
            "status": "complete",
            "run_signature": {"report_hash": REVIEW.stable_hash(report)},
            "suggestions": [],
            "groups": [],
            "domain_notes": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "llm.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = REVIEW.load_llm_payload(path, report, "cafe")
            self.assertEqual(loaded["domain_key"], "cafe")

            payload["run_signature"]["report_hash"] = "otro"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "otra versión"):
                REVIEW.load_llm_payload(path, report, "cafe")

    def test_invalid_saved_json_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            path.write_text("{invalido", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "JSON válido"):
                REVIEW.load_optional_json(path)

    def test_save_json_is_atomic(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            REVIEW.save_json(path, {"ok": True})
            self.assertEqual(REVIEW.load_json(path), {"ok": True})
            self.assertFalse(list(Path(temporary).glob("*.tmp")))


class DomainReviewConfigTests(unittest.TestCase):
    def test_duplicate_aspect_rows_are_merged(self):
        preview = {
            "quality_aspects": {},
            "lexicon": {"aspects": {}, "positive": [], "negative": [], "negation": []},
        }
        aspects = pd.DataFrame([
            {"usar": True, "grupo": "sabor", "nombre_visible": "Sabor", "terminos": "rico"},
            {"usar": True, "grupo": "sabor", "nombre_visible": "Sabor", "terminos": "sabroso"},
        ])
        polarity = pd.DataFrame(columns=["usar", "tipo", "termino"])

        edited = REVIEW.apply_lexicon_edits(preview, aspects, polarity)

        self.assertEqual(edited["lexicon"]["aspects"]["sabor"], ["rico", "sabroso"])

    def test_profile_validation_detects_ambiguous_terms_and_polarity(self):
        config = {
            "domain_key": "cafe",
            "quality_aspects": {
                "sabor": {"label": "Sabor"},
                "aroma": {"label": "Aroma"},
            },
            "lexicon": {
                "aspects": {"sabor": ["rico"], "aroma": ["Ríco"]},
                "positive": ["bueno"],
                "negative": ["Bueno"],
                "negation": ["no"],
            },
        }

        errors = REVIEW.validate_domain_config(config, "cafe")

        self.assertTrue(any("aparece" in error for error in errors))
        self.assertTrue(any("positive y negative" in error for error in errors))

    def test_existing_domain_profiles_pass_validation(self):
        paths = [
            path
            for path in (REPO_ROOT / "config" / "domains").glob("*.json")
            if not path.name.endswith((".draft.json", ".curation_rules.json"))
        ]
        for path in paths:
            with self.subTest(path=path.name):
                config = REVIEW.load_json(path)
                if "lexicon" not in config:
                    continue
                self.assertEqual(
                    REVIEW.validate_domain_config(config, config["domain_key"]),
                    [],
                )


if __name__ == "__main__":
    unittest.main()
