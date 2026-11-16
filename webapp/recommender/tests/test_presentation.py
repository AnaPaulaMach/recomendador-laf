"""Capa de presentación: discrepancias E2-E4 del chequeo humano (2026-09-03).

No tocan el ranking: solo qué razones se muestran y cómo se rotulan.
"""
import json
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from recommender.domain.contracts import ArgumentEvidence, EvaluationResult, RankingEntry
from recommender.services.comparison import ClaimRow, build_score_breakdown
from recommender.web.presentation import (
    FIRST_MATCH_LABEL,
    LOW_SUPPORT_NOTE,
    SHARED_LABEL_MAX_GAP,
    SHARED_MATCH_LABEL,
    aspect_claim_narrative,
    attach_primary_copy,
    head_gaps,
    is_marginal_negative,
    match_label,
    negative_mentions_by_aspect,
    positive_mentions_by_aspect,
)

# Batería del snapshot congelado (café, recongelado 2026-09-10). Los puntajes de
# la cabeza de "solo sabor" y del perfil neutro salen de acá, no de una copia a
# mano: es la misma salida que valida validacion_robustez/RESULTADOS.md.
BATTERY = (
    Path(settings.REPOSITORY_ROOT)
    / "validacion_laf1"
    / "salidas"
    / "battery_multicriterio_mlm194329_20260528_142014.json"
)


def _arg(aspect: str, polarity: str, mentions: int, preference: float = 1.0, confidence: float = 0.5):
    return ArgumentEvidence(
        argument_id=f"{aspect}-{polarity}",
        title=f"{aspect} {polarity}",
        aspect=aspect,
        polarity=polarity,  # type: ignore[arg-type]
        confidence=confidence,
        preference=preference,
        evidence_count=mentions,
    )


def _entry(entity_id: str, evidence_count: int, arguments_for=(), arguments_against=(), metadata=None):
    return RankingEntry(
        entity_id=entity_id,
        entity_name=f"Producto {entity_id}",
        position=1,
        final_score=0.5,
        confidence=0.5,
        preference=1.0,
        status="recommended",
        evidence_count=evidence_count,
        arguments_for=tuple(arguments_for),
        arguments_against=tuple(arguments_against),
        metadata=dict(metadata or {}),
    )


def _result(*entries):
    return EvaluationResult(
        run_id="run",
        evaluation_status="validated",
        evaluator_version="test",
        operator_profile="budan_2017",
        dataset_key="ds",
        domain="cafe",
        strategy="D",
        generated_at="2026-09-03T00:00:00Z",
        ranking=tuple(entries),
    )


