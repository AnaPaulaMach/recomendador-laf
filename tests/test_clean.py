"""Pruebas unitarias para la limpieza RAW -> CLEAN."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))


def load_cleaner():
    path = SRC_DIR / "01_clean.py"
    spec = importlib.util.spec_from_file_location("cleaner_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CLEANER = load_cleaner()


class _DeleteQuery:
    def __init__(self):
        self.deleted_ids = []

    def delete(self):
        return self

    def in_(self, column, values):
        if column != "id":
            raise AssertionError(f"Columna inesperada: {column}")
        self.deleted_ids.extend(values)
        return self

    def execute(self):
        return object()


class _FakeSupabase:
    def __init__(self):
        self.queries = {}

    def table(self, name):
        return self.queries.setdefault(name, _DeleteQuery())


class NormalizeTests(unittest.TestCase):
    def test_normalize_preserves_accents_and_removes_noise(self):
        text = "  CAFÉ\nExcelente 😊 https://example.com yo@test.com  "
        self.assertEqual(CLEANER.normalize(text), "café excelente")

    def test_normalize_truncates_without_splitting_last_word(self):
        self.assertEqual(CLEANER.normalize("uno dos tres", max_length=9), "uno dos")

    def test_normalize_empty_values(self):
        self.assertEqual(CLEANER.normalize(None), "")
        self.assertEqual(CLEANER.normalize("   "), "")


class ConversionTests(unittest.TestCase):
    def test_safe_int(self):
        self.assertEqual(CLEANER.safe_int("12"), 12)
        self.assertEqual(
            CLEANER.safe_int("1234567890123456789"),
            1234567890123456789,
        )
        self.assertEqual(CLEANER.safe_int(None, None), None)
        self.assertEqual(CLEANER.safe_int("no-numero", 7), 7)
        self.assertEqual(CLEANER.safe_int("Infinity", 7), 7)

    def test_safe_float(self):
        self.assertEqual(CLEANER.safe_float("1.25"), 1.25)
        self.assertIsNone(CLEANER.safe_float("no-numero", None))
        self.assertIsNone(CLEANER.safe_float("NaN", None))

    def test_normalize_forbidden_value(self):
        cases = [
            (None, 0),
            (True, 1),
            (["a", "b"], 2),
            ({"count": "3"}, 3),
            ('{"count": 4}', 4),
            ("texto-no-json", 1),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(
                    CLEANER.normalize_forbidden_value(value),
                    expected,
                )

    def test_has_media(self):
        self.assertFalse(CLEANER.has_media(None))
        self.assertFalse(CLEANER.has_media("[]"))
        self.assertTrue(CLEANER.has_media('[{"id": 1}]'))
        self.assertTrue(CLEANER.has_media("contenido-no-json"))

    def test_parse_seller_address(self):
        value = {
            "city": {"name": "Santiago"},
            "state": {"name": "Santiago del Estero"},
            "country": {"id": "AR"},
        }
        self.assertEqual(
            CLEANER.parse_seller_address(value),
            "Santiago, Santiago del Estero, AR",
        )

    def test_valid_rate(self):
        self.assertEqual(CLEANER.valid_rate("5"), 5)
        self.assertIsNone(CLEANER.valid_rate(0))
        self.assertIsNone(CLEANER.valid_rate(6))

    def test_money_is_quantized_without_binary_artifacts(self):
        amount = CLEANER.parse_money(0.1 + 0.2)
        self.assertEqual(amount, Decimal("0.30"))
        self.assertEqual(CLEANER.money_for_storage(amount), "0.30")
        self.assertIsNone(CLEANER.parse_money("NaN"))


class DatabaseResilienceTests(unittest.TestCase):
    def test_execute_with_retry_retries_only_transient_errors(self):
        attempts = []
        waits = []

        def operation():
            attempts.append(1)
            if len(attempts) < 3:
                raise TimeoutError("connection timeout")
            return "ok"

        result = CLEANER.execute_with_retry(
            operation,
            "prueba",
            max_attempts=3,
            sleep_fn=waits.append,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(waits, [2, 4])

    def test_execute_with_retry_does_not_repeat_validation_errors(self):
        operation = mock.Mock(side_effect=ValueError("dato invalido"))
        with self.assertRaises(ValueError):
            CLEANER.execute_with_retry(
                operation,
                "prueba",
                max_attempts=3,
                sleep_fn=lambda _: None,
            )
        operation.assert_called_once()

    def test_prune_stale_rows_deletes_only_keys_not_seen_in_raw(self):
        sb = _FakeSupabase()
        clean_rows = [[
            {"id": 10, "dataset_key": "d", "product_id": "p", "review_id": 1},
            {"id": 11, "dataset_key": "d", "product_id": "p", "review_id": 2},
        ]]
        with mock.patch.object(CLEANER, "fetch_pages", return_value=clean_rows):
            deleted = CLEANER.prune_stale_rows(
                sb,
                "reviews_clean",
                "d",
                ("dataset_key", "product_id", "review_id"),
                {("d", "p", 2)},
                page_size=100,
            )
        self.assertEqual(deleted, 1)
        self.assertEqual(sb.queries["reviews_clean"].deleted_ids, [10])

    def test_missing_review_schema_is_not_confused_with_network_error(self):
        self.assertTrue(
            CLEANER.is_missing_product_review_schema_error(
                Exception("42703: column analysis_status does not exist")
            )
        )
        self.assertFalse(
            CLEANER.is_missing_product_review_schema_error(
                Exception("connection timeout reading products_seed")
            )
        )

    def test_clean_items_writes_exact_decimal_strings(self):
        raw_rows = [[{
            "id": 1,
            "dataset_key": "d",
            "product_id": "p",
            "item_id": "i",
            "price": 0.1 + 0.2,
            "original_price": "1.005",
            "condition": "new",
            "listing_type_id": "gold_special",
            "seller_id": "1234567890123456789",
            "seller_address": None,
            "official_store_id": None,
        }]]
        cfg = CLEANER.RunConfig(
            dataset_key="d",
            page_size=100,
            max_content_length=10000,
            reset_clean=False,
        )
        with (
            mock.patch.object(CLEANER, "fetch_pages", return_value=raw_rows),
            mock.patch.object(CLEANER, "upsert_rows", return_value=1) as upsert,
            mock.patch.object(CLEANER, "prune_stale_rows", return_value=0),
        ):
            CLEANER.clean_items(object(), cfg)

        written = upsert.call_args.args[2][0]
        self.assertEqual(written["price"], "0.30")
        self.assertEqual(written["original_price"], "1.01")
        self.assertEqual(written["seller_id"], 1234567890123456789)


if __name__ == "__main__":
    unittest.main()
