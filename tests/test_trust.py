"""Pruebas de trust individual, estrategias y operaciones resilientes de 06."""

from __future__ import annotations

import importlib.util
import math
import os
import sys
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import Mock, patch

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def load_trust_module():
    """Importa 06 sin ejecutar el pipeline ni exigir credenciales."""
    path = REPO_ROOT / "src" / "06_trust.py"
    spec = importlib.util.spec_from_file_location("trust_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TRUST = load_trust_module()


class RpcResponse:
    """Respuesta minima compatible con el cliente de Supabase."""

    def __init__(self, data=None):
        self.data = data


class RpcRequest:
    """Peticion diferida usada para registrar la llamada a ``execute``."""

    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class RpcClient:
    """Cliente falso que permite comprobar nombre y parametros de una RPC."""

    def __init__(self, response_data=None):
        self.calls = []
        self.response_data = response_data or {}

    def rpc(self, name, params):
        self.calls.append((name, params))
        return RpcRequest(RpcResponse(self.response_data))


class TrustScoreTests(unittest.TestCase):
    def test_import_is_free_of_runtime_configuration(self):
        self.assertEqual(TRUST.SUPABASE_URL, "")
        self.assertEqual(TRUST.DATASET_KEY, "")
        self.assertEqual(TRUST.DOMAIN, {})

    def test_trust_ignores_rating_and_forbidden_words(self):
        base = {
            "relevance": 10,
            "likes": 2,
            "has_media": False,
            "content_length": 50,
        }
        low_rating = TRUST.compute_trust(
            {**base, "rate": 1, "forbidden_words": 10}
        )
        high_rating = TRUST.compute_trust(
            {**base, "rate": 5, "forbidden_words": 0}
        )
        self.assertEqual(low_rating, high_rating)
        self.assertEqual(low_rating["rate_bonus"], 0.0)
        self.assertEqual(low_rating["flag_penalty"], 0.0)

    def test_calibrated_media_bonus_and_short_penalty_have_magnitude_015(self):
        base = {
            "relevance": 0,
            "likes": 0,
            "has_media": False,
            "content_length": 50,
        }
        media = TRUST.compute_trust({**base, "has_media": True})
        short = TRUST.compute_trust({**base, "content_length": 19})
        self.assertEqual(media["media_bonus"], 0.15)
        self.assertEqual(media["trust_score"], 0.45)
        self.assertEqual(short["short_penalty"], -0.15)
        self.assertEqual(short["trust_score"], 0.15)

    def test_trust_is_clamped_and_negative_inputs_do_not_subtract(self):
        low = TRUST.compute_trust(
            {
                "relevance": -100,
                "likes": -5,
                "has_media": False,
                "content_length": 0,
            }
        )
        high = TRUST.compute_trust(
            {
                "relevance": 10_000,
                "likes": 10_000,
                "has_media": True,
                "content_length": 100,
            }
        )
        self.assertGreaterEqual(low["trust_score"], 0.0)
        self.assertLessEqual(high["trust_score"], 1.0)

    def test_extraction_confidence_must_be_a_finite_probability(self):
        for invalid in (-0.1, 1.1, float("nan"), "texto"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(RuntimeError, "\[0, 1\]|numerico"):
                    TRUST.unit_interval(invalid, "extraction_confidence")

    def test_strategy_d_is_symmetric_and_does_not_create_absent_fact(self):
        positive = TRUST.evidence_share("D", "pos", 3.0, 3.0, 1.0, 4)
        negative = TRUST.evidence_share("D", "neg", 1.0, 3.0, 1.0, 4)
        self.assertTrue(math.isclose(positive + negative, 1.0, abs_tol=1e-4))

        rows = TRUST.build_product_aspect_rows(
            {("p1", "sabor"): {"pos": [0.8], "neg": []}},
            {("p1", "sabor", "pos"): 1},
            {},
            "D",
            "dataset-a",
        )
        self.assertEqual([row["polarity"] for row in rows], ["pos"])
        self.assertEqual(rows[0]["evidence_weight"], 0.8)
        self.assertEqual(rows[0]["total_evidence_weight"], 0.8)
        self.assertAlmostEqual(rows[0]["belief_mass"], 0.07407407)
        self.assertAlmostEqual(rows[0]["uncertainty"], 0.92592593)
        self.assertEqual(rows[0]["agg_confidence"], 0.537)

    def test_strategy_d_persists_evidence_and_uncertainty(self):
        rows = TRUST.build_product_aspect_rows(
            {
                ("p1", "sabor"): {
                    "pos": [1.0] * 6,
                    "neg": [1.0] * 4,
                }
            },
            defaultdict(int),
            {},
            "D",
            "dataset-a",
        )
        by_polarity = {row["polarity"]: row for row in rows}
        self.assertEqual(by_polarity["pos"]["evidence_weight"], 6.0)
        self.assertEqual(by_polarity["neg"]["evidence_weight"], 4.0)
        self.assertEqual(by_polarity["pos"]["total_evidence_weight"], 10.0)
        self.assertEqual(by_polarity["pos"]["belief_mass"], 0.3)
        self.assertEqual(by_polarity["neg"]["belief_mass"], 0.2)
        self.assertEqual(by_polarity["pos"]["uncertainty"], 0.5)
        self.assertEqual(by_polarity["neg"]["uncertainty"], 0.5)
        self.assertEqual(by_polarity["pos"]["agg_confidence"], 0.55)
        self.assertEqual(by_polarity["neg"]["agg_confidence"], 0.45)

        self.assertAlmostEqual(
            by_polarity["pos"]["belief_mass"]
            + by_polarity["neg"]["belief_mass"]
            + by_polarity["pos"]["uncertainty"],
            1.0,
        )
        for polarity, row in by_polarity.items():
            prior_share = (
                TRUST.PRIOR_MEAN
                if polarity == "pos"
                else 1.0 - TRUST.PRIOR_MEAN
            )
            self.assertAlmostEqual(
                row["agg_confidence"],
                row["belief_mass"] + prior_share * row["uncertainty"],
                places=4,
            )

    def test_equal_projection_can_have_different_uncertainty(self):
        rows = TRUST.build_product_aspect_rows(
            {
                ("few", "sabor"): {"pos": [0.2], "neg": [0.2]},
                ("many", "sabor"): {
                    "pos": [1.0] * 50,
                    "neg": [1.0] * 50,
                },
            },
            defaultdict(int),
            {},
            "D",
            "dataset-a",
        )
        positive = {
            row["product_id"]: row
            for row in rows
            if row["polarity"] == "pos"
        }
        self.assertEqual(positive["few"]["agg_confidence"], 0.5)
        self.assertEqual(positive["many"]["agg_confidence"], 0.5)
        self.assertAlmostEqual(positive["few"]["uncertainty"], 0.96153846)
        self.assertAlmostEqual(positive["many"]["uncertainty"], 0.09090909)

    def test_strategy_d_converges_to_unregularized_evidence(self):
        raw = TRUST.evidence_share("E", "pos", 6.0, 6.0, 4.0, 10)
        sparse = TRUST.evidence_share("D", "pos", 6.0, 6.0, 4.0, 10)
        abundant = TRUST.evidence_share(
            "D",
            "pos",
            6000.0,
            6000.0,
            4000.0,
            10_000,
        )
        self.assertEqual(raw, 0.6)
        self.assertEqual(sparse, 0.55)
        self.assertLess(abs(abundant - raw), abs(sparse - raw))
        self.assertAlmostEqual(abundant, raw, places=3)

    def test_aggregation_rejects_invalid_polarity_or_weights(self):
        with self.assertRaisesRegex(ValueError, "Polaridad"):
            TRUST.evidence_share("D", "neu", 1.0, 1.0, 0.0, 1)
        with self.assertRaisesRegex(ValueError, "finitos"):
            TRUST.evidence_share("D", "pos", -1.0, -1.0, 0.0, 1)

    def test_strategy_b_applies_threshold_per_polarity(self):
        rows = TRUST.build_product_aspect_rows(
            {
                ("p1", "sabor"): {
                    "pos": [0.8] * TRUST.MIN_REVIEWS,
                    "neg": [0.7],
                }
            },
            defaultdict(int),
            {},
            "B",
            "dataset-a",
        )
        self.assertEqual([row["polarity"] for row in rows], ["pos"])

    def test_strategy_c_uses_catalog_only_without_any_reviews(self):
        catalog = {("p1", "wifi", "pos"): TRUST.CATALOG_CONF}
        with_negative_review = TRUST.build_product_aspect_rows(
            {("p1", "wifi"): {"pos": [], "neg": [0.8]}},
            defaultdict(int),
            catalog,
            "C",
            "dataset-a",
        )
        self.assertEqual(len(with_negative_review), 1)
        self.assertEqual(with_negative_review[0]["polarity"], "neg")
        self.assertFalse(with_negative_review[0]["from_catalog"])

        without_reviews = TRUST.build_product_aspect_rows(
            {},
            defaultdict(int),
            catalog,
            "C",
            "dataset-a",
        )
        self.assertEqual(len(without_reviews), 1)
        self.assertTrue(without_reviews[0]["from_catalog"])

    def test_repeated_mentions_keep_maximum_effective_evidence(self):
        trust_map = {(1, "p1"): 0.8}
        evidence = {}
        mentions = defaultdict(int)
        rows = [
            {
                "review_id": 1,
                "product_id": "p1",
                "aspect": "sabor",
                "polarity": "pos",
                "extraction_confidence": 0.5,
            },
            {
                "review_id": 1,
                "product_id": "p1",
                "aspect": "sabor",
                "polarity": "pos",
                "extraction_confidence": 0.9,
            },
        ]
        TRUST.add_aspect_evidence(rows, trust_map, evidence, mentions)
        self.assertEqual(len(evidence), 1)
        self.assertAlmostEqual(next(iter(evidence.values())), 0.72)
        self.assertEqual(mentions[("p1", "sabor", "pos")], 2)

    def test_zero_effective_evidence_never_creates_a_fact(self):
        evidence = {}
        mentions = defaultdict(int)
        TRUST.add_aspect_evidence(
            [
                {
                    "review_id": 1,
                    "product_id": "p1",
                    "aspect": "sabor",
                    "polarity": "pos",
                    "extraction_confidence": 0.0,
                }
            ],
            {(1, "p1"): 0.8},
            evidence,
            mentions,
        )
        self.assertEqual(evidence, {})
        self.assertEqual(mentions[("p1", "sabor", "pos")], 1)

        with patch.object(TRUST, "MIN_REVIEWS", 1):
            for strategy in TRUST.STRATEGIES:
                with self.subTest(strategy=strategy):
                    empty_rows = TRUST.build_product_aspect_rows(
                        {("p1", "sabor"): {"pos": [0.0], "neg": []}},
                        mentions,
                        {},
                        strategy,
                        "dataset-a",
                    )
                    self.assertEqual(empty_rows, [])
                    rows = TRUST.build_product_aspect_rows(
                        {("p1", "sabor"): {"pos": [0.0], "neg": [0.8]}},
                        mentions,
                        {},
                        strategy,
                        "dataset-a",
                    )
                    self.assertNotIn("pos", [row["polarity"] for row in rows])

    def test_only_strategy_d_exposes_the_regularized_decomposition(self):
        grouped = {("p1", "sabor"): {"pos": [0.8], "neg": [0.4]}}
        diagnostic_fields = (
            "evidence_weight",
            "total_evidence_weight",
            "belief_mass",
            "uncertainty",
        )
        with patch.object(TRUST, "MIN_REVIEWS", 1):
            for strategy in ("A", "B", "C", "E"):
                rows = TRUST.build_product_aspect_rows(
                    grouped,
                    defaultdict(int),
                    {},
                    strategy,
                    "dataset-a",
                )
                for row in rows:
                    self.assertTrue(
                        all(row[field] is None for field in diagnostic_fields)
                    )

        catalog_rows = TRUST.build_product_aspect_rows(
            {},
            defaultdict(int),
            {("p1", "wifi", "pos"): TRUST.CATALOG_CONF},
            "C",
            "dataset-a",
        )
        self.assertTrue(
            all(catalog_rows[0][field] is None for field in diagnostic_fields)
        )

    def test_missing_individual_trust_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "sin trust individual"):
            TRUST.add_aspect_evidence(
                [
                    {
                        "review_id": 1,
                        "product_id": "p1",
                        "aspect": "sabor",
                        "polarity": "pos",
                        "extraction_confidence": 0.8,
                    }
                ],
                {},
                {},
                defaultdict(int),
            )

    def test_catalog_parser_reports_invalid_json(self):
        with self.assertRaisesRegex(ValueError, "JSON de atributos invalido"):
            TRUST.parse_catalog_attributes("{invalido")
        self.assertEqual(
            TRUST.parse_catalog_attributes('[{"id": "WIFI"}]'),
            [{"id": "WIFI"}],
        )

    def test_cursor_iteration_uses_last_id(self):
        calls = []

        def loader(last_id, page_size):
            calls.append((last_id, page_size))
            if last_id == 0:
                return [{"id": 2}, {"id": 4}]
            if last_id == 4:
                # Una pagina corta no prueba EOF: PostgREST puede imponer un
                # limite menor que el solicitado.
                return [{"id": 8}]
            return []

        pages = list(TRUST.iter_cursor_pages(loader, page_size=2))
        self.assertEqual(pages, [[{"id": 2}, {"id": 4}], [{"id": 8}]])
        self.assertEqual(calls, [(0, 2), (4, 2), (8, 2)])

    def test_cursor_rejects_a_page_that_does_not_advance(self):
        def loader(last_id, _page_size):
            return [{"id": 1}] if last_id == 0 else [{"id": 1}]

        with self.assertRaisesRegex(RuntimeError, "fuera de orden"):
            list(TRUST.iter_cursor_pages(loader, page_size=1))

    def test_transient_operation_is_retried(self):
        calls = 0

        def operation():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ConnectError("temporal")
            return "ok"

        with patch.object(TRUST.time, "sleep"):
            self.assertEqual(TRUST.execute_with_retry(operation, "prueba"), "ok")
        self.assertEqual(calls, 2)

    def test_settings_are_validated_at_runtime(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SUPABASE_URL"):
                TRUST.load_settings()

    def test_finalize_sends_exact_counts_for_every_strategy(self):
        client = RpcClient()
        counts = {"A": 10, "B": 2, "C": 11, "D": 10, "E": 10}
        TRUST.finalize_trust_run(
            client,
            "dataset-a",
            "run-a",
            list(TRUST.STRATEGIES),
            25,
            counts,
        )
        self.assertEqual(len(client.calls), 1)
        name, params = client.calls[0]
        self.assertEqual(name, TRUST.FINALIZE_RPC)
        self.assertEqual(params["p_expected_fact_rows"], sum(counts.values()))
        self.assertEqual(params["p_expected_fact_rows_by_strategy"], counts)

    def test_finalize_reports_a_superseded_or_stale_activation(self):
        for response, message in (
            ({"superseded": True}, "mas nueva"),
            ({"source_changed": True}, "fuentes cambiaron"),
        ):
            with self.subTest(response=response):
                client = RpcClient(response)
                with self.assertRaisesRegex(RuntimeError, message):
                    TRUST.finalize_trust_run(
                        client,
                        "dataset-a",
                        "run-a",
                        list(TRUST.STRATEGIES),
                        0,
                        {strategy: 0 for strategy in TRUST.STRATEGIES},
                    )

    def test_only_schema_errors_are_reported_as_missing_migration(self):
        class FakeError(Exception):
            def __init__(self, code):
                super().__init__(code)
                self.code = code

        self.assertTrue(TRUST.is_missing_staging_setup(FakeError("42P01")))
        self.assertTrue(TRUST.is_missing_staging_setup(FakeError("PGRST202")))
        self.assertFalse(TRUST.is_missing_staging_setup(FakeError("23514")))

    def test_cli_strategy_parameters_are_auditable(self):
        original = (
            TRUST.LOG_REF,
            TRUST.MIN_REVIEWS,
            TRUST.CATALOG_CONF,
            TRUST.PRIOR_WEIGHT,
        )
        try:
            TRUST.configure_strategy_parameters(
                log_ref=100,
                min_reviews=10,
                catalog_confidence=0.8,
                prior_weight=5.0,
            )
            params = TRUST.strategy_parameters()
            self.assertEqual(params["log_ref"], 100)
            self.assertEqual(params["min_reviews_per_polarity"], 10)
            self.assertEqual(params["prior_weight"], 5.0)
            self.assertEqual(params["primary_strategy"], "D")
            self.assertEqual(params["methodology_version"], 4)
            self.assertEqual(params["trust_weights"]["media"], 0.15)
            self.assertEqual(params["trust_weights"]["short_penalty"], -0.15)
            self.assertEqual(
                params["d_decomposition"]["stored_for_strategy"],
                "D",
            )
        finally:
            TRUST.configure_strategy_parameters(
                log_ref=original[0],
                min_reviews=original[1],
                catalog_confidence=original[2],
                prior_weight=original[3],
            )

    def test_prior_weight_must_be_finite_and_configuration_is_atomic(self):
        original = (
            TRUST.LOG_REF,
            TRUST.MIN_REVIEWS,
            TRUST.CATALOG_CONF,
            TRUST.PRIOR_WEIGHT,
        )
        for invalid in (float("nan"), float("inf"), float("-inf"), 0.0, -1.0):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(RuntimeError, "positivos"):
                    TRUST.configure_strategy_parameters(
                        log_ref=100,
                        min_reviews=10,
                        catalog_confidence=0.8,
                        prior_weight=invalid,
                    )
                self.assertEqual(
                    (
                        TRUST.LOG_REF,
                        TRUST.MIN_REVIEWS,
                        TRUST.CATALOG_CONF,
                        TRUST.PRIOR_WEIGHT,
                    ),
                    original,
                )

    def test_obsolete_aggregate_functions_were_removed(self):
        for name in (
            "aggregate_A",
            "aggregate_B",
            "aggregate_C",
            "aggregate_D",
            "aggregate_E",
        ):
            self.assertFalse(hasattr(TRUST, name))

    def test_run_rebuilds_all_strategies_in_one_finalize_call(self):
        client = object()
        build = Mock(return_value=[])
        finalize = Mock()
        with (
            patch.object(TRUST, "DATASET_KEY", "dataset-a"),
            patch.object(TRUST, "initialize_runtime"),
            patch.object(TRUST, "create_client", return_value=client),
            patch.object(
                TRUST,
                "require_included_product_ids",
                return_value={"p1"},
            ),
            patch.object(TRUST, "begin_trust_run"),
            patch.object(
                TRUST,
                "calculate_review_trust",
                return_value=({(1, "p1"): 0.8}, {0.8: 1}),
            ),
            patch.object(
                TRUST,
                "calculate_aspect_evidence",
                return_value=({}, defaultdict(int)),
            ),
            patch.object(TRUST, "load_catalog_evidence", return_value={}),
            patch.object(TRUST, "build_product_aspect_rows", build),
            patch.object(TRUST, "upsert_staging_rows"),
            patch.object(TRUST, "finalize_trust_run", finalize),
            patch("builtins.print"),
        ):
            TRUST.run("D")

        self.assertEqual(
            [item.args[3] for item in build.call_args_list],
            list(TRUST.STRATEGIES),
        )
        finalize.assert_called_once()
        self.assertEqual(
            finalize.call_args.args[-1],
            {strategy: 0 for strategy in TRUST.STRATEGIES},
        )

    def test_run_discards_staging_when_processing_fails(self):
        client = object()
        discard = Mock()
        with (
            patch.object(TRUST, "DATASET_KEY", "dataset-a"),
            patch.object(TRUST, "initialize_runtime"),
            patch.object(TRUST, "create_client", return_value=client),
            patch.object(
                TRUST,
                "require_included_product_ids",
                return_value={"p1"},
            ),
            patch.object(TRUST, "begin_trust_run"),
            patch.object(
                TRUST,
                "calculate_review_trust",
                side_effect=RuntimeError("fallo controlado"),
            ),
            patch.object(TRUST, "discard_trust_run", discard),
            patch("builtins.print"),
        ):
            with self.assertRaisesRegex(RuntimeError, "fallo controlado"):
                TRUST.run("all")
        discard.assert_called_once()


class TrustDatabaseContractTests(unittest.TestCase):
    def test_schema_and_migration_expose_the_atomic_contract(self):
        required_fragments = (
            "trust_source_state",
            "trg_review_aspects_trust_revision",
            "guard_trust_staging_write",
            "p_expected_fact_rows_by_strategy jsonb",
            "source_changed",
            "hashtextextended('06_trust:'",
        )
        for relative_path in (
            "database/schema.sql",
            "database/20260805_trust_staging.sql",
        ):
            with self.subTest(path=relative_path):
                sql = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
                for fragment in required_fragments:
                    self.assertIn(fragment, sql)

    def test_schema_and_migration_persist_the_d_decomposition(self):
        required_fragments = (
            "evidence_weight double precision",
            "total_evidence_weight double precision",
            "belief_mass",
            "uncertainty",
            "product_aspect_trust_decomposition_check",
            "agg_confidence, evidence_weight, total_evidence_weight",
            "belief_mass, uncertainty",
        )
        for relative_path in (
            "database/schema.sql",
            "database/20260807_trust_uncertainty.sql",
        ):
            with self.subTest(path=relative_path):
                sql = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
                for fragment in required_fragments:
                    self.assertIn(fragment, sql)

    def test_laf_generator_keeps_catalog_source_separate(self):
        source = (REPO_ROOT / "src" / "08_laf1_generate.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('default="D"', source)
        self.assertIn('pred = "catalogoDeclara"', source)
        self.assertIn('conf = e["agg_confidence"]', source)
        self.assertNotIn('e["uncertainty"]', source)
        self.assertNotIn('"C": "Catalogo como base garantizada"', source)


if __name__ == "__main__":
    unittest.main()
