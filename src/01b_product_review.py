"""
01b_product_review.py - Revision humana de productos desde la consola.

Muestra, para cada producto del ranking original:
  - nombre, familia, domain_id y categoria;
  - atributos de catalogo;
  - cantidad de resenas y publicaciones limpias;
  - descripciones comerciales recuperadas por WF03;
  - ejemplos de resenas.

La decision vigente se guarda en products_seed. Cada cambio se registra en
product_review_decisions para conservar un historial auditable.

Uso:
    .\venv\Scripts\python.exe src\01b_product_review.py
    .\venv\Scripts\python.exe src\01b_product_review.py --list
    .\venv\Scripts\python.exe src\01b_product_review.py --all
    .\venv\Scripts\python.exe src\01b_product_review.py --product-id MLM34290592
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import create_client

from product_scope import (
    MIGRATION_PATH,
    ProductReviewSetupError,
    load_product_review_rows,
    scope_summary,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MIN_REVIEW_EVIDENCE = 30
# Estas funciones viven en PostgreSQL: una evita escrituras parciales y la otra
# evita transferir todos los IDs a Python solo para contarlos.
SAVE_DECISION_RPC = "save_product_review_decision"
PRODUCT_COUNTS_RPC = "product_clean_counts"
STATUS_LABELS = {
    "pending": "PENDIENTE",
    "included": "INCLUIDO",
    "excluded": "EXCLUIDO",
}
DECISION_KEYS = {
    "i": "included",
    "e": "excluded",
    "p": "pending",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Revisa manualmente que productos pertenecen al corpus analitico."
    )
    parser.add_argument(
        "--dataset-key",
        default=None,
        help="Dataset a revisar. Si se omite, usa DATASET_KEY de .env.",
    )
    parser.add_argument(
        "--reviewer",
        default=None,
        help="Nombre que quedara en el historial de decisiones.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Permite revisar tambien productos ya incluidos o excluidos.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Muestra el resumen y termina sin pedir decisiones.",
    )
    parser.add_argument(
        "--product-id",
        default=None,
        help="Revisa solamente un product_id.",
    )
    parser.add_argument(
        "--review-examples",
        type=int,
        default=3,
        help="Cantidad de resenas de ejemplo a mostrar (default: 3).",
    )
    parser.add_argument(
        "--min-review-evidence",
        type=int,
        default=MIN_REVIEW_EVIDENCE,
        help=(
            "Umbral informativo para marcar evidencia escasa; no excluye "
            f"productos (default: {MIN_REVIEW_EVIDENCE})."
        ),
    )
    return parser.parse_args()

#Funciones auxiliares para normalizar datos y evitar errores de tipo o None.
def parse_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def resolve_reviewer(explicit_reviewer: str | None) -> str:
    """Resuelve el autor de la decisión una vez que ``.env`` ya fue cargado.

    El argumento de la CLI tiene prioridad para permitir ejecuciones puntuales
    con otro revisor sin modificar la configuración persistente.
    """
    value = (
        explicit_reviewer
        if explicit_reviewer is not None
        else os.environ.get("PRODUCT_REVIEWER", "Ana Paula Machado")
    )
    return clean_text(value)


def truncate(value: Any, limit: int = 500) -> str:
    text = clean_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def fetch_all(
    sb: Any,
    table: str,
    columns: str,
    dataset_key: str,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    """Lee todas las filas mediante paginación estable por la clave ``id``.

    Se usa paginación por cursor (``id > último_id``) en lugar de ``offset``.
    Así, una inserción o eliminación concurrente no desplaza las páginas y no
    provoca filas repetidas u omitidas. ``id`` se añade al SELECT porque es el
    cursor, aunque el llamador no lo haya pedido expresamente.
    """
    rows_out: list[dict[str, Any]] = []
    selected_columns = [part.strip() for part in columns.split(",")]
    if "id" not in selected_columns:
        selected_columns.insert(0, "id")
    select_clause = ",".join(selected_columns)
    last_id = 0
    while True:
        rows = (
            sb.table(table)
            .select(select_clause)
            .eq("dataset_key", dataset_key)
            .gt("id", last_id)
            .order("id")
            .range(0, page_size - 1)
            .execute()
            .data
        )
        if not rows:
            break
        rows_out.extend(rows)
        if len(rows) < page_size:
            break
        last_id = int(rows[-1]["id"])
    return rows_out


def load_product_raw(sb: Any, dataset_key: str) -> dict[str, dict[str, Any]]:
    rows = fetch_all(
        sb,
        "products_raw",
        "product_id,name,family_name,domain_id,attributes,raw_json",
        dataset_key,
    )
    return {row["product_id"]: row for row in rows}


def load_counts(sb: Any, dataset_key: str) -> tuple[Counter, Counter]:
    """Obtiene un conteo por producto calculado dentro de PostgreSQL.

    La RPC devuelve solo un resumen por producto. Esto reemplaza la descarga de
    miles de ``product_id`` desde ambas tablas y reduce red, memoria y tiempo.
    """
    try:
        rows = (
            sb.rpc(PRODUCT_COUNTS_RPC, {"p_dataset_key": dataset_key})
            .execute()
            .data
            or []
        )
    except Exception as exc:
        if is_missing_rpc_error(exc, PRODUCT_COUNTS_RPC):
            raise ProductReviewSetupError(
                f"Falta instalar la funcion {PRODUCT_COUNTS_RPC}. "
                f"Ejecuta {MIGRATION_PATH} en Supabase SQL Editor."
            ) from exc
        raise

    review_counts = Counter()
    item_counts = Counter()
    for row in rows:
        product_id = row.get("product_id")
        if product_id:
            review_counts[product_id] = int(row.get("review_count") or 0)
            item_counts[product_id] = int(row.get("item_count") or 0)
    return review_counts, item_counts


def is_missing_rpc_error(exc: Exception, function_name: str) -> bool:
    """Distingue una migración pendiente de un fallo real de conexión o permisos."""
    message = str(exc).lower()
    markers = ("pgrst202", "could not find the function", "schema cache")
    return function_name.lower() in message and any(
        marker in message for marker in markers
    )


def is_missing_descriptions_schema_error(exc: Exception) -> bool:
    """Reconoce exclusivamente tabla o columnas opcionales de WF03 ausentes.

    No alcanza con buscar un mensaje genérico como ``schema cache``: el error
    también debe mencionar la tabla o una de sus columnas para no confundir un
    problema operativo con la ausencia legítima de esta fuente opcional.
    """
    message = str(exc).lower()
    mentions_source = (
        "item_descriptions_raw" in message
        or "plain_text" in message
        or "product_id" in message
    )
    missing_markers = (
        "42p01",
        "42703",
        "pgrst204",
        "pgrst205",
        "does not exist",
        "could not find",
        "schema cache",
    )
    return mentions_source and any(marker in message for marker in missing_markers)


def load_descriptions(
    sb: Any,
    dataset_key: str,
) -> tuple[dict[str, list[dict[str, Any]]], str | None]:
    """Carga WF03 sin ocultar errores que requieren intervención.

    La revisión puede continuar si la tabla/columnas opcionales aún no fueron
    instaladas. En cambio, errores de red, credenciales o permisos se propagan:
    seguir en esos casos mostraría datos incompletos como si fueran válidos.
    """
    try:
        rows = fetch_all(
            sb,
            "item_descriptions_raw",
            "product_id,item_id,plain_text,text",
            dataset_key,
        )
    except Exception as exc:
        if is_missing_descriptions_schema_error(exc):
            return {}, str(exc)
        raise RuntimeError("No se pudo consultar item_descriptions_raw.") from exc

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("product_id"):
            grouped[row["product_id"]].append(row)
    return dict(grouped), None


def load_review_examples(
    sb: Any,
    dataset_key: str,
    product_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    return (
        sb.table("reviews_clean")
        .select("review_id,rate,title,content,relevance")
        .eq("dataset_key", dataset_key)
        .eq("product_id", product_id)
        .order("relevance", desc=True)
        .limit(limit)
        .execute()
        .data
    )


def product_identity(
    raw: dict[str, Any] | None,
    product_id: str,
) -> dict[str, str]:
    raw = raw or {}
    payload = parse_json(raw.get("raw_json"), {})
    name = (
        clean_text(raw.get("name"))
        or clean_text(payload.get("name"))
        or "[nombre no disponible]"
    )
    family = (
        clean_text(raw.get("family_name"))
        or clean_text(payload.get("family_name"))
        or "No disponible"
    )
    return {
        "product_id": product_id,
        "name": name,
        "family_name": family,
        "domain_id": (
            clean_text(raw.get("domain_id"))
            or clean_text(payload.get("domain_id"))
            or "No disponible"
        ),
        "category_id": clean_text(payload.get("category_id")) or "No disponible",
    }


def product_attributes(raw: dict[str, Any] | None) -> list[dict[str, str]]:
    raw = raw or {}
    payload = parse_json(raw.get("raw_json"), {})
    attributes = parse_json(raw.get("attributes"), [])
    if not attributes:
        attributes = payload.get("attributes") or []

    rows = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        value = (
            attribute.get("value_name")
            or (attribute.get("value_struct") or {}).get("number")
            or ""
        )
        rows.append(
            {
                "name": clean_text(attribute.get("name") or attribute.get("id")),
                "value": clean_text(value),
                "id": clean_text(attribute.get("id")),
            }
        )
    return rows


def automatic_flags(
    identity: dict[str, str],
    review_count: int,
    item_count: int,
    descriptions: list[dict[str, Any]],
    min_review_evidence: int = MIN_REVIEW_EVIDENCE,
) -> list[str]:
    """Genera advertencias informativas; ninguna cambia la decisión humana."""
    flags = []
    if identity["name"] == "[nombre no disponible]":
        flags.append("nombre no disponible")
    if review_count < min_review_evidence:
        flags.append(f"evidencia escasa: {review_count} resenas limpias")
    if item_count == 0:
        flags.append("sin publicaciones limpias")
    if not descriptions:
        flags.append("sin descripcion de WF03")
    return flags


def print_overview(
    seed_rows: list[dict[str, Any]],
    raw_by_product: dict[str, dict[str, Any]],
    review_counts: Counter,
    item_counts: Counter,
) -> None:
    print()
    print("Resumen de productos")
    print(
        "pos estado     product_id       producto"
        "                                      reviews items"
    )
    print("-" * 104)
    for seed in seed_rows:
        pid = seed["product_id"]
        identity = product_identity(raw_by_product.get(pid), pid)
        print(
            f"{int(seed['position']):>3} "
            f"{STATUS_LABELS[seed['analysis_status']]:10s} "
            f"{pid[:16]:16s} "
            f"{identity['name'][:44]:44s} "
            f"{review_counts.get(pid, 0):7d} "
            f"{item_counts.get(pid, 0):5d}"
        )


def print_product_detail(
    sb: Any,
    dataset_key: str,
    seed: dict[str, Any],
    raw: dict[str, Any] | None,
    review_count: int,
    item_count: int,
    descriptions: list[dict[str, Any]],
    review_examples: int,
    min_review_evidence: int,
) -> None:
    pid = seed["product_id"]
    identity = product_identity(raw, pid)
    attributes = product_attributes(raw)
    flags = automatic_flags(
        identity,
        review_count,
        item_count,
        descriptions,
        min_review_evidence,
    )

    print()
    print("=" * 88)
    print(
        f"Producto #{int(seed['position']):02d} | "
        f"{STATUS_LABELS[seed['analysis_status']]} | {pid}"
    )
    print("=" * 88)
    print(f"Nombre:      {identity['name']}")
    print(f"Familia:     {identity['family_name']}")
    print(f"Domain ID:   {identity['domain_id']}")
    print(f"Categoria:   {identity['category_id']}")
    print(f"Datos:       {review_count} resenas clean | {item_count} publicaciones clean")
    if flags:
        print("Alertas:     " + "; ".join(flags))
    else:
        print("Alertas:     sin alertas estructurales")

    print()
    print("Atributos de catalogo:")
    if attributes:
        for row in attributes[:15]:
            label = row["name"] or row["id"] or "atributo"
            print(f"  - {label}: {row['value'] or '[sin valor]'}")
        if len(attributes) > 15:
            print(f"  ... {len(attributes) - 15} atributos mas")
    else:
        print("  [sin atributos disponibles]")

    print()
    print("Descripciones de publicaciones:")
    if descriptions:
        shown = 0
        for row in descriptions:
            text = row.get("plain_text") or row.get("text")
            if not clean_text(text):
                continue
            shown += 1
            print(f"  [{shown}] item {row.get('item_id') or 'sin ID'}")
            print(f"      {truncate(text, 700)}")
            if shown >= 2:
                break
        if shown == 0:
            print("  [las descripciones recuperadas estan vacias]")
    else:
        print("  [sin descripciones recuperadas]")

    print()
    print("Resenas de ejemplo:")
    examples = load_review_examples(
        sb,
        dataset_key,
        pid,
        review_examples,
    )
    if examples:
        for index, row in enumerate(examples, start=1):
            rate = row.get("rate") if row.get("rate") is not None else "?"
            print(f"  [{index}] {rate} estrellas | review {row.get('review_id')}")
            if clean_text(row.get("title")):
                print(f"      Titulo: {truncate(row.get('title'), 140)}")
            print(f"      {truncate(row.get('content'), 500)}")
    else:
        print("  [sin resenas limpias]")

    if clean_text(seed.get("analysis_reason")):
        print()
        print(f"Fundamento vigente: {seed['analysis_reason']}")


def prompt_decision(current_status: str) -> str:
    while True:
        print()
        value = input(
            "Decision: [i] incluir, [e] excluir, [p] pendiente, "
            "[s] saltar, [q] salir: "
        ).strip().lower()
        if value in DECISION_KEYS:
            return DECISION_KEYS[value]
        if value in {"s", "q"}:
            return value
        if not value:
            print(f"Estado actual: {STATUS_LABELS[current_status]}. Elegi una opcion.")
        else:
            print("Opcion invalida.")


def save_decision(
    sb: Any,
    dataset_key: str,
    seed: dict[str, Any],
    decision: str,
    reason: str,
    reviewer: str,
) -> None:
    """Guarda el estado vigente y su historial en una transacción PostgreSQL.

    La RPC ejecuta UPDATE e INSERT dentro de la misma transacción: si cualquiera
    falla, PostgreSQL revierte ambos. ``p_expected_reviewed_at`` implementa un
    control optimista para no sobrescribir una decisión guardada por otra persona
    desde que esta pantalla cargó el producto.
    """
    try:
        rows = (
            sb.rpc(
                SAVE_DECISION_RPC,
                {
                    "p_dataset_key": dataset_key,
                    "p_product_id": seed["product_id"],
                    "p_decision": decision,
                    "p_reason": reason or None,
                    "p_reviewer": reviewer,
                    "p_expected_reviewed_at": seed.get("analysis_reviewed_at"),
                },
            )
            .execute()
            .data
            or []
        )
    except Exception as exc:
        if is_missing_rpc_error(exc, SAVE_DECISION_RPC):
            raise ProductReviewSetupError(
                f"Falta instalar la funcion {SAVE_DECISION_RPC}. "
                f"Ejecuta {MIGRATION_PATH} en Supabase SQL Editor."
            ) from exc
        raise

    if not rows:
        raise RuntimeError("Supabase no devolvio la decision guardada.")
    seed.update(rows[0])


def confirm_save() -> bool:
    answer = input("Guardar esta decision? [S/n]: ").strip().lower()
    return answer in {"", "s", "si", "sí", "y", "yes"}


def main() -> None:
    # Debe ocurrir antes de parsear/resolver opciones porque PRODUCT_REVIEWER
    # puede estar definido únicamente en el archivo .env.
    load_dotenv(REPO_ROOT / ".env")
    args = parse_args()

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    dataset_key = args.dataset_key or os.environ.get("DATASET_KEY")

    if not supabase_url or not supabase_key:
        print("ERROR: faltan SUPABASE_URL y/o SUPABASE_KEY en .env.", file=sys.stderr)
        sys.exit(1)
    if not dataset_key:
        print("ERROR: falta DATASET_KEY en .env o --dataset-key.", file=sys.stderr)
        sys.exit(1)
    reviewer = resolve_reviewer(args.reviewer)
    if not reviewer:
        print("ERROR: --reviewer no puede estar vacio.", file=sys.stderr)
        sys.exit(1)
    if args.review_examples < 0:
        print("ERROR: --review-examples no puede ser negativo.", file=sys.stderr)
        sys.exit(1)
    if args.min_review_evidence < 0:
        print("ERROR: --min-review-evidence no puede ser negativo.", file=sys.stderr)
        sys.exit(1)

    sb = create_client(supabase_url, supabase_key)
    try:
        seed_rows = load_product_review_rows(sb, dataset_key)
    except ProductReviewSetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "Ejecuta en Supabase SQL Editor:",
            REPO_ROOT / MIGRATION_PATH,
            sep="\n  ",
            file=sys.stderr,
        )
        sys.exit(1)

    if not seed_rows:
        print(f"ERROR: products_seed no tiene filas para {dataset_key}.", file=sys.stderr)
        sys.exit(1)

    raw_by_product = load_product_raw(sb, dataset_key)
    try:
        review_counts, item_counts = load_counts(sb, dataset_key)
    except ProductReviewSetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    descriptions_by_product, descriptions_error = load_descriptions(sb, dataset_key)

    print(f"Dataset: {dataset_key}")
    print(f"Revisor/a: {reviewer}")
    if descriptions_error:
        print(
            "AVISO: no se pudo leer item_descriptions_raw. "
            "Se mostraran catalogo y resenas."
        )
    print_overview(seed_rows, raw_by_product, review_counts, item_counts)

    if args.list:
        return

    if args.product_id:
        queue = [
            row
            for row in seed_rows
            if row["product_id"].lower() == args.product_id.lower()
        ]
        if not queue:
            print(f"ERROR: no existe product_id={args.product_id!r}.", file=sys.stderr)
            sys.exit(1)
    elif args.all:
        queue = seed_rows
    else:
        queue = [
            row for row in seed_rows if row["analysis_status"] == "pending"
        ]

    if not queue:
        print()
        print("No hay productos pendientes.")
        print("Usa --all para revisar decisiones anteriores.")
    else:
        for seed in queue:
            pid = seed["product_id"]
            print_product_detail(
                sb,
                dataset_key,
                seed,
                raw_by_product.get(pid),
                review_counts.get(pid, 0),
                item_counts.get(pid, 0),
                descriptions_by_product.get(pid, []),
                args.review_examples,
                args.min_review_evidence,
            )
            decision = prompt_decision(seed["analysis_status"])
            if decision == "q":
                print("Revision interrumpida por el usuario. Las decisiones previas quedaron guardadas.")
                break
            if decision == "s":
                print("Producto omitido; conserva su estado actual.")
                continue

            if decision == "excluded":
                reason = ""
                while not clean_text(reason):
                    reason = input("Motivo obligatorio de exclusion: ").strip()
            elif decision == "included":
                reason = input(
                    "Fundamento [Producto verificado como perteneciente al dominio]: "
                ).strip()
                if not reason:
                    reason = "Producto verificado como perteneciente al dominio."
            else:
                reason = input("Nota del pendiente [opcional]: ").strip()

            if not confirm_save():
                print("Decision no guardada.")
                continue

            save_decision(
                sb,
                dataset_key,
                seed,
                decision,
                clean_text(reason),
                reviewer,
            )
            print(
                f"OK: {pid} -> {STATUS_LABELS[decision]}. "
                "Estado e historial guardados."
            )

    final_rows = load_product_review_rows(sb, dataset_key)
    summary = scope_summary(final_rows)
    print()
    print("Estado final de la revision")
    print(
        f"  Incluidos: {summary['included']} | "
        f"Excluidos: {summary['excluded']} | "
        f"Pendientes: {summary['pending']}"
    )
    if summary["pending"] == 0:
        print("Revision completa. Siguiente paso:")
        print(r"  .\venv\Scripts\python.exe src\02_domain_discovery.py")
    else:
        print("Completa los pendientes antes de ejecutar los scripts 02 en adelante.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nRevision cancelada. Las decisiones ya guardadas se conservan.")
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
