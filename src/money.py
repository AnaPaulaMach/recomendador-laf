"""Utilidades para manipular importes sin introducir errores binarios."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


MONEY_QUANTUM = Decimal("0.01")


def parse_money(value: Any, default: Decimal | None = None) -> Decimal | None:
    """Convierte un importe a dos decimales usando su representacion textual.

    ``Decimal(str(value))`` evita incorporar al resultado los artefactos
    binarios de un ``float`` recibido desde un cliente JSON. Los valores no
    numericos, NaN e infinitos se consideran invalidos.
    """
    if value is None or value == "":
        return default
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default
    if not amount.is_finite():
        return default
    return amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def money_for_storage(value: Decimal) -> str:
    """Devuelve un decimal exacto apto para JSON/PostgREST."""
    return format(value, ".2f")
