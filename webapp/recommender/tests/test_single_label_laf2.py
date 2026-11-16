"""Regresión de la corrida por condición de LAF 2 con una sola etiqueta.

Espejo de `test_single_label_laf1.py`. Ver `docs/ADR-007-LAF2-UNA-ETIQUETA-POR-CONDICION.md`.
"""
from pathlib import Path
from unittest.mock import Mock

from django.conf import settings
from django.test import SimpleTestCase

from recommender.domain.contracts import EvaluationRequest
from recommender.services.laf2_programs import LAF2ProgramService
from recommender.services.laf_api import LAFProgramParser


def _raw_item(item_id, **overrides):
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


def program_service(raw_items):
    repository = Mock()
    repository.laf2_generation_items.return_value = (
        {"product_id": "MCO123", "name": "Cafe de auditoria", "position": 1},
        raw_items,
    )
    repository.laf2_dataset_items.return_value = raw_items
    return LAF2ProgramService(repository, Path(settings.REPOSITORY_ROOT))


ITEMS = [
    _raw_item("MCO-ITEM-1", shipping_free_shipping=True, official_store_id=42),
    _raw_item("MCO-ITEM-2", price="150.00", shipping_free_shipping=True),
    _raw_item("MCO-ITEM-3", price="200.00"),
]
REQUEST = EvaluationRequest(
    domain="cafe",
    dataset_key="mco_dataset_prueba",
    strategy="D",
    selected_entity_id="MCO123",
    preferences={"precio": 0.67, "envio": 1.0, "tienda_oficial": 0.33, "cuotas": 0.0},
)


class SingleLabelLAF2ProgramsTests(SimpleTestCase):
    def test_selects_condition_facts_before_generation_and_preserves_backup(self):
        service = program_service(ITEMS)
        original = service.generate(REQUEST)
        service.repository.reset_mock()

        backup, programs = service.generate_conditions(REQUEST)

        service.repository.laf2_generation_items.assert_called_once()
        self.assertEqual(backup.text, original.text)
        self.assertEqual(backup.run_id, original.run_id)
        # Sólo las condiciones con peso > 0; «cuotas» en 0 no genera programa.
        self.assertEqual(set(programs), {"precio", "envio", "tienda_oficial"})

        parser = LAFProgramParser()
        self.assertEqual(parser.parse(backup.text).attribute_count, 2)
        full = parser.parse(backup.text).to_request_payload()
        predicates = {
            "precio": "precioBueno",
            "envio": "tieneEnvioGratis",
            "tienda_oficial": "esTiendaOficial",
        }
        for condition, program in programs.items():
            parsed = parser.parse(program.text)
            payload = parsed.to_request_payload()
            self.assertEqual(parsed.attribute_count, 1)
            self.assertEqual(
                [label["labelName"] for label in payload["operations"]["labels"]],
                ["confidence"],
            )
            # Sólo los hechos de esa condición y sólo sus dos reglas.
            for fact in payload["facts"]:
                self.assertEqual(fact["name"], predicates[condition])
            self.assertEqual(
                [rule["bodyLiterals"] for rule in payload["rules"]],
                [[predicates[condition]], ["compraBuena"]],
            )
            for other in set(predicates.values()) - {predicates[condition]}:
                self.assertNotIn(other, program.text)
            # La confianza es la del constructor congelado, con su redondeo.
            for fact in payload["facts"]:
                expected = next(
                    row for row in full["facts"]
                    if row["name"] == fact["name"]
                    and row["argument"] == fact["argument"]
                )
                self.assertEqual(fact["attributes"][0], expected["attributes"][0])
            for rule in payload["rules"]:
                expected = next(
                    row for row in full["rules"]
                    if row["headName"] == rule["headName"]
                    and row["bodyLiterals"] == rule["bodyLiterals"]
                )
                self.assertEqual(rule["attributes"][0], expected["attributes"][0])

    def test_condition_facts_do_not_depend_on_the_user_weights(self):
        """Los pesos son externos: el programa por condición no los lleva."""
        service = program_service(ITEMS)
        _, primero = service.generate_conditions(REQUEST)
        _, segundo = service.generate_conditions(
            EvaluationRequest(
                domain=REQUEST.domain,
                dataset_key=REQUEST.dataset_key,
                strategy=REQUEST.strategy,
                selected_entity_id=REQUEST.selected_entity_id,
                preferences={"precio": 0.33, "envio": 0.67, "tienda_oficial": 1.0},
            )
        )
        for condition in ("precio", "envio", "tienda_oficial"):
            # El texto que va al motor es el mismo; el `run_id` sigue incluyendo
            # las preferencias como huella de la sesión, igual que en LAF 1.
            self.assertEqual(primero[condition].text, segundo[condition].text)

    def test_a_condition_without_evidence_produces_no_facts(self):
        """Sin hechos la condición sale del denominador; el evaluador la saltea."""
        service = program_service(ITEMS)
        _, programs = service.generate_conditions(
            EvaluationRequest(
                domain=REQUEST.domain,
                dataset_key=REQUEST.dataset_key,
                strategy=REQUEST.strategy,
                selected_entity_id=REQUEST.selected_entity_id,
                preferences={"cuotas": 1.0},
            )
        )
        self.assertEqual(programs["cuotas"].facts_count, 0)
        self.assertEqual(programs["cuotas"].rules_count, 2)
