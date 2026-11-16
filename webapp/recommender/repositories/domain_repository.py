"""Acceso seguro y dinámico a config/domains/<dominio>.json."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class AspectConfig:
    key: str
    label: str
    icon: str = ""


@dataclass(frozen=True)
class DomainConfig:
    key: str
    display_name: str
    product_label: str
    item_label: str
    quality_aspects: tuple[AspectConfig, ...]
    purchase_aspects: tuple[AspectConfig, ...]
    dataset_category_labels: tuple[str, ...]
    ui: dict[str, str]


class DomainConfigRepository:
    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)

    def list_domains(self) -> tuple[DomainConfig, ...]:
        domains: list[DomainConfig] = []
        if not self.config_dir.exists():
            return ()
        for path in sorted(self.config_dir.glob("*.json")):
            if ".draft." in path.name or ".curation_rules." in path.name:
                continue
            try:
                domains.append(self._read(path))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
        return tuple(domains)

    def get(self, domain_key: str) -> DomainConfig:
        safe_key = "".join(char for char in domain_key if char.isalnum() or char == "_")
        if not safe_key or safe_key != domain_key:
            raise ValueError("Clave de dominio no válida.")
        path = self.config_dir / f"{safe_key}.json"
        if not path.is_file():
            raise ValueError(f"No existe la configuración del dominio «{domain_key}».")
        return self._read(path)

    def _read(self, path: Path) -> DomainConfig:
        data = json.loads(path.read_text(encoding="utf-8"))
        key = str(data.get("domain_key") or path.stem)
        quality = self._aspects(data.get("quality_aspects") or {})
        purchase = self._aspects(data.get("purchase_aspects") or {})
        if not quality:
            raise ValueError(f"El dominio {key} no define aspectos de calidad.")
        return DomainConfig(
            key=key,
            display_name=self._display_text(
                str(data.get("display_name") or key.replace("_", " ").title())
            ),
            product_label=str(data.get("product_label") or "producto"),
            item_label=str(data.get("item_label") or "publicación"),
            quality_aspects=quality,
            purchase_aspects=purchase,
            dataset_category_labels=tuple(
                str(value)
                for value in (
                    data.get("dataset_category_labels")
                    or [data.get("display_name") or key]
                )
                if str(value).strip()
            ),
            ui={
                str(k): self._display_text(str(v))
                for k, v in (data.get("ui") or {}).items()
                if v is not None
            },
        )

    @classmethod
    def _aspects(cls, raw: dict[str, Any]) -> tuple[AspectConfig, ...]:
        result: list[AspectConfig] = []
        for key, value in raw.items():
            if isinstance(value, dict):
                label = value.get("label") or key
                icon = value.get("icon") or ""
            else:
                label = value or key
                icon = ""
            result.append(
                AspectConfig(
                    key=str(key),
                    label=cls._display_text(str(label)),
                    icon=str(icon),
                )
            )
        return tuple(result)

    @staticmethod
    def _display_text(value: str) -> str:
        """Corrige tildes omitidas por perfiles históricos sin alterar sus claves."""
        replacements = {
            "Cafe": "Café",
            "cafe": "café",
            "Que": "Qué",
            "Como": "Cómo",
            "buscas": "buscás",
            "queres": "querés",
            "Presentacion": "Presentación",
            "presentacion": "presentación",
            "Preparacion": "Preparación",
            "preparacion": "preparación",
            "disolucion": "disolución",
            "Tamano": "Tamaño",
            "tamano": "tamaño",
            "Financiacion": "Financiación",
            "financiacion": "financiación",
            "interes": "interés",
            "Garantia": "Garantía",
            "garantia": "garantía",
            "Envio": "Envío",
            "envio": "envío",
            "rapido": "rápido",
            "resenas": "reseñas",
            "segun": "según",
            "publicacion": "publicación",
        }
        normalized = value
        for source, target in replacements.items():
            normalized = re.sub(rf"\b{source}\b", target, normalized)
        normalized = normalized.replace("que tan", "qué tan")
        if normalized.endswith("?") and not normalized.startswith("¿"):
            normalized = f"¿{normalized}"
        return normalized
