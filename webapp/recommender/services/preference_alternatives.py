"""Modelos alternativos de preferencia, para comparar contra el vigente.

Herramienta de validacion, no del recorrido de usuario: corre variantes de la
funcion de preferencia sobre los mismos resultados LAF y escribe reportes.
"""
from __future__ import annotations

from collections import Counter
import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from statistics import mean
from typing import Callable, Iterable

from recommender.domain.contracts import EvaluationRequest, RankingEntry
from recommender.services.post_laf_decision import (
    normalized_multicriteria_ranking,
    zero_threshold_payload,
)
from recommender.services.recommendation_quality import QualityProfile


MODEL_LABELS = {
    "actual": "Configuración actual",
    "zero_threshold": "Excluir preferencia cero",
    "weighted_confidence": "Influencia ponderada dentro de LAF",
    "post_laf_multicriteria": "Decisión multicriterio después de LAF",
}


@dataclass(frozen=True)
class AlternativeCase:
    model: str
    profile_name: str
    profile_title: str
    profile_kind: str
    focused_aspects: tuple[str, ...]
    preferences: dict[str, float]
    expected_winner_ids: tuple[str, ...]
    winner_id: str
    winner_name: str
    winner_score: float
    runner_up_score: float
    margin: float
    top3_ids: tuple[str, ...]
    top3_names: tuple[str, ...]
    exact_match: bool | None
    expected_in_top3: bool | None
    high_score: bool


def _number(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric if math.isfinite(numeric) else 0.0


def _format_number(value: float) -> str:
    return f"{max(0.0, min(float(value), 1.0)):.12g}"


def weighted_confidence_payload(payload: dict[str, object]) -> dict[str, object]:
    """Convierte confianza×preferencia en una etiqueta operativa de influencia."""
    transformed = zero_threshold_payload(payload)
    for fact in transformed.get("facts", []):
        attributes = list(fact.get("attributes") or [])
        if len(attributes) < 2:
            continue
        confidence = _number(attributes[0])
        preference = _number(attributes[1])
        attributes[0] = _format_number(confidence * preference)
        attributes[1] = "1"
        fact["attributes"] = attributes
        intervals = list(fact.get("attributeIntervals") or [])
        if len(intervals) >= 2:
            intervals[0] = None
            intervals[1] = None
            fact["attributeIntervals"] = intervals
    return transformed


def build_weight_sweep_profiles(
    aspect_labels: dict[str, str],
    *,
    background: float = 0.67,
    levels: tuple[float, ...] = (0.33, 0.67, 1.0),
) -> tuple[QualityProfile, ...]:
    """Varía un aspecto por vez contra un fondo neutral para medir sensibilidad real."""
    profiles = []
    for aspect, label in aspect_labels.items():
        for level in levels:
            preferences = {key: background for key in aspect_labels}
            preferences[aspect] = level
            code = f"{round(level * 100):03d}"
            profiles.append(
                QualityProfile(
                    name=f"peso_{aspect}_{code}",
                    title=f"{label}: {level:.2f} con los demás en {background:.2f}",
                    kind="weight_sweep",
                    focused_aspects=(aspect,),
                    preferences=preferences,
                )
            )
    return tuple(profiles)


def _ranking_rows(ranking: Iterable[RankingEntry]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "entity_id": entry.entity_id,
            "entity_name": entry.entity_name,
            "score": entry.final_score,
            "confidence": entry.confidence,
            "preference": entry.preference,
        }
        for entry in ranking
    )