class PresentationTests(SimpleTestCase):
    def test_not_recommended_listing_gets_an_honest_label(self):
        first = _entry("A", 10)
        last = RankingEntry(**{**_entry("B", 10).__dict__, "position": 2, "final_score": 0.0, "status": "not_recommended"})

        attach_primary_copy(_result(first, last))

        self.assertEqual(first.metadata["match_label"], "Mejor opción para vos")
        self.assertEqual(last.metadata["match_label"], "No cumple lo que pediste")

    def test_e3_marginal_negative_hidden_from_card_but_kept_in_explanation(self):
        # Gourmet Espresso 400g, aroma: 46 elogios, 1 crítica -> no es una razón principal.
        entry = _entry(
            "A",
            120,
            arguments_for=[_arg("aroma", "positive", 46), _arg("sabor", "positive", 60)],
            arguments_against=[_arg("aroma", "negative", 1)],
        )
        attach_primary_copy(_result(entry, _entry("B", 100)))

        self.assertEqual(entry.metadata["arguments_against_display"], [])
        self.assertEqual(entry.metadata["arguments_against_marginal_count"], 1)
        against = entry.metadata["explanation_contributions_against"]
        self.assertEqual(len(against), 1)
        self.assertTrue(against[0]["marginal"])
        self.assertEqual(against[0]["evidence_label"], "1 de 47 menciones sobre aroma")
        self.assertEqual(against[0]["share_percent"], 2)

    def test_e3_substantial_negative_is_shown_with_counts(self):
        # Nescafé Bolsa 400g, sabor: 45 elogios, 7 críticas (13 %) -> sí se muestra.
        entry = _entry(
            "A",
            120,
            arguments_for=[_arg("sabor", "positive", 45)],
            arguments_against=[_arg("sabor", "negative", 7)],
        )
        attach_primary_copy(_result(entry, _entry("B", 100)))

        shown = entry.metadata["arguments_against_display"]
        self.assertEqual(len(shown), 1)
        self.assertFalse(shown[0]["marginal"])
        self.assertEqual(shown[0]["evidence_label"], "7 de 52 menciones sobre sabor")
        self.assertEqual(shown[0]["share_percent"], 13)

    def test_e3_thresholds(self):
        self.assertTrue(is_marginal_negative(_arg("x", "negative", 1), 0))      # una sola mención
        self.assertTrue(is_marginal_negative(_arg("x", "negative", 3), 191))    # 1,5 %
        self.assertFalse(is_marginal_negative(_arg("x", "negative", 2), 9))     # 18 %
        self.assertFalse(is_marginal_negative(_arg("x", "negative", 7), 45))    # 13 %

    def test_e4_arguments_of_disabled_aspects_are_not_shown(self):
        # Perfil "solo aroma": sabor tiene preferencia 0 -> sus críticas no son razón principal.
        entry = _entry(
            "A",
            200,
            arguments_for=[_arg("aroma", "positive", 30, preference=1.0), _arg("sabor", "positive", 90, preference=0.0)],
            arguments_against=[_arg("sabor", "negative", 20, preference=0.0), _arg("aroma", "negative", 4, preference=1.0)],
        )
        attach_primary_copy(_result(entry, _entry("B", 200)))

        titles_for = [item["title"] for item in entry.metadata["arguments_for_display"]]
        self.assertEqual(len(titles_for), 1)
        self.assertNotIn("sabor", titles_for[0].casefold())
        shown_against = entry.metadata["arguments_against_display"]
        self.assertEqual(len(shown_against), 1)
        self.assertIn("aroma", shown_against[0]["evidence_label"])

    def test_e2_low_support_note_and_coverage_from_evidence(self):
        # Arábico 900g: 67 menciones contra una mediana de ~230; 8 aspectos con evidencia.
        small = _entry(
            "arabico",
            67,
            arguments_for=[_arg(a, "positive", 5) for a in ("sabor", "aroma", "tueste", "dulzor", "intensidad", "presentacion", "originalidad", "molienda")],
        )
        others = [_entry(f"P{i}", n, arguments_for=[_arg("sabor", "positive", n)]) for i, n in enumerate((230, 240, 250, 300))]
        attach_primary_copy(_result(small, *others))

        self.assertEqual(small.metadata["support_note"], LOW_SUPPORT_NOTE)
        self.assertEqual(small.metadata["coverage_display"], "Información sobre 8 características")
        self.assertNotIn("support_note", others[0].metadata)

    def test_aspect_criticism_marks_relevant_vs_marginal(self):
        # Base para los estados en lenguaje común de "Ver por qué" (E5/R3):
        # una crítica de 1 mención NO es relevante; 7/52 (13 %) sí.
        entry = _entry(
            "A",
            200,
            arguments_for=[_arg("aroma", "positive", 46), _arg("sabor", "positive", 45)],
            arguments_against=[_arg("aroma", "negative", 1), _arg("sabor", "negative", 7)],
        )
        attach_primary_copy(_result(entry, _entry("B", 200)))

        criticism = entry.metadata["aspect_criticism"]
        self.assertFalse(criticism["aroma"]["relevant"])   # 1 mención -> marginal
        self.assertEqual(criticism["aroma"]["favor"], 46)
        self.assertTrue(criticism["sabor"]["relevant"])    # 7/52 -> relevante
        self.assertEqual(criticism["sabor"]["against"], 7)

    def test_e2_breakdown_marks_aspects_without_evidence(self):
        entry = _entry(
            "arabico",
            67,
            arguments_for=[_arg("sabor", "positive", 37), _arg("aroma", "positive", 16)],
            metadata={
                "decision_model": "post_laf_multicriteria_v1",
                "aspect_contributions": [
                    {"aspect": "sabor", "weight": 0.67, "normalized_weight": 0.5, "laf_score": 0.523, "contribution": 0.26},
                    {"aspect": "rendimiento", "weight": 0.67, "normalized_weight": 0.5, "laf_score": 0.0, "contribution": 0.0},
                ],
            },
        )
        breakdown = build_score_breakdown(entry, None)

        rows = {row.key: row for row in breakdown.contributions}
        self.assertTrue(rows["sabor"].has_evidence)
        self.assertFalse(rows["rendimiento"].has_evidence)


