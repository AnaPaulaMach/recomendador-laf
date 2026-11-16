"""06d - Valida y, opcionalmente, congela la metodologia de una categoria.

La validacion es offline: no consulta usuarios ni Supabase. El manifiesto de
congelacion registra una huella de la configuracion que luego consumen 07-10.

Uso:
    python src/06d_validate_and_freeze.py --domain cafe
    python src/06d_validate_and_freeze.py --domain cafe --freeze
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain_config import domain_artifact_dir, load_domain_config_for_key


def _in_unit_interval(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return 0.0 <= number <= 1.0


def _is_neutral_beta(value: Any) -> bool:
    try:
        return float(value) == 1.0
    except (TypeError, ValueError):
        return False


def validate_category(config: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    pending: list[str] = []

    quality = set(config.get("quality_aspects", {}))
    purchase = set(config.get("purchase_aspects", {}))
    lexicon_aspects = set(config.get("lexicon", {}).get("aspects", {}))
    if not quality:
        errors.append("No hay aspectos de calidad.")
    if not purchase:
        errors.append("No hay condiciones de compra.")
    missing_lexicon = sorted(quality - lexicon_aspects)
    if missing_lexicon:
        errors.append(f"Aspectos de calidad sin entrada de lexicon: {missing_lexicon}")

    laf1 = config.get("laf1_rule_structure") or {}
    dimensions = laf1.get("dimensions", {}) if laf1.get("mode") == "hierarchical" else {}
    if not dimensions:
        errors.append("LAF 1 no tiene una estructura jerarquica experta para congelar.")
    else:
        if laf1.get("beta_semantics") != "user_only_structural_neutral":
            errors.append(
                "LAF 1 debe declarar beta_semantics=user_only_structural_neutral."
            )
        assigned: set[str] = set()
        for dimension_key, dimension in dimensions.items():
            for raw_rule in dimension.get("aspects", []):
                rule = {"aspect": raw_rule} if isinstance(raw_rule, str) else dict(raw_rule or {})
                aspect = rule.get("aspect")
                if not aspect:
                    errors.append(f"Dimension {dimension_key}: regla sin aspecto.")
                    continue
                assigned.add(aspect)
                if aspect not in quality:
                    errors.append(f"Dimension {dimension_key}: aspecto desconocido {aspect!r}.")
                for field in ("confidence", "negative_confidence"):
                    if field in rule and not _in_unit_interval(rule[field]):
                        errors.append(
                            f"Dimension {dimension_key}, aspecto {aspect}: {field} fuera de [0,1]."
                        )
                for field in ("preference", "negative_preference"):
                    if field in rule and not _is_neutral_beta(rule[field]):
                        errors.append(
                            f"Dimension {dimension_key}, aspecto {aspect}: {field} debe ser 1.0."
                        )
            for branch in ("recommend", "not_recommend"):
                rule = dimension.get(branch) or {}
                if "confidence" in rule and not _in_unit_interval(rule["confidence"]):
                    errors.append(
                        f"Dimension {dimension_key}, {branch}: confidence fuera de [0,1]."
                    )
                if "preference" in rule and not _is_neutral_beta(rule["preference"]):
                    errors.append(
                        f"Dimension {dimension_key}, {branch}: preference debe ser 1.0."
                    )
        unassigned = sorted(quality - assigned)
        if unassigned and laf1.get("unassigned_aspect_policy") != "direct":
            errors.append(f"Aspectos de calidad sin dimension: {unassigned}")
        elif unassigned:
            warnings.append(f"Aspectos con recomendacion directa, sin dimension: {unassigned}")

    laf2 = config.get("laf2_rule_structure") or {}
    conditions = laf2.get("conditions", {})
    condition_keys = set(conditions)
    missing_conditions = sorted(purchase - condition_keys)
    extra_conditions = sorted(condition_keys - purchase)
    if missing_conditions:
        errors.append(f"Condiciones de compra sin regla LAF 2: {missing_conditions}")
    if extra_conditions:
        warnings.append(f"Reglas LAF 2 no usadas por esta categoria: {extra_conditions}")
    for key in sorted(purchase & condition_keys):
        condition = conditions[key]
        status = condition.get("status")
        if status == "pending":
            pending.append(f"LAF 2/{key}: {condition.get('reason', 'implementacion pendiente')}")
        elif status != "implemented":
            errors.append(f"LAF 2/{key}: estado invalido {status!r}.")
        if not condition.get("fact_predicate"):
            errors.append(f"LAF 2/{key}: falta fact_predicate.")
        if not _in_unit_interval(condition.get("rule_confidence")):
            errors.append(f"LAF 2/{key}: rule_confidence fuera de [0,1].")

    recommendation = laf2.get("recommendation", {})
    for key in recommendation.get("preference_keys", []):
        if key not in purchase:
            errors.append(f"LAF 2/recommendation: preference_key desconocida {key!r}.")
    if not _in_unit_interval(recommendation.get("confidence")):
        errors.append("LAF 2/recommendation: confidence fuera de [0,1].")

    program_dir = domain_artifact_dir(config, "programas_laf")
    for filename in ("programa_laf1_auditoria_D.txt", "programa_laf2_auditoria.txt"):
        if not (program_dir / filename).exists():
            errors.append(f"Falta el programa de auditoria {filename}; ejecuta 06a.")

    return errors, warnings, pending


def _canonical_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, help="Clave en config/domains")
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="Escribe el manifiesto solo si no hay errores ni pendientes.",
    )
    args = parser.parse_args()

    config = load_domain_config_for_key(args.domain)
    errors, warnings, pending = validate_category(config)

    for message in errors:
        print(f"ERROR: {message}")
    for message in warnings:
        print(f"AVISO: {message}")
    for message in pending:
        print(f"PENDIENTE: {message}")

    if errors:
        print(f"NO VALIDADA: {len(errors)} error(es).")
        return 1
    print("VALIDACION ESTRUCTURAL OK.")

    if args.freeze:
        if pending:
            print("NO CONGELADA: hay condiciones metodologicas pendientes.")
            return 2
        manifest = {
            "domain_key": config["domain_key"],
            "display_name": config["display_name"],
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "methodology_sha256": _canonical_hash(config),
            "laf2_scope": config["laf2_rule_structure"].get("scope"),
            "warnings": warnings,
        }
        path = domain_artifact_dir(config, "reportes") / "category_freeze.json"
        _write_atomic(path, manifest)
        print(f"CATEGORIA CONGELADA: {path}")
    elif pending:
        print("La estructura puede revisarse, pero no congelarse mientras haya pendientes.")
    else:
        print("Lista para congelar con --freeze.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
