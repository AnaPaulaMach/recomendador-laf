"""
01_clean.py - Limpieza y normalizacion de reviews e items.

Lee reviews_raw e items_raw, descarta registros no utilizables, normaliza texto
y escribe en reviews_clean e items_clean. Esta etapa no infiere aspectos ni
polaridad: solo prepara una base consistente y auditable para los scripts
siguientes.

Uso:
    # Recomendado en Windows/PowerShell: usar el Python del venv directamente.
    # Asi no hace falta activar el entorno con Activate.ps1.
    .\venv\Scripts\python.exe src\01_clean.py
    .\venv\Scripts\python.exe src\01_clean.py --dataset-key mla_xxx
    .\venv\Scripts\python.exe src\01_clean.py --reset-clean

    # Si falta algun modulo, instalar dependencias una vez:
    .\venv\Scripts\python.exe -m pip install -r requirements.txt

    # Si se prefiere activar el entorno y PowerShell bloquea Activate.ps1:
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\venv\Scripts\Activate.ps1
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from supabase import create_client

from money import money_for_storage, parse_money


# Raiz del proyecto: sirve para encontrar el .env aunque ejecutes el script
# desde otra carpeta.
REPO_ROOT = Path(__file__).resolve().parents[1]

# Parametros de calidad de datos. Estos valores definen que resenas entran a
# la capa clean, pero no interpretan sentimiento ni aspectos.
MIN_CONTENT_LENGTH = 10
# Techo defensivo para evitar que un valor anomalo monopolice memoria, trafico
# y procesamiento NLP. No es un criterio de calidad: puede ajustarse por CLI.
MAX_CONTENT_LENGTH = 10000
DEFAULT_PAGE_SIZE = 1000
MAX_FETCH_RETRIES = 3
MAX_WRITE_RETRIES = 3

# Expresiones regulares usadas por normalize(). Se compilan una sola vez para
# no recompilarlas por cada resena.
# Limpian URLs, emails, emojis, caracteres de control y espacios repetidos.
URL_RE = re.compile(r"https?://\S+|www\.\S+")
EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002600-\U000027BF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA70-\U0001FAFF"
    "]+",
    flags=re.UNICODE,
)
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
WS_RE = re.compile(r"\s+")

#Guarda la configuracion de ejecucion
@dataclass
class RunConfig:
    """Configuracion comun que se pasa a las funciones de limpieza."""

    dataset_key: str
    page_size: int
    max_content_length: int
    reset_clean: bool


def normalize(text: Any, max_length: int = MAX_CONTENT_LENGTH) -> str:
    """Normaliza texto conservando acentos y contenido util para NLP.

    Hace solo limpieza superficial:
    - pasa a minusculas;
    - quita URLs, emails, emojis y caracteres de control;
    - compacta espacios y saltos de linea;
    - corta textos demasiado largos.

    No elimina acentos porque despues spaCy y el lexicon pueden necesitarlos.
    """
    if text is None:
        return ""

    t = str(text).lower()
    t = URL_RE.sub(" ", t)
    t = EMAIL_RE.sub(" ", t)
    t = EMOJI_RE.sub(" ", t)
    t = CONTROL_RE.sub(" ", t)
    t = WS_RE.sub(" ", t).strip()

    if len(t) <= max_length:
        return t

    # Si hay que cortar, intenta no partir la ultima palabra.
    shortened = t[:max_length].rsplit(" ", 1)[0].strip()
    return shortened or t[:max_length].strip()


def safe_int(value: Any, default: int | None = 0) -> int | None:
    """Convierte valores del dump a int sin romper el script."""
    if value is None or value == "":
        return default
    try:
        parsed = Decimal(str(value))
        return int(parsed) if parsed.is_finite() else default
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return default


def safe_float(value: Any, default: float | None = 0.0) -> float | None:
    """Convierte valores del dump a float sin romper el script."""
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError, OverflowError):
        return default


def normalize_forbidden_value(value: Any) -> int:
    """Normaliza el indicador ``forbidden_words`` sin interpretarlo.

    Segun el origen del dump, forbidden_words puede venir como numero, lista,
    diccionario o texto JSON. Mercado Libre no aporta una semantica suficiente
    para tratarlo como cantidad de malas palabras ni como criterio de
    exclusion; se conserva solo como metadato auditable.
    """
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        raw_count = value.get("count")
        if raw_count is not None:
            return safe_int(raw_count, 0) or 0
        return len(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return 0
        parsed_int = safe_int(stripped, None)
        if parsed_int is not None:
            return parsed_int
        try:
            return normalize_forbidden_value(json.loads(stripped))
        except json.JSONDecodeError:
            return 1
    return 0

# Esto aporta al calculo de confianza de la resena: si tiene fotos/videos asociados, suele ser mas confiable.
def has_media(media_field: Any) -> bool:
    """Indica si la resena trae fotos/videos asociados."""
    if not media_field:
        return False
    if isinstance(media_field, list):
        return len(media_field) > 0
    if isinstance(media_field, dict):
        return len(media_field) > 0
    if isinstance(media_field, str):
        stripped = media_field.strip()
        if stripped in ("", "[]", "{}", "null", "None"):
            return False
        try:
            return has_media(json.loads(stripped))
        except json.JSONDecodeError:
            return True
    return True


def parse_seller_address(value: Any) -> str | None:
    """Convierte seller_address a texto simple para items_clean."""
    if not value:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for key in ("city", "state", "country"):
            part = value.get(key)
            if isinstance(part, dict):
                part = part.get("name") or part.get("id")
            if part:
                parts.append(str(part))
        return ", ".join(parts) if parts else json.dumps(value, ensure_ascii=False)
    return str(value)


def valid_rate(value: Any) -> int | None:
    """Acepta solo calificaciones entre 1 y 5."""
    rate = safe_int(value, None)
    if rate is None or not 1 <= rate <= 5:
        return None
    return rate


def is_transient_database_error(exc: Exception) -> bool:
    """Reconoce fallos temporales para los que repetir es seguro."""
    message = str(exc).lower()
    status = str(
        getattr(exc, "status_code", "") or getattr(exc, "code", "")
    ).lower()
    if status in {"429", "502", "503", "504", "57014"}:
        return True
    transient_markers = (
        "statement timeout",
        "timed out",
        "timeout",
        "57014",
        "connection reset",
        "connection aborted",
        "server disconnected",
        "temporarily unavailable",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "too many requests",
        "rate limit",
        " 429",
        " 502",
        " 503",
        " 504",
    )
    return any(marker in message for marker in transient_markers)


def execute_with_retry(
    operation: Any,
    description: str,
    max_attempts: int = MAX_WRITE_RETRIES,
    sleep_fn: Any = time.sleep,
) -> Any:
    """Ejecuta una escritura idempotente con backoff exponencial."""
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if not is_transient_database_error(exc) or attempt >= max_attempts:
                raise
            wait_seconds = min(10, 2 ** attempt)
            print(
                f"  AVISO: fallo temporal en {description}. "
                f"Reintento {attempt}/{max_attempts} en {wait_seconds}s...",
                file=sys.stderr,
            )
            sleep_fn(wait_seconds)
    raise RuntimeError(f"No se pudo completar {description}.")


def fetch_pages(
    sb: Any,
    table: str,
    columns: str,
    dataset_key: str,
    page_size: int,
) -> Iterable[list[dict[str, Any]]]:
    """Lee una tabla de Supabase por paginas.

    Supabase devuelve una cantidad limitada de filas por consulta. Por eso el
    script pagina por id: pide filas posteriores al ultimo id leido. Esto evita
    que la base tenga que recalcular paginas grandes con offset cuando hay
    muchos datasets acumulados.
    """
    last_id = 0
    while True:
        rows = []
        for attempt in range(1, MAX_FETCH_RETRIES + 1):
            query = (
                sb.table(table)
                .select(columns)
                .eq("dataset_key", dataset_key)
                .gt("id", last_id)
                .order("id")
                .range(0, page_size - 1)
            )
            try:
                rows = query.execute().data or []
                break
            except Exception as exc:
                is_transient = is_transient_database_error(exc)
                if is_transient and attempt < MAX_FETCH_RETRIES:
                    wait_seconds = min(10, 2 ** attempt)
                    print(
                        f"  AVISO: fallo temporal leyendo {table} despues de id>{last_id}. "
                        f"Reintento {attempt}/{MAX_FETCH_RETRIES} en {wait_seconds}s...",
                        file=sys.stderr,
                    )
                    time.sleep(wait_seconds)
                    continue
                if is_transient:
                    print(
                        "ERROR: Supabase no pudo completar la lectura. "
                        "Ejecuta database/schema.sql o crea indices compuestos "
                        f"sobre {table}(dataset_key, id), y reintenta con "
                        "--page-size 200.",
                        file=sys.stderr,
                    )
                raise
        if not rows:
            break
        yield rows
        last_id = int(rows[-1]["id"])


def chunked(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    """Parte una lista grande en lotes mas chicos para insertar."""
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def upsert_rows(
    sb: Any,
    table: str,
    rows: list[dict[str, Any]],
    on_conflict: str,
    chunk_size: int = 500,
) -> int:
    """Inserta o actualiza filas en la tabla clean.

    upsert evita duplicar si el script se corre mas de una vez para el mismo
    dataset. El parametro on_conflict define la clave de unicidad.
    """
    inserted = 0
    for chunk in chunked(rows, chunk_size):
        execute_with_retry(
            lambda chunk=chunk: (
                sb.table(table)
                .upsert(chunk, on_conflict=on_conflict)
                .execute()
            ),
            f"upsert de {len(chunk)} filas en {table}",
        )
        inserted += len(chunk)
    return inserted


def prune_stale_rows(
    sb: Any,
    table: str,
    dataset_key: str,
    key_columns: tuple[str, ...],
    valid_keys: set[tuple[Any, ...]],
    page_size: int,
    delete_chunk_size: int = 500,
) -> int:
    """Elimina filas CLEAN que ya no corresponden a una fila RAW valida.

    Solo se llama despues de terminar todos los upserts. Si la lectura o una
    escritura previa falla, no se poda nada y la version CLEAN anterior queda
    disponible. Una poda interrumpida es idempotente: la siguiente corrida la
    completa sin borrar filas validas.
    """
    columns = "id," + ",".join(key_columns)
    stale_ids: list[int] = []
    for rows in fetch_pages(sb, table, columns, dataset_key, page_size):
        for row in rows:
            key = tuple(row.get(column) for column in key_columns)
            if key not in valid_keys:
                stale_ids.append(int(row["id"]))

    for ids in chunked(stale_ids, delete_chunk_size):
        execute_with_retry(
            lambda ids=ids: sb.table(table).delete().in_("id", ids).execute(),
            f"eliminacion de {len(ids)} filas obsoletas en {table}",
        )
    return len(stale_ids)


def is_missing_product_review_schema_error(exc: Exception) -> bool:
    """Distingue una migracion ausente de errores operativos reales."""
    message = str(exc).lower()
    mentions_review_schema = (
        "analysis_status" in message or "products_seed" in message
    )
    missing_schema_markers = (
        "42703",
        "42p01",
        "pgrst204",
        "does not exist",
        "schema cache",
        "could not find",
    )
    return mentions_review_schema and any(
        marker in message for marker in missing_schema_markers
    )


def clean_reviews(sb: Any, cfg: RunConfig) -> dict[str, Any]:
    """Limpia reviews_raw y guarda el resultado en reviews_clean."""
    print("Limpiando reviews...")

    # Seleccionamos solo las columnas que usa esta etapa. Esto hace la lectura
    # mas liviana y deja explicito de que depende el script.
    columns = (
        "id,dataset_key,review_id,product_id,item_id,rate,title,content,likes,"
        "dislikes,relevance,forbidden_words,media,buying_date,date_created"
    )
    total_read = 0
    inserted = 0

    # skipped guarda cuantas resenas se descartan por cada motivo.
    skipped = Counter()

    # by_product permite imprimir al final cuantas resenas raw/clean quedaron
    # por producto.
    by_product = defaultdict(lambda: {"raw": 0, "clean": 0})

    # Evita duplicados dentro de la misma corrida antes de llegar a Supabase.
    seen_keys = set()

    for rows in fetch_pages(sb, "reviews_raw", columns, cfg.dataset_key, cfg.page_size):
        total_read += len(rows)
        batch_to_insert = []

        for row in rows:
            product_id = row.get("product_id")
            review_id = row.get("review_id")

            # Cuenta raw por producto aunque despues la resena se descarte.
            if product_id:
                by_product[product_id]["raw"] += 1

            # Sin producto o sin review_id no hay forma segura de trazar la
            # resena entre raw y clean.
            if not product_id:
                skipped["sin_producto"] += 1
                continue
            if review_id is None:
                skipped["sin_review_id"] += 1
                continue

            # Normaliza el texto antes de medir longitud. Asi no cuentan URLs,
            # emojis o espacios repetidos como contenido real.
            content_norm = normalize(
                row.get("content"),
                max_length=cfg.max_content_length,
            )
            if not content_norm:
                skipped["sin_texto"] += 1
                continue
            if len(content_norm) < MIN_CONTENT_LENGTH:
                skipped["muy_corta"] += 1
                continue

            # Se conserva el indicador para auditoria, pero no se usa para
            # descartar. La muestra manual encontro textos con evidencia del
            # producto (enfriamiento, ruido o conectividad) aun con valores
            # altos; la relevancia se decide despues mediante los aspectos.
            forbidden_value = normalize_forbidden_value(row.get("forbidden_words"))

            # La identidad real de una resena es dataset + producto + review_id.
            # El campo id de cada tabla es solo un autoincremental interno.
            key = (row["dataset_key"], product_id, int(review_id))
            if key in seen_keys:
                skipped["duplicada_en_lote"] += 1
                continue
            seen_keys.add(key)

            # Esta fila ya paso los filtros minimos. Se arma con el formato de
            # reviews_clean.
            batch_to_insert.append(
                {
                    "dataset_key": row["dataset_key"],
                    "review_id": int(review_id),
                    "product_id": product_id,
                    "item_id": row.get("item_id"),
                    "rate": valid_rate(row.get("rate")),
                    "title": normalize(row.get("title")) or None,
                    "content": content_norm,
                    "content_length": len(content_norm),
                    "likes": safe_int(row.get("likes"), 0) or 0,
                    "dislikes": safe_int(row.get("dislikes"), 0) or 0,
                    "relevance": safe_float(row.get("relevance"), 0.0) or 0.0,
                    "forbidden_words": forbidden_value,
                    "has_media": has_media(row.get("media")),
                    "buying_date": row.get("buying_date"),
                    "date_created": row.get("date_created"),
                }
            )
            by_product[product_id]["clean"] += 1

        if batch_to_insert:
            # Upsert: si la resena ya existe en clean, se actualiza; si no,
            # se inserta. Esto permite correr el script nuevamente.
            inserted += upsert_rows(
                sb,
                "reviews_clean",
                batch_to_insert,
                on_conflict="dataset_key,product_id,review_id",
            )

        print(f"  reviews: {total_read} leidas, {inserted} validas...")

    deleted_stale = prune_stale_rows(
        sb,
        "reviews_clean",
        cfg.dataset_key,
        ("dataset_key", "product_id", "review_id"),
        seen_keys,
        cfg.page_size,
    )
    print(f"\nReviews: {total_read} leidas -> {inserted} limpias")
    if deleted_stale:
        print(f"  eliminadas por obsoletas: {deleted_stale}")
    for reason, count in skipped.most_common():
        print(f"  descartadas ({reason}): {count}")

    return {
        "total_read": total_read,
        "inserted": inserted,
        "deleted_stale": deleted_stale,
        "skipped": skipped,
        "by_product": by_product,
    }


def clean_items(sb: Any, cfg: RunConfig) -> dict[str, Any]:
    """Limpia items_raw y guarda el resultado en items_clean."""
    print("\nLimpiando items...")

    # Items representa publicaciones/precios. No analiza resenas.
    columns = (
        "id,dataset_key,product_id,item_id,price,original_price,condition,"
        "listing_type_id,seller_id,seller_address,official_store_id"
    )
    total_read = 0
    inserted = 0
    skipped = Counter()
    by_product = defaultdict(lambda: {"raw": 0, "clean": 0})
    seen_keys = set()

    for rows in fetch_pages(sb, "items_raw", columns, cfg.dataset_key, cfg.page_size):
        total_read += len(rows)
        batch_to_insert = []

        for row in rows:
            product_id = row.get("product_id")
            item_id = row.get("item_id")

            # Cuenta publicaciones raw por producto para el resumen final.
            if product_id:
                by_product[product_id]["raw"] += 1

            # Sin producto o sin item_id no se puede identificar la publicacion.
            if not product_id:
                skipped["sin_producto"] += 1
                continue
            if not item_id:
                skipped["sin_item_id"] += 1
                continue

            # El LAF 2 necesita precio para comparar publicaciones; por eso los
            # items sin precio o con precio invalido quedan fuera.
            price = parse_money(row.get("price"), None)
            if price is None:
                skipped["sin_precio"] += 1
                continue
            if price <= 0:
                skipped["precio_invalido"] += 1
                continue

            # Clave unica esperada para una publicacion.
            key = (row["dataset_key"], product_id, item_id)
            if key in seen_keys:
                skipped["duplicado_en_lote"] += 1
                continue
            seen_keys.add(key)

            original_price = parse_money(row.get("original_price"), None)
            if original_price is not None and original_price <= 0:
                original_price = None

            # Esta fila ya paso los filtros minimos. Se arma con el formato de
            # items_clean.
            batch_to_insert.append(
                {
                    "dataset_key": row["dataset_key"],
                    "product_id": product_id,
                    "item_id": item_id,
                    # PostgREST acepta el decimal como texto y PostgreSQL lo
                    # convierte a NUMERIC sin pasar por un float binario.
                    "price": money_for_storage(price),
                    "original_price": (
                        money_for_storage(original_price)
                        if original_price is not None
                        else None
                    ),
                    "condition": row.get("condition"),
                    "listing_type": row.get("listing_type_id"),
                    "seller_id": safe_int(row.get("seller_id"), None),
                    "official_store_id": safe_int(row.get("official_store_id"), None),
                    "seller_address": parse_seller_address(row.get("seller_address")),
                }
            )
            by_product[product_id]["clean"] += 1

        if batch_to_insert:
            # Igual que en reviews: evita duplicar si el script se corre mas de
            # una vez.
            inserted += upsert_rows(
                sb,
                "items_clean",
                batch_to_insert,
                on_conflict="dataset_key,product_id,item_id",
            )

        print(f"  items: {total_read} leidos, {inserted} validos...")

    deleted_stale = prune_stale_rows(
        sb,
        "items_clean",
        cfg.dataset_key,
        ("dataset_key", "product_id", "item_id"),
        seen_keys,
        cfg.page_size,
    )
    print(f"\nItems: {total_read} leidos -> {inserted} limpios")
    if deleted_stale:
        print(f"  eliminados por obsoletos: {deleted_stale}")
    for reason, count in skipped.most_common():
        print(f"  descartados ({reason}): {count}")

    return {
        "total_read": total_read,
        "inserted": inserted,
        "deleted_stale": deleted_stale,
        "skipped": skipped,
        "by_product": by_product,
    }


def print_product_summary(
    sb: Any,
    dataset_key: str,
    review_stats: dict[str, Any],
    item_stats: dict[str, Any],
    limit: int = 30,
) -> None:
    """Imprime una auditoria corta por producto.

    Ayuda a detectar rapido productos sin resenas limpias o sin publicaciones.
    """
    product_ids = sorted(
        set(review_stats["by_product"].keys()) | set(item_stats["by_product"].keys())
    )

    if not product_ids:
        print("\nNo se encontraron productos para el dataset elegido.")
        return

    raw_rows = (
        sb.table("products_raw")
        .select("product_id,name,family_name")
        .eq("dataset_key", dataset_key)
        .execute()
        .data
    )
    product_names = {
        row["product_id"]: (
            str(row.get("name") or row.get("family_name") or "").strip()
            or "[nombre no disponible]"
        )
        for row in raw_rows
    }

    review_status = {}
    review_schema_ready = True
    try:
        seed_rows = (
            sb.table("products_seed")
            .select("product_id,analysis_status")
            .eq("dataset_key", dataset_key)
            .execute()
            .data
        )
        review_status = {
            row["product_id"]: str(row.get("analysis_status") or "pending")
            for row in seed_rows
        }
    except Exception as exc:
        if is_missing_product_review_schema_error(exc):
            review_schema_ready = False
        else:
            raise RuntimeError(
                "No se pudo consultar products_seed para construir el resumen."
            ) from exc

    print("\nResumen por producto")
    print(
        "Cada fila muestra cuanto dato original habia y cuanto quedo usable "
        "despues de la limpieza."
    )
    print("- reviews raw/clean: resenas originales / resenas validas para NLP y trust.")
    print("- items raw/clean: publicaciones originales / publicaciones validas para LAF 2.")
    print(
        "Si clean es menor que raw, el script descarto registros vacios, muy cortos, "
        "duplicados o sin precio valido."
    )
    print(
        "Los productos con menos datos clean aparecen primero para facilitar la auditoria."
    )
    print()
    print(
        "estado     product_id       producto"
        "                                  reviews raw->clean   items raw->clean"
    )
    print("-" * 112)

    # Ordena primero los productos con menos datos clean, porque suelen ser los
    # que mas interesa revisar.
    def sort_key(pid: str) -> tuple[int, int, str]:
        review_clean = review_stats["by_product"].get(pid, {}).get("clean", 0)
        item_clean = item_stats["by_product"].get(pid, {}).get("clean", 0)
        return (review_clean, item_clean, pid)

    for pid in sorted(product_ids, key=sort_key)[:limit]:
        rv = review_stats["by_product"].get(pid, {"raw": 0, "clean": 0})
        it = item_stats["by_product"].get(pid, {"raw": 0, "clean": 0})
        status = review_status.get(pid, "pending") if review_schema_ready else "sin 1b"
        name = product_names.get(pid, "[nombre no disponible]")
        print(
            f"{status[:10]:10s} "
            f"{pid[:16]:16s} "
            f"{name[:40]:40s} "
            f"{rv['raw']:7d}->{rv['clean']:<7d} "
            f"{it['raw']:7d}->{it['clean']:<7d}"
        )

    if len(product_ids) > limit:
        print(f"... {len(product_ids) - limit} productos mas no mostrados")

    products_without_reviews = sum(
        1
        for pid in product_ids
        if review_stats["by_product"].get(pid, {}).get("clean", 0) == 0
    )
    products_without_items = sum(
        1
        for pid in product_ids
        if item_stats["by_product"].get(pid, {}).get("clean", 0) == 0
    )
    print("\nLectura rapida:")
    print(
        f"- Productos analizados: {len(product_ids)}. "
        f"Sin resenas limpias: {products_without_reviews}. "
        f"Sin publicaciones limpias: {products_without_items}."
    )
    print(
        "- Para LAF 1 importan las resenas clean: de ahi salen aspectos, polaridad "
        "y confianza."
    )
    print(
        "- Para LAF 2 importan los items clean: de ahi salen precios y publicaciones "
        "comprables."
    )
    if not review_schema_ready:
        print(
            "- Falta instalar la revision de productos. Ejecuta en Supabase SQL Editor: "
            "database/20260728_product_review.sql"
        )


def parse_args() -> argparse.Namespace:
    """Define los parametros que se pueden pasar por consola."""
    parser = argparse.ArgumentParser(
        description="Limpia reviews_raw/items_raw hacia reviews_clean/items_clean."
    )
    parser.add_argument(
        "--dataset-key",
        default=None,
        help="Dataset a procesar. Si se omite, usa DATASET_KEY del .env.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Filas por pagina al leer Supabase (default: {DEFAULT_PAGE_SIZE}).",
    )
    parser.add_argument(
        "--max-content-length",
        type=int,
        default=MAX_CONTENT_LENGTH,
        help=(
            "Maximo de caracteres conservados por resena despues de normalizar "
            f"(default: {MAX_CONTENT_LENGTH})."
        ),
    )
    parser.add_argument(
        "--reset-clean",
        action="store_true",
        help=(
            "Compatibilidad: fuerza una sincronizacion completa. Ya no borra "
            "las tablas antes de escribir porque la poda segura se ejecuta siempre."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Punto de entrada del script."""
    args = parse_args()

    # Carga SUPABASE_URL, SUPABASE_KEY y DATASET_KEY desde el .env del proyecto.
    load_dotenv(REPO_ROOT / ".env")

    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_KEY"]
    dataset_key = args.dataset_key or os.environ.get("DATASET_KEY")

    if not dataset_key:
        print(
            "ERROR: defini DATASET_KEY en .env o pasalo con --dataset-key.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.page_size <= 0:
        print("ERROR: --page-size debe ser mayor que 0.", file=sys.stderr)
        sys.exit(1)
    if args.max_content_length < MIN_CONTENT_LENGTH:
        print(
            "ERROR: --max-content-length debe ser al menos "
            f"{MIN_CONTENT_LENGTH}.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Agrupa la configuracion para pasarla a clean_reviews y clean_items.
    cfg = RunConfig(
        dataset_key=dataset_key,
        page_size=args.page_size,
        max_content_length=args.max_content_length,
        reset_clean=args.reset_clean,
    )
    sb = create_client(supabase_url, supabase_key)

    print(f"Dataset: {cfg.dataset_key}")
    if cfg.reset_clean:
        print(
            "Sincronizacion completa solicitada. Se conservara la capa CLEAN "
            "anterior hasta terminar los upserts y luego se podaran obsoletos."
        )

    review_stats = clean_reviews(sb, cfg)
    item_stats = clean_items(sb, cfg)
    print_product_summary(sb, cfg.dataset_key, review_stats, item_stats)

    # El script 2 usa reviews_clean. Por eso se sugiere como siguiente paso.
    print("\nOK.")
    print("Siguiente paso:")
    print("- Revisar y aprobar los productos del corpus:")
    print(r"  .\venv\Scripts\python.exe src\01b_product_review.py")
    print("- Si el dominio NO tiene perfil final:")
    print(r"  .\venv\Scripts\python.exe src\02_domain_discovery.py")
    print(r"  .\venv\Scripts\python.exe src\03_llm_suggestions.py  # opcional")
    print(r"  .\venv\Scripts\streamlit.exe run src\04_domain_review.py")
    print("- Si el perfil del dominio YA existe:")
    print(r"  .\venv\Scripts\python.exe src\05_aspects.py")


if __name__ == "__main__":
    try:
        main()
    except KeyError as exc:
        print(f"ERROR: falta variable de entorno {exc}.", file=sys.stderr)
        sys.exit(1)