class AspectMentionLineTests(SimpleTestCase):
    """Líneas de la tarjeta: "Aspecto: F de T menciones favorables" (E3, 2026-09-09).

    Presentación pura: no intervienen en el puntaje ni en el orden.
    """

    def _entry_with_three_aspects(self):
        return _entry(
            "A",
            # Como en el camino real, la evidencia del producto es la suma de las
            # menciones de sus argumentos (laf_api.py, evaluators.py).
            46 + 1 + 45 + 7 + 12,
            arguments_for=[
                _arg("aroma", "positive", 46),
                _arg("sabor", "positive", 45),
                _arg("tueste", "positive", 12),
            ],
            arguments_against=[
                _arg("aroma", "negative", 1),
                _arg("sabor", "negative", 7),
            ],
        )

    def test_lines_follow_profile_weight_and_report_counts(self):
        entry = self._entry_with_three_aspects()
        attach_primary_copy(
            _result(entry, _entry("B", 100)),
            preferences={"sabor": 1.0, "aroma": 0.33, "tueste": 0.67, "precio": 0.0},
        )

        lines = entry.metadata["aspect_mention_lines"]
        self.assertEqual(
            [line["text"] for line in lines],
            [
                "Sabor: 45 de 52 menciones favorables",
                "Calidad del tueste: 12 de 12 menciones favorables",
                "Aroma: 46 de 47 menciones favorables",
            ],
        )
        # Un aspecto con peso 0 no aparece, aunque tuviera menciones (E4).
        self.assertNotIn("precio", [line["aspect"] for line in lines])

    def test_flat_profile_falls_back_to_total_mentions(self):
        entry = self._entry_with_three_aspects()
        attach_primary_copy(
            _result(entry, _entry("B", 100)),
            preferences={"sabor": 0.67, "aroma": 0.67, "tueste": 0.67},
        )

        self.assertEqual(
            [line["aspect"] for line in entry.metadata["aspect_mention_lines"]],
            ["sabor", "aroma", "tueste"],
        )

    def test_at_most_three_lines_and_aspect_without_evidence_says_so(self):
        entry = _entry("A", 30, arguments_for=[_arg("sabor", "positive", 30)])
        attach_primary_copy(
            _result(entry, _entry("B", 100)),
            preferences={"sabor": 1.0, "aroma": 0.67, "tueste": 0.33, "precio": 0.33},
        )

        lines = entry.metadata["aspect_mention_lines"]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["text"], "Sabor: 30 de 30 menciones favorables")
        self.assertEqual(lines[1]["text"], "Aroma: sin menciones en las reseñas")

    def test_favorable_never_exceeds_total_and_totals_add_up_to_evidence(self):
        entry = self._entry_with_three_aspects()
        attach_primary_copy(
            _result(entry, _entry("B", 100)),
            preferences={"sabor": 1.0, "aroma": 0.33, "tueste": 0.67},
        )

        mentions = entry.metadata["aspect_mentions"]
        for aspect, counts in mentions.items():
            self.assertLessEqual(counts["favorable"], counts["total"], aspect)
        for line in entry.metadata["aspect_mention_lines"]:
            self.assertLessEqual(line["favorable"], line["total"], line["aspect"])
        self.assertEqual(
            sum(counts["total"] for counts in mentions.values()),
            entry.evidence_count,
        )

    def test_negative_counter_mirrors_the_positive_one(self):
        entry = self._entry_with_three_aspects()

        self.assertEqual(
            positive_mentions_by_aspect(entry),
            {"aroma": 46, "sabor": 45, "tueste": 12},
        )
        self.assertEqual(
            negative_mentions_by_aspect(entry),
            {"aroma": 1, "sabor": 7},
        )


