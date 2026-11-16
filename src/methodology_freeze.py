"""Validacion compartida de la configuracion congelada por el paso 06d."""
from __future__ import annotations

import hashlib
import json

from domain_config import domain_artifact_dir


def canonical_methodology_hash(config):
    payload = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_freeze_manifest(config, manifest):
    expected_domain = config.get("domain_key")
    if manifest.get("domain_key") != expected_domain:
        raise RuntimeError(
            "El manifiesto congelado pertenece a otro dominio: "
            f"{manifest.get('domain_key')!r} != {expected_domain!r}."
        )
    current_hash = canonical_methodology_hash(config)
    frozen_hash = manifest.get("methodology_sha256")
    if frozen_hash != current_hash:
        raise RuntimeError(
            "La configuracion de la categoria cambio despues de 06d. "
            "Ejecuta 06a, revisa/compila si corresponde y vuelve a congelar "
            "con 06d antes de generar un programa LAF."
        )
    return current_hash


def load_and_validate_freeze(config):
    path = domain_artifact_dir(config, "reportes") / "category_freeze.json"
    if not path.exists():
        raise RuntimeError(
            f"No existe el manifiesto de categoria congelada: {path}. "
            "Ejecuta primero 06d --freeze."
        )
    with open(path, encoding="utf-8") as stream:
        manifest = json.load(stream)
    return manifest, validate_freeze_manifest(config, manifest)
