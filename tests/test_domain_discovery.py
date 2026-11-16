"""Pruebas unitarias para el descubrimiento asistido de aspectos."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))


def load_module():
    path = SRC_DIR / "02_domain_discovery.py"
    spec = importlib.util.spec_from_file_location("domain_discovery_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DISCOVERY = load_module()


class _Response:
    def __init__(self, data):
        self.data = data


class DomainDiscoveryPureTests(unittest.TestCase):
    def test_coffee_dataset_variants_share_the_curated_domain(self):
        for category_label in (
            "Cafe",
            "Café instantáneo",
            "Cafe instantaneo c",
            "Café en granos y molido",
        ):
            with self.subTest(category_label=category_label):
                self.assertEqual(
                    DISCOVERY.domain_key_from_category_label(category_label),
                    "cafe",
                )

    def test_normalize_keyify_and_unicode_fallback(self):
        self.assertEqual(DISCOVERY.normalize("Cámara Frontal"), "camara frontal")
        self.assertEqual(DISCOVERY.keyify("Cámara Frontal"), "camara_frontal")
        terms = DISCOVERY.token_terms_fallback("Cámara rápida y batería")
        self.assertIn("camara", terms)
        self.assertIn("bateria", terms)
        self.assertIn("camara rapida", terms)

    def test_candidate_filter_discards_noise(self):
        excluded = {"producto", "excelente"}
        self.assertFalse(DISCOVERY.is_candidate_term("", excluded))
        self.assertFalse(DISCOVERY.is_candidate_term("123", excluded))
        self.assertFalse(DISCOVERY.is_candidate_term("producto excelente", excluded))
        self.assertTrue(DISCOVERY.is_candidate_term("duracion bateria", excluded))

    def test_global_exclusions_do_not_hide_domain_dependent_terms(self):
        for term in ("minisplit", "tiempo", "equipo", "equipos"):
            self.assertNotIn(term, DISCOVERY.GENERIC_EXCLUDE)

    def test_exploratory_sentiment(self):
        positive = {"bueno", "excelente"}
        negative = {"malo"}
        self.assertEqual(
            DISCOVERY.sentiment_for_sentence("producto excelente", positive, negative),
            "pos",
        )
        self.assertEqual(
            DISCOVERY.sentiment_for_sentence("producto malo", positive, negative),
            "neg",
        )

    def test_invalid_numeric_arguments_are_rejected(self):
        for arguments in (
            ["--limit", "0"],
            ["--page-size", "-1"],
            ["--min-review-mentions", "0"],
            ["--top-terms", "0"],
            ["--draft-aspects", "-1"],
            ["--top-terms", "2", "--draft-aspects", "3"],
            ["--artifact-suffix", "../../otro"],
            ["--artifact-suffix", "con espacios"],
        ):
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit):
                DISCOVERY.parse_args(arguments)

    def test_spacy_fallback_only_accepts_missing_model(self):
        missing_model = mock.Mock()
        missing_model.load.side_effect = OSError("[E050] Can't find model")
        with mock.patch.dict(sys.modules, {"spacy": missing_model}):
            self.assertIsNone(DISCOVERY.load_spacy_model())

        broken_model = mock.Mock()
        broken_model.load.side_effect = RuntimeError("instalación dañada")
        with (
            mock.patch.dict(sys.modules, {"spacy": broken_model}),
            self.assertRaisesRegex(RuntimeError, "dañada"),
        ):
            DISCOVERY.load_spacy_model()


class DomainDiscoveryDatabaseTests(unittest.TestCase):
    def test_fetch_reviews_uses_keyset_pagination_and_skips_empty_content(self):
        query = mock.Mock()
        for method in ("select", "eq", "in_", "gt", "order", "range"):
            getattr(query, method).return_value = query
        query.execute.side_effect = [
            _Response([
                {"id": 1, "review_id": 10, "product_id": "p1", "content": "uno"},
                {"id": 2, "review_id": 11, "product_id": "p1", "content": ""},
            ]),
            _Response([
                {"id": 3, "review_id": 12, "product_id": "p1", "content": "dos"},
            ]),
        ]
        sb = mock.Mock()
        sb.table.return_value = query

        rows = DISCOVERY.fetch_reviews(sb, "reviews_clean", "dataset", 10, 2, {"p1"})

        self.assertEqual([row["id"] for row in rows], [1, 3])
        self.assertEqual(query.gt.call_args_list, [mock.call("id", 0), mock.call("id", 2)])
        query.order.assert_has_calls([mock.call("id"), mock.call("id")])
        query.range.assert_has_calls([mock.call(0, 1), mock.call(0, 1)])


class _Sentence:
    def __init__(self, text: str):
        self.text = text


class _Document:
    def __init__(self, text: str):
        self.sents = [_Sentence(text)]


class _BatchNlp:
    def __init__(self):
        self.calls = []

    def pipe(self, texts, batch_size):
        texts = list(texts)
        self.calls.append((texts, batch_size))
        return [_Document(text) for text in texts]


class DomainDiscoveryProcessingTests(unittest.TestCase):
    def test_build_candidates_uses_spacy_pipe(self):
        nlp = _BatchNlp()
        reviews = [
            {"review_id": 1, "content": "bateria excelente"},
            {"review_id": 2, "content": "bateria excelente"},
        ]
        with mock.patch.object(DISCOVERY, "sentence_terms_spacy", return_value={"bateria"}):
            rows = DISCOVERY.build_candidates(
                reviews,
                {"excelente"},
                {"malo"},
                set(),
                nlp,
            )

        self.assertEqual(len(nlp.calls), 1)
        self.assertEqual(nlp.calls[0][1], 64)
        self.assertEqual(rows[0]["term"], "bateria")
        self.assertEqual(rows[0]["reviews_mencion"], 2)

    def test_reports_and_draft_are_written_with_supplied_lexicon(self):
        rows = [{
            "term": "bateria",
            "aspect_key_sugerido": "bateria",
            "reviews_mencion": 2,
            "oraciones_mencion": 2,
            "pos": 2,
            "neg": 0,
            "neu": 0,
            "polaridad_neta": 1.0,
            "examples": ["bateria excelente"],
        }]
        lexicon = {"positive": ["bueno"], "negative": ["malo"], "negation": ["no"]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports = root / "reportes"
            domains = root / "domains"
            with (
                mock.patch.object(DISCOVERY, "domain_artifact_dir", return_value=reports),
                mock.patch.object(DISCOVERY, "DOMAIN_DIR", domains),
                mock.patch.object(
                    DISCOVERY,
                    "load_base_lexicon",
                    side_effect=AssertionError("no debe releer el lexicon"),
                ),
            ):
                json_path, csv_path = DISCOVERY.write_reports(
                    "cafe", rows, {"category_label": "Café"}, "grano_mx"
                )
                draft_path = DISCOVERY.write_draft_config(
                    "cafe",
                    {"category_label": "Café"},
                    rows,
                    1,
                    lexicon,
                    "grano_mx",
                )

            self.assertTrue(json_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertEqual(json_path.name, "domain_discovery_cafe_grano_mx.json")
            self.assertEqual(csv_path.name, "domain_discovery_cafe_grano_mx.csv")
            self.assertEqual(draft_path.name, "cafe.grano_mx.draft.json")
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["candidates"], rows)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertEqual(draft["lexicon"]["negation"], ["no"])
            self.assertFalse(list(root.rglob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
