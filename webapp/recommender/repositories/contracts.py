"""Contratos mínimos que los servicios necesitan de una fuente de datos."""
from __future__ import annotations

from typing import Any, Protocol


class LAF1SourceRepository(Protocol):
    """Fuente capaz de preparar la entrada del generador LAF 1."""

    def laf1_generation_data(
        self,
        dataset_key: str,
        strategy: str = "D",
        *,
        top_n: int = 20,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]: ...


class LAF2SourceRepository(Protocol):
    """Fuente capaz de preparar publicaciones y condiciones para LAF 2."""

    def laf2_generation_items(
        self,
        dataset_key: str,
        product_id: str,
        *,
        budget_min: float | None = None,
        budget_max: float | None = None,
        top_n: int = 20,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]: ...

    def laf2_dataset_items(
        self,
        dataset_key: str,
        *,
        top_n: int = 20,
    ) -> list[dict[str, Any]]: ...
