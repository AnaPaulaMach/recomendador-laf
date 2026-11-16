"""
product_scope.py - Alcance analitico de productos revisado por una persona.

La extraccion conserva todos los productos del ranking original. Antes del
descubrimiento del dominio y del razonamiento, una persona debe marcar cada
producto como incluido o excluido mediante 01b_product_review.py.
"""

from __future__ import annotations

from typing import Any


MIGRATION_PATH = "database/20260728_product_review.sql"
VALID_STATUSES = {"pending", "included", "excluded"}


class ProductReviewSetupError(RuntimeError):
    """La base todavia no tiene el esquema de revision de productos."""


class ProductReviewPendingError(RuntimeError):
    """Hay productos sin una decision humana persistida."""


def load_product_review_rows(sb: Any, dataset_key: str) -> list[dict[str, Any]]:
    """Carga el estado vigente de los productos del dataset."""
    try:
        rows = (
            sb.table("products_seed")
            .select(
                "product_id,position,analysis_status,"
                "analysis_reason,analysis_reviewed_at"
            )
            .eq("dataset_key", dataset_key)
            .order("position")
            .execute()
            .data
        )
    except Exception as exc:
        detail = str(exc)
        if "analysis_status" in detail or "analysis_reason" in detail:
            raise ProductReviewSetupError(
                "Falta instalar la migracion de revision de productos. "
                f"Ejecuta {MIGRATION_PATH} en Supabase SQL Editor."
            ) from exc
        raise

    for row in rows:
        status = str(row.get("analysis_status") or "pending").strip().lower()
        row["analysis_status"] = status if status in VALID_STATUSES else "pending"
    return rows


def require_included_product_ids(
    sb: Any,
    dataset_key: str | None,
    *,
    stage_name: str,
) -> set[str]:
    """Devuelve productos incluidos y bloquea si quedan decisiones pendientes."""
    if not dataset_key:
        raise ProductReviewPendingError(
            f"{stage_name}: falta DATASET_KEY; no se puede aplicar el alcance analitico."
        )

    rows = load_product_review_rows(sb, dataset_key)
    if not rows:
        raise ProductReviewPendingError(
            f"{stage_name}: products_seed no contiene productos para "
            f"DATASET_KEY={dataset_key!r}."
        )

    pending = [
        row["product_id"]
        for row in rows
        if row["analysis_status"] == "pending"
    ]
    if pending:
        preview = ", ".join(pending[:5])
        suffix = "" if len(pending) <= 5 else f" y {len(pending) - 5} mas"
        raise ProductReviewPendingError(
            f"{stage_name}: hay {len(pending)} productos pendientes de revision "
            f"({preview}{suffix}). Ejecuta primero: "
            r".\venv\Scripts\python.exe src\01b_product_review.py"
        )

    included = {
        row["product_id"]
        for row in rows
        if row["analysis_status"] == "included"
    }
    if not included:
        raise ProductReviewPendingError(
            f"{stage_name}: no hay productos incluidos para el analisis."
        )
    return included


def scope_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Cuenta estados para interfaces y mensajes de auditoria."""
    summary = {"pending": 0, "included": 0, "excluded": 0}
    for row in rows:
        status = row.get("analysis_status") or "pending"
        if status in summary:
            summary[status] += 1
    return summary