def _case_from_ranking(
    model: str,
    profile: QualityProfile,
    ranking: tuple[dict[str, object], ...],
    expectation: dict[str, object],
) -> AlternativeCase:
    approved = str(expectation.get("review_status") or "") == "approved"
    expected = tuple(
        str(value)
        for value in expectation.get("expected_winner_ids", [])
        if str(value)
    ) if approved else ()
    winner = ranking[0] if ranking else {}
    top3 = ranking[:3]
    winner_id = str(winner.get("entity_id") or "")
    score = _number(winner.get("score"))
    runner_up = _number(ranking[1].get("score")) if len(ranking) > 1 else 0.0
    top3_ids = tuple(str(row.get("entity_id") or "") for row in top3)
    return AlternativeCase(
        model=model,
        profile_name=profile.name,
        profile_title=profile.title,
        profile_kind=profile.kind,
        focused_aspects=profile.focused_aspects,
        preferences=dict(profile.preferences),
        expected_winner_ids=expected,
        winner_id=winner_id,
        winner_name=str(winner.get("entity_name") or ""),
        winner_score=score,
        runner_up_score=runner_up,
        margin=score - runner_up,
        top3_ids=top3_ids,
        top3_names=tuple(str(row.get("entity_name") or "") for row in top3),
        exact_match=(winner_id in expected) if expected else None,
        expected_in_top3=bool(set(expected) & set(top3_ids)) if expected else None,
        high_score=score >= 0.95,
    )


class PreferenceAlternativesRunner:
    def __init__(self, evaluator):
        self.evaluator = evaluator

    def run(
        self,
        base_request: EvaluationRequest,
        profiles: Iterable[QualityProfile],
        *,
        expectations: dict[str, dict[str, object]],
        progress: Callable[[str], None] | None = None,
    ) -> list[AlternativeCase]:
        profiles = tuple(profiles)
        cases: list[AlternativeCase] = []
        entity_names: dict[str, str] = {}

        for index, profile in enumerate(profiles, start=1):
            generated, payload = self._program(base_request, profile.preferences)
            entity_names.update(
                {
                    str(entity.get("entity_id") or ""): str(entity.get("entity_name") or "")
                    for entity in generated.entities
                }
            )
            variants = {
                "actual": payload,
                "zero_threshold": zero_threshold_payload(payload),
                "weighted_confidence": weighted_confidence_payload(payload),
            }
            for model, candidate_payload in variants.items():
                ranking = self._evaluate_payload(candidate_payload, generated.entities)
                cases.append(
                    _case_from_ranking(
                        model,
                        profile,
                        ranking,
                        expectations.get(profile.name, {}),
                    )
                )
            if progress:
                progress(f"[{index:>2}/{len(profiles)}] {profile.name}: tres variantes LAF")

        aspect_scores: dict[str, dict[str, float]] = {}
        aspects = tuple(dict.fromkeys(
            aspect
            for profile in profiles
            for aspect in profile.preferences
        ))
        for index, aspect in enumerate(aspects, start=1):
            generated, payload = self._program(base_request, {aspect: 1.0})
            ranking = self._evaluate_payload(
                zero_threshold_payload(payload),
                generated.entities,
            )
            aspect_scores[aspect] = {
                str(row["entity_id"]): _number(row["score"])
                for row in ranking
            }
            entity_names.update(
                {
                    str(entity.get("entity_id") or ""): str(entity.get("entity_name") or "")
                    for entity in generated.entities
                }
            )
            if progress:
                progress(f"[{index:>2}/{len(aspects)}] matriz multicriterio: {aspect}")

        for profile in profiles:
            ranking = normalized_multicriteria_ranking(
                aspect_scores,
                profile.preferences,
                entity_names,
            )
            cases.append(
                _case_from_ranking(
                    "post_laf_multicriteria",
                    profile,
                    ranking,
                    expectations.get(profile.name, {}),
                )
            )
        return cases

    def _program(
        self,
        base_request: EvaluationRequest,
        preferences: dict[str, float],
    ):
        request = EvaluationRequest(
            domain=base_request.domain,
            dataset_key=base_request.dataset_key,
            strategy=base_request.strategy,
            preferences=preferences,
        )
        generated = self.evaluator.laf1_programs.generate(request)
        return generated, self.evaluator.parser.parse(generated.text).to_request_payload()

    def _evaluate_payload(
        self,
        payload: dict[str, object],
        entities: Iterable[dict[str, object]],
    ) -> tuple[dict[str, object], ...]:
        graph = self.evaluator.api_client.build_graph(payload)
        return _ranking_rows(self.evaluator.ranking_mapper.map(graph, entities))


