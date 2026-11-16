"""Regresión de aislamiento, trazabilidad y compatibilidad de LAF1."""
import io
import zipfile
from dataclasses import replace
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from recommender.domain.contracts import EvaluationRequest, EvaluationResult
from recommender.models import RecommendationSession
from recommender.repositories.fixture_repository import FixtureRepository
from recommender.services.evaluators import LAFHttpRecommendationEvaluator
from recommender.services.laf1_programs import LAF1ProgramService
from recommender.services.laf_api import LAFProgramParser, LAFGraphPresentationMapper


def program_service():
    repository = Mock()
    repository.laf1_generation_data.return_value = (
        {"P1": {"name": "Café de prueba", "position": 1,
                "price_min": None, "price_max": None, "n_items": 1}},
        [
            {"product_id": "P1", "aspect": aspect, "polarity": polarity,
             "agg_confidence": confidence, "n_reviews": 3, "from_catalog": False}
            for aspect in ("sabor", "aroma", "rendimiento", "preparacion")
            for polarity, confidence in (("pos", 0.8), ("neg", 0.2))
        ],
    )
    return LAF1ProgramService(repository, settings.REPOSITORY_ROOT)


REQUEST = EvaluationRequest("cafe", "real-single-label-test", "D", {"sabor": 1.0, "aroma": 0.33})


class SingleLabelProgramsTests(SimpleTestCase):
    def test_selects_evidence_before_generation_and_preserves_backup(self):
        service = program_service()
        original = service.generate(REQUEST)
        service.repository.reset_mock()
        backup, programs = service.generate_aspects(REQUEST)
        service.repository.laf1_generation_data.assert_called_once()
        self.assertEqual(backup.text, original.text)
        self.assertEqual(backup.run_id, original.run_id)
        self.assertEqual(set(programs), {"sabor", "aroma"})
        parser = LAFProgramParser()
        self.assertEqual(parser.parse(backup.text).attribute_count, 2)
        for aspect, program in programs.items():
            parsed = parser.parse(program.text)
            payload = parsed.to_request_payload()
            self.assertEqual(parsed.attribute_count, 1)
            self.assertEqual(len(parsed.rules), 6)
            self.assertEqual(len(parsed.facts), 2)
            self.assertEqual([x["labelName"] for x in payload["operations"]["labels"]], ["confidence"])
            for fact in payload["facts"]:
                self.assertTrue(fact["name"].lower().endswith(aspect))
            other = "aroma" if aspect == "sabor" else "sabor"
            self.assertNotIn(other + "Bueno", program.text)
            self.assertIn("sensorialBueno(X)", program.text)
            self.assertIn("~recomendar(X)", program.text)
            # Alpha is the frozen constructor's value, including its rounding.
            full = parser.parse(backup.text).to_request_payload()
            for fact in payload["facts"]:
                expected = next(x for x in full["facts"] if x["name"] == fact["name"])
                self.assertEqual(fact["attributes"][0], expected["attributes"][0])
            for rule in payload["rules"]:
                expected = next(x for x in full["rules"] if x["headName"] == rule["headName"]
                                and x["bodyLiterals"] == rule["bodyLiterals"])
                self.assertEqual(rule["attributes"][0], expected["attributes"][0])

    def test_negative_recommendation_of_row_13_reaches_valor_and_elaboracion(self):
        """Fila 13 (recongelado 2026-09-10): `valor` y `elaboracion` ya llevan `~recomendar`.

        Antes del recongelado estas dos dimensiones no tenían regla negativa
        hacia la recomendación y el aspecto se cortaba en `~valorBueno` /
        `~elaboracionBueno` (5 reglas). La configuración congelada de café
        agregó `~recomendar(X) :- ~valorBueno(X). {0.80; 1.00}` y
        `~recomendar(X) :- ~elaboracionBueno(X). {0.75; 1.00}`, con la confianza
        simétrica a la positiva de cada dimensión, así que ahora son 6 reglas.
        Datos: `validacion_laf1/EXP11_FILA13_IMPACTO.md` y
        `validacion_laf1/salidas/recongelado_20260910/RESUMEN.md`.
        """
        service = program_service()
        _, programs = service.generate_aspects(replace(REQUEST, preferences={"rendimiento": 1.0, "sabor": 0.0}))
        self.assertEqual(set(programs), {"rendimiento"})
        rendimiento = programs["rendimiento"].text
        self.assertIn("~valorBueno(X) :- ~rendimientoBueno(X).", rendimiento)
        self.assertIn("recomendar(X) :- valorBueno(X). {0.80}", rendimiento)
        self.assertIn("~recomendar(X) :- ~valorBueno(X). {0.80}", rendimiento)
        self.assertEqual(programs["rendimiento"].rules_count, 6)
        _, elaboracion = service.generate_aspects(replace(REQUEST, preferences={"preparacion": 1.0}))
        preparacion = elaboracion["preparacion"].text
        self.assertIn("~recomendar(X) :- ~elaboracionBueno(X). {0.75}", preparacion)
        self.assertEqual(elaboracion["preparacion"].rules_count, 6)
        # Un aspecto en "No me importa" (peso 0) sigue sin generar programa.
        _, empty = service.generate_aspects(replace(REQUEST, preferences={"sabor": 0.0}))
        self.assertEqual(empty, {})

    def test_raw_graph_union_has_no_cross_aspect_edges_or_id_collisions(self):
        graph = {"nodes": [{"id": "1", "label": "recomendar(p1)", "type": "FACT", "attributes": [0.6]}],
                 "edges": [{"from": "1", "to": "1", "kind": "SUPPORT"}]}
        merged = LAFHttpRecommendationEvaluator._merge_aspect_graphs({"sabor": graph, "aroma": graph})
        self.assertEqual({n["id"] for n in merged["nodes"]}, {"sabor:1", "aroma:1"})
        for edge in merged["edges"]:
            self.assertEqual(edge["from"].split(":")[0], edge["to"].split(":")[0])
        self.assertEqual(graph["nodes"][0]["id"], "1")


