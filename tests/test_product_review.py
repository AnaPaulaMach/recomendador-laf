"""Pruebas unitarias para la revision humana de productos."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))


def load_reviewer_module():
    path = SRC_DIR / "01b_product_review.py"
    spec = importlib.util.spec_from_file_location("product_reviewer_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


REVIEWER = load_reviewer_module()


class _Response:
    def __init__(self, data):
        self.data = data


class ProductReviewPureTests(unittest.TestCase):
    def test_parse_json_and_text_helpers(self):
        self.assertEqual(REVIEWER.parse_json('{"a": 1}', {}), {"a": 1})
        self.assertEqual(REVIEWER.parse_json("invalido", []), [])
        self.assertEqual(REVIEWER.clean_text("  uno\n dos  "), "uno dos")
        self.assertEqual(REVIEWER.truncate("abcdefgh", 6), "abc...")

    def test_reviewer_prefers_cli_then_environment(self):
        with mock.patch.dict(os.environ, {"PRODUCT_REVIEWER": "  Revisora Env  "}):
            self.assertEqual(REVIEWER.resolve_reviewer(None), "Revisora Env")
            self.assertEqual(
                REVIEWER.resolve_reviewer("  Revisora CLI  "),
                "Revisora CLI",
            )

    def test_product_identity_uses_raw_payload_as_fallback(self):
        raw = {
            "name": "",
            "raw_json": {
                "name": "Producto",
                "family_name": "Familia",
                "domain_id": "DOM",
                "category_id": "CAT",
            },
        }
        self.assertEqual(
            REVIEWER.product_identity(raw, "P"),
            {
                "product_id": "P",
                "name": "Producto",
                "family_name": "Familia",
                "domain_id": "DOM",
                "category_id": "CAT",
            },
        )

    def test_automatic_flags_uses_configurable_non_excluding_threshold(self):
        identity = {"name": "Producto"}
        self.assertIn(
            "evidencia escasa: 4 resenas limpias",
            REVIEWER.automatic_flags(identity, 4, 1, [{}], 5),
        )
        self.assertNotIn(
            "evidencia escasa: 5 resenas limpias",
            REVIEWER.automatic_flags(identity, 5, 1, [{}], 5),
        )


class ProductReviewDatabaseTests(unittest.TestCase):
    def test_fetch_all_uses_id_keyset_pagination(self):
        query = mock.Mock()
        query.select.return_value = query
        query.eq.return_value = query
        query.gt.return_value = query
        query.order.return_value = query
        query.range.return_value = query
        query.execute.side_effect = [
            _Response([
                {"id": 1, "product_id": "p1"},
                {"id": 2, "product_id": "p2"},
            ]),
            _Response([{"id": 3, "product_id": "p3"}]),
        ]
        sb = mock.Mock()
        sb.table.return_value = query

        rows = REVIEWER.fetch_all(
            sb,
            "reviews_clean",
            "product_id",
            "dataset",
            page_size=2,
        )

        self.assertEqual([row["id"] for row in rows], [1, 2, 3])
        self.assertEqual(
            query.gt.call_args_list,
            [mock.call("id", 0), mock.call("id", 2)],
        )
        query.order.assert_has_calls([mock.call("id"), mock.call("id")])
        query.select.assert_called_with("id,product_id")

    def test_load_counts_uses_one_grouped_rpc(self):
        rpc_query = mock.Mock()
        rpc_query.execute.return_value = _Response([
            {"product_id": "p1", "review_count": 12, "item_count": 3},
            {"product_id": "p2", "review_count": 0, "item_count": 1},
        ])
        sb = mock.Mock()
        sb.rpc.return_value = rpc_query

        reviews, items = REVIEWER.load_counts(sb, "dataset")

        sb.rpc.assert_called_once_with(
            REVIEWER.PRODUCT_COUNTS_RPC,
            {"p_dataset_key": "dataset"},
        )
        self.assertEqual(reviews["p1"], 12)
        self.assertEqual(reviews["p2"], 0)
        self.assertEqual(items["p1"], 3)

    def test_save_decision_calls_atomic_rpc_and_refreshes_seed(self):
        rpc_query = mock.Mock()
        rpc_query.execute.return_value = _Response([{
            "analysis_status": "included",
            "analysis_reason": "Pertenece",
            "analysis_reviewed_at": "2026-08-01T12:00:00+00:00",
        }])
        sb = mock.Mock()
        sb.rpc.return_value = rpc_query
        seed = {
            "product_id": "p1",
            "analysis_status": "pending",
            "analysis_reviewed_at": None,
        }

        REVIEWER.save_decision(
            sb,
            "dataset",
            seed,
            "included",
            "Pertenece",
            "Ana",
        )

        sb.rpc.assert_called_once_with(
            REVIEWER.SAVE_DECISION_RPC,
            {
                "p_dataset_key": "dataset",
                "p_product_id": "p1",
                "p_decision": "included",
                "p_reason": "Pertenece",
                "p_reviewer": "Ana",
                "p_expected_reviewed_at": None,
            },
        )
        self.assertEqual(seed["analysis_status"], "included")
        self.assertEqual(
            seed["analysis_reviewed_at"],
            "2026-08-01T12:00:00+00:00",
        )

    def test_missing_rpc_is_reported_as_setup_error(self):
        sb = mock.Mock()
        sb.rpc.side_effect = Exception(
            "PGRST202 Could not find the function product_clean_counts "
            "in the schema cache"
        )
        with self.assertRaises(REVIEWER.ProductReviewSetupError):
            REVIEWER.load_counts(sb, "dataset")

    def test_missing_description_table_is_optional(self):
        error = Exception(
            "42P01 relation item_descriptions_raw does not exist"
        )
        with mock.patch.object(REVIEWER, "fetch_all", side_effect=error):
            rows, detail = REVIEWER.load_descriptions(object(), "dataset")
        self.assertEqual(rows, {})
        self.assertIn("42P01", detail)

    def test_network_description_error_is_not_hidden(self):
        with mock.patch.object(
            REVIEWER,
            "fetch_all",
            side_effect=TimeoutError("connection timeout"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "No se pudo consultar item_descriptions_raw",
            ):
                REVIEWER.load_descriptions(object(), "dataset")


if __name__ == "__main__":
    unittest.main()
