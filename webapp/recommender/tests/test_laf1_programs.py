from pathlib import Path
from unittest.mock import Mock

from django.conf import settings
from django.test import SimpleTestCase

from recommender.domain.contracts import EvaluationRequest
from recommender.services.laf1_programs import LAF1ProgramService
from recommender.services.laf_api import LAFProgramParser


class LAF1ProgramServiceTests(SimpleTestCase):
    def test_generates_step_08_program_with_frozen_methodology(self):
        repository = Mock()
        repository.laf1_generation_data.return_value = (
            {
                "P1": {
                    "name": "Café de prueba",
                    "position": 1,
                    "price_min": 100.0,
                    "price_max": 150.0,
                    "n_items": 2,
                }
            },
            [
                {
                    "product_id": "P1",
                    "aspect": "sabor",
                    "polarity": "pos",
                    "agg_confidence": 0.8,
                    "n_reviews": 4,
                    "coverage_ratio": 0.5,
                    "from_catalog": False,
                }
            ],
        )
        service = LAF1ProgramService(
            repository,
            Path(settings.REPOSITORY_ROOT),
        )

        generated = service.generate(
            EvaluationRequest(
                domain="cafe",
                dataset_key="mco_dataset_prueba",
                strategy="D",
                preferences={"sabor": 1.0, "tueste": 0.67},
            )
        )

        self.assertIn("% Dataset key: mco_dataset_prueba", generated.text)
        self.assertIn("%   sabor: 1.00", generated.text)
        self.assertIn("%   tueste: 0.67", generated.text)
        self.assertIn("%   aroma: 0.00", generated.text)
        self.assertIn("p1_cafe_de_prueba", generated.text)
        self.assertTrue(generated.methodology_sha256)
        self.assertEqual(generated.products_count, 1)
        self.assertGreater(generated.facts_count, 0)
        self.assertGreater(generated.rules_count, 0)
        parsed = LAFProgramParser().parse(generated.text)
        self.assertEqual(len(parsed.facts), generated.facts_count)
        self.assertEqual(len(parsed.rules), generated.rules_count)
        self.assertEqual(generated.entities[0]["entity_id"], "P1")