def evaluated_result():
    service = program_service()
    api = Mock()
    def build_graph(payload):
        argument = payload["facts"][0]["argument"]
        count = len(payload["operations"]["labels"])
        values = [0.99, 1.0] if count == 2 else [0.6 if "Sabor" in payload["facts"][0]["name"] else 0.3]
        return {"nodes": [{"id": "conclusion", "label": f"recomendar({argument})", "type": "FACT",
                           "attributes": values, "deltaAttributes": values}], "edges": []}
    api.build_graph.side_effect = build_graph
    evaluator = LAFHttpRecommendationEvaluator(FixtureRepository(settings.FIXTURE_DIR), service, Mock(), api,
                                               results_validated=True)
    return evaluator.evaluate_products(REQUEST), api


class SingleLabelEvaluationTests(SimpleTestCase):
    def test_uses_one_label_payloads_and_persists_exact_runs(self):
        result, api = evaluated_result()
        self.assertEqual(result.evaluation_status, "validated")
        self.assertAlmostEqual(result.ranking[0].final_score, (0.6 + 0.33 * 0.3) / 1.33)
        self.assertEqual([len(c.args[0]["operations"]["labels"]) for c in api.build_graph.call_args_list], [2, 1, 1])
        self.assertEqual(set(result.aspect_graphs), {"aroma", "sabor"})
        self.assertEqual(result.backup_laf_graph["nodes"][0]["attributes"], [0.99, 1.0])
        self.assertEqual(EvaluationResult.from_dict(result.to_dict()), result)
        mapped = LAFGraphPresentationMapper().map(result.laf_graph)
        self.assertTrue(all(n["metadata"]["hide_preference"] for n in mapped["nodes"]))


class SingleLabelStoredViewTests(TestCase):
    def setUp(self):
        self.result, _ = evaluated_result()
        self.flow = RecommendationSession.objects.create(
            domain_key=REQUEST.domain, dataset_key=REQUEST.dataset_key,
            quality_preferences=REQUEST.preferences, laf1_result=self.result.to_dict(),
        )

    @patch("recommender.web.views.get_evaluator", side_effect=AssertionError("Must not recompute LAF"))
    def test_aspect_graph_reads_saved_evaluation(self, evaluator):
        response = self.client.get(reverse("recommender:aspect-graph", args=[self.flow.id]),
                                   {"entity_id": "P1", "aspect": "sabor"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["source"], "stored_evaluation")
        self.assertEqual(data["nodes"][0]["confidence"], 0.6)
        evaluator.assert_not_called()

    def test_download_contains_separate_programs_and_historical_backup(self):
        url = reverse("recommender:export-laf1-program", args=[self.flow.id])
        response = self.client.get(url, {"bundle": "1"})
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(archive.read("aspectos/sabor.txt").decode(), self.result.aspect_programs["sabor"])
            self.assertEqual(archive.read("respaldo-completo-dos-etiquetas.txt").decode(), self.result.laf_program)
            self.assertIn("resultado.json", archive.namelist())
        # El combinado se sigue entregando, pero encabezado por lo que es: no
        # produce el ranking (U40 de la evaluación heurística, ADR-006).
        combinado = self.client.get(url).content.decode()
        self.assertIn("PROGRAMA LAF1 COMBINADO — NO INTERVIENE EN EL RANKING", combinado)
        self.assertTrue(combinado.endswith(self.result.laf_program))
        self.assertEqual(self.client.get(url, {"aspect": "sabor"}).content.decode(), self.result.aspect_programs["sabor"])
        self.assertEqual(self.client.get(url, {"aspect": "no-existe"}).status_code, 404)

    def test_download_used_programs_as_one_readable_text_file(self):
        url = reverse("recommender:export-laf1-program", args=[self.flow.id])
        response = self.client.get(url, {"used": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertEqual(
            response["Content-Disposition"],
            'attachment; filename="programas-laf1-utilizados.txt"',
        )
        text = response.content.decode()
        self.assertIn("PROGRAMAS LAF1 UTILIZADOS PARA EL RANKING", text)
        self.assertIn("PROGRAMA 1/2 — AROMA", text)
        self.assertIn("PROGRAMA 2/2 — SABOR", text)
        self.assertEqual(text.count("Ejecución independiente · una etiqueta: confianza"), 2)
        self.assertEqual(text.count("% LAF1 independiente: una etiqueta (confianza)"), 2)
        self.assertNotIn("respaldo-completo", text)