class SharedFirstLabelTests(SimpleTestCase):
    """Resguardo del rótulo del 1.º (validacion_robustez/RESULTADOS.md §3)."""

    @staticmethod
    def _ranking(*scores: float) -> EvaluationResult:
        entries = []
        for position, score in enumerate(scores, start=1):
            base = _entry(f"P{position}", 100)
            entries.append(
                RankingEntry(
                    **{**base.__dict__, "position": position, "final_score": score}
                )
            )
        return _result(*entries)

    def test_a_clear_first_keeps_the_single_best_label(self):
        result = self._ranking(0.3631, 0.3498, 0.3017)

        attach_primary_copy(result)

        self.assertEqual(result.ranking[0].metadata["match_label"], FIRST_MATCH_LABEL)
        self.assertEqual(result.ranking[1].metadata["match_label"], "Buena coincidencia")
        self.assertEqual(result.ranking[2].metadata["match_label"], "Coincidencia media")
        for entry in result.ranking:
            self.assertNotIn("shared_label_note", entry.metadata)

    def test_a_tied_head_shares_the_label_and_says_how_many(self):
        # Puntajes reales de "solo sabor": 1.º y 2.º difieren en 0,0009 y los
        # cuatro primeros entran en un centésimo.
        result = self._ranking(0.641167, 0.640305, 0.631273, 0.631273, 0.621230)

        attach_primary_copy(result)

        labels = [entry.metadata["match_label"] for entry in result.ranking]
        self.assertEqual(labels[:4], [SHARED_MATCH_LABEL] * 4)
        self.assertEqual(labels[4], "Coincidencia media")
        self.assertEqual(
            result.ranking[0].metadata["shared_label_note"],
            "Las 4 primeras opciones quedaron a menos de 0,01 de puntaje: "
            "el orden entre ellas no es concluyente",
        )
        self.assertNotIn("shared_label_note", result.ranking[4].metadata)

    def test_the_threshold_is_the_only_boundary(self):
        justo_abajo = self._ranking(0.50, 0.50 - SHARED_LABEL_MAX_GAP + 1e-6)
        justo_arriba = self._ranking(0.50, 0.50 - SHARED_LABEL_MAX_GAP)

        attach_primary_copy(justo_abajo)
        attach_primary_copy(justo_arriba)

        self.assertEqual(justo_abajo.ranking[0].metadata["match_label"], SHARED_MATCH_LABEL)
        self.assertEqual(justo_arriba.ranking[0].metadata["match_label"], FIRST_MATCH_LABEL)

    def test_a_single_option_is_not_a_tie(self):
        result = self._ranking(0.3631)

        attach_primary_copy(result)

        self.assertEqual(result.ranking[0].metadata["match_label"], FIRST_MATCH_LABEL)

    def test_a_rejected_option_keeps_its_own_label_and_does_not_count(self):
        result = self._ranking(0.3631, 0.3498)
        rejected = RankingEntry(
            **{**_entry("Z", 10).__dict__, "position": 3, "final_score": 0.0,
               "status": "not_recommended"}
        )
        result = _result(*result.ranking, rejected)

        attach_primary_copy(result)

        self.assertEqual(result.ranking[0].metadata["match_label"], FIRST_MATCH_LABEL)
        self.assertEqual(result.ranking[2].metadata["match_label"], "No cumple lo que pediste")
        self.assertEqual(head_gaps(result.ranking)[1], 0)

    def test_match_label_needs_the_distance(self):
        with self.assertRaises(TypeError):
            match_label(1)  # type: ignore[call-arg]


