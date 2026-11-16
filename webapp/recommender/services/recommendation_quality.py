"""Evaluación reproducible de calidad del ranking frente a referencias externas."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
from pathlib import Path
import re
from statistics import mean
from typing import Callable, Iterable

from recommender.domain.contracts import EvaluationRequest, EvaluationResult, RankingEntry
from recommender.services.laf_api import LAFProgramParseError, LAFProgramParser


NEUTRAL_LEVEL = 0.67


@dataclass(frozen=True)
class QualityProfile:
    name: str
    title: str
    kind: str
    preferences: dict[str, float]
    focused_aspects: tuple[str, ...]


@dataclass(frozen=True)
class QualityCase:
    name: str
    title: str
    kind: str
    focused_aspects: tuple[str, ...]
    preferences: dict[str, float]
    status: str
    error: str
    laf_winner_id: str
    laf_winner_name: str
    laf_winner_score: float
    laf_winner_confidence: float
    laf_winner_preference: float
    laf_runner_up_score: float
    laf_winner_margin: float
    top3_preference_saturated: bool
    laf_top3_ids: tuple[str, ...]
    laf_top3_names: tuple[str, ...]
    baseline_winner_id: str
    baseline_winner_name: str
    baseline_winner_score: float
    baseline_top3_ids: tuple[str, ...]
    baseline_top3_names: tuple[str, ...]
    baseline_candidates: tuple[dict[str, object], ...]
    assisted_decision: str
    assisted_winner_ids: tuple[str, ...]
    assisted_winner_names: tuple[str, ...]
    assisted_rationale: str
    baseline_match: bool
    laf_winner_in_baseline_top3: bool
    top3_overlap: float
    winner_reasons: tuple[dict[str, object], ...]
    review_status: str
    expected_winner_ids: tuple[str, ...]
    expected_top3_ids: tuple[str, ...]
    expert_rationale: str
    reviewer: str
    reviewed_at: str
    human_winner_match: bool | None
    human_expected_in_laf_top3: bool | None


def build_quality_profiles(
    aspect_labels: dict[str, str],
    dimensions: dict[str, dict[str, object]],
    current: dict[str, float] | None = None,
) -> tuple[QualityProfile, ...]:
    """Crea casos interpretables: neutral, aspecto único y dimensión completa."""
    aspects = tuple(aspect_labels)
    neutral = {aspect: NEUTRAL_LEVEL for aspect in aspects}
    profiles = [
        QualityProfile(
            name="neutral",
            title="Todas las preferencias en nivel neutral",
            kind="neutral",
            preferences=neutral,
            focused_aspects=aspects,
        )
    ]
    normalized_current = {
        aspect: float((current or {}).get(aspect, NEUTRAL_LEVEL))
        for aspect in aspects
    }
    if normalized_current != neutral:
        profiles.append(
            QualityProfile(
                name="perfil_actual",
                title="Preferencias guardadas en el recorrido",
                kind="current",
                preferences=normalized_current,
                focused_aspects=tuple(
                    aspect for aspect in aspects if normalized_current[aspect] > 0
                ),
            )
        )
    for aspect in aspects:
        profiles.append(
            QualityProfile(
                name=f"solo_{aspect}",
                title=f"Sólo importa {aspect_labels[aspect]}",
                kind="one_hot",
                preferences={key: 1.0 if key == aspect else 0.0 for key in aspects},
                focused_aspects=(aspect,),
            )
        )
    for dimension_key, raw_dimension in dimensions.items():
        dimension_aspects = tuple(
            aspect
            for aspect in raw_dimension.get("aspects", ())
            if aspect in aspect_labels
        )
        if not dimension_aspects:
            continue
        label = str(raw_dimension.get("label") or dimension_key.replace("_", " ").title())
        profiles.append(
            QualityProfile(
                name=f"dimension_{dimension_key}",
                title=f"Prioridad: {label}",
                kind="dimension",
                preferences={
                    key: 1.0 if key in dimension_aspects else 0.0 for key in aspects
                },
                focused_aspects=dimension_aspects,
            )
        )
    return tuple(profiles)


def load_expectations(path: Path | None) -> dict[str, dict[str, object]]:
    if path is None:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("cases", []) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("El archivo de expectativas debe contener una lista 'cases'.")
    return {
        str(row.get("name") or ""): row
        for row in rows
        if isinstance(row, dict) and str(row.get("name") or "")
    }


def _number(value: object) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _aspect_from_fact(name: str) -> tuple[str, str] | None:
    match = re.match(r"^resena(Positiva|Negativa)([A-Z].*)$", name.lstrip("~"))
    if match is None:
        return None
    aspect = re.sub(r"(?<!^)(?=[A-Z])", "_", match.group(2)).casefold()
    polarity = "positive" if match.group(1) == "Positiva" else "negative"
    return aspect, polarity


def _evidence_baseline(result: EvaluationResult) -> tuple[dict[str, object], ...]:
    """Ordena candidatos con una suma firmada anterior a las reglas de LAF.

    Esta línea base usa únicamente los hechos de reseñas del programa generado:
    confianza × preferencia para evidencia positiva y el opuesto para negativa.
    No usa la conclusión ``recomendar`` ni su posición en el ranking LAF.
    """
    if not result.laf_program:
        return ()
    try:
        facts = LAFProgramParser().parse(result.laf_program).facts
    except LAFProgramParseError:
        return ()
    entries_by_argument = {
        str(entry.metadata.get("laf_argument") or ""): entry
        for entry in result.ranking
        if str(entry.metadata.get("laf_argument") or "")
    }
    evidence: dict[str, dict[str, dict[str, float]]] = {}
    for fact in facts:
        parsed = _aspect_from_fact(str(fact.get("name") or ""))
        argument = str(fact.get("argument") or "")
        if parsed is None or argument not in entries_by_argument:
            continue
        aspect, polarity = parsed
        attributes = fact.get("attributes") or []
        confidence = _number(attributes[0] if attributes else 0)
        preference = _number(attributes[1] if len(attributes) > 1 else 0)
        bucket = evidence.setdefault(argument, {}).setdefault(
            aspect,
            {"positive": 0.0, "negative": 0.0, "preference": preference},
        )
        bucket[polarity] = max(bucket[polarity], confidence)
        bucket["preference"] = max(bucket["preference"], preference)

    rows = []
    for argument, entry in entries_by_argument.items():
        by_aspect = evidence.get(argument, {})
        evidence_counts = {
            (item.aspect, item.polarity): item.evidence_count
            for item in (*entry.arguments_for, *entry.arguments_against)
        }
        contributions = []
        for aspect, values in by_aspect.items():
            positive = values["positive"] * values["preference"]
            negative = values["negative"] * values["preference"]
            contributions.append(
                {
                    "aspect": aspect,
                    "preference": values["preference"],
                    "positive_confidence": values["positive"],
                    "negative_confidence": values["negative"],
                    "positive": positive,
                    "negative": negative,
                    "net": positive - negative,
                    "positive_reviews": evidence_counts.get((aspect, "positive"), 0),
                    "negative_reviews": evidence_counts.get((aspect, "negative"), 0),
                }
            )
        score = sum(float(item["net"]) for item in contributions)
        rows.append(
            {
                "entity_id": entry.entity_id,
                "entity_name": entry.entity_name,
                "score": score,
                "coverage": sum(1 for item in contributions if item["positive"] or item["negative"]),
                "contributions": tuple(
                    sorted(contributions, key=lambda item: (-abs(float(item["net"])), item["aspect"]))
                ),
            }
        )
    rows.sort(key=lambda row: (-float(row["score"]), str(row["entity_id"]).casefold()))
    return tuple(rows)


def _assisted_proposal(
    baseline: tuple[dict[str, object], ...],
) -> tuple[str, tuple[str, ...], tuple[str, ...], str]:
    """Propone candidatos con una rúbrica fija, sin consultar la posición LAF."""
    if not baseline:
        return "insufficient", (), (), "No se pudo reconstruir la evidencia inicial."
    top_score = float(baseline[0]["score"])
    if top_score <= 0:
        return (
            "insufficient",
            (),
            (),
            "Ningún candidato obtuvo un balance directo de evidencia positivo.",
        )
    tolerance = max(abs(top_score) * 0.05, 0.02)
    acceptable = tuple(
        row for row in baseline[:5]
        if top_score - float(row["score"]) <= tolerance
    )[:3]
    top_contributions = [
        item
        for item in baseline[0].get("contributions", ())
        if float(item.get("preference", 0)) > 0
    ]
    review_count = sum(
        int(item.get("positive_reviews", 0)) + int(item.get("negative_reviews", 0))
        for item in top_contributions
    )
    if review_count < 3:
        decision = "insufficient"
    elif len(acceptable) > 1:
        decision = "ambiguous"
    else:
        decision = "clear"
    runner_up_score = float(baseline[1]["score"]) if len(baseline) > 1 else 0.0
    gap = top_score - runner_up_score
    evidence_note = ", ".join(
        f"{item['aspect']}: +{float(item['positive_confidence']):.2f}"
        f"/−{float(item['negative_confidence']):.2f}"
        f" ({int(item['positive_reviews'])}+/{int(item['negative_reviews'])}− reseñas)"
        for item in top_contributions[:3]
    ) or "sin aportes enfocados"
    rationale = (
        f"Mayor balance previo a LAF ({top_score:.3f}), con una ventaja de {gap:.3f} "
        f"sobre el segundo. Evidencia principal: {evidence_note}."
    )
    if decision == "ambiguous":
        rationale += " La diferencia está dentro del 5%, por eso se proponen varios ganadores aceptables."
    elif decision == "insufficient":
        rationale += " La cantidad de reseñas enfocadas es menor que 3; conviene excluir o revisar manualmente."
    return (
        decision,
        tuple(str(row["entity_id"]) for row in acceptable),
        tuple(str(row["entity_name"]) for row in acceptable),
        rationale,
    )


def _winner_reasons(entry: RankingEntry, focused_aspects: tuple[str, ...]) -> tuple[dict[str, object], ...]:
    focused = set(focused_aspects)
    reasons = []
    for argument in (*entry.arguments_for, *entry.arguments_against):
        if focused and argument.aspect not in focused:
            continue
        influence = min(argument.confidence, argument.preference)
        reasons.append(
            {
                "aspect": argument.aspect,
                "polarity": argument.polarity,
                "confidence": argument.confidence,
                "preference": argument.preference,
                "influence": influence,
                "evidence_count": argument.evidence_count,
            }
        )
    reasons.sort(
        key=lambda item: (
            0 if item["polarity"] == "positive" else 1,
            -float(item["influence"]),
            str(item["aspect"]),
        )
    )
    return tuple(reasons[:6])


def _set_overlap(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 1.0


class RecommendationQualityRunner:
    def __init__(self, evaluator):
        self.evaluator = evaluator

    def run(
        self,
        base_request: EvaluationRequest,
        profiles: Iterable[QualityProfile],
        *,
        expectations: dict[str, dict[str, object]] | None = None,
        progress: Callable[[int, QualityProfile, QualityCase], None] | None = None,
    ) -> list[QualityCase]:
        expectations = expectations or {}
        cases = []
        for index, profile in enumerate(profiles, start=1):
            error = ""
            result: EvaluationResult | None = None
            try:
                result = self.evaluator.evaluate_products(
                    EvaluationRequest(
                        domain=base_request.domain,
                        dataset_key=base_request.dataset_key,
                        strategy=base_request.strategy,
                        preferences=profile.preferences,
                    )
                )
                if not result.ranking:
                    error = (
                        f"La evaluación quedó {result.evaluation_status} y no publicó ranking."
                    )
            except Exception as exc:  # El informe registra el error y sigue.
                error = f"{type(exc).__name__}: {exc}"

            ranking = result.ranking if result and not error else ()
            baseline = _evidence_baseline(result) if result and ranking else ()
            laf_top3 = ranking[:3]
            baseline_top3 = baseline[:3]
            expectation = expectations.get(profile.name, {})
            review_status = str(expectation.get("review_status") or "pending")
            if review_status not in {"pending", "approved", "excluded"}:
                review_status = "pending"
            expected_winners = tuple(
                str(value) for value in expectation.get("expected_winner_ids", []) if str(value)
            )
            expected_top3 = tuple(
                str(value) for value in expectation.get("expected_top3_ids", []) if str(value)
            )
            approved = review_status == "approved" and bool(expected_winners)
            laf_winner_id = ranking[0].entity_id if ranking else ""
            laf_top3_ids = tuple(entry.entity_id for entry in laf_top3)
            runner_up_score = ranking[1].final_score if len(ranking) > 1 else 0.0
            assisted_decision, assisted_ids, assisted_names, assisted_rationale = (
                _assisted_proposal(baseline)
            )
            case = QualityCase(
                name=profile.name,
                title=profile.title,
                kind=profile.kind,
                focused_aspects=profile.focused_aspects,
                preferences=profile.preferences,
                status="ok" if ranking else "error",
                error=error,
                laf_winner_id=laf_winner_id,
                laf_winner_name=ranking[0].entity_name if ranking else "",
                laf_winner_score=ranking[0].final_score if ranking else 0.0,
                laf_winner_confidence=ranking[0].confidence if ranking else 0.0,
                laf_winner_preference=ranking[0].preference if ranking else 0.0,
                laf_runner_up_score=runner_up_score,
                laf_winner_margin=(ranking[0].final_score - runner_up_score) if ranking else 0.0,
                top3_preference_saturated=bool(
                    laf_top3 and all(entry.preference >= 0.999 for entry in laf_top3)
                ),
                laf_top3_ids=laf_top3_ids,
                laf_top3_names=tuple(entry.entity_name for entry in laf_top3),
                baseline_winner_id=str(baseline[0]["entity_id"]) if baseline else "",
                baseline_winner_name=str(baseline[0]["entity_name"]) if baseline else "",
                baseline_winner_score=float(baseline[0]["score"]) if baseline else 0.0,
                baseline_top3_ids=tuple(str(row["entity_id"]) for row in baseline_top3),
                baseline_top3_names=tuple(str(row["entity_name"]) for row in baseline_top3),
                baseline_candidates=tuple(dict(row) for row in baseline[:5]),
                assisted_decision=assisted_decision,
                assisted_winner_ids=assisted_ids,
                assisted_winner_names=assisted_names,
                assisted_rationale=assisted_rationale,
                baseline_match=bool(baseline and laf_winner_id == baseline[0]["entity_id"]),
                laf_winner_in_baseline_top3=bool(
                    baseline and laf_winner_id in {row["entity_id"] for row in baseline_top3}
                ),
                top3_overlap=_set_overlap(
                    laf_top3_ids,
                    (str(row["entity_id"]) for row in baseline_top3),
                ) if baseline else 0.0,
                winner_reasons=_winner_reasons(ranking[0], profile.focused_aspects) if ranking else (),
                review_status=review_status,
                expected_winner_ids=expected_winners,
                expected_top3_ids=expected_top3,
                expert_rationale=str(expectation.get("rationale") or ""),
                reviewer=str(expectation.get("reviewer") or ""),
                reviewed_at=str(expectation.get("reviewed_at") or ""),
                human_winner_match=laf_winner_id in expected_winners if approved else None,
                human_expected_in_laf_top3=bool(set(expected_winners) & set(laf_top3_ids)) if approved else None,
            )
            cases.append(case)
            if progress:
                progress(index, profile, case)
        return cases


def summarize_quality(cases: list[QualityCase]) -> dict[str, object]:
    successful = [case for case in cases if case.status == "ok"]
    with_baseline = [case for case in successful if case.baseline_winner_id]
    reviewed = [
        case
        for case in successful
        if case.review_status == "approved" and case.expected_winner_ids
    ]
    winner_distribution: dict[str, dict[str, object]] = {}
    for case in successful:
        bucket = winner_distribution.setdefault(
            case.laf_winner_id,
            {"winner_name": case.laf_winner_name, "count": 0, "cases": []},
        )
        bucket["count"] = int(bucket["count"]) + 1
        bucket["cases"].append(case.name)
    dominant = max(
        winner_distribution.items(),
        key=lambda item: int(item[1]["count"]),
        default=("", {"winner_name": "", "count": 0, "cases": []}),
    )
    return {
        "total_cases": len(cases),
        "successful_cases": len(successful),
        "failed_cases": len(cases) - len(successful),
        "baseline_cases": len(with_baseline),
        "baseline_winner_agreement": (
            mean(case.baseline_match for case in with_baseline) if with_baseline else None
        ),
        "laf_winner_in_baseline_top3": (
            mean(case.laf_winner_in_baseline_top3 for case in with_baseline)
            if with_baseline else None
        ),
        "average_top3_overlap": (
            mean(case.top3_overlap for case in with_baseline) if with_baseline else None
        ),
        "reviewed_cases": len(reviewed),
        "pending_human_review": sum(case.review_status == "pending" for case in successful),
        "human_winner_accuracy": (
            mean(bool(case.human_winner_match) for case in reviewed) if reviewed else None
        ),
        "human_expected_in_laf_top3": (
            mean(bool(case.human_expected_in_laf_top3) for case in reviewed)
            if reviewed else None
        ),
        "top3_preference_saturation_rate": (
            mean(case.top3_preference_saturated for case in successful)
            if successful else None
        ),
        "high_winner_score_rate": (
            mean(case.laf_winner_score >= 0.95 for case in successful)
            if successful else None
        ),
        "average_winner_margin": (
            mean(case.laf_winner_margin for case in successful) if successful else None
        ),
        "winner_distribution": winner_distribution,
        "dominant_winner_id": dominant[0],
        "dominant_winner_name": str(dominant[1]["winner_name"]),
        "dominant_winner_share": (
            int(dominant[1]["count"]) / len(successful) if successful else 0.0
        ),
        "correctness_status": (
            "measured" if reviewed else "pending_human_labels"
        ),
    }


def _percent(value: object) -> str:
    return "No medido" if value is None else f"{float(value):.1%}"


def _candidate_evidence_summary(candidate: dict[str, object]) -> str:
    contributions = [
        item
        for item in candidate.get("contributions", ())
        if float(item.get("preference", 0)) > 0
    ]
    return "; ".join(
        f"{item['aspect']}: +{float(item['positive_confidence']):.2f} "
        f"(n={int(item['positive_reviews'])}), −{float(item['negative_confidence']):.2f} "
        f"(n={int(item['negative_reviews'])})"
        for item in contributions[:3]
    ) or "Sin evidencia enfocada"


def _expected_winner_names(case: QualityCase) -> str:
    names_by_id = {
        str(candidate["entity_id"]): str(candidate["entity_name"])
        for candidate in case.baseline_candidates
    }
    names_by_id.update(zip(case.laf_top3_ids, case.laf_top3_names, strict=True))
    if case.laf_winner_id:
        names_by_id[case.laf_winner_id] = case.laf_winner_name
    return " · ".join(
        names_by_id.get(entity_id, entity_id)
        for entity_id in case.expected_winner_ids
    )


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", r"\|").replace("\r", " ").replace("\n", " ")


def write_quality_reports(
    output_dir: Path,
    *,
    metadata: dict[str, object],
    cases: list[QualityCase],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize_quality(cases)
    json_path = output_dir / "auditoria_calidad.json"
    csv_path = output_dir / "casos.csv"
    review_path = output_dir / "casos_para_revision.json"
    assisted_json_path = output_dir / "casos_propuestos_para_aprobar.json"
    assisted_markdown_path = output_dir / "revision_asistida.md"
    markdown_path = output_dir / "resumen.md"

    json_path.write_text(
        json.dumps(
            {"metadata": metadata, "summary": summary, "cases": [asdict(case) for case in cases]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "caso", "tipo", "aspectos", "estado", "ganador_laf", "puntaje_laf",
                "confianza_laf", "preferencia_laf", "margen_sobre_segundo",
                "preferencia_top3_saturada",
                "ganador_linea_base", "coincide_ganador", "laf_en_top3_linea_base",
                "solapamiento_top3", "revision_humana", "ganadores_esperados",
                "acierto_humano", "esperado_en_top3_laf", "razones", "error",
            ]
        )
        for case in cases:
            reasons = " | ".join(
                f"{row['aspect']}:{row['polarity']}:{float(row['influence']):.3f}:n={row['evidence_count']}"
                for row in case.winner_reasons
            )
            writer.writerow(
                [
                    case.name, case.kind, " | ".join(case.focused_aspects), case.status,
                    case.laf_winner_name, f"{case.laf_winner_score:.6f}",
                    f"{case.laf_winner_confidence:.6f}", f"{case.laf_winner_preference:.6f}",
                    f"{case.laf_winner_margin:.6f}", case.top3_preference_saturated,
                    case.baseline_winner_name, case.baseline_match,
                    case.laf_winner_in_baseline_top3, f"{case.top3_overlap:.6f}",
                    case.review_status, " | ".join(case.expected_winner_ids),
                    case.human_winner_match, case.human_expected_in_laf_top3,
                    reasons, case.error,
                ]
            )

    review_path.write_text(
        json.dumps(
            {
                "instructions": (
                    "Completá expected_winner_ids, opcionalmente expected_top3_ids y rationale. "
                    "Cambiá review_status a approved sólo después de revisar el caso sin usar "
                    "el ganador de LAF como verdad. Volvé a ejecutar el comando con --expectations."
                ),
                "metadata": metadata,
                "cases": [
                    {
                        "name": case.name,
                        "title": case.title,
                        "preferences": case.preferences,
                        "candidate_options_from_evidence_baseline": [
                            {"entity_id": entity_id, "entity_name": entity_name}
                            for entity_id, entity_name in zip(
                                case.baseline_top3_ids,
                                case.baseline_top3_names,
                                strict=True,
                            )
                        ],
                        "review_status": case.review_status,
                        "expected_winner_ids": list(case.expected_winner_ids),
                        "expected_top3_ids": list(case.expected_top3_ids),
                        "rationale": case.expert_rationale,
                        "reviewer": case.reviewer,
                        "reviewed_at": case.reviewed_at,
                    }
                    for case in cases
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assisted_json_path.write_text(
        json.dumps(
            {
                "instructions": (
                    "Estas expectativas son propuestas técnicas asistidas, no validación humana. "
                    "Para aprobar un caso, revisá su detalle y cambiá review_status a approved. "
                    "Podés modificar expected_winner_ids o marcar excluded."
                ),
                "rubric": {
                    "score": "suma de confianza×preferencia positiva menos negativa, antes de LAF",
                    "tie_tolerance": "5% del mejor balance, con mínimo absoluto 0.02",
                    "insufficient_evidence": "menos de 3 reseñas enfocadas en el candidato principal",
                    "laf_result_used_for_proposal": False,
                },
                "metadata": metadata,
                "cases": [
                    {
                        "name": case.name,
                        "title": case.title,
                        "proposal_status": case.assisted_decision,
                        "review_status": "pending",
                        "expected_winner_ids": list(case.assisted_winner_ids),
                        "expected_top3_ids": list(case.baseline_top3_ids),
                        "rationale": case.assisted_rationale,
                        "reviewer": "",
                        "reviewed_at": "",
                        "candidate_details": list(case.baseline_candidates),
                    }
                    for case in cases
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    review_lines = [
        "# Revisión asistida para aprobación",
        "",
        "Las propuestas se calcularon sin usar la posición ni el puntaje final de LAF.",
        "La rúbrica suma evidencia positiva y resta negativa antes de las reglas argumentativas.",
        "Una diferencia menor al 5% se considera ambigua y menos de 3 reseñas se considera insuficiente.",
        "",
        "Para cada caso elegí una opción: **aprobar**, **cambiar ganador** o **excluir**.",
        "",
    ]
    for index, case in enumerate(cases, start=1):
        proposed = " · ".join(case.assisted_winner_names) or "Sin propuesta"
        review_lines.extend(
            [
                f"## {index}. {case.title}",
                "",
                f"- Estado de la propuesta: **{case.assisted_decision}**",
                f"- Ganador(es) propuesto(s): **{proposed}**",
                f"- Justificación: {case.assisted_rationale}",
                "",
                "| Candidato | Balance directo | Cobertura | Evidencia principal |",
                "|---|---:|---:|---|",
            ]
        )
        for candidate in case.baseline_candidates:
            review_lines.append(
                f"| {_markdown_cell(candidate['entity_name'])} (`{candidate['entity_id']}`) "
                f"| {float(candidate['score']):.3f} | {int(candidate['coverage'])} "
                f"| {_candidate_evidence_summary(candidate)} |"
            )
        review_lines.extend(
            [
                "",
                "- [ ] Aprobar propuesta",
                "- [ ] Cambiar ganador: ____________________",
                "- [ ] Excluir por evidencia insuficiente o caso ambiguo",
                "- Observación: ____________________",
                "",
            ]
        )
    assisted_markdown_path.write_text("\n".join(review_lines), encoding="utf-8")

    lines = [
        "# Auditoría de calidad de recomendaciones",
        "",
        f"- Dataset: `{metadata.get('dataset_key', '')}`",
        f"- Estrategia: `{metadata.get('strategy', '')}`",
        f"- Casos: {summary['successful_cases']} correctos, {summary['failed_cases']} con error",
        f"- Casos aprobados por una persona: {summary['reviewed_cases']}",
        "",
        "## Qué puede concluirse",
        "",
        f"- Coincidencia de ganador con la línea base de evidencia: {_percent(summary['baseline_winner_agreement'])}",
        f"- Ganador LAF dentro del top 3 de la línea base: {_percent(summary['laf_winner_in_baseline_top3'])}",
        f"- Solapamiento medio de top 3: {_percent(summary['average_top3_overlap'])}",
        f"- Acierto contra expectativas humanas aprobadas: {_percent(summary['human_winner_accuracy'])}",
        f"- Casos con preferencia 1 en todo el top 3: {_percent(summary['top3_preference_saturation_rate'])}",
        f"- Casos cuyo ganador supera 0,95: {_percent(summary['high_winner_score_rate'])}",
        f"- Margen medio entre primero y segundo: {float(summary['average_winner_margin'] or 0):.4f}",
        "",
    ]
    if not summary["reviewed_cases"]:
        lines.extend(
            [
                "> **La exactitud todavía no está medida.** La línea base es una comparación "
                "transparente, no una verdad de referencia. Hay que completar y aprobar "
                "`casos_para_revision.json`.",
                "",
            ]
        )
    if float(summary["top3_preference_saturation_rate"] or 0) >= 0.7:
        lines.extend(
            [
                "> **Señal metodológica:** en la mayoría de los perfiles el top 3 llega a "
                "preferencia 1. La proyección final queda entonces dominada por la confianza "
                "global, aunque varios aspectos estén configurados en cero.",
                "",
            ]
        )
    if summary["reviewed_cases"]:
        reviewed = [
            case
            for case in cases
            if case.status == "ok"
            and case.review_status == "approved"
            and case.expected_winner_ids
        ]
        exact_matches = sum(bool(case.human_winner_match) for case in reviewed)
        top3_matches = sum(bool(case.human_expected_in_laf_top3) for case in reviewed)
        lines.extend(
            [
                "## Validación contra la revisión humana asistida",
                "",
                f"- Acierto exacto: **{exact_matches} de {len(reviewed)} "
                f"({_percent(summary['human_winner_accuracy'])})**.",
                f"- Al menos un ganador aceptable dentro del top 3 de LAF: "
                f"**{top3_matches} de {len(reviewed)} "
                f"({_percent(summary['human_expected_in_laf_top3'])})**.",
                f"- Casos cuyo ganador no coincide: **{len(reviewed) - exact_matches}**.",
                f"- Casos sin ningún ganador aceptable en el top 3: "
                f"**{len(reviewed) - top3_matches}**.",
                "",
                "| Caso | Ganador(es) esperado(s) | Ganador LAF | Acierto exacto | Esperado en top 3 |",
                "|---|---|---|:---:|:---:|",
            ]
        )
        for case in reviewed:
            lines.append(
                f"| {_markdown_cell(case.title)} | "
                f"{_markdown_cell(_expected_winner_names(case))} | "
                f"{_markdown_cell(case.laf_winner_name)} | "
                f"{'Sí' if case.human_winner_match else 'No'} | "
                f"{'Sí' if case.human_expected_in_laf_top3 else 'No'} |"
            )
        lines.append("")
        if float(summary["human_winner_accuracy"] or 0) < 0.5:
            lines.extend(
                [
                    "> **Resultado:** la configuración actual no alcanza todavía una "
                    "concordancia suficiente con la revisión aprobada. Conviene diagnosticar "
                    "la propagación de preferencias antes de ajustar la interfaz o desplegar.",
                    "",
                ]
            )
        if float(summary["dominant_winner_share"] or 0) >= 0.5:
            lines.extend(
                [
                    "> **Concentración de resultados:** un mismo producto gana al menos la "
                    "mitad de los perfiles. Esto puede indicar que la confianza global está "
                    "pesando más que los aspectos elegidos.",
                    "",
                ]
            )
    lines.extend(
        [
            "## Casos",
            "",
            "| Caso | Ganador LAF | Línea base de evidencia | ¿Coincide? | Revisión humana |",
            "|---|---|---|:---:|:---:|",
        ]
    )
    for case in cases:
        lines.append(
            f"| {_markdown_cell(case.title)} | "
            f"{_markdown_cell(case.laf_winner_name or 'ERROR')} | "
            f"{_markdown_cell(case.baseline_winner_name or 'Sin línea base')} | "
            f"{'Sí' if case.baseline_match else 'No'} | {case.review_status} |"
        )
    lines.extend(
        [
            "",
            "## Producto dominante",
            "",
            f"**{summary['dominant_winner_name'] or 'Sin ganador'}** ganó "
            f"{float(summary['dominant_winner_share']):.1%} de los casos.",
            "",
        ]
    )
    dominant_id = str(summary["dominant_winner_id"])
    for case in cases:
        if case.laf_winner_id != dominant_id:
            continue
        reasons = ", ".join(
            f"{row['aspect']} ({row['polarity']}, influencia {float(row['influence']):.2f}, n={row['evidence_count']})"
            for row in case.winner_reasons[:3]
        ) or "sin evidencia enfocada disponible"
        baseline_position = (
            case.baseline_top3_ids.index(dominant_id) + 1
            if dominant_id in case.baseline_top3_ids else "fuera del top 3"
        )
        lines.append(
            f"- **{case.title}:** {reasons}. Posición en la línea base: {baseline_position}."
        )
    lines.extend(
        [
            "",
            "## Interpretación metodológica",
            "",
            "La línea base suma `confianza × preferencia` de los hechos positivos y resta "
            "el mismo valor para los negativos, antes de aplicar reglas, dimensiones, "
            "agregación y conflicto de LAF. Una diferencia no prueba un error: identifica "
            "casos donde la estructura argumentativa cambia lo sugerido por la evidencia directa.",
            "",
            "La exactitud sólo debe informarse con los casos marcados `approved` por una persona.",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "json": json_path,
        "csv": csv_path,
        "review": review_path,
        "assisted_json": assisted_json_path,
        "assisted_markdown": assisted_markdown_path,
        "markdown": markdown_path,
    }
