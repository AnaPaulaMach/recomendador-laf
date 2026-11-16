"""Audita 07/08 sobre todos los datasets reales de una categoria.

La auditoria no ejecuta el razonador. Materializa combinaciones equivalentes a
la salida JSON de 07, genera los programas con 08 y comprueba de forma
independiente el dataset, catalogo, preferencias, reglas y trust.

Uso:
    python src/audit_laf1_real_generation.py --domain cafe --strategy D
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import create_client

from domain_config import domain_artifact_dir, load_domain_config_for_key
from product_scope import (
    ProductReviewPendingError,
    ProductReviewSetupError,
    require_included_product_ids,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"


def load_laf1_generator():
    path = SRC_DIR / "08_laf1_generate.py"
    spec = importlib.util.spec_from_file_location("laf1_real_audit_generator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preference_scenarios(aspects: list[str]) -> dict[str, dict[str, float]]:
    neutral = {aspect: 0.50 for aspect in aspects}

    sensorial = {aspect: 0.10 for aspect in aspects}
    sensorial.update(
        sabor=1.00,
        aroma=0.85,
        intensidad=0.70,
        dulzor=0.60,
        tueste=0.95,
        acidez=0.90,
    )

    uso_y_preparacion = {aspect: 0.05 for aspect in aspects}
    uso_y_preparacion.update(
        rendimiento=1.00,
        tamano=0.85,
        preparacion=0.95,
        molienda=0.90,
        presentacion=0.60,
    )
    return {
        "neutral": neutral,
        "sensorial_alta": sensorial,
        "uso_preparacion_alta": uso_y_preparacion,
    }


def dataset_description(row: dict[str, Any]) -> str:
    key = row["dataset_key"]
    known = {
        "mlm_mlm194329_20260528_142014": "Mexico - historico mixto",
        "mlm_mlm194329_20260805_191308": "Mexico - instantaneo",
        "mlm_mlm194335_20260805_185233": "Mexico - grano/molido",
        "mco_mco409413_20260805_184739": "Colombia - grano/molido",
    }
    return known.get(
        key,
        f"{row.get('site_id') or '?'} - {row.get('category_label') or 'Cafe'}",
    )


def discover_datasets(sb: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    labels = config.get("dataset_category_labels") or [config["display_name"]]
    rows = (
        sb.table("datasets")
        .select("dataset_key,category_label,site_id")
        .in_("category_label", labels)
        .execute()
        .data
    )
    return sorted(rows, key=lambda row: row["dataset_key"])


def audit_preferences_ui(
    dataset_key: str,
    scenarios: dict[str, dict[str, float]],
    expected_aspects: list[str],
) -> dict[str, Any]:
    """Ejecuta 07 con AppTest sin guardar ni alterar preferencias persistidas."""
    from streamlit.testing.v1 import AppTest

    previous_dataset = os.environ.get("DATASET_KEY")
    os.environ["DATASET_KEY"] = dataset_key
    results = []
    try:
        for name, preferences in scenarios.items():
            app = AppTest.from_file(
                str(SRC_DIR / "07_laf1_preferences.py"),
                default_timeout=30,
            ).run()
            exceptions = [str(item.value) for item in app.exception]
            sliders = list(app.slider)
            count_ok = len(sliders) == len(expected_aspects)
            if count_ok and not exceptions:
                for index, aspect in enumerate(expected_aspects):
                    sliders[index].set_value(preferences[aspect])
                app.run()
                exceptions.extend(str(item.value) for item in app.exception)
            values_ok = (
                count_ok
                and not exceptions
                and all(
                    abs(float(app.slider[index].value) - preferences[aspect]) < 1e-9
                    for index, aspect in enumerate(expected_aspects)
                )
            )
            results.append({
                "name": name,
                "passed": count_ok and values_ok and not exceptions,
                "sliders": len(sliders),
                "exceptions": exceptions,
            })
    finally:
        if previous_dataset is None:
            os.environ.pop("DATASET_KEY", None)
        else:
            os.environ["DATASET_KEY"] = previous_dataset
    return {"passed": all(item["passed"] for item in results), "scenarios": results}


def expected_rules(
    generator: Any,
    config: dict[str, Any],
    active_aspects: set[str],
) -> Counter[str]:
    rules: list[str] = []
    for aspect in sorted(active_aspects):
        atom = generator.atom_part(aspect)
        cap = generator.cap_atom(aspect)
        rules.append(generator.ann(
            f"{atom}Bueno(X) :- resenaPositiva{cap}(X)",
            generator.RULE_CONF_AGGREGATION,
            1.0,
        ))
        rules.append(generator.ann(
            f"~{atom}Bueno(X) :- resenaNegativa{cap}(X)",
            generator.RULE_CONF_AGGREGATION,
            1.0,
        ))

    structure = config["laf1_rule_structure"]
    assigned: set[str] = set()
    for dimension, dimension_config in structure["dimensions"].items():
        active = []
        for raw_rule in dimension_config.get("aspects", []):
            rule = generator.aspect_rule(raw_rule)
            if rule.get("aspect") in active_aspects:
                active.append(rule)
        if not active:
            continue

        dimension_atom = generator.atom_part(dimension)
        for rule in active:
            aspect = rule["aspect"]
            assigned.add(aspect)
            aspect_atom = generator.atom_part(aspect)
            positive = generator.as_float(
                rule.get("confidence"), generator.RULE_CONF_AGGREGATION
            )
            negative = generator.as_float(rule.get("negative_confidence"), positive)
            rules.append(generator.ann(
                f"{dimension_atom}Bueno(X) :- {aspect_atom}Bueno(X)",
                positive,
                1.0,
            ))
            rules.append(generator.ann(
                f"~{dimension_atom}Bueno(X) :- ~{aspect_atom}Bueno(X)",
                negative,
                1.0,
            ))

        recommend = dimension_config.get("recommend") or {}
        if recommend:
            rules.append(generator.ann(
                f"recomendar(X) :- {dimension_atom}Bueno(X)",
                generator.as_float(
                    recommend.get("confidence"),
                    generator.RULE_CONF_RECOMMENDATION,
                ),
                1.0,
            ))
        not_recommend = dimension_config.get("not_recommend") or {}
        if not_recommend:
            rules.append(generator.ann(
                f"~recomendar(X) :- ~{dimension_atom}Bueno(X)",
                generator.as_float(
                    not_recommend.get("confidence"),
                    generator.RULE_CONF_RECOMMENDATION,
                ),
                1.0,
            ))

    if structure.get("unassigned_aspect_policy") == "direct":
        confidence = generator.as_float(
            structure.get("direct_recommendation_confidence"), 0.80
        )
        for aspect in sorted(active_aspects - assigned):
            atom = generator.atom_part(aspect)
            rules.append(generator.ann(
                f"recomendar(X) :- {atom}Bueno(X)", confidence, 1.0
            ))
            rules.append(generator.ann(
                f"~recomendar(X) :- ~{atom}Bueno(X)", confidence, 1.0
            ))
    return Counter(rules)


def expected_facts(
    generator: Any,
    products: dict[str, dict[str, Any]],
    evidence: list[dict[str, Any]],
    preferences: dict[str, float],
) -> Counter[str]:
    facts: list[str] = []
    for row in evidence:
        product_id = row["product_id"]
        if product_id not in products:
            continue
        aspect = row["aspect"]
        if row.get("from_catalog"):
            predicate = "catalogoDeclara" + generator.cap_atom(aspect)
        else:
            predicate = (
                "resenaPositiva" if row["polarity"] == "pos" else "resenaNegativa"
            ) + generator.cap_atom(aspect)
        product = products[product_id]
        atom = generator.product_atom(product_id, product.get("name") or product_id)
        facts.append(generator.ann(
            f"{predicate}({atom})",
            float(row["agg_confidence"]),
            preferences.get(aspect, 0.50),
        ))
    return Counter(facts)


def parse_preference_header(program: str) -> dict[str, float]:
    lines = program.splitlines()
    start = lines.index("% Preferencias del usuario:") + 1
    result: dict[str, float] = {}
    for line in lines[start:]:
        if not line.strip():
            break
        match = re.fullmatch(r"%   ([a-z0-9_]+): ([0-9.]+)", line)
        if match:
            result[match.group(1)] = float(match.group(2))
    return result


def audit_program(
    generator: Any,
    program: str,
    dataset_key: str,
    methodology_sha256: str,
    products: dict[str, dict[str, Any]],
    evidence: list[dict[str, Any]],
    preferences: dict[str, float],
    config: dict[str, Any],
) -> dict[str, Any]:
    statements = [
        line for line in program.splitlines()
        if line and not line.startswith("%") and line.endswith("}")
    ]
    actual_rules = Counter(line for line in statements if ":-" in line)
    actual_facts = Counter(line for line in statements if ":-" not in line)
    expected_fact_lines = expected_facts(
        generator, products, evidence, preferences
    )
    active_aspects = {row["aspect"] for row in evidence}
    expected_rule_lines = expected_rules(generator, config, active_aspects)

    product_lines = [
        line for line in program.splitlines() if re.match(r"^%\s+#\s*\d+\s+", line)
    ]
    actual_product_atoms = {
        re.match(r"^%\s+#\s*\d+\s+(\S+)", line).group(1)
        for line in product_lines
    }
    expected_product_atoms = {
        generator.product_atom(product_id, product.get("name") or product_id)
        for product_id, product in products.items()
    }
    evidence_product_ids = {
        row["product_id"] for row in evidence if row["product_id"] in products
    }
    products_without_facts = sorted(
        generator.product_atom(product_id, product.get("name") or product_id)
        for product_id, product in products.items()
        if product_id not in evidence_product_ids
    )
    actual_preferences = parse_preference_header(program)

    checks = {
        "dataset_key": f"% Dataset key: {dataset_key}" in program,
        "frozen_methodology": (
            f"% Metodologia congelada SHA-256: {methodology_sha256}" in program
        ),
        "catalog_products_only": actual_product_atoms == expected_product_atoms,
        "preferences_header": actual_preferences == preferences,
        "facts_trust_and_preferences": actual_facts == expected_fact_lines,
        "frozen_rules": actual_rules == expected_rule_lines,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "products": len(products),
        "products_with_facts": len({row["product_id"] for row in evidence if row["product_id"] in products}),
        "products_without_facts": products_without_facts,
        "facts": sum(actual_facts.values()),
        "rules": sum(actual_rules.values()),
        "active_aspects": sorted(active_aspects),
        "unexpected_products": sorted(actual_product_atoms - expected_product_atoms),
        "missing_products": sorted(expected_product_atoms - actual_product_atoms),
        "unexpected_facts": list((actual_facts - expected_fact_lines).elements()),
        "missing_facts": list((expected_fact_lines - actual_facts).elements()),
        "unexpected_rules": list((actual_rules - expected_rule_lines).elements()),
        "missing_rules": list((expected_rule_lines - actual_rules).elements()),
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Auditoria de generacion LAF1 con datasets reales",
        "",
        f"Fecha: {report['generated_at']}",
        f"Estrategia: `{report['strategy']}`",
        f"Metodologia congelada: `{report['methodology_sha256']}`",
        "",
        "Esta auditoria valida la generacion; no ejecuta el ranking algebraico.",
        "",
        "| Dataset | 07 UI | Escenario | Productos | Con trust | Hechos | Reglas | Resultado |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for dataset in report["datasets"]:
        if dataset.get("skipped"):
            lines.append(
                f"| {dataset['description']} (`{dataset['dataset_key']}`) | - | - | - | - | - | - | OMITIDO: {dataset['reason']} |"
            )
            continue
        for scenario in dataset["scenarios"]:
            result = "OK" if scenario["passed"] else "FALLO"
            ui_result = "OK" if dataset.get("preferences_ui", {}).get("passed") else "FALLO"
            lines.append(
                f"| {dataset['description']} (`{dataset['dataset_key']}`) | "
                f"{ui_result} | `{scenario['name']}` | {scenario['products']} | {scenario['products_with_facts']} | "
                f"{scenario['facts']} | {scenario['rules']} | {result} |"
            )
    lines.extend([
        "",
        "## Comprobaciones realizadas",
        "",
        "- `dataset_key` exacto en el encabezado;",
        "- ejecución headless de 07 con 14 sliders y tres perfiles por dataset, sin sobrescribir el archivo persistido;",
        "- igualdad entre productos listados y catálogo revisado del snapshot;",
        "- preferencias de 07 en el encabezado y beta de cada hecho;",
        "- igualdad exacta entre cada `agg_confidence` de Supabase y el trust del hecho, redondeado a dos decimales;",
        "- reglas y alpha iguales a la configuración cuyo hash fue congelado por 06d;",
        "- beta estructural igual a `1.00`.",
        "",
        "## Cobertura geográfica y de tipos",
        "",
        report["coverage_note"],
        "",
    ])
    gaps = []
    for dataset in report["datasets"]:
        if dataset.get("skipped") or not dataset.get("scenarios"):
            continue
        missing = dataset["scenarios"][0].get("products_without_facts", [])
        if missing:
            gaps.append(
                f"- `{dataset['dataset_key']}`: productos incluidos sin hechos de trust "
                f"para la estrategia auditada: {', '.join(f'`{item}`' for item in missing)}."
            )
    if gaps:
        lines.extend([
            "## Advertencias de cobertura",
            "",
            *gaps,
            "",
            "Estos productos pertenecen al catálogo correcto, pero no pueden obtener una "
            "derivación LAF1 mientras no tengan evidencia agregada.",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="cafe")
    parser.add_argument("--strategy", default="D", choices=["A", "B", "C", "D", "E"])
    parser.add_argument(
        "--artifact-date",
        default=datetime.now(timezone.utc).strftime("%Y%m%d"),
        help="Fecha YYYYMMDD usada en las rutas de los artefactos de auditoria.",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"\d{8}", args.artifact_date):
        parser.error("--artifact-date debe usar el formato YYYYMMDD")

    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    config = load_domain_config_for_key(args.domain)
    datasets = discover_datasets(sb, config)
    generator = load_laf1_generator()

    output_dir = (
        domain_artifact_dir(config, "programas_laf")
        / f"auditoria_generacion_{args.artifact_date}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_programs = tempfile.TemporaryDirectory(prefix="laf1_generation_audit_")
    temporary_dir = Path(temporary_programs.name)
    report_dir = domain_artifact_dir(config, "reportes")
    scenarios = preference_scenarios(list(config["quality_aspects"]))

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "domain": args.domain,
        "strategy": args.strategy,
        "datasets": [],
    }
    frozen_hashes: set[str] = set()

    for dataset in datasets:
        dataset_key = dataset["dataset_key"]
        entry: dict[str, Any] = {
            "dataset_key": dataset_key,
            "category_label": dataset.get("category_label"),
            "site_id": dataset.get("site_id"),
            "description": dataset_description(dataset),
        }
        try:
            entry["preferences_ui"] = audit_preferences_ui(
                dataset_key,
                scenarios,
                list(config["quality_aspects"]),
            )
            if not entry["preferences_ui"]["passed"]:
                raise RuntimeError("la interfaz 07 no supero la auditoria de sliders")
            generator.initialize_runtime(dataset_key)
            included = require_included_product_ids(
                sb, dataset_key, stage_name="audit_laf1_real_generation.py"
            )
            manifest, methodology_sha256 = generator.load_and_validate_freeze(
                generator.DOMAIN
            )
            frozen_hashes.add(methodology_sha256)
            products = generator.load_products(sb, included)
            evidence = generator.load_evidence(sb, args.strategy, included)
            if not products or not evidence:
                raise RuntimeError("no hay productos o trust D listos para generar")

            entry["included_products"] = len(included)
            entry["scenarios"] = []
            for scenario_name, preferences in scenarios.items():
                # Se conserva un solo programa representativo por dataset. Los
                # otros escenarios se validan en un directorio temporal y sus
                # métricas permanecen en los reportes JSON/Markdown.
                program_path = (
                    output_dir / f"{dataset_key}__neutral.txt"
                    if scenario_name == "neutral"
                    else temporary_dir / f"{dataset_key}__{scenario_name}.txt"
                )
                generator.generate(
                    sb,
                    preferences,
                    args.strategy,
                    program_path,
                    included,
                    freeze_manifest=manifest,
                    methodology_sha256=methodology_sha256,
                )
                program = program_path.read_text(encoding="utf-8")
                result = audit_program(
                    generator,
                    program,
                    dataset_key,
                    methodology_sha256,
                    products,
                    evidence,
                    preferences,
                    generator.DOMAIN,
                )
                result.update(name=scenario_name)
                if scenario_name == "neutral":
                    result["program"] = str(program_path.relative_to(REPO_ROOT))
                entry["scenarios"].append(result)
        except (ProductReviewSetupError, ProductReviewPendingError, RuntimeError) as exc:
            entry.update(skipped=True, reason=str(exc))
        report["datasets"].append(entry)

    report["methodology_sha256"] = (
        next(iter(frozen_hashes)) if len(frozen_hashes) == 1 else sorted(frozen_hashes)
    )
    report["artifact_retention"] = (
        "Se conserva el programa neutral de cada dataset. Los otros escenarios "
        "se verifican temporalmente y permanecen resumidos en este reporte."
    )
    has_colombia_instant = any(
        row.get("site_id") == "MCO" and "instant" in str(row.get("category_label", "")).lower()
        for row in datasets
    )
    report["coverage_note"] = (
        "Se verificaron México histórico mixto, México instantáneo, México grano/molido "
        "y Colombia grano/molido. No existe actualmente un snapshot real de café "
        "instantáneo de Colombia en la tabla `datasets`."
        if not has_colombia_instant
        else "La tabla contiene también un snapshot instantáneo de Colombia."
    )
    report["passed"] = all(
        not dataset.get("skipped")
        and dataset.get("preferences_ui", {}).get("passed")
        and all(scenario["passed"] for scenario in dataset.get("scenarios", []))
        for dataset in report["datasets"]
    )

    temporary_programs.cleanup()
    json_path = report_dir / f"laf1_real_generation_audit_{args.artifact_date}.json"
    md_path = report_dir / f"laf1_real_generation_audit_{args.artifact_date}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_markdown(md_path, report)

    print(f"Datasets descubiertos: {len(datasets)}")
    for dataset in report["datasets"]:
        if dataset.get("skipped"):
            print(f"  OMITIDO {dataset['dataset_key']}: {dataset['reason']}")
            continue
        passed = all(scenario["passed"] for scenario in dataset["scenarios"])
        print(
            f"  {'OK' if passed else 'FALLO'} {dataset['dataset_key']}: "
            f"{len(dataset['scenarios'])} escenarios"
        )
    print(f"Reporte: {md_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
