from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from recommender.repositories.supabase_repository import SupabaseRepository


class SupabaseRepositoryTests(SimpleTestCase):
    def test_laf1_data_uses_only_reviewed_included_products(self):
        seed_rows = [
            {"product_id": "P1", "position": 1, "analysis_status": "included"},
            {"product_id": "P2", "position": 2, "analysis_status": "excluded"},
        ]
        raw_rows = [{"product_id": "P1", "name": "Café uno", "family_name": None}]
        item_rows = [{"product_id": "P1", "price": "125.50"}]
        trust_rows = [
            {
                "product_id": "P1",
                "aspect": "sabor",
                "polarity": "pos",
                "agg_confidence": 0.8,
                "n_reviews": 4,
                "coverage_ratio": 0.5,
                "from_catalog": False,
            }
        ]
        query = Mock()
        for method in ("select", "eq", "order", "in_"):
            getattr(query, method).return_value = query
        query.execute.side_effect = [
            SimpleNamespace(data=seed_rows),
            SimpleNamespace(data=raw_rows),
            SimpleNamespace(data=item_rows),
            SimpleNamespace(data=trust_rows),
        ]
        client = Mock()
        client.table.return_value = query
        repository = SupabaseRepository("https://proyecto.supabase.co", "clave")

        with patch.object(repository, "client", return_value=client):
            products, evidence = repository.laf1_generation_data("dataset", "D")

        self.assertEqual(tuple(products), ("P1",))
        self.assertEqual(products["P1"]["price_min"], 125.5)
        self.assertEqual(evidence[0]["product_id"], "P1")
        self.assertNotIn("P2", products)
        for call in query.in_.call_args_list:
            self.assertNotIn("P2", call.args[1])

    def test_laf1_data_blocks_pending_product_review(self):
        query = Mock()
        for method in ("select", "eq", "order"):
            getattr(query, method).return_value = query
        query.execute.return_value = SimpleNamespace(
            data=[
                {
                    "product_id": "P1",
                    "position": 1,
                    "analysis_status": "pending",
                }
            ]
        )
        client = Mock()
        client.table.return_value = query
        repository = SupabaseRepository("https://proyecto.supabase.co", "clave")

        with patch.object(repository, "client", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "pendientes de revisión"):
                repository.laf1_generation_data("dataset")

    def test_available_aspects_require_multiple_products_and_reviews(self):
        rows = [
            {"id": 1, "aspect": "sabor", "product_id": "p1", "n_reviews": 2},
            {"id": 2, "aspect": "sabor", "product_id": "p2", "n_reviews": 1},
            {"id": 3, "aspect": "acidez", "product_id": "p1", "n_reviews": 8},
            {"id": 4, "aspect": "aroma", "product_id": "p1", "n_reviews": 1},
            {"id": 5, "aspect": "aroma", "product_id": "p2", "n_reviews": 1},
        ]
        query = Mock()
        for method in ("select", "eq", "order", "range"):
            getattr(query, method).return_value = query
        query.execute.return_value = SimpleNamespace(data=rows)
        client = Mock()
        client.table.return_value = query
        repository = SupabaseRepository("https://proyecto.supabase.co", "clave")

        with patch.object(repository, "client", return_value=client):
            available = repository.available_quality_aspect_keys(
                "dataset",
                "D",
            )

        self.assertEqual(available, ("sabor",))
        client.table.assert_called_once_with("product_aspect_trust")
        query.select.assert_called_once_with("id,aspect,product_id,n_reviews")
        query.eq.assert_any_call("dataset_key", "dataset")
        query.eq.assert_any_call("strategy", "D")

    def test_available_aspects_reject_invalid_thresholds(self):
        repository = SupabaseRepository("https://proyecto.supabase.co", "clave")
        with self.assertRaises(ValueError):
            repository.available_quality_aspect_keys(
                "dataset",
                minimum_products=0,
            )

    def test_dataset_option_exposes_type_country_and_capture_date(self):
        option = SupabaseRepository._dataset_option(
            {
                "dataset_key": "mlm_test_20260805",
                "category_label": "Cafe instantaneo",
                "site_id": "MLM",
                "created_at": "2026-08-05T19:13:08+00:00",
            },
            "cafe",
        )

        self.assertEqual(option["key"], "mlm_test_20260805")
        self.assertEqual(
            option["label"],
            "Cafe instantaneo · México · 05/08/2026",
        )

    def test_extracts_first_secure_mlstatic_picture(self):
        payload = {
            "pictures": [
                {
                    "secure_url": "https://http2.mlstatic.com/secure.jpg",
                    "url": "https://http2.mlstatic.com/original.jpg",
                }
            ]
        }

        self.assertEqual(
            SupabaseRepository._catalog_image_url(payload),
            "https://http2.mlstatic.com/secure.jpg",
        )

    def test_rejects_non_https_or_external_picture_urls(self):
        for url in (
            "http://http2.mlstatic.com/insecure.jpg",
            "https://example.com/not-mercadolibre.jpg",
            "javascript:alert(1)",
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    SupabaseRepository._catalog_image_url(
                        {"pictures": [{"url": url}]}
                    ),
                    "",
                )

    def test_calculates_listing_price_range_from_valid_prices(self):
        self.assertEqual(
            SupabaseRepository._price_range(
                [{"price": "410"}, {"price": 121.22}, {"price": None}]
            ),
            (121.22, 410.0, 2),
        )

    def test_laf2_items_are_scoped_to_reviewed_product_and_budget(self):
        seed_rows = [
            {"product_id": "MCO123", "position": 1, "analysis_status": "included"},
            {"product_id": "MCO999", "position": 2, "analysis_status": "excluded"},
        ]
        product_rows = [{"product_id": "MCO123", "name": "Cafe controlado"}]
        clean_rows = [
            {
                "item_id": "ITEM-1",
                "price": "120.00",
                "original_price": "150.00",
                "listing_type": "gold_pro",
                "seller_id": 7,
                "official_store_id": 42,
            },
            {"item_id": "ITEM-FUERA", "price": "500.00"},
        ]
        raw_rows = [
            {
                "item_id": "ITEM-1",
                "price": "119.00",
                "tags": ["12x_campaign"],
                "sale_terms": [],
                "shipping_free_shipping": True,
            }
        ]
        query = Mock()
        for method in ("select", "eq", "order", "in_", "limit"):
            getattr(query, method).return_value = query
        query.execute.side_effect = [
            SimpleNamespace(data=seed_rows),
            SimpleNamespace(data=product_rows),
            SimpleNamespace(data=clean_rows),
            SimpleNamespace(data=raw_rows),
        ]
        client = Mock()
        client.table.return_value = query
        repository = SupabaseRepository("https://proyecto.supabase.co", "clave")

        with patch.object(repository, "client", return_value=client):
            product, items = repository.laf2_generation_items(
                "dataset",
                "MCO123",
                budget_min=100,
                budget_max=200,
            )

        self.assertEqual(product["name"], "Cafe controlado")
        self.assertEqual([item["item_id"] for item in items], ["ITEM-1"])
        self.assertEqual(items[0]["price"], "120.00")
        self.assertTrue(items[0]["shipping_free_shipping"])
        query.eq.assert_any_call("dataset_key", "dataset")
        query.eq.assert_any_call("product_id", "MCO123")