def summarize_alternatives(cases: Iterable[AlternativeCase]) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[AlternativeCase]] = {}
    for case in cases:
        grouped.setdefault(case.model, []).append(case)
    result: dict[str, dict[str, object]] = {}
    for model, model_cases in grouped.items():
        reviewed = [case for case in model_cases if case.expected_winner_ids]
        distribution = Counter(case.winner_name for case in model_cases if case.winner_name)
        dominant_name, dominant_count = distribution.most_common(1)[0] if distribution else ("", 0)
        neutral_winner = next(
            (case.winner_id for case in model_cases if case.profile_name == "neutral"),
            "",
        )
        non_neutral = [case for case in model_cases if case.profile_name != "neutral"]
        result[model] = {
            "label": MODEL_LABELS.get(model, model),
            "cases": len(model_cases),
            "reviewed_cases": len(reviewed),
            "exact_matches": sum(bool(case.exact_match) for case in reviewed),
            "exact_accuracy": mean(bool(case.exact_match) for case in reviewed) if reviewed else None,
            "top3_matches": sum(bool(case.expected_in_top3) for case in reviewed),
            "top3_accuracy": mean(bool(case.expected_in_top3) for case in reviewed) if reviewed else None,
            "high_score_rate": mean(case.high_score for case in model_cases) if model_cases else None,
            "average_margin": mean(case.margin for case in model_cases) if model_cases else 0.0,
            "distinct_winners": len(distribution),
            "dominant_winner_name": dominant_name,
            "dominant_winner_count": dominant_count,
            "dominant_winner_share": dominant_count / len(model_cases) if model_cases else 0.0,
            "winner_change_from_neutral": (
                mean(case.winner_id != neutral_winner for case in non_neutral)
                if non_neutral and neutral_winner else None
            ),
            "winner_distribution": dict(distribution),
        }
    return result


def summarize_weight_sweep(cases: Iterable[AlternativeCase]) -> dict[str, dict[str, object]]:
    grouped: dict[str, dict[str, list[AlternativeCase]]] = {}
    for case in cases:
        if case.profile_kind != "weight_sweep" or not case.focused_aspects:
            continue
        grouped.setdefault(case.model, {}).setdefault(
            case.focused_aspects[0], []
        ).append(case)
    result: dict[str, dict[str, object]] = {}
    for model, by_aspect in grouped.items():
        details = []
        for aspect, aspect_cases in by_aspect.items():
            ordered = sorted(
                aspect_cases,
                key=lambda case: float(case.preferences.get(aspect, 0.0)),
            )
            if len(ordered) < 2:
                continue
            low, high = ordered[0], ordered[-1]
            union = set(low.top3_ids) | set(high.top3_ids)
            overlap = (
                len(set(low.top3_ids) & set(high.top3_ids)) / len(union)
                if union else 1.0
            )
            details.append(
                {
                    "aspect": aspect,
                    "winner_changed_low_to_high": low.winner_id != high.winner_id,
                    "top3_changed_low_to_high": set(low.top3_ids) != set(high.top3_ids),
                    "top3_overlap_low_high": overlap,
                    "absolute_top_score_change_low_high": abs(
                        high.winner_score - low.winner_score
                    ),
                    "sequence": [
                        {
                            "level": float(case.preferences.get(aspect, 0.0)),
                            "winner_id": case.winner_id,
                            "winner_name": case.winner_name,
                            "winner_score": case.winner_score,
                            "top3_ids": list(case.top3_ids),
                        }
                        for case in ordered
                    ],
                }
            )
        result[model] = {
            "label": MODEL_LABELS.get(model, model),
            "aspects": len(details),
            "winner_changed_aspects": sum(
                row["winner_changed_low_to_high"] for row in details
            ),
            "winner_change_rate": (
                mean(row["winner_changed_low_to_high"] for row in details)
                if details else None
            ),
            "top3_changed_aspects": sum(
                row["top3_changed_low_to_high"] for row in details
            ),
            "top3_change_rate": (
                mean(row["top3_changed_low_to_high"] for row in details)
                if details else None
            ),
            "average_top3_overlap": (
                mean(float(row["top3_overlap_low_high"]) for row in details)
                if details else None
            ),
            "score_changed_aspects": sum(
                float(row["absolute_top_score_change_low_high"]) > 1e-9
                for row in details
            ),
            "average_absolute_top_score_change": (
                mean(
                    float(row["absolute_top_score_change_low_high"])
                    for row in details
                ) if details else 0.0
            ),
            "high_score_rate": (
                mean(case.high_score for rows in by_aspect.values() for case in rows)
                if by_aspect else None
            ),
            "details": details,
        }
    return result


