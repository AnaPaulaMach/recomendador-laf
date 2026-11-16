"""Auditoría reproducible de sensibilidad del ranking ante preferencias."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations, product
import csv
import json
from pathlib import Path
from statistics import mean
from typing import Callable, Iterable, Iterator

from recommender.domain.contracts import EvaluationRequest, EvaluationResult


NEUTRAL_LEVEL = 0.67
UI_LEVELS = (0.0, 0.33, 0.67, 1.0)
BINARY_LEVELS = (0.0, 1.0)


@dataclass(frozen=True)
class PreferenceProfile:
    name: str
    kind: str
    preferences: dict[str, float]
    aspect: str = ""


@dataclass(frozen=True)
class AuditCase:
    name: str
    kind: str
    aspect: str
    preferences: dict[str, float]
    status: str
    error: str
    winner_id: str
    winner_name: str
    winner_score: float
    top3_ids: tuple[str, ...]
    top3_names: tuple[str, ...]
    ranking: tuple[dict[str, object], ...]
    winner_changed: bool = False
    top3_overlap: float = 0.0
    mean_rank_movement: float = 0.0
    rank_correlation: float = 0.0


def projected_case_count(aspects: Iterable[str], mode: str, levels=UI_LEVELS) -> int:
    count = len(tuple(aspects))
    if mode == "quick":
        return 4 + count
    if mode == "standard":
        return 4 + (count * 5)
    if mode == "pairwise":
        return 4 + (count * 5) + (count * (count - 1) // 2)
    if mode == "exhaustive":
        levels = tuple(levels)
        includes_neutral = NEUTRAL_LEVEL in levels
        return (len(levels) ** count) + (0 if includes_neutral else 1)
    raise ValueError(f"Modo de auditoría desconocido: {mode}")


def iter_profiles(
    aspects: Iterable[str],
    current: dict[str, float] | None = None,
    *,
    mode: str = "standard",
    levels=UI_LEVELS,
) -> Iterator[PreferenceProfile]:
    aspects = tuple(aspects)
    neutral = {aspect: NEUTRAL_LEVEL for aspect in aspects}
    current = {
        aspect: float((current or {}).get(aspect, NEUTRAL_LEVEL))
        for aspect in aspects
    }

    if mode == "exhaustive":
        neutral_tuple = tuple(neutral[aspect] for aspect in aspects)
        yield PreferenceProfile("neutral", "baseline", neutral)
        for index, values in enumerate(product(levels, repeat=len(aspects)), start=1):
            if values == neutral_tuple:
                continue
            yield PreferenceProfile(
                f"combinacion_{index:0{max(4, len(str(len(levels) ** len(aspects))))}d}",
                "exhaustive",
                dict(zip(aspects, values, strict=True)),
            )
        return

    profiles = [
        PreferenceProfile("neutral", "baseline", neutral),
        PreferenceProfile("perfil_actual", "current", current),
        PreferenceProfile("ningun_aspecto", "all_low", {aspect: 0.0 for aspect in aspects}),
        PreferenceProfile("todos_prioridad", "all_high", {aspect: 1.0 for aspect in aspects}),
    ]
    for aspect in aspects:
        profiles.append(
            PreferenceProfile(
                f"solo_{aspect}",
                "one_hot",
                {key: 1.0 if key == aspect else 0.0 for key in aspects},
                aspect,
            )
        )
        if mode in {"standard", "pairwise"}:
            for name, kind, value in (
                (f"prioridad_{aspect}", "priority", 1.0),
                (f"ignorar_{aspect}", "ignored", 0.0),
                (f"perturbacion_menos_{aspect}", "perturb_down", NEUTRAL_LEVEL - 0.01),
                (f"perturbacion_mas_{aspect}", "perturb_up", NEUTRAL_LEVEL + 0.01),
            ):
                values = dict(neutral)
                values[aspect] = value
                profiles.append(PreferenceProfile(name, kind, values, aspect))
    if mode == "pairwise":
        for left, right in combinations(aspects, 2):
            profiles.append(
                PreferenceProfile(
                    f"solo_{left}_y_{right}",
                    "pairwise",
                    {key: 1.0 if key in {left, right} else 0.0 for key in aspects},
                    f"{left}+{right}",
                )
            )

    for profile in profiles:
        yield profile


def _ranking_payload(result: EvaluationResult) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "position": entry.position,
            "entity_id": entry.entity_id,
            "entity_name": entry.entity_name,
            "score": entry.final_score,
            "confidence": entry.confidence,
            "preference": entry.preference,
        }
        for entry in result.ranking
    )


def _rank_metrics(
    baseline: AuditCase,
    ranking: tuple[dict[str, object], ...],
) -> tuple[bool, float, float, float]:
    if not ranking or not baseline.ranking:
        return False, 0.0, 0.0, 0.0
    winner_changed = str(ranking[0]["entity_id"]) != baseline.winner_id
    baseline_top = set(baseline.top3_ids)
    current_top = {str(item["entity_id"]) for item in ranking[:3]}
    union = baseline_top | current_top
    top3_overlap = len(baseline_top & current_top) / len(union) if union else 1.0

    baseline_positions = {
        str(item["entity_id"]): int(item["position"]) for item in baseline.ranking
    }
    current_positions = {
        str(item["entity_id"]): int(item["position"]) for item in ranking
    }
    shared = tuple(sorted(set(baseline_positions) & set(current_positions)))
    movement = mean(
        abs(baseline_positions[item] - current_positions[item]) for item in shared
    ) if shared else 0.0

    concordant = 0
    discordant = 0
    for left, right in combinations(shared, 2):
        before = baseline_positions[left] - baseline_positions[right]
        after = current_positions[left] - current_positions[right]
        if before * after > 0:
            concordant += 1
        elif before * after < 0:
            discordant += 1
    pairs = concordant + discordant
    correlation = (concordant - discordant) / pairs if pairs else 1.0
    return winner_changed, top3_overlap, movement, correlation


class PreferenceAuditRunner:
    def __init__(self, evaluator):
        self.evaluator = evaluator

    def run(
        self,
        base_request: EvaluationRequest,
        profiles: Iterable[PreferenceProfile],
        *,
        progress: Callable[[int, PreferenceProfile, AuditCase], None] | None = None,
    ) -> list[AuditCase]:
        cases: list[AuditCase] = []
        baseline: AuditCase | None = None
        for index, profile in enumerate(profiles, start=1):
            try:
                result = self.evaluator.evaluate_products(
                    EvaluationRequest(
                        domain=base_request.domain,
                        dataset_key=base_request.dataset_key,
                        strategy=base_request.strategy,
                        preferences=profile.preferences,
                    )
                )
                ranking = _ranking_payload(result)
                error = "" if ranking else (
                    f"La evaluación quedó {result.evaluation_status} y no publicó ranking."
                )
            except Exception as exc:  # El informe debe registrar fallos y continuar.
                ranking = ()
                error = f"{type(exc).__name__}: {exc}"

            winner_changed = False
            overlap = 0.0
            movement = 0.0
            correlation = 0.0
            if baseline is not None and ranking:
                winner_changed, overlap, movement, correlation = _rank_metrics(
                    baseline,
                    ranking,
                )
            case = AuditCase(
                name=profile.name,
                kind=profile.kind,
                aspect=profile.aspect,
                preferences=profile.preferences,
                status="ok" if ranking else "error",
                error=error,
                winner_id=str(ranking[0]["entity_id"]) if ranking else "",
                winner_name=str(ranking[0]["entity_name"]) if ranking else "",
                winner_score=float(ranking[0]["score"]) if ranking else 0.0,
                top3_ids=tuple(str(item["entity_id"]) for item in ranking[:3]),
                top3_names=tuple(str(item["entity_name"]) for item in ranking[:3]),
                ranking=ranking,
                winner_changed=winner_changed,
                top3_overlap=overlap if baseline is not None else 1.0,
                mean_rank_movement=movement,
                rank_correlation=correlation if baseline is not None else 1.0,
            )
            if baseline is None and case.status == "ok":
                baseline = case
            cases.append(case)
            if progress:
                progress(index, profile, case)
        return cases


def summarize(cases: list[AuditCase]) -> dict[str, object]:
    successful = [case for case in cases if case.status == "ok"]
    comparisons = successful[1:] if successful else []
    distinct_winners = sorted({case.winner_id for case in successful})
    winner_changes = sum(case.winner_changed for case in comparisons)
    perturbations = [case for case in comparisons if case.kind.startswith("perturb_")]
    average_movement = mean(case.mean_rank_movement for case in comparisons) if comparisons else 0.0
    average_overlap = mean(case.top3_overlap for case in comparisons) if comparisons else 0.0
    change_rate = winner_changes / len(comparisons) if comparisons else 0.0
    perturbation_change_rate = (
        sum(case.winner_changed for case in perturbations) / len(perturbations)
        if perturbations else 0.0
    )
    change_rate_by_kind = {}
    for kind in ("one_hot", "priority", "ignored", "perturb_down", "perturb_up", "pairwise"):
        grouped = [case for case in comparisons if case.kind == kind]
        if grouped:
            change_rate_by_kind[kind] = sum(case.winner_changed for case in grouped) / len(grouped)
    one_hot_cases = [case for case in successful if case.kind == "one_hot"]
    one_hot_distribution: dict[str, dict[str, object]] = {}
    for case in one_hot_cases:
        bucket = one_hot_distribution.setdefault(
            case.winner_id,
            {"winner_name": case.winner_name, "aspects": [], "count": 0},
        )
        bucket["aspects"].append(case.aspect)
        bucket["count"] += 1
    dominant_one_hot_share = (
        max(int(item["count"]) for item in one_hot_distribution.values()) / len(one_hot_cases)
        if one_hot_cases else 0.0
    )
    if not successful:
        verdict = "No fue posible evaluar ningún perfil."
    elif len(distinct_winners) == 1 and average_movement < 0.01:
        verdict = "El ranking no respondió a los perfiles probados."
    elif len(distinct_winners) == 1:
        verdict = "Cambian posiciones internas, pero el ganador permanece fijo."
    else:
        verdict = "Las preferencias modifican el ganador y/o el orden del ranking."
    return {
        "total_cases": len(cases),
        "successful_cases": len(successful),
        "failed_cases": len(cases) - len(successful),
        "distinct_winners": len(distinct_winners),
        "winner_ids": distinct_winners,
        "winner_change_rate": change_rate,
        "average_top3_overlap": average_overlap,
        "average_rank_movement": average_movement,
        "small_perturbation_winner_change_rate": perturbation_change_rate,
        "change_rate_by_kind": change_rate_by_kind,
        "one_hot_winner_distribution": one_hot_distribution,
        "dominant_one_hot_winner_share": dominant_one_hot_share,
        "verdict": verdict,
        "correctness_note": (
            "Este informe mide sensibilidad y estabilidad. Para medir acierto hace falta "
            "comparar contra elecciones humanas o casos esperados etiquetados."
        ),
    }


def write_reports(
    output_dir: Path,
    *,
    metadata: dict[str, object],
    cases: list[AuditCase],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(cases)
    json_path = output_dir / "auditoria_preferencias.json"
    csv_path = output_dir / "casos.csv"
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
                "caso", "tipo", "aspecto", "estado", "ganador_id", "ganador",
                "puntaje", "cambio_ganador", "solapamiento_top3",
                "movimiento_medio", "correlacion_ranking", "top3", "preferencias", "error",
            ]
        )
        for case in cases:
            writer.writerow(
                [
                    case.name, case.kind, case.aspect, case.status, case.winner_id,
                    case.winner_name, f"{case.winner_score:.6f}", case.winner_changed,
                    f"{case.top3_overlap:.6f}", f"{case.mean_rank_movement:.6f}",
                    f"{case.rank_correlation:.6f}", " | ".join(case.top3_names),
                    json.dumps(case.preferences, ensure_ascii=False, sort_keys=True), case.error,
                ]
            )

    aspect_cases = [case for case in cases if case.kind == "one_hot"]
    lines = [
        "# Auditoría de sensibilidad de preferencias",
        "",
        f"- Dataset: `{metadata.get('dataset_key', '')}`",
        f"- Estrategia: `{metadata.get('strategy', '')}`",
        f"- Modo: `{metadata.get('mode', '')}`",
        f"- Aspectos: {len(metadata.get('aspects', []))}",
        f"- Casos ejecutados: {summary['successful_cases']} correctos, {summary['failed_cases']} con error",
        "",
        "## Resultado",
        "",
        str(summary["verdict"]),
        "",
        f"- Ganadores distintos: {summary['distinct_winners']}",
        f"- Casos que cambian el ganador: {float(summary['winner_change_rate']):.1%}",
        f"- Solapamiento medio del top 3: {float(summary['average_top3_overlap']):.1%}",
        f"- Movimiento medio de posiciones: {float(summary['average_rank_movement']):.2f}",
        f"- Cambios de ganador ante ±0,01: {float(summary['small_perturbation_winner_change_rate']):.1%}",
        f"- Cambio al poner un único aspecto en 1 y el resto en 0: {float(summary['change_rate_by_kind'].get('one_hot', 0)):.1%}",
        f"- Cambio al subir un aspecto de 0,67 a 1: {float(summary['change_rate_by_kind'].get('priority', 0)):.1%}",
        f"- Cambio al bajar un aspecto de 0,67 a 0: {float(summary['change_rate_by_kind'].get('ignored', 0)):.1%}",
        "",
        "## Un único aspecto como prioridad",
        "",
        "| Aspecto | Ganador | Puntaje | ¿Cambió? | Top 3 |",
        "|---|---|---:|:---:|---|",
    ]
    for case in aspect_cases:
        lines.append(
            f"| {case.aspect} | {case.winner_name or 'ERROR'} | {case.winner_score:.4f} "
            f"| {'Sí' if case.winner_changed else 'No'} | {' · '.join(case.top3_names)} |"
        )
    if float(summary["dominant_one_hot_winner_share"]) >= 0.7:
        lines.extend(
            [
                "",
                "> **Señal para revisar:** un mismo producto gana al menos el 70% de los perfiles "
                "de aspecto único. Esto no prueba un error, pero merece auditar cobertura de evidencia "
                "y reglas por aspecto.",
            ]
        )
    lines.extend(["", "## Alcance", "", str(summary["correctness_note"]), ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": markdown_path}
