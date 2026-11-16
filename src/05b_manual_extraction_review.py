"""Prepara una validación humana, revisión por revisión, de las extracciones.

El script es de sólo lectura. Une ``reviews_clean``, ``review_trust`` y
``review_aspects`` para conservar la cadena completa:

    texto original -> trust de la reseña -> aspecto/polaridad -> evidencia efectiva

Uso:
    python src/05b_manual_extraction_review.py \
      --dataset-key mlm_mlm194329_20260528_142014 \
      --sample-size 20
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Callable

from dotenv import load_dotenv
from supabase import create_client

from domain_config import load_domain_config
from product_scope import require_included_product_ids


REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")
DEFAULT_DATASET = "mlm_mlm194329_20260528_142014"
DEFAULT_SAMPLE_SIZE = 20
DEFAULT_SEED = 20260831
PAGE_SIZE = 1000


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("debe ser mayor que cero")
    return parsed


def load_excluded_case_ids(response_paths: list[str] | tuple[str, ...]) -> set[str]:
    """Carga identificadores ya muestreados para construir una tanda independiente."""
    excluded: set[str] = set()
    for raw_path in response_paths:
        path = Path(raw_path)
        if not path.exists():
            raise FileNotFoundError(f"No existe el archivo de respuestas a excluir: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        for case in payload.get("cases", []):
            case_id = str(case.get("case_id") or "").strip()
            if case_id:
                excluded.add(case_id)
    return excluded


def fetch_all(page_loader: Callable[[int, int], list[dict[str, Any]]], page_size: int = PAGE_SIZE):
    rows: list[dict[str, Any]] = []
    last_id = 0
    while True:
        page = page_loader(last_id, page_size) or []
        if not page:
            break
        rows.extend(page)
        if len(page) < page_size:
            break
        last_id = int(page[-1]["id"])
    return rows


def _number(value: object) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _signed_number(value: object) -> float:
    """Conserva el signo de componentes aditivos como las penalizaciones."""
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _integer(value: object) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def group_review_cases(
    reviews: list[dict[str, Any]],
    trusts: list[dict[str, Any]],
    extractions: list[dict[str, Any]],
    product_names: dict[str, str],
) -> list[dict[str, Any]]:
    trust_by_key = {
        (str(row.get("review_id")), str(row.get("product_id"))): row
        for row in trusts
    }
    extractions_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in extractions:
        key = (str(row.get("review_id")), str(row.get("product_id")))
        confidence = _number(row.get("extraction_confidence"))
        trust_score = _number(trust_by_key.get(key, {}).get("trust_score"))
        extractions_by_key[key].append(
            {
                "extraction_id": row.get("id"),
                "aspect": str(row.get("aspect") or ""),
                "polarity": str(row.get("polarity") or ""),
                "extraction_confidence": confidence,
                "sentence_excerpt": _clean(row.get("sentence_excerpt")),
                "effective_evidence": round(trust_score * confidence, 6),
            }
        )

    cases = []
    for review in reviews:
        key = (str(review.get("review_id")), str(review.get("product_id")))
        review_extractions = sorted(
            extractions_by_key.get(key, ()),
            key=lambda item: (str(item["sentence_excerpt"]), str(item["aspect"]), str(item["polarity"])),
        )
        if not review_extractions:
            continue
        trust = trust_by_key.get(key, {})
        aspects = sorted({str(item["aspect"]) for item in review_extractions})
        polarities = sorted({str(item["polarity"]) for item in review_extractions})
        cases.append(
            {
                "case_id": f"{key[0]}|{key[1]}",
                "review_id": key[0],
                "product_id": key[1],
                "product_name": product_names.get(key[1], key[1]),
                "rate": _integer(review.get("rate")),
                "content": _clean(review.get("content")),
                "review_metadata": {
                    "relevance": _integer(review.get("relevance")),
                    "likes": _integer(review.get("likes")),
                    "has_media": bool(review.get("has_media")),
                    "content_length": _integer(review.get("content_length")),
                },
                "trust": {
                    name: (
                        _number(trust.get(name))
                        if name == "trust_score"
                        else _signed_number(trust.get(name))
                    )
                    for name in (
                        "trust_score", "base_score", "rate_bonus", "relevance_bonus",
                        "media_bonus", "likes_bonus", "flag_penalty", "short_penalty",
                    )
                },
                "extractions": review_extractions,
                "is_multi_aspect": len(aspects) > 1,
                "has_negative": "neg" in polarities,
                "has_mixed_polarity": "pos" in polarities and "neg" in polarities,
                "minimum_extraction_confidence": min(
                    float(item["extraction_confidence"]) for item in review_extractions
                ),
            }
        )
    return sorted(cases, key=lambda item: item["case_id"])


def choose_review_cases(cases: list[dict[str, Any]], sample_size: int, seed: int):
    """Crea una muestra diversa y determinística sin mirar aciertos humanos."""
    if sample_size <= 0:
        raise ValueError("sample_size debe ser positivo.")
    buckets = (
        ("mixed_polarity", lambda item: bool(item["has_mixed_polarity"])),
        ("multi_aspect", lambda item: bool(item["is_multi_aspect"])),
        ("negative", lambda item: bool(item["has_negative"])),
        ("low_confidence", lambda item: float(item["minimum_extraction_confidence"]) < 0.65),
        ("general", lambda _item: True),
    )
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    quota = max(1, sample_size // len(buckets))
    for reason, predicate in buckets:
        eligible = [item for item in cases if item["case_id"] not in selected_ids and predicate(item)]
        eligible.sort(
            key=lambda item: hashlib.sha256(
                f"{seed}:{reason}:{item['case_id']}".encode("utf-8")
            ).hexdigest()
        )
        for item in eligible[:quota]:
            selected.append({**item, "selection_reason": reason})
            selected_ids.add(str(item["case_id"]))
            if len(selected) == sample_size:
                return selected
    remaining = [item for item in cases if item["case_id"] not in selected_ids]
    remaining.sort(
        key=lambda item: hashlib.sha256(f"{seed}:fill:{item['case_id']}".encode("utf-8")).hexdigest()
    )
    for item in remaining:
        selected.append({**item, "selection_reason": "deterministic_fill"})
        if len(selected) == sample_size:
            break
    return selected


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
            suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def write_review_packet(
    output_dir: Path,
    *,
    dataset_key: str,
    cases: list[dict[str, Any]],
    seed: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    case_paths: list[Path] = []
    response_cases = []
    for index, case in enumerate(cases, start=1):
        path = output_dir / f"caso_{index:02d}.md"
        case_paths.append(path)
        trust = case["trust"]
        metadata = case["review_metadata"]
        lines = [
            f"# Revisión {index} de {len(cases)}",
            "",
            f"**Producto:** {case['product_name']}",
            f"**Estrellas:** {case['rate']} de 5",
            f"**Reseña:** `{case['review_id']}`",
            "",
            "## Texto original completo",
            "",
            f"> {case['content']}",
            "",
            "## Trust de la reseña",
            "",
            f"**Trust final:** {float(trust['trust_score']):.2f}",
            "",
            "| Componente | Valor |",
            "|---|---:|",
            f"| Base | {float(trust['base_score']):.2f} |",
            f"| Relevancia | {float(trust['relevance_bonus']):.2f} |",
            f"| Contenido multimedia | {float(trust['media_bonus']):.2f} |",
            f"| Likes | {float(trust['likes_bonus']):.2f} |",
            f"| Penalización por texto corto | {float(trust['short_penalty']):.2f} |",
            "",
            f"Metadatos: relevancia {metadata['relevance']}, likes {metadata['likes']}, "
            f"multimedia {'sí' if metadata['has_media'] else 'no'}, longitud {metadata['content_length']}.",
            "",
            "El rating no modifica el trust; se muestra sólo como contexto.",
            "",
            "## Extracciones automáticas",
            "",
            "| Nº | Fragmento | Aspecto | Polaridad | Confianza de extracción | Trust × confianza |",
            "|---:|---|---|---|---:|---:|",
        ]
        for extraction_index, extraction in enumerate(case["extractions"], start=1):
            excerpt = str(extraction["sentence_excerpt"]).replace("|", r"\|")
            lines.append(
                f"| {extraction_index} | {excerpt} | {extraction['aspect']} | "
                f"{extraction['polarity']} | {float(extraction['extraction_confidence']):.2f} | "
                f"{float(extraction['effective_evidence']):.2f} |"
            )
        lines.extend([
            "",
            "## Tu revisión",
            "",
            "Para cada fila indicá: correcta, aspecto incorrecto, polaridad incorrecta o extracción que no corresponde.",
            "",
            "- Fila(s) correctas: ____________________",
            "- Correcciones: _________________________",
            "- Aspectos importantes que faltaron: ____",
            "- ¿El trust parece razonable?: sí / no / no sé",
            "- Comentario: ___________________________",
            "",
        ])
        path.write_text("\n".join(lines), encoding="utf-8")
        response_cases.append(
            {
                "case_number": index,
                "case_id": case["case_id"],
                "review_status": "pending",
                "extraction_decisions": [
                    {
                        "extraction_id": item["extraction_id"],
                        "verdict": "",
                        "expected_aspect": "",
                        "expected_polarity": "",
                        "note": "",
                    }
                    for item in case["extractions"]
                ],
                "missing_aspects": [],
                "trust_verdict": "",
                "comment": "",
                "reviewer": "",
                "reviewed_at": "",
            }
        )

    session_path = output_dir / "muestra.json"
    responses_path = output_dir / "respuestas.json"
    readme_path = output_dir / "LEEME.md"
    _write_json_atomic(
        session_path,
        {
            "dataset_key": dataset_key,
            "seed": seed,
            "case_count": len(cases),
            "cases": cases,
        },
    )
    if not responses_path.exists():
        _write_json_atomic(
            responses_path,
            {
                "instructions": (
                    "Completar un caso por vez. verdict admite correct, wrong_aspect, "
                    "wrong_polarity, spurious o ambiguous. No borrar identificadores."
                ),
                "dataset_key": dataset_key,
                "cases": response_cases,
            },
        )
    readme_path.write_text(
        "\n".join([
            "# Validación manual de extracción",
            "",
            "Abrí sólo `caso_01.md`. Después de responder, continuá con el siguiente.",
            "No hace falta recomendar productos ni comparar reseñas entre sí.",
            "La tarea es verificar si cada aspecto y polaridad corresponden al texto original.",
            "El trust se audita por separado: indica utilidad de la reseña como evidencia, no sentimiento.",
            "`Trust × confianza` es el peso con que esa extracción entra a la agregación.",
            "",
            f"Dataset: `{dataset_key}`",
            f"Casos: {len(cases)}",
            f"Semilla reproducible: {seed}",
        ]),
        encoding="utf-8",
    )
    return {
        "readme": readme_path,
        "sample": session_path,
        "responses": responses_path,
        "case_files": tuple(case_paths),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepara una muestra manual de reseñas y extracciones trazables.",
    )
    parser.add_argument("--dataset-key", default=DEFAULT_DATASET)
    parser.add_argument("--sample-size", type=positive_int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir")
    parser.add_argument(
        "--exclude-responses",
        action="append",
        default=[],
        metavar="RUTA",
        help=(
            "Archivo respuestas.json cuyos case_id deben excluirse. "
            "Puede indicarse más de una vez."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    url = str(os.getenv("SUPABASE_URL") or "").strip()
    key = str(os.getenv("SUPABASE_KEY") or "").strip()
    if not url or not key:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY en .env.")
    domain = load_domain_config()
    domain_key = str(domain.get("domain_key") or "").strip()
    client = create_client(url, key)
    product_ids = sorted(
        require_included_product_ids(
            client,
            args.dataset_key,
            stage_name="05b_manual_extraction_review.py",
        )
    )

    def load(table: str, columns: str):
        return fetch_all(
            lambda last_id, size: (
                client.table(table).select(columns).eq("dataset_key", args.dataset_key)
                .in_("product_id", product_ids).gt("id", last_id).order("id").limit(size)
                .execute().data
            )
        )

    reviews = load(
        "reviews_clean",
        "id,review_id,product_id,rate,content,relevance,likes,has_media,content_length",
    )
    trusts = load(
        "review_trust",
        "id,review_id,product_id,trust_score,base_score,rate_bonus,relevance_bonus,"
        "media_bonus,likes_bonus,flag_penalty,short_penalty",
    )
    extractions = load(
        "review_aspects",
        "id,review_id,product_id,aspect,polarity,extraction_confidence,sentence_excerpt",
    )
    product_rows = (
        client.table("products_raw").select("product_id,name,family_name")
        .eq("dataset_key", args.dataset_key).in_("product_id", product_ids).execute().data or []
    )
    names = {
        str(row.get("product_id")): str(
            row.get("name") or row.get("family_name") or row.get("product_id")
        )
        for row in product_rows
    }
    all_cases = group_review_cases(reviews, trusts, extractions, names)
    excluded_case_ids = load_excluded_case_ids(args.exclude_responses)
    eligible_cases = [case for case in all_cases if case["case_id"] not in excluded_case_ids]
    cases = choose_review_cases(
        eligible_cases,
        min(args.sample_size, len(eligible_cases)),
        args.seed,
    )
    if not cases:
        raise RuntimeError("No quedaron casos elegibles después de aplicar las exclusiones.")
    output_dir = Path(args.output_dir) if args.output_dir else (
        REPO_ROOT / "artifacts_por_dominio" / domain_key / "otros"
        / "manual_extraction_review" / args.dataset_key
    )
    paths = write_review_packet(
        output_dir,
        dataset_key=args.dataset_key,
        cases=cases,
        seed=args.seed,
    )
    print(f"Dataset: {args.dataset_key}")
    print(f"Productos incluidos: {len(product_ids)}")
    print(f"Reseñas con extracción: {len(all_cases)}")
    print(f"Casos anteriores excluidos: {len(excluded_case_ids)}")
    print(f"Casos elegibles: {len(eligible_cases)}")
    print(f"Casos seleccionados: {len(cases)}")
    print(f"Primer caso: {paths['case_files'][0]}")
    print(f"Respuestas: {paths['responses']}")


if __name__ == "__main__":
    main()
