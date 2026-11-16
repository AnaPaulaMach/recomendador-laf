"""Resume de forma reproducible una validación manual de extracciones."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any


def _percentage(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(100 * numerator / denominator, 2)


def summarize_review(payload: dict[str, Any]) -> dict[str, Any]:
    cases = list(payload.get("cases") or [])
    reviewed = [case for case in cases if case.get("review_status") == "reviewed"]
    decisions = [
        {"case_number": case.get("case_number"), **decision}
        for case in reviewed
        for decision in (case.get("extraction_decisions") or [])
    ]
    verdicts = Counter(str(item.get("verdict") or "missing") for item in decisions)
    trust_verdicts = Counter(str(case.get("trust_verdict") or "missing") for case in reviewed)
    missing_aspects = [
        {"case_number": case.get("case_number"), **aspect}
        for case in reviewed
        for aspect in (case.get("missing_aspects") or [])
    ]
    exact_cases = [
        case for case in reviewed
        if case.get("extraction_decisions")
        and all(item.get("verdict") == "correct" for item in case["extraction_decisions"])
        and not case.get("missing_aspects")
    ]
    aspect_supported = sum(
        verdicts[name] for name in ("correct", "wrong_polarity", "ambiguous")
    )
    polarity_denominator = verdicts["correct"] + verdicts["wrong_polarity"]
    errors = [item for item in decisions if item.get("verdict") != "correct"]

    return {
        "dataset_key": payload.get("dataset_key"),
        "cases_total": len(cases),
        "cases_reviewed": len(reviewed),
        "cases_pending": len(cases) - len(reviewed),
        "decisions_total": len(decisions),
        "verdict_counts": dict(sorted(verdicts.items())),
        "strict_decision_accuracy_pct": _percentage(verdicts["correct"], len(decisions)),
        "aspect_supported_pct": _percentage(aspect_supported, len(decisions)),
        "polarity_accuracy_on_supported_decisions_pct": _percentage(
            verdicts["correct"], polarity_denominator
        ),
        "exact_case_matches": len(exact_cases),
        "exact_case_match_pct": _percentage(len(exact_cases), len(reviewed)),
        "missing_aspects_total": len(missing_aspects),
        "missing_aspects": missing_aspects,
        "trust_verdict_counts": dict(sorted(trust_verdicts.items())),
        "non_correct_decisions": errors,
        "reviewers": sorted({str(case.get("reviewer")) for case in reviewed if case.get("reviewer")}),
        "methodological_note": (
            "La muestra es determinística y deliberadamente diversa; estas tasas describen "
            "los casos revisados y no estiman por sí solas el error de todo el corpus."
        ),
    }


def build_markdown(summary: dict[str, Any]) -> str:
    pct = lambda value: "n/d" if value is None else f"{value:.2f}%"
    lines = [
        "# Resultado de la validación manual de extracción",
        "",
        f"- Dataset: `{summary['dataset_key']}`",
        f"- Casos revisados: **{summary['cases_reviewed']} de {summary['cases_total']}**",
        f"- Extracciones evaluadas: **{summary['decisions_total']}**",
        f"- Decisiones estrictamente correctas: **{pct(summary['strict_decision_accuracy_pct'])}**",
        f"- Extracciones con aspecto pertinente: **{pct(summary['aspect_supported_pct'])}**",
        f"- Polaridad correcta entre decisiones pertinentes y no ambiguas: "
        f"**{pct(summary['polarity_accuracy_on_supported_decisions_pct'])}**",
        f"- Casos completamente correctos y sin omisiones: **{summary['exact_case_matches']} "
        f"({pct(summary['exact_case_match_pct'])})**",
        f"- Aspectos omitidos detectados: **{summary['missing_aspects_total']}**",
        "",
        "## Tipos de decisión",
        "",
    ]
    for verdict, count in summary["verdict_counts"].items():
        lines.append(f"- `{verdict}`: {count}")
    lines.extend(["", "## Evaluación del trust", ""])
    for verdict, count in summary["trust_verdict_counts"].items():
        lines.append(f"- `{verdict}`: {count}")
    lines.extend([
        "",
        "## Casos que requieren atención",
        "",
    ])
    for item in summary["non_correct_decisions"]:
        lines.append(
            f"- Caso {item.get('case_number')}, extracción `{item.get('extraction_id')}`: "
            f"**{item.get('verdict')}**. {item.get('note') or ''}".rstrip()
        )
    for item in summary["missing_aspects"]:
        lines.append(
            f"- Caso {item.get('case_number')}: aspecto omitido "
            f"`{item.get('aspect')} — {item.get('polarity')}`; evidencia: "
            f"“{item.get('evidence')}”."
        )
    lines.extend([
        "",
        "## Alcance",
        "",
        summary["methodological_note"],
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.responses.read_text(encoding="utf-8"))
    summary = summarize_review(payload)
    output_dir = args.output_dir or args.responses.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "resumen_revision.json"
    markdown_path = output_dir / "resumen_revision.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(build_markdown(summary), encoding="utf-8")
    print(f"Casos revisados: {summary['cases_reviewed']} de {summary['cases_total']}")
    print(f"Extracciones evaluadas: {summary['decisions_total']}")
    print(f"Resumen JSON: {json_path}")
    print(f"Informe: {markdown_path}")


if __name__ == "__main__":
    main()
