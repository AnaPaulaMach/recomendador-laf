"""Material ciego para etiquetar recomendaciones con evidencia textual real."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import csv
import json
from math import ceil
from pathlib import Path
from typing import Iterable


LEVEL_LABELS = {
    1.0: "Muy importante",
    0.67: "Bastante importante",
    0.33: "Poco importante",
}


@dataclass(frozen=True)
class BlindProfile:
    name: str
    title: str
    preferences: dict[str, float]
    focused_aspects: tuple[str, ...]


def build_blind_profiles(
    aspect_labels: dict[str, str],
    *,
    case_count: int = 10,
) -> tuple[BlindProfile, ...]:
    """Crea perfiles mixtos nuevos, distintos de los casos de aspecto único."""
    aspects = tuple(aspect_labels)
    if len(aspects) < 3:
        raise ValueError("La revisión ciega necesita al menos tres aspectos.")
    if case_count <= 0:
        raise ValueError("case_count debe ser positivo.")
    profiles: list[BlindProfile] = []
    groups = max(1, ceil(case_count / 2))
    for group_index in range(groups):
        start = (group_index * 3) % len(aspects)
        focused = tuple(aspects[(start + offset) % len(aspects)] for offset in range(3))
        for weights in ((1.0, 0.67, 0.33), (0.33, 0.67, 1.0)):
            index = len(profiles) + 1
            preferences = {aspect: 0.0 for aspect in aspects}
            preferences.update(dict(zip(focused, weights, strict=True)))
            title = " · ".join(
                f"{aspect_labels[aspect]}: {LEVEL_LABELS[weight]}"
                for aspect, weight in zip(focused, weights, strict=True)
            )
            profiles.append(
                BlindProfile(
                    name=f"ciego_mixto_{index:02d}",
                    title=title,
                    preferences=preferences,
                    focused_aspects=focused,
                )
            )
            if len(profiles) == case_count:
                return tuple(profiles)
    return tuple(profiles)


def _number(value: object) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _integer(value: object) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _deduplicate_reviews(rows: Iterable[dict[str, object]]) -> tuple[dict[str, object], ...]:
    unique: dict[tuple[str, str, str, str], dict[str, object]] = {}
    for raw in rows:
        product_id = str(raw.get("product_id") or "").strip()
        review_id = str(raw.get("review_id") or "").strip()
        aspect = str(raw.get("aspect") or "").strip()
        polarity = str(raw.get("polarity") or "").strip()
        content = _clean_text(raw.get("content"))
        if not product_id or not review_id or not aspect or polarity not in {"pos", "neg"} or not content:
            continue
        trust = _number(raw.get("trust_score"))
        extraction = _number(raw.get("extraction_confidence"))
        row = {
            "product_id": product_id,
            "review_id": review_id,
            "rate": _integer(raw.get("rate")),
            "content": content,
            "aspect": aspect,
            "polarity": polarity,
            "trust_score": trust,
            "extraction_confidence": extraction,
            "effective_evidence": trust * extraction,
        }
        key = (product_id, review_id, aspect, polarity)
        previous = unique.get(key)
        if previous is None or float(row["effective_evidence"]) > float(previous["effective_evidence"]):
            unique[key] = row
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                str(item["product_id"]),
                str(item["aspect"]),
                str(item["polarity"]),
                str(item["review_id"]),
            ),
        )
    )


def _candidate_codes(
    dataset_key: str,
    profile_name: str,
    product_ids: Iterable[str],
) -> dict[str, str]:
    ordered = sorted(
        product_ids,
        key=lambda product_id: sha256(
            f"{dataset_key}:{profile_name}:{product_id}".encode("utf-8")
        ).hexdigest(),
    )
    return {product_id: chr(65 + index) for index, product_id in enumerate(ordered)}


def _select_case_candidates(
    *,
    dataset_key: str,
    profile: BlindProfile,
    product_ids: Iterable[str],
    evidence_index: dict[tuple[str, str, str], list[dict[str, object]]],
    candidate_count: int,
    prior_usage: dict[str, int],
) -> tuple[str, ...]:
    """Selecciona candidatos por cobertura sin usar resultados LAF."""
    product_ids = tuple(product_ids)
    if candidate_count <= 0:
        raise ValueError("candidate_count debe ser positivo.")
    if candidate_count > len(product_ids):
        raise ValueError("candidate_count no puede superar la cantidad de productos.")
    required_coverage = min(2, len(profile.focused_aspects))

    def coverage(product_id: str) -> tuple[int, int]:
        covered = 0
        review_ids: set[str] = set()
        for aspect in profile.focused_aspects:
            aspect_ids = {
                str(row["review_id"])
                for polarity in ("pos", "neg")
                for row in evidence_index.get((product_id, aspect, polarity), ())
            }
            if aspect_ids:
                covered += 1
                review_ids.update(aspect_ids)
        return covered, len(review_ids)

    coverage_by_product = {product_id: coverage(product_id) for product_id in product_ids}
    eligible = [
        product_id
        for product_id in product_ids
        if coverage_by_product[product_id][0] >= required_coverage
        and coverage_by_product[product_id][1] >= 3
    ]
    if len(eligible) < candidate_count:
        eligible = [product_id for product_id in product_ids if coverage_by_product[product_id][1] > 0]
    if len(eligible) < candidate_count:
        eligible = list(product_ids)
    eligible.sort(
        key=lambda product_id: (
            prior_usage.get(product_id, 0),
            sha256(f"{dataset_key}:{profile.name}:shortlist:{product_id}".encode("utf-8")).hexdigest(),
        )
    )
    selected = tuple(eligible[:candidate_count])
    for product_id in selected:
        prior_usage[product_id] = prior_usage.get(product_id, 0) + 1
    return selected


def _sample_rows(
    rows: Iterable[dict[str, object]],
    *,
    limit: int,
) -> tuple[dict[str, object], ...]:
    ordered = sorted(
        rows,
        key=lambda item: (
            -float(item["effective_evidence"]),
            str(item["review_id"]),
        ),
    )
    return tuple(ordered if limit == 0 else ordered[:limit])


def write_blind_review_packet(
    output_dir: Path,
    *,
    metadata: dict[str, object],
    products: dict[str, dict[str, object]],
    aspect_labels: dict[str, str],
    profiles: Iterable[BlindProfile],
    review_rows: Iterable[dict[str, object]],
    samples_per_polarity: int = 3,
    candidates_per_case: int | None = None,
) -> dict[str, object]:
    """Escribe fichas sin resultados LAF y anexos completos de trazabilidad."""
    if samples_per_polarity < 0:
        raise ValueError("samples_per_polarity no puede ser negativo.")
    if candidates_per_case is not None and candidates_per_case <= 0:
        raise ValueError("candidates_per_case debe ser positivo.")
    output_dir.mkdir(parents=True, exist_ok=True)
    profiles = tuple(profiles)
    reviews = _deduplicate_reviews(review_rows)
    by_product_aspect_polarity: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in reviews:
        by_product_aspect_polarity[
            (str(row["product_id"]), str(row["aspect"]), str(row["polarity"]))
        ].append(row)

    reading_csv = output_dir / "resenas_completas_lectura.csv"
    technical_csv = output_dir / "trazabilidad_tecnica.csv"
    with reading_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["producto_id", "producto", "review_id", "estrellas", "aspecto", "polaridad_detectada", "texto_original"])
        for row in reviews:
            writer.writerow([
                row["product_id"], products.get(str(row["product_id"]), {}).get("name", row["product_id"]),
                row["review_id"], row["rate"], aspect_labels.get(str(row["aspect"]), row["aspect"]),
                "favorable" if row["polarity"] == "pos" else "crítica", row["content"],
            ])
    with technical_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "producto_id", "producto", "review_id", "estrellas", "aspecto", "polaridad",
            "trust_reseña", "confianza_extraccion", "evidencia_efectiva", "texto_original",
        ])
        for row in reviews:
            writer.writerow([
                row["product_id"], products.get(str(row["product_id"]), {}).get("name", row["product_id"]),
                row["review_id"], row["rate"], row["aspect"], row["polarity"],
                f"{float(row['trust_score']):.6f}", f"{float(row['extraction_confidence']):.6f}",
                f"{float(row['effective_evidence']):.6f}", row["content"],
            ])

    manifest_cases = []
    response_cases = []
    case_paths: list[Path] = []
    all_product_ids = tuple(products)
    candidate_count = candidates_per_case or len(all_product_ids)
    prior_usage: dict[str, int] = {}
    for case_index, profile in enumerate(profiles, start=1):
        product_ids = _select_case_candidates(
            dataset_key=str(metadata.get("dataset_key") or ""),
            profile=profile,
            product_ids=all_product_ids,
            evidence_index=by_product_aspect_polarity,
            candidate_count=candidate_count,
            prior_usage=prior_usage,
        )
        codes = _candidate_codes(str(metadata.get("dataset_key") or ""), profile.name, product_ids)
        candidate_rows = []
        for product_id in sorted(product_ids, key=lambda item: codes[item]):
            product = products[product_id]
            evidence = []
            for aspect in profile.focused_aspects:
                positive = by_product_aspect_polarity.get((product_id, aspect, "pos"), [])
                negative = by_product_aspect_polarity.get((product_id, aspect, "neg"), [])
                evidence.append({
                    "aspect": aspect,
                    "aspect_label": aspect_labels.get(aspect, aspect),
                    "positive_reviews": len({str(row["review_id"]) for row in positive}),
                    "negative_reviews": len({str(row["review_id"]) for row in negative}),
                    "positive_samples": list(_sample_rows(positive, limit=samples_per_polarity)),
                    "negative_samples": list(_sample_rows(negative, limit=samples_per_polarity)),
                })
            candidate_rows.append({
                "code": codes[product_id],
                "entity_id": product_id,
                "entity_name": str(product.get("name") or product_id),
                "evidence": evidence,
            })

        case_path = output_dir / f"caso_{case_index:02d}_{profile.name}.md"
        case_paths.append(case_path)
        lines = [
            f"# Caso {case_index}: elección ciega",
            "",
            "Elegí un ganador y un segundo usando sólo esta ficha. El resultado de post-LAF no aparece aquí.",
            "",
            "## Preferencias",
            "",
            "| Aspecto | Importancia |",
            "|---|---|",
        ]
        for aspect in profile.focused_aspects:
            weight = float(profile.preferences[aspect])
            lines.append(f"| {aspect_labels.get(aspect, aspect)} | {LEVEL_LABELS[weight]} ({weight:.2f}) |")
        lines.extend(["", "## Productos candidatos", ""])
        for candidate in candidate_rows:
            lines.extend([
                f"### Opción {candidate['code']}: {candidate['entity_name']}",
                "",
                f"- Identificador: `{candidate['entity_id']}`",
                "",
            ])
            for evidence in candidate["evidence"]:
                lines.append(
                    f"**{evidence['aspect_label']}**: {evidence['positive_reviews']} reseñas favorables y "
                    f"{evidence['negative_reviews']} críticas extraídas."
                )
                lines.append("")
                samples = [
                    ("Favorable", row) for row in evidence["positive_samples"]
                ] + [("Crítica", row) for row in evidence["negative_samples"]]
                if not samples:
                    lines.append("- No se extrajeron reseñas para este aspecto.")
                for polarity_label, row in samples:
                    stars = f"{row['rate']}★" if int(row["rate"]) > 0 else "sin rating"
                    lines.append(
                        f"- {polarity_label} · {stars} · reseña `{row['review_id']}`: “{row['content']}”"
                    )
                lines.append("")
        lines.extend([
            "## Tu decisión",
            "",
            "- Ganador: __________",
            "- Segundo: __________",
            "- Confianza (alta/media/baja): __________",
            "- Motivo principal: ________________________________________________",
            "- ¿Faltó información para decidir?: ________________________________",
            "- Errores de extracción observados: ________________________________",
            "",
        ])
        case_path.write_text("\n".join(lines), encoding="utf-8")
        manifest_cases.append({
            "name": profile.name,
            "title": profile.title,
            "preferences": profile.preferences,
            "focused_aspects": list(profile.focused_aspects),
            "candidate_codes": {candidate["code"]: {
                "entity_id": candidate["entity_id"], "entity_name": candidate["entity_name"]
            } for candidate in candidate_rows},
            "case_file": case_path.name,
        })
        response_cases.append({
            "name": profile.name,
            "review_status": "pending",
            "winner_code": "",
            "runner_up_code": "",
            "confidence": "",
            "rationale": "",
            "missing_information": "",
            "extraction_errors": [],
            "reviewer": "",
            "reviewed_at": "",
        })

    manifest_path = output_dir / "manifiesto_ciego.json"
    responses_path = output_dir / "respuestas_ciegas.json"
    instructions_path = output_dir / "LEEME.md"
    manifest_path.write_text(
        json.dumps({"metadata": metadata, "contains_system_results": False, "cases": manifest_cases}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    responses_path.write_text(json.dumps({"cases": response_cases}, ensure_ascii=False, indent=2), encoding="utf-8")
    instructions_path.write_text(
        "\n".join([
            "# Validación humana ciega",
            "",
            "1. Abrí cada archivo `caso_*.md` sin consultar el ranking de la aplicación.",
            "2. Elegí ganador y segundo. Indicá confianza alta, media o baja.",
            "3. Registrá las respuestas y cualquier error de extracción en `respuestas_ciegas.json`.",
            "4. Recién al terminar se traducen las letras a productos y se compara con post-LAF.",
            "",
            "Las fichas muestran muestras positivas y negativas por aspecto. La selección usa la mayor evidencia efectiva sólo para elegir qué textos caben en la ficha; no usa posiciones ni resultados LAF.",
            "No se muestran precio, envío, vendedores ni otras condiciones de compra: esos datos pertenecen a LAF2 y sesgarían esta validación de LAF1.",
            "La polaridad indicada es la extracción automática, no una verdad humana. Si contradice el texto o las estrellas, registralo como error de extracción.",
            "",
            "`resenas_completas_lectura.csv` contiene todos los textos relevantes sin puntuaciones técnicas.",
            "`trazabilidad_tecnica.csv` agrega trust, confianza de extracción y evidencia efectiva; conviene abrirlo después de decidir para mantener mayor independencia.",
            "",
            f"Casos: {len(profiles)}",
            f"Productos por caso: {candidate_count}",
            f"Productos disponibles en el anexo completo: {len(products)}",
            f"Extracciones únicas incluidas: {len(reviews)}",
        ]),
        encoding="utf-8",
    )
    return {
        "instructions": instructions_path,
        "manifest": manifest_path,
        "responses": responses_path,
        "reading_csv": reading_csv,
        "technical_csv": technical_csv,
        "case_files": tuple(case_paths),
        "review_count": len(reviews),
        "candidate_count": candidate_count,
    }
