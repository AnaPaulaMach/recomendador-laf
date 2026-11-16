"""Pruebas de regresion para polaridad local por aspecto."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))


def load_extractor():
    path = REPO_ROOT / "src" / "05_aspects.py"
    spec = importlib.util.spec_from_file_location("aspect_extractor_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.initialize_analysis()
    return module


EXTRACTOR = load_extractor()


def by_aspect(text):
    grouped = defaultdict(list)
    for row in EXTRACTOR.process_review(text):
        grouped[row["aspect"]].append(row)
    return grouped


def polarities(grouped, aspect):
    return {row["polarity"] for row in grouped.get(aspect, [])}


class AspectPolarityTests(unittest.TestCase):
    def test_connector_without_spaces_separates_opposite_sabor(self):
        result = by_aspect(
            "sabe bien, es dulce,pero casi no sabe a cafe."
        )
        self.assertEqual(polarities(result, "sabor"), {"pos", "neg"})
        self.assertEqual(polarities(result, "dulzor"), {"neu"})

    def test_connector_is_case_insensitive(self):
        result = by_aspect("buen sabor, PERO rinde muy poco.")
        self.assertEqual(polarities(result, "sabor"), {"pos"})
        self.assertEqual(polarities(result, "rendimiento"), {"neg"})

    def test_sin_duda_does_not_negate_recommendation(self):
        result = by_aspect(
            "sin duda lo recomiendo, exquisito sabor y aroma."
        )
        self.assertEqual(polarities(result, "sabor"), {"pos"})
        self.assertEqual(polarities(result, "aroma"), {"pos"})

    def test_negation_does_not_cross_comma(self):
        result = by_aspect(
            "no, buen tamano y excelente sabor y aroma."
        )
        self.assertEqual(polarities(result, "tamano"), {"pos"})
        self.assertEqual(polarities(result, "sabor"), {"pos"})
        self.assertEqual(polarities(result, "aroma"), {"pos"})

    def test_phrase_has_priority_over_positive_component(self):
        doc = EXTRACTOR.nlp("no recomiendo este sabor.")
        sent = next(doc.sents)
        signals, _ = EXTRACTOR.resolve_polarity_matches(sent)
        self.assertEqual(
            [signal["polarity"] for signal in signals],
            ["neg"],
        )

    def test_local_signals_are_assigned_to_different_aspects(self):
        result = by_aspect(
            "no trae el medidor, eso no me gusto, "
            "viene sellado y con buena caducidad."
        )
        self.assertEqual(
            polarities(result, "presentacion"),
            {"pos", "neg"},
        )
        self.assertEqual(polarities(result, "caducidad"), {"pos"})

    def test_negation_scope_stops_at_coordination(self):
        result = by_aspect(
            "se disuelve perfecto, sin grumos y excelente sabor."
        )
        self.assertEqual(polarities(result, "preparacion"), {"pos"})
        self.assertEqual(polarities(result, "sabor"), {"pos"})

    def test_negation_is_consumed_by_nearest_signal(self):
        result = by_aspect("nunca falla, buen sabor y aroma.")
        self.assertEqual(polarities(result, "sabor"), {"pos"})
        self.assertEqual(polarities(result, "aroma"), {"pos"})

    def test_quotes_inside_phrase_do_not_break_match(self):
        result = by_aspect(
            'aroma agradable y sabor que no sabe "quemado" ni amargo.'
        )
        self.assertEqual(polarities(result, "aroma"), {"pos"})
        self.assertEqual(polarities(result, "sabor"), {"pos"})
        self.assertEqual(polarities(result, "dulzor"), {"pos"})

    def test_fragment_is_not_resegmented_after_connector_split(self):
        result = by_aspect(
            "viene bien sellado, y la caducidad es buena."
        )
        self.assertEqual(polarities(result, "presentacion"), {"pos"})
        self.assertEqual(polarities(result, "caducidad"), {"pos"})

    def test_global_fallback_has_lower_confidence(self):
        result = by_aspect(
            "excelente producto con sabor agradable, contiene un kilo."
        )
        sabor_conf = max(
            row["extraction_confidence"] for row in result["sabor"]
        )
        tamano_conf = max(
            row["extraction_confidence"] for row in result["tamano"]
        )
        self.assertEqual(polarities(result, "tamano"), {"pos"})
        self.assertLess(tamano_conf, sabor_conf)

    def test_negation_flag_belongs_only_to_affected_aspect(self):
        result = by_aspect(
            "no tiene buen sabor y conserva un aroma excelente."
        )
        self.assertTrue(any(row["has_negation"] for row in result["sabor"]))
        self.assertFalse(any(row["has_negation"] for row in result["aroma"]))

    def test_no_sabe_tan_rico_is_only_negative(self):
        result = by_aspect("no sabe tan rico.")
        self.assertEqual(polarities(result, "sabor"), {"neg"})

    def test_repeated_no_sabe_clauses_keep_their_own_aspect(self):
        result = by_aspect("no sabe mucho a dulce no sabe mal")
        self.assertEqual(polarities(result, "dulzor"), {"neg"})
        self.assertEqual(polarities(result, "sabor"), {"pos"})

    def test_no_sabe_a_negative_descriptor_is_positive(self):
        result = by_aspect("el cafe es muy rico, no sabe a quemado.")
        self.assertEqual(polarities(result, "sabor"), {"pos"})

    def test_single_aspect_can_receive_distant_recommendation(self):
        result = by_aspect(
            "si te gusta el cafe fuerte, es una opcion muy recomendable."
        )
        self.assertEqual(polarities(result, "intensidad"), {"pos"})

    def test_practico_is_positive_for_presentation(self):
        result = by_aspect(
            "muy practico, lo guarde en mi frasco de vidrio anterior."
        )
        self.assertEqual(polarities(result, "presentacion"), {"pos"})

    def test_human_reviewed_negative_presentation_stays_negative(self):
        result = by_aspect(
            "es un producto que deja mucho que desear, desde el empaque se ve "
            "pirata y el sabor es malo no sabe ni un poco a nescafe, la verdad "
            "hice una mala compra."
        )
        self.assertEqual(polarities(result, "presentacion"), {"neg"})

    def test_aspect_in_non_product_context_is_excluded(self):
        result = by_aspect("opten por el ahorro y el rendimiento de su bolsillo.")
        self.assertNotIn("rendimiento", result)

    def test_comparison_reference_does_not_create_aspects(self):
        result = by_aspect(
            "no es como comprar autentico grano molido pero es muy parecido."
        )
        self.assertNotIn("molienda", result)
        self.assertNotIn("originalidad", result)

    def test_negative_answer_inverts_previous_question(self):
        result = by_aspect(
            "sabe rico? si. es un buen capuchino de vainilla french? "
            "de ninguna manera."
        )
        self.assertEqual(polarities(result, "sabor"), {"pos"})
        self.assertEqual(polarities(result, "variedad"), {"neg"})

    def test_semantic_signal_hint_keeps_sabroso_on_sabor(self):
        result = by_aspect(
            "bien, es mas dulce que sabor moka, de cafe no sabe nada, "
            "rinde y es sabroso pero no sustituye un capuchino de verdad."
        )
        self.assertEqual(polarities(result, "sabor"), {"pos", "neg"})
        self.assertEqual(polarities(result, "rendimiento"), {"pos"})
        self.assertEqual(polarities(result, "variedad"), {"neu", "neg"})

    def test_caramel_variety_context_does_not_duplicate_sabor(self):
        result = by_aspect(
            "no sabe mucho a dulce no sabe mal pero no lo volveria a comprar "
            "ya que no me sabe a caramelo. tiene un aroma delicioso."
        )
        self.assertEqual(polarities(result, "sabor"), {"pos"})
        self.assertEqual(polarities(result, "dulzor"), {"neg"})
        self.assertEqual(polarities(result, "variedad"), {"neu"})
        self.assertEqual(polarities(result, "aroma"), {"pos"})

    def test_idiom_no_tiene_pierde_keeps_only_positive(self):
        # Caso 4 (153660): 'no' no debe invertir 'excelente'.
        result = by_aspect("no tiene pierde excelente calidad y sabor.")
        self.assertEqual(polarities(result, "sabor"), {"pos"})

    def test_no_tiene_still_negates_a_real_descriptor(self):
        # La excepcion es solo la locucion; 'no tiene buen sabor' sigue siendo
        # una negacion legitima.
        result = by_aspect("no tiene buen sabor.")
        self.assertEqual(polarities(result, "sabor"), {"neg"})

    def test_composition_no_contiene_azucar_is_not_dulzor(self):
        # Caso 13 (155661): describir la composicion no valora el dulzor.
        result = by_aspect(
            "excelente sabor, queda muy espumoso, no contiene azucar."
        )
        self.assertEqual(polarities(result, "sabor"), {"pos"})
        self.assertNotIn("dulzor", result)

    def test_local_dulzor_valuation_is_still_kept(self):
        # La exclusion no debe borrar un dulzor genuinamente valorado.
        result = by_aspect("el dulzor es perfecto, muy dulce y rico.")
        self.assertEqual(polarities(result, "dulzor"), {"pos"})

    def test_comparison_with_other_product_keeps_only_reviewed_opinion(self):
        # Caso 11 (157463): la critica es al nescafe normal, no al producto.
        result = by_aspect(
            "no se porque este cafe sabe bueno y el nescafe normal sabe malo."
        )
        self.assertEqual(polarities(result, "sabor"), {"pos"})

    def test_lo_unico_malo_frame_scopes_forward_not_to_prior_aspect(self):
        # Caso 3 (155107): 'malo' habla de la publicidad, no del sabor previo.
        result = by_aspect(
            "muy rico me encanto el sabor lo unico malo es que la publicidad "
            "la pasan mucho y aveces me es dificil pedir."
        )
        self.assertEqual(polarities(result, "sabor"), {"pos"})

    def test_lo_bueno_es_que_frame_reaches_following_aspect(self):
        # El marco no debe romper la lectura cuando el aspecto SI esta despues.
        result = by_aspect("lo bueno es que rinde muchisimo.")
        self.assertEqual(polarities(result, "rendimiento"), {"pos"})

    def test_comparison_marker_does_not_suppress_own_normal_coffee(self):
        # 'un cafe normal' se describe a si mismo; no es una comparacion y no
        # debe activar el corte de clausula comparativa.
        result = by_aspect("es un cafe normal, buen sabor y aroma.")
        self.assertEqual(polarities(result, "sabor"), {"pos"})
        self.assertEqual(polarities(result, "aroma"), {"pos"})

    def test_encanto_past_tense_distributes_positive_over_list(self):
        # Muestra ciega caso 12: 'me encanto el aroma, el sabor' -> ambos pos.
        result = by_aspect("me encanto el aroma, el sabor y el precio.")
        self.assertEqual(polarities(result, "aroma"), {"pos"})
        self.assertEqual(polarities(result, "sabor"), {"pos"})

    def test_mas_a_chocolate_is_descriptive_not_negative_variety(self):
        # Muestra ciega casos 2 y 15: 'sabe mas a chocolate' es descriptivo.
        result = by_aspect("le falta cafe sabe mas a chocolate.")
        self.assertEqual(polarities(result, "variedad"), {"neu"})

    def test_chocolate_variety_still_positive_with_local_signal(self):
        # No se pierde la variedad cuando si hay una valoracion.
        result = by_aspect("tiene sabor a chocolate delicioso.")
        self.assertEqual(polarities(result, "variedad"), {"pos"})

    def test_batch_processing_matches_individual_processing(self):
        texts = [
            "buen sabor y aroma.",
            "no recomiendo su presentacion.",
        ]
        expected = [EXTRACTOR.process_review(text) for text in texts]
        self.assertEqual(EXTRACTOR.process_reviews(texts), expected)


class QueryRecorder:
    """Doble minimo para comprobar la consulta fluida enviada a Supabase."""

    def __init__(self, data=None):
        self.calls = []
        self.data = data or []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self

        return record

    def execute(self):
        self.calls.append(("execute", (), {}))
        return SimpleNamespace(data=self.data)


class FakeSupabase:
    """Expone solamente la parte del cliente necesaria para estas pruebas."""

    def __init__(self, query):
        self.query = query
        self.tables = []
        self.rpc_calls = []

    def table(self, name):
        self.tables.append(name)
        return self.query

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return self.query


class AspectPersistenceTests(unittest.TestCase):
    def test_settings_are_validated_at_runtime(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SUPABASE_URL"):
                EXTRACTOR.load_settings()

    def test_cursor_query_selects_only_required_columns(self):
        query = QueryRecorder(data=[{"id": 11}])
        sb = FakeSupabase(query)

        rows = EXTRACTOR.fetch_review_page(
            sb,
            "dataset-a",
            {"p2", "p1"},
            10,
            500,
        )

        self.assertEqual(rows, [{"id": 11}])
        self.assertEqual(sb.tables, ["reviews_clean"])
        self.assertIn(
            (
                "select",
                ("id,dataset_key,review_id,product_id,content",),
                {},
            ),
            query.calls,
        )
        self.assertIn(("gt", ("id", 10), {}), query.calls)
        self.assertIn(("order", ("id",), {}), query.calls)
        self.assertIn(("limit", (500,), {}), query.calls)

    def test_staging_upsert_uses_run_id_in_conflict_key(self):
        query = QueryRecorder()
        sb = FakeSupabase(query)
        row = {
            "run_id": "00000000-0000-0000-0000-000000000001",
            "dataset_key": "dataset-a",
            "review_id": 1,
            "product_id": "p1",
            "aspect": "sabor",
            "polarity": "pos",
            "sentence_excerpt": "buen sabor",
        }

        EXTRACTOR.upsert_chunk_with_retry(sb, [row])

        self.assertEqual(sb.tables, [EXTRACTOR.STAGING_TABLE])
        upsert_call = next(call for call in query.calls if call[0] == "upsert")
        self.assertEqual(
            upsert_call[2]["on_conflict"],
            EXTRACTOR.STAGING_ON_CONFLICT,
        )

    def test_dedupe_keeps_different_reviews(self):
        base = {
            "dataset_key": "dataset-a",
            "review_id": 1,
            "product_id": "p1",
            "aspect": "sabor",
            "polarity": "pos",
            "sentence_excerpt": "buen sabor",
        }
        duplicate = dict(base)
        another_review = {**base, "review_id": 2}
        self.assertEqual(
            EXTRACTOR.dedupe_rows([base, duplicate, another_review]),
            [base, another_review],
        )

    def test_finalize_uses_transactional_rpc(self):
        query = QueryRecorder()
        sb = FakeSupabase(query)
        run_id = "00000000-0000-0000-0000-000000000001"

        EXTRACTOR.finalize_extraction_run(sb, "dataset-a", run_id)

        self.assertEqual(
            sb.rpc_calls,
            [
                (
                    EXTRACTOR.FINALIZE_RPC,
                    {"p_dataset_key": "dataset-a", "p_run_id": run_id},
                )
            ],
        )

    def test_failed_pipeline_discards_only_its_staging_run(self):
        sb = object()
        with (
            patch.object(EXTRACTOR, "load_settings", return_value=("url", "key", "dataset-a")),
            patch.object(EXTRACTOR, "initialize_analysis"),
            patch.object(EXTRACTOR, "create_client", return_value=sb),
            patch.object(EXTRACTOR, "require_included_product_ids", return_value={"p1"}),
            patch.object(EXTRACTOR, "begin_extraction_run") as begin,
            patch.object(
                EXTRACTOR,
                "fetch_review_page",
                return_value=[
                    {
                        "id": 1,
                        "dataset_key": "dataset-a",
                        "review_id": 1,
                        "product_id": "p1",
                        "content": "buen sabor",
                    }
                ],
            ),
            patch.object(EXTRACTOR, "process_reviews", side_effect=ValueError("fallo")),
            patch.object(EXTRACTOR, "discard_extraction_run") as discard,
            patch.object(EXTRACTOR, "finalize_extraction_run") as finalize,
        ):
            with self.assertRaisesRegex(ValueError, "fallo"):
                EXTRACTOR.main()

        run_id = begin.call_args.args[2]
        discard.assert_called_once_with(sb, run_id)
        finalize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
