"""06a - Genera programas LAF sinteticos para auditar reglas de categoria.

No representa el recorrido de un usuario. Usa preferencias neutrales (0.50)
y datos sinteticos. Genera una auditoria completa para inspeccionar todas las
reglas y una compacta para comprobar rapidamente el motor LAF.

Uso:
    python src/06a_generate_test_program.py --domain cafe
"""

from __future__ import annotations

import argparse
import importlib.util
import os
from decimal import Decimal
from pathlib import Path
from types import ModuleType

from domain_config import artifact_path, load_domain_config_for_key


SRC_DIR = Path(__file__).resolve().parent


def _load_stage(filename: str, module_name: str) -> ModuleType:
    path = SRC_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _laf1_fixture(config: dict) -> tuple[dict, list[dict], dict]:
    product_id = "producto_auditoria"
    products = {
        product_id: {
            "name": "Producto de auditoria",
            "position": 1,
            "price_min": Decimal("100"),
            "price_max": Decimal("120"),
            "n_items": 2,
        }
    }
    evidence = []
    for aspect in config["quality_aspects"]:
        evidence.extend(
            [
                {
                    "product_id": product_id,
                    "aspect": aspect,
                    "polarity": "pos",
                    "agg_confidence": 0.65,
                    "n_reviews": 3,
                    "coverage_ratio": 1.0,
                    "from_catalog": False,
                },
                {
                    "product_id": product_id,
                    "aspect": aspect,
                    "polarity": "neg",
                    "agg_confidence": 0.35,
                    "n_reviews": 2,
                    "coverage_ratio": 1.0,
                    "from_catalog": False,
                },
            ]
        )
    preferences = {aspect: 0.50 for aspect in config["quality_aspects"]}
    return products, evidence, preferences


def _representative_laf1_aspect(config: dict) -> str:
    """Elige un aspecto que recorra una dimension jerarquica completa."""
    dimensions = (config.get("laf1_rule_structure") or {}).get("dimensions") or {}
    quality_aspects = config.get("quality_aspects") or {}
    for dimension in dimensions.values():
        for raw_rule in dimension.get("aspects", []):
            aspect = raw_rule if isinstance(raw_rule, str) else (raw_rule or {}).get("aspect")
            if aspect in quality_aspects:
                return aspect
    if quality_aspects:
        return next(iter(quality_aspects))
    raise ValueError("La categoria no tiene aspectos de calidad para la auditoria compacta.")


def _compact_laf1_fixture(config: dict) -> tuple[dict, list[dict], dict, str]:
    """Reduce la auditoria a una sola cadena positiva/negativa representativa."""
    products, evidence, _ = _laf1_fixture(config)
    aspect = _representative_laf1_aspect(config)
    compact_evidence = [row for row in evidence if row["aspect"] == aspect]
    return products, compact_evidence, {aspect: 0.50}, aspect


def _laf2_fixture(config: dict) -> tuple[list[dict], dict]:
    items = [
        {
            "item_id": "item_auditoria_completo",
            "price": Decimal("100"),
            "has_discount": True,
            "discount_pct": 0.20,
            "has_3x": False,
            "has_9x": False,
            "has_12x": True,
            "has_cuotas": True,
            "warranty_months": 12,
            "has_long_warranty": True,
            "is_official_store": True,
            "has_invoice": True,
            "has_free_shipping": True,
            "shipping_logistic_type": "fulfillment",
            "shipping_mode": "me2",
            "is_gold_pro": True,
        },
        {
            "item_id": "item_auditoria_basico",
            "price": Decimal("120"),
            "has_discount": False,
            "discount_pct": 0.0,
            "has_3x": False,
            "has_9x": False,
            "has_12x": False,
            "has_cuotas": False,
            "warranty_months": 0,
            "has_long_warranty": False,
            "is_official_store": False,
            "has_invoice": False,
            "has_free_shipping": False,
            "shipping_logistic_type": "drop_off",
            "shipping_mode": "me2",
            "is_gold_pro": False,
        },
    ]
    preferences = {aspect: 0.50 for aspect in config["purchase_aspects"]}
    return items, preferences


def generate(domain_key: str) -> tuple[Path, Path, Path]:
    config = load_domain_config_for_key(domain_key)
    laf1 = _load_stage("08_laf1_generate.py", "laf1_generator_for_audit")
    laf2 = _load_stage("10_laf2_generate.py", "laf2_generator_for_audit")

    products, evidence, quality_preferences = _laf1_fixture(config)
    laf1_program = laf1.build_laf1(
        products,
        evidence,
        quality_preferences,
        "D",
        domain=config,
    )

    compact_products, compact_evidence, compact_preferences, compact_aspect = (
        _compact_laf1_fixture(config)
    )
    compact_laf1_program = laf1.build_laf1(
        compact_products,
        compact_evidence,
        compact_preferences,
        "D",
        domain=config,
    )
    compact_laf1_program = (
        "% AUDITORIA COMPACTA PARA PRUEBA RAPIDA DEL MOTOR LAF\n"
        f"% Cadena representativa: {compact_aspect} (positiva y negativa).\n"
        "% No reemplaza la auditoria completa de todas las reglas.\n\n"
        + compact_laf1_program
    )

    items, purchase_preferences = _laf2_fixture(config)
    laf2_program = laf2.build_laf2(
        items,
        purchase_preferences,
        "Producto de auditoria",
        strategy_note="Programa offline con preferencias neutrales (0.50).",
        domain=config,
    )

    laf1_path = artifact_path("programa_laf1_auditoria_D", ".txt", config)
    compact_laf1_path = artifact_path("programa_laf1_auditoria_compacta_D", ".txt", config)
    laf2_path = artifact_path("programa_laf2_auditoria", ".txt", config)
    _write_atomic(laf1_path, laf1_program)
    _write_atomic(compact_laf1_path, compact_laf1_program)
    _write_atomic(laf2_path, laf2_program)
    return laf1_path, compact_laf1_path, laf2_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True, help="Clave en config/domains")
    args = parser.parse_args()

    laf1_path, compact_laf1_path, laf2_path = generate(args.domain)
    print(f"OK LAF 1 de auditoria completa: {laf1_path}")
    print(f"OK LAF 1 de auditoria compacta (probar primero): {compact_laf1_path}")
    print(f"OK LAF 2 de auditoria: {laf2_path}")
    print("PROXIMO PASO: streamlit run src/06b_laf_rule_review.py")


if __name__ == "__main__":
    main()
