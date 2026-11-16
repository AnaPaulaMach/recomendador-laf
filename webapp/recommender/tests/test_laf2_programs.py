from pathlib import Path
from unittest.mock import Mock

from django.conf import settings
from django.test import SimpleTestCase

from recommender.domain.contracts import EvaluationRequest
from recommender.repositories.domain_repository import DomainConfigRepository
from recommender.services.laf2_programs import LAF2ProgramService
from recommender.services.laf_api import LAFProgramParser


class LAF2ProgramServiceTests(SimpleTestCase):
    def test_generates_step_10_program_without_claiming_a_ranking(self):
        repository = Mock()
        repository.laf2_generation_items.return_value = (
            {
                "product_id": "MCO123",
                "name": "Cafe de auditoria",
                "position": 1,
            },
            [
                {
                    "item_id": "MCO-ITEM-1",
                    "price": "120.00",
                    "original_price": "150.00",
                    "official_store_id": 42,
                    "listing_type_id": "gold_pro",
                    "tags": ["12x_campaign"],
                    "sale_terms": [
                        {
                            "id": "WARRANTY_TIME",
                            "value_struct": {"number": 12, "unit": "meses"},
                        },
                        {"id": "INVOICE", "value_name": "Factura A"},
                    ],
                    "seller_id": 7,
                    "shipping_free_shipping": True,
                    "shipping_logistic_type": "fulfillment",
                    "shipping_mode": "me2",
                }
            ],
        )
        service = LAF2ProgramService(repository, Path(settings.REPOSITORY_ROOT))

        generated = service.generate(
            EvaluationRequest(
                domain="cafe",
                dataset_key="mco_dataset_prueba",
                strategy="D",
                selected_entity_id="MCO123",
                budget_min=100,
                budget_max=200,
                preferences={
                    "precio": 1.0,
                    "descuento": 0.67,
                    "cuotas": 1.0,
                    "garantia": 0.67,
                    "tienda_oficial": 0.33,
                    "factura": 0.33,
                    "envio": 1.0,
                },
            )
        )

        self.assertIn("% Dataset key: mco_dataset_prueba", generated.text)
        self.assertIn("% Product ID: MCO123", generated.text)
        self.assertIn("% Presupuesto solicitado: 100 a 200", generated.text)
        self.assertIn("tieneEnvioGratis(mco_item_1)", generated.text)
        self.assertIn("esTiendaOficial(mco_item_1)", generated.text)
        self.assertIn("recomendar(X) :- compraBuena(X)", generated.text)
        self.assertEqual(generated.items_count, 1)
        self.assertGreater(generated.facts_count, 0)
        self.assertGreater(generated.rules_count, 0)
        self.assertTrue(generated.methodology_sha256)
        parsed = LAFProgramParser().parse(generated.text)
        self.assertEqual(len(parsed.facts), generated.facts_count)
        self.assertEqual(len(parsed.rules), generated.rules_count)
        self.assertEqual(generated.entities[0]["entity_id"], "MCO-ITEM-1")
        self.assertEqual(generated.entities[0]["metadata"]["warranty"], "12 meses")

    def test_preserves_days_in_the_visible_warranty_label(self):
        self.assertEqual(
            LAF2ProgramService._warranty_label(
                {
                    "sale_terms": [
                        {
                            "id": "WARRANTY_TIME",
                            "value_struct": {"number": 1, "unit": "días"},
                        }
                    ]
                }
            ),
            "1 día",
        )

    def _repository(self, raw_items):
        repository = Mock()
        repository.laf2_generation_items.return_value = (
            {"product_id": "MCO123", "name": "Cafe de auditoria", "position": 1},
            raw_items,
        )
        repository.laf2_dataset_items.return_value = raw_items
        return repository

    def _raw_item(self, item_id, **overrides):
        row = {
            "item_id": item_id,
            "price": "120.00",
            "original_price": None,
            "official_store_id": None,
            "listing_type_id": "gold_special",
            "tags": [],
            "sale_terms": [],
            "seller_id": 7,
            "shipping_free_shipping": False,
            "shipping_logistic_type": "xd_drop_off",
            "shipping_mode": "me2",
        }
        row.update(overrides)
        return row

    def test_generate_many_loads_supabase_once_for_all_variants(self):
        repository = self._repository([
            self._raw_item("MCO-ITEM-1", shipping_free_shipping=True),
            self._raw_item("MCO-ITEM-2", price="150.00"),
        ])
        service = LAF2ProgramService(repository, Path(settings.REPOSITORY_ROOT))
        request = EvaluationRequest(
            domain="cafe", dataset_key="mco_dataset_prueba", strategy="D",
            selected_entity_id="MCO123", preferences={"precio": 0.5, "envio": 1.0},
        )

        variants = service.generate_many(
            request,
            [request.preferences, {"precio": 1.0, "envio": 0.0}, {"precio": 0.0, "envio": 1.0}],
        )

        self.assertEqual(len(variants), 3)
        repository.laf2_generation_items.assert_called_once()
        self.assertIn("precioBueno(mco_item_1). {0.95; 0.50}", variants[0].text)
        self.assertIn("tieneEnvioGratis(mco_item_1). {0.95; 1.00}", variants[0].text)
        self.assertIn("tieneEnvioGratis(mco_item_1). {0.95; 0.00}", variants[1].text)
        self.assertIn("precioBueno(mco_item_1). {0.95; 0.00}", variants[2].text)
        self.assertEqual(variants[0].run_id != variants[1].run_id, True)

    def test_available_purchase_conditions_come_from_catalog_rows(self):
        repository = self._repository([
            self._raw_item("MCO-ITEM-1", shipping_free_shipping=True, official_store_id=42),
            self._raw_item("MCO-ITEM-2", original_price="200.00"),
        ])
        service = LAF2ProgramService(repository, Path(settings.REPOSITORY_ROOT))

        available = service.available_purchase_condition_keys("mco_dataset_prueba", "cafe")

        self.assertEqual(available, ("descuento", "envio", "precio", "tienda_oficial"))
        repository.laf2_dataset_items.assert_called_once_with("mco_dataset_prueba")

    def test_available_purchase_conditions_can_be_scoped_to_selected_product(self):
        repository = self._repository([
            self._raw_item("MCO-ITEM-1", shipping_free_shipping=True),
        ])
        service = LAF2ProgramService(repository, Path(settings.REPOSITORY_ROOT))

        available = service.available_purchase_condition_keys(
            "mco_dataset_prueba",
            "cafe",
            product_id="MCO123",
        )

        self.assertEqual(available, ("envio", "precio"))
        repository.laf2_generation_items.assert_called_once_with(
            "mco_dataset_prueba",
            "MCO123",
        )
        repository.laf2_dataset_items.assert_not_called()

