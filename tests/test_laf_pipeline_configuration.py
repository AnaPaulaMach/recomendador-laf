from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from domain_config import load_domain_config_for_key


def _load_generator(filename, module_name):
    path = SRC_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_laf2_generator():
    return _load_generator("10_laf2_generate.py", "laf2_generator_test")


def test_shared_laf2_structure_covers_every_current_domain():
    domain_keys = (
        "aires_acondicionados",
        "cafe",
        "celulares",
        "freidora_de_aire",
    )
    for domain_key in domain_keys:
        config = load_domain_config_for_key(domain_key)
        purchase = set(config["purchase_aspects"])
        conditions = set(config["laf2_rule_structure"]["conditions"])
        assert purchase <= conditions


def test_shipping_uses_real_structured_free_shipping_field():
    config = load_domain_config_for_key("cafe")
    shipping = config["laf2_rule_structure"]["conditions"]["envio"]
    assert shipping["status"] == "implemented"
    assert shipping["fact_predicate"] == "tieneEnvioGratis"
    assert shipping["source_field"] == "items_raw.shipping_free_shipping"


def test_laf1_structural_betas_are_neutral_and_user_slider_stays_on_facts():
    module = _load_generator("08_laf1_generate.py", "laf1_generator_test")
    config = load_domain_config_for_key("cafe")
    products = {
        "p1": {"name": "Cafe test", "position": 1, "price_min": 100, "price_max": 100, "n_items": 1}
    }
    evidence = [{
        "product_id": "p1", "aspect": "sabor", "polarity": "pos",
        "agg_confidence": 0.8, "n_reviews": 2, "from_catalog": False,
    }]
    program = module.build_laf1(products, evidence, {"sabor": 0.37}, "D", domain=config)

    assert "resenaPositivaSabor(p1_cafe_test). {0.80; 0.37}" in program
    assert "saborBueno(X) :- resenaPositivaSabor(X). {0.85; 1.00}" in program
    assert "sensorialBueno(X) :- saborBueno(X). {0.90; 1.00}" in program


def test_laf1_records_dataset_and_frozen_methodology_in_program():
    module = _load_generator("08_laf1_generate.py", "laf1_metadata_test")
    config = load_domain_config_for_key("cafe")
    program = module.build_laf1(
        {},
        [],
        {"sabor": 0.5},
        "D",
        domain=config,
        dataset_key="dataset_real_1",
        methodology_sha256="abc123",
        frozen_at="2026-08-13T00:00:00+00:00",
    )

    assert "% Dataset key: dataset_real_1" in program
    assert "% Metodologia congelada SHA-256: abc123" in program
    assert "% Congelada en: 2026-08-13T00:00:00+00:00" in program


def test_laf1_completes_preferences_saved_before_new_aspects_were_added():
    module = _load_generator("08_laf1_generate.py", "laf1_preferences_test")
    config = load_domain_config_for_key("cafe")
    preferences = module.normalize_prefs({"sabor": 0.80}, config)

    assert set(preferences) == set(config["quality_aspects"])
    assert preferences["sabor"] == 0.80
    assert preferences["tueste"] == 0.50
    assert preferences["acidez"] == 0.50


def test_laf1_rejects_a_manifest_for_a_different_or_changed_methodology():
    module = _load_generator("08_laf1_generate.py", "laf1_freeze_test")
    config = load_domain_config_for_key("cafe")
    valid_hash = module.canonical_methodology_hash(config)

    assert module.validate_freeze_manifest(
        config,
        {"domain_key": "cafe", "methodology_sha256": valid_hash},
    ) == valid_hash

    try:
        module.validate_freeze_manifest(
            config,
            {"domain_key": "cafe", "methodology_sha256": "outdated"},
        )
    except RuntimeError as exc:
        assert "cambio despues de 06d" in str(exc)
    else:
        raise AssertionError("Una metodologia no congelada debe ser rechazada")


def test_compact_laf1_audit_has_one_positive_and_negative_chain():
    audit = _load_generator("06a_generate_test_program.py", "audit_generator_test")
    laf1 = _load_generator("08_laf1_generate.py", "compact_laf1_generator_test")
    config = load_domain_config_for_key("cafe")
    products, evidence, preferences, aspect = audit._compact_laf1_fixture(config)

    program = laf1.build_laf1(products, evidence, preferences, "D", domain=config)
    statements = [
        line for line in program.splitlines()
        if line and not line.startswith("%") and "{" in line
    ]

    assert aspect == "sabor"
    assert len(evidence) == 2
    assert len(statements) == 8
    assert "recomendar(X) :- sensorialBueno(X)" in program
    assert "~recomendar(X) :- ~sensorialBueno(X)" in program


def test_laf2_rules_come_from_configuration_and_have_no_orphan_negative_price_rule():
    module = _load_laf2_generator()
    config = load_domain_config_for_key("cafe")
    item = {
        "item_id": "item_test",
        "price": Decimal("100"),
        "has_discount": True,
        "discount_pct": 0.10,
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
    }
    preferences = {key: 0.5 for key in config["purchase_aspects"]}

    program = module.build_laf2(
        [item],
        preferences,
        "Producto test",
        domain=config,
    )

    assert "compraBuena(X) :- precioBueno(X)" in program
    assert "tieneEnvioGratis(item_test). {0.95; 0.50}" in program
    assert "compraBuena(X) :- tieneEnvioGratis(X). {0.85; 0.50}" in program
    assert "~recomendar(X) :- ~precioBueno(X)" not in program


def test_parse_item_reads_structured_free_shipping_boolean():
    module = _load_laf2_generator()
    parsed = module.parse_item({
        "item_id": "x", "price": "100", "original_price": None,
        "shipping_free_shipping": True,
        "shipping_logistic_type": "cross_docking", "shipping_mode": "me2",
    })
    assert parsed["has_free_shipping"] is True
    assert parsed["shipping_logistic_type"] == "cross_docking"