@unittest.skipUnless(BATTERY.exists(), "falta la batería del snapshot congelado")
class SharedFirstLabelOnFrozenSnapshotTests(SimpleTestCase):
    """El rótulo sobre los puntajes reales de la batería, sin copiarlos a mano."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.battery = json.loads(BATTERY.read_text(encoding="utf-8"))

    def _labels(self, profile: str) -> list[str]:
        rows = self.battery[profile]
        entries = [
            RankingEntry(
                **{
                    **_entry(row["product"], int(row.get("reviews") or 0)).__dict__,
                    "position": position,
                    "final_score": float(row["score"]),
                }
            )
            for position, row in enumerate(rows, start=1)
        ]
        result = _result(*entries)
        attach_primary_copy(result)
        return [entry.metadata["match_label"] for entry in result.ranking]

    def test_solo_sabor_does_not_declare_a_single_best(self):
        labels = self._labels("solo_sabor")

        self.assertEqual(labels[0], SHARED_MATCH_LABEL)
        self.assertNotIn(FIRST_MATCH_LABEL, labels)

    def test_neutro_keeps_the_single_best(self):
        labels = self._labels("neutral")

        self.assertEqual(labels[0], FIRST_MATCH_LABEL)
        self.assertNotIn(SHARED_MATCH_LABEL, labels)


def _claim(favor: int, against: int, fact_favor: float, fact_against: float,
           mu: float = 0.0, delta: float = 0.0) -> ClaimRow:
    return ClaimRow(
        key="sabor",
        label="Sabor",
        status="assured",
        status_label="Sostenido",
        formal_status="Assured",
        mu=mu,
        delta=delta,
        favor=1 if favor else 0,
        against=1 if against else 0,
        refuted=0,
        standing=1 if against else 0,
        preference=0.67,
        priority_label="Bastante",
        priority_key="high",
        narrative="",
        mentions_favor=favor,
        mentions_against=against,
        fact_favor=fact_favor,
        fact_against=fact_against,
    )


class AspectNarrativeTests(SimpleTestCase):
    """Una sola oración por característica, con y sin críticas (Tarea 2)."""

    def test_with_a_criticism_it_shows_the_conflict_and_the_laf_result(self):
        # Texto que ya mostraba la plantilla, ahora desde presentation.py.
        oracion = aspect_claim_narrative(
            _claim(45, 7, 0.93, 0.62, mu=0.84, delta=0.53), laf_score=0.478
        )

        self.assertEqual(
            oracion,
            "45 menciones del aspecto a favor y 7 en contra en las reseñas de "
            "este café. La evidencia favorable pesa 0,93 y la crítica 0,62. "
            "Al enfrentarlas, la conclusión favorable pasa de 0,84 a 0,53; "
            "las reglas que llevan de este punto a la recomendación la dejan "
            "en 0,48.",
        )

    def test_without_criticism_it_also_shows_the_values(self):
        oracion = aspect_claim_narrative(
            _claim(61, 0, 0.91, 0.0, mu=0.82, delta=0.82), laf_score=0.737
        )

        self.assertEqual(
            oracion,
            "61 menciones del aspecto a favor y ninguna en contra en las "
            "reseñas de este café. La evidencia favorable pesa 0,91; sin "
            "críticas, la conclusión no fue debilitada y las reglas que llevan "
            "de este punto a la recomendación la dejan en 0,74.",
        )

    def test_one_mention_is_singular(self):
        oracion = aspect_claim_narrative(_claim(1, 0, 0.5, 0.0), laf_score=0.4)

        self.assertTrue(oracion.startswith("1 mención del aspecto a favor y ninguna en contra"))

    def test_without_a_laf_result_it_does_not_invent_one(self):
        # Un aspecto con peso 0 no entra al desglose: no hay resultado LAF.
        con_critica = aspect_claim_narrative(_claim(45, 7, 0.93, 0.62, mu=0.84, delta=0.53))
        sin_critica = aspect_claim_narrative(_claim(61, 0, 0.91, 0.0))

        self.assertTrue(con_critica.endswith("pasa de 0,84 a 0,53."))
        self.assertTrue(sin_critica.endswith("la conclusión no fue debilitada."))
        for oracion in (con_critica, sin_critica):
            self.assertNotIn("None", oracion)
            self.assertNotIn("reglas que llevan", oracion)

    def test_a_criticism_without_an_aggregated_fact_only_counts(self):
        oracion = aspect_claim_narrative(_claim(45, 7, 0.93, 0.0), laf_score=0.5)

        self.assertEqual(
            oracion,
            "45 menciones del aspecto a favor y 7 en contra en las reseñas de este café.",
        )
