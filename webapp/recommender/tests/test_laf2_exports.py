from django.test import TestCase
from django.urls import reverse

from recommender.models import RecommendationSession


class LAF2TraceExportTests(TestCase):
    def test_used_download_contains_program_and_exact_execution_payload(self):
        flow = RecommendationSession.objects.create(
            domain_key="cafe",
            dataset_key="catalogo-real",
            strategy="D",
            selected_product_id="producto-1",
            selected_product_name="Producto 1",
            laf2_result={
                "run_id": "laf2-trazable",
                "evaluation_status": "validated",
                "evaluator_version": "laf-http-api-laf2-traceable-2.0.0",
                "operator_profile": "budan_2017",
                "dataset_key": "catalogo-real",
                "domain": "cafe",
                "strategy": "D",
                "generated_at": "2026-09-10T12:00:00-03:00",
                "ranking": [],
                "program_status": "generated",
                "program_kind": "laf2",
                "laf_program": "respaldoCompleto(item). {0.9; 1.0}",
                "aspect_programs": {
                    "envio": "tieneEnvioGratis(item). {0.95; 1.0}"
                },
                "execution_payloads": {
                    "envio": {
                        "facts": [
                            {
                                "name": "tieneEnvioGratis",
                                "argument": "item",
                                "attributes": ["0.95", "1.0"],
                            }
                        ],
                        "rules": [],
                    }
                },
            },
        )

        response = self.client.get(
            reverse("recommender:export-laf2-program", args=[flow.id]),
            {"used": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="programas-laf2-utilizados.txt"',
        )
        text = response.content.decode()
        self.assertIn("PROGRAMA 1/1 — CONDICIÓN: ENVIO", text)
        self.assertIn("tieneEnvioGratis(item)", text)
        self.assertIn("PAYLOAD JSON EXACTO ENVIADO A /api/graph", text)
        self.assertIn('"name": "tieneEnvioGratis"', text)

        backup = self.client.get(
            reverse("recommender:export-laf2-program", args=[flow.id])
        )
        self.assertIn("respaldoCompleto", backup.content.decode())
        self.assertNotIn("PAYLOAD JSON EXACTO", backup.content.decode())
