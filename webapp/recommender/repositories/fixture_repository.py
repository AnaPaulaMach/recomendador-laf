"""Fuente de datos de demostracion: lee los fixtures JSON de ``webapp/fixtures``."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


class FixtureRepository:
    """Fuente reproducible para demostración y pruebas."""

    def __init__(self, fixture_dir: Path):
        self.fixture_dir = Path(fixture_dir)

    def load(self, domain_key: str) -> dict[str, Any]:
        safe_key = "".join(char for char in domain_key if char.isalnum() or char == "_")
        path = self.fixture_dir / f"{safe_key}.json"
        if not safe_key or safe_key != domain_key or not path.is_file():
            path = self.fixture_dir / "default.json"
        return deepcopy(json.loads(path.read_text(encoding="utf-8")))

    def datasets(self, domain_key: str) -> tuple[dict[str, str], ...]:
        data = self.load(domain_key)
        return tuple(
            {
                "key": str(item.get("key") or "dataset_demo"),
                "label": str(item.get("label") or "Dataset de demostración"),
                "description": str(item.get("description") or ""),
            }
            for item in data.get("datasets", [])
        )

    def demonstration_dataset_keys(self, domain_key: str) -> frozenset[str]:
        """Incluye la clave del fixture y los snapshots reales que lo originaron."""
        keys: set[str] = set()
        for item in self.load(domain_key).get("datasets", []):
            key = str(item.get("key") or "").strip()
            if key:
                keys.add(key)
            keys.update(
                str(source_key).strip()
                for source_key in (item.get("source_dataset_keys") or [])
                if str(source_key).strip()
            )
        return frozenset(keys)

    def fixture_dataset_keys(self, domain_key: str) -> frozenset[str]:
        """Claves sintéticas que pueden mostrar rankings de demostración.

        ``source_dataset_keys`` conserva procedencia académica, pero no vuelve
        ficticio a un snapshot real ni autoriza a sustituir sus productos.
        """
        return frozenset(
            str(item.get("key") or "").strip()
            for item in self.load(domain_key).get("datasets", [])
            if str(item.get("key") or "").strip()
        )