def _percent(value: object) -> str:
    return "No medido" if value is None else f"{float(value):.1%}"


def _md(value: object) -> str:
    return str(value).replace("|", r"\|").replace("\r", " ").replace("\n", " ")


def write_alternative_reports(
    output_dir: Path,
    *,
    metadata: dict[str, object],
    cases: list[AlternativeCase],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize_alternatives(cases)
    json_path = output_dir / "experimento_preferencias.json"
    csv_path = output_dir / "casos_modelos.csv"
    markdown_path = output_dir / "resumen.md"

    json_path.write_text(
        json.dumps(
            {
                "metadata": metadata,
                "summary": summary,
                "cases": [asdict(case) for case in cases],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "modelo", "caso", "tipo", "ganador", "puntaje", "margen",
                "ganadores_esperados", "acierto_exacto", "esperado_en_top3",
                "top3",
            ]
        )
        for case in cases:
            writer.writerow(
                [
                    case.model,
                    case.profile_name,
                    case.profile_kind,
                    case.winner_name,
                    f"{case.winner_score:.6f}",
                    f"{case.margin:.6f}",
                    " | ".join(case.expected_winner_ids),
                    case.exact_match,
                    case.expected_in_top3,
                    " | ".join(case.top3_names),
                ]
            )

    lines = [
        "# Comparación experimental de modelos de preferencia",
        "",
        f"- Dataset: `{metadata.get('dataset_key', '')}`",
        f"- Estrategia LAF: `{metadata.get('strategy', '')}`",
        f"- Casos aprobados usados: {metadata.get('approved_cases', 0)}",
        "",
        "> **Alcance:** estos 20 casos son casos de desarrollo con revisión humana asistida. "
        "Sirven para comparar comportamiento y detectar regresiones, pero no constituyen "
        "una evaluación ciega independiente.",
        "",
        "## Alternativas",
        "",
        "1. **Configuración actual:** propaga confianza y preferencia como etiquetas independientes.",
        "2. **Excluir preferencia cero:** no envía al motor hechos que el usuario desactivó.",
        "3. **Influencia ponderada dentro de LAF:** usa `confianza × preferencia` como "
        "confianza operativa y deja beta neutral en los hechos activos.",
        "4. **Decisión multicriterio después de LAF:** ejecuta LAF por aspecto y combina "
        "sus resultados con un promedio ponderado normalizado.",
        "",
        "## Resultados generales",
        "",
        "| Modelo | Acierto exacto | Esperado en top 3 | Ganadores distintos | Dominancia | "
        "Cambio frente a neutral | Puntajes ≥ 0,95 | Margen medio |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model in MODEL_LABELS:
        row = summary.get(model, {})
        lines.append(
            f"| {_md(row.get('label', model))} "
            f"| {_percent(row.get('exact_accuracy'))} "
            f"| {_percent(row.get('top3_accuracy'))} "
            f"| {row.get('distinct_winners', 0)} "
            f"| {_percent(row.get('dominant_winner_share'))} "
            f"| {_percent(row.get('winner_change_from_neutral'))} "
            f"| {_percent(row.get('high_score_rate'))} "
            f"| {float(row.get('average_margin') or 0):.4f} |"
        )

    lines.extend(
        [
            "",
            "## Propiedades esperadas de los sliders",
            "",
            "| Propiedad | Actual | Excluir cero | Influencia ponderada | Multicriterio |",
            "|---|:---:|:---:|:---:|:---:|",
            "| Un aspecto en 0 no altera el ranking | No | Sí | Sí | Sí |",
            "| 0,33 influye menos que 0,67 y 1 frente a otros aspectos | No garantizado | "
            "No garantizado | Sí en la entrada | Sí en la decisión |",
            "| Conserva la confianza LAF sin mezclarla con utilidad | Sí | Sí | No | Sí |",
            "| Evita que las preferencias se sumen dentro de LAF hasta 1 | No | No | "
            "La segunda etiqueta sí | Sí |",
            "| Produce un orden total simple | Sí | Sí | Sí | Sí |",
            "",
            "## Resultados por caso",
            "",
            "| Caso | Actual | Excluir cero | Ponderada | Multicriterio | Esperado |",
            "|---|---|---|---|---|---|",
        ]
    )
    by_profile: dict[str, dict[str, AlternativeCase]] = {}
    for case in cases:
        by_profile.setdefault(case.profile_name, {})[case.model] = case
    for profile_name, rows in by_profile.items():
        reference = next(iter(rows.values()))
        cells = []
        for model in MODEL_LABELS:
            case = rows.get(model)
            if not case:
                cells.append("Sin resultado")
                continue
            marker = "✓" if case.exact_match else "✗"
            cells.append(f"{_md(case.winner_name)} ({marker})")
        lines.append(
            f"| {_md(reference.profile_title)} | "
            + " | ".join(cells)
            + f" | {' · '.join(reference.expected_winner_ids)} |"
        )

    lines.extend(
        [
            "",
            "## Cómo interpretar la comparación",
            "",
            "- El acierto contra estos casos no debe usarse solo para elegir el modelo: las "
            "expectativas se propusieron originalmente mediante una línea base ponderada.",
            "- La exclusión de cero es una propiedad semántica comprobable: si el usuario dice "
            "que un aspecto no importa, variar su evidencia no debe cambiar el resultado.",
            "- Los pesos intermedios deben evaluarse por influencia relativa y estabilidad, no "
            "por exigir que cambien el ganador cuando son el único aspecto activo.",
            "- Antes de adoptar una alternativa hace falta un conjunto nuevo de casos revisados "
            "sin mostrar la salida de ninguno de los modelos.",
            "",
            "## Decisiones metodológicas pendientes",
            "",
            "1. Confirmar si `0` significa excluir totalmente un aspecto de la personalización.",
            "2. Separar restricciones obligatorias —seguridad, fraude o vencimiento real— de "
            "preferencias opcionales.",
            "3. Decidir si la evidencia negativa de rendimiento, preparación y molienda debe "
            "atacar la recomendación.",
            "4. Elegir si la confianza debe conservar su significado puro o si puede convertirse "
            "en una medida de influencia ponderada.",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {"markdown": markdown_path, "csv": csv_path, "json": json_path}


def write_weight_sweep_reports(
    output_dir: Path,
    *,
    metadata: dict[str, object],
    cases: list[AlternativeCase],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize_weight_sweep(cases)
    json_path = output_dir / "sensibilidad_pesos.json"
    csv_path = output_dir / "sensibilidad_pesos.csv"
    markdown_path = output_dir / "sensibilidad_pesos.md"
    json_path.write_text(
        json.dumps(
            {
                "metadata": metadata,
                "summary": summary,
                "cases": [asdict(case) for case in cases],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["modelo", "aspecto", "nivel", "ganador", "puntaje", "top3"]
        )
        for case in cases:
            aspect = case.focused_aspects[0] if case.focused_aspects else ""
            writer.writerow(
                [
                    case.model,
                    aspect,
                    case.preferences.get(aspect, 0),
                    case.winner_name,
                    f"{case.winner_score:.6f}",
                    " | ".join(case.top3_names),
                ]
            )

    lines = [
        "# Sensibilidad real a pesos intermedios",
        "",
        "Para cada uno de los 14 aspectos se mantuvieron los demás en `0.67` y se "
        "varió el aspecto analizado entre `0.33`, `0.67` y `1`. Estos perfiles no "
        "tienen un ganador humano esperado: miden respuesta y estabilidad, no exactitud.",
        "",
        "| Modelo | Aspectos que cambian ganador 0,33→1 | Aspectos que cambian top 3 | "
        "Puntaje cambia | Cambio absoluto medio | Solapamiento top 3 | Puntajes ≥ 0,95 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model in MODEL_LABELS:
        row = summary.get(model, {})
        lines.append(
            f"| {_md(row.get('label', model))} "
            f"| {row.get('winner_changed_aspects', 0)}/{row.get('aspects', 0)} "
            f"| {row.get('top3_changed_aspects', 0)}/{row.get('aspects', 0)} "
            f"| {row.get('score_changed_aspects', 0)}/{row.get('aspects', 0)} "
            f"| {float(row.get('average_absolute_top_score_change') or 0):.6f} "
            f"| {_percent(row.get('average_top3_overlap'))} "
            f"| {_percent(row.get('high_score_rate'))} |"
        )
    no_score_response = [
        summary[model].get("label", model)
        for model in MODEL_LABELS
        if summary.get(model, {}).get("aspects", 0)
        and summary[model].get("score_changed_aspects", 0) == 0
    ]
    score_only_response = [
        summary[model].get("label", model)
        for model in MODEL_LABELS
        if summary.get(model, {}).get("score_changed_aspects", 0) > 0
        and summary[model].get("top3_changed_aspects", 0) == 0
    ]
    lines.extend(["", "## Lectura de los resultados", ""])
    if no_score_response:
        lines.append(
            "- **Sin respuesta a pesos intermedios:** "
            + ", ".join(_md(label) for label in no_score_response)
            + ". Al variar un aspecto de 0,33 a 1 no cambió ni el puntaje del ganador."
        )
    if score_only_response:
        lines.append(
            "- **Respuesta numérica sin cambio del top 3:** "
            + ", ".join(_md(label) for label in score_only_response)
            + ". Los pesos sí alteraron puntajes, pero no alcanzaron a cambiar los tres "
            "primeros productos en esta muestra."
        )
    lines.extend(
        [
            "- `Excluir preferencia cero` coincide con la configuración actual en esta "
            "prueba porque todos los pesos ensayados son mayores que cero. Esa alternativa "
            "solo cambia el comportamiento cuando el usuario desactiva un aspecto.",
            "- Esta prueba mide sensibilidad, no calidad del ganador. La exactitud se evalúa "
            "por separado con los 20 casos revisados por una persona.",
        ]
    )
    lines.extend(
        [
            "",
            "## Secuencia por aspecto",
            "",
            "Cada celda muestra el ganador con peso `0.33 → 0.67 → 1`.",
            "",
            "| Aspecto | Actual | Excluir cero | Ponderada | Multicriterio |",
            "|---|---|---|---|---|",
        ]
    )
    aspects = sorted(
        {
            detail["aspect"]
            for model in summary.values()
            for detail in model.get("details", [])
        }
    )
    detail_index = {
        (model, detail["aspect"]): detail
        for model, model_summary in summary.items()
        for detail in model_summary.get("details", [])
    }
    for aspect in aspects:
        cells = []
        for model in MODEL_LABELS:
            detail = detail_index.get((model, aspect), {})
            sequence = detail.get("sequence", [])
            cells.append(" → ".join(_md(row["winner_name"]) for row in sequence))
        lines.append(f"| `{aspect}` | " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "> Que el ganador no cambie no implica necesariamente insensibilidad: puede "
            "mantenerse primero mientras cambian puntajes o posiciones inferiores. Por eso se "
            "informa también el cambio y solapamiento del top 3.",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {"markdown": markdown_path, "csv": csv_path, "json": json_path}
