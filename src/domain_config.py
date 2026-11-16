"""
domain_config.py - Carga la configuracion del dominio activo.

El pipeline es generico, pero cada dominio define sus aspectos, textos de UI,
lexicon y mapeos de atributos de catalogo.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOMAIN_SLUG = "celulares"
DATASETS_TABLE = "datasets"
ARTIFACTS_DIR = REPO_ROOT / "artifacts_por_dominio"
SHARED_LAF2_RULES_PATH = REPO_ROOT / "config" / "laf2_rule_structure.json"


def _config_path(domain_key: str) -> Path:
    custom_path = os.environ.get("DOMAIN_CONFIG_PATH")
    if custom_path:
        return Path(custom_path).expanduser().resolve()
    return REPO_ROOT / "config" / "domains" / f"{domain_key}.json"


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _resolve_relative(path_value: str, base_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _normalize_options(raw: dict[str, Any]) -> dict[str, dict[str, str]]:
    options = {}
    for key, value in raw.items():
        if isinstance(value, str):
            options[key] = {"label": value, "icon": ""}
        else:
            options[key] = {
                "label": value.get("label", key),
                "icon": value.get("icon", ""),
            }
    return options


def _slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")


def domain_key_from_category_label(category_label: str) -> str:
    aliases = {
        "cafe_instantaneo": "cafe",
        "cafe_instantaneo_c": "cafe",
        "cafe_en_granos_y_molido": "cafe",
        "celular": "celulares",
        "celulares": "celulares",
        "telefonos_celulares": "celulares",
        "smartphones": "celulares",
    }
    slug = _slugify(category_label)
    return aliases.get(slug, slug)


def _category_label_from_dataset(dataset_key: str) -> str | None:
    try:
        from supabase import create_client

        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            return None
        sb = create_client(url, key)
        rows = (
            sb.table(DATASETS_TABLE)
            .select("category_label")
            .eq("dataset_key", dataset_key)
            .limit(1)
            .execute()
            .data
        )
        if rows:
            return rows[0].get("category_label")
    except Exception:
        return None
    return None


def resolve_domain_key() -> str:
    """Resuelve el dominio activo desde la categoria del dataset."""
    if os.environ.get("DOMAIN_CONFIG_PATH"):
        return DEFAULT_DOMAIN_SLUG

    dataset_key = os.environ.get("DATASET_KEY")
    if not dataset_key:
        raise RuntimeError(
            "Falta DATASET_KEY. No se puede inferir el dominio sin un dataset activo."
        )

    category_label = _category_label_from_dataset(dataset_key)
    if category_label:
        return domain_key_from_category_label(category_label)

    raise RuntimeError(
        f"No se encontro category_label para DATASET_KEY={dataset_key!r} "
        f"en la tabla {DATASETS_TABLE}."
    )


def load_domain_config_for_key(domain_key: str) -> dict[str, Any]:
    """Carga un dominio explicito sin consultar el dataset activo.

    Esta variante se usa en la preparacion offline de una categoria, donde
    todavia no existe un recorrido de usuario ni es necesario consultar
    Supabase para inferir el dominio.
    """
    if not re.fullmatch(r"[a-z0-9_]+", domain_key):
        raise ValueError(f"Clave de dominio invalida: {domain_key!r}")
    path = _config_path(domain_key)
    if not path.exists():
        raise FileNotFoundError(
            f"No existe la configuracion de dominio: {path}. "
            f"Crea config/domains/{domain_key}.json o define DOMAIN_CONFIG_PATH."
        )

    config = _load_json(path)
    config.setdefault("domain_key", domain_key)
    config.setdefault("display_name", config["domain_key"])

    if "lexicon" not in config:
        lexicon_path = config.get("lexicon_path")
        if not lexicon_path:
            raise KeyError("El dominio debe definir 'lexicon' o 'lexicon_path'.")
        config["lexicon"] = _load_json(_resolve_relative(lexicon_path, path.parent))

    lexicon = config["lexicon"]
    for required_key in ("aspects", "positive", "negative", "negation"):
        if required_key not in lexicon:
            raise KeyError(f"Falta '{required_key}' en el lexicon del dominio.")

    if "quality_aspects" not in config:
        config["quality_aspects"] = {
            key: {"label": key.replace("_", " ").title(), "icon": ""}
            for key in lexicon["aspects"]
        }
    config["quality_aspects"] = _normalize_options(config["quality_aspects"])

    config["purchase_aspects"] = _normalize_options(config.get("purchase_aspects", {}))
    config.setdefault("catalog_aspect_map", {})
    config.setdefault("ui", {})
    config.setdefault("laf", {})

    # Las condiciones de compra son transversales a las categorias actuales.
    # Un dominio puede sobreescribirlas de forma explicita si en el futuro lo
    # necesita, pero no se duplican cuatro copias identicas por defecto.
    if "laf2_rule_structure" not in config:
        if not SHARED_LAF2_RULES_PATH.exists():
            raise FileNotFoundError(
                f"No existe la estructura compartida de LAF 2: {SHARED_LAF2_RULES_PATH}"
            )
        config["laf2_rule_structure"] = deepcopy(_load_json(SHARED_LAF2_RULES_PATH))

    return config


def load_domain_config() -> dict[str, Any]:
    return load_domain_config_for_key(resolve_domain_key())


def domain_artifact_dir(
    config_or_domain: dict[str, Any] | str | None = None,
    section: str | None = None,
) -> Path:
    """Devuelve/crea la carpeta de artifacts del dominio activo.

    Las salidas generadas no se guardan en la raiz del proyecto: quedan
    agrupadas por dominio para evitar mezclar programas, preferencias y reportes.
    """
    if isinstance(config_or_domain, dict):
        domain_key = config_or_domain.get("domain_key", DEFAULT_DOMAIN_SLUG)
    elif isinstance(config_or_domain, str) and config_or_domain:
        domain_key = config_or_domain
    else:
        domain_key = load_domain_config().get("domain_key", DEFAULT_DOMAIN_SLUG)

    base = ARTIFACTS_DIR / domain_key
    path = base / section if section else base
    path.mkdir(parents=True, exist_ok=True)
    return path


def artifact_section(stem: str) -> str:
    if stem.startswith("programa_laf"):
        return "programas_laf"
    if stem.startswith("prefs_laf"):
        return "preferencias"
    if stem.startswith(("domain_discovery", "llm_suggestions", "laf_rule_review")):
        return "reportes"
    return "otros"


def artifact_path(stem: str, suffix: str, config: dict[str, Any] | None = None) -> Path:
    """Devuelve una ruta de salida ordenada por dominio."""
    cfg = config or load_domain_config()
    section = artifact_section(stem)
    return domain_artifact_dir(cfg, section) / f"{stem}{suffix}"
