"""Compara el evaluador real anterior y nuevo sobre una entrada local inmutable.

Ejecutar con el venv del repositorio. No escribe en Supabase ni en sesiones.
El JSON source contiene products, evidence, domain_config, manifest y
methodology_sha256; request contiene los campos de EvaluationRequest.
"""
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "laf_web.settings")
import django
django.setup()

from django.conf import settings
from recommender.domain.contracts import EvaluationRequest
from recommender.services.laf1_programs import _load_step_08
from recommender.services.use_cases import get_evaluator


def numerical_signature(result):
    return [
        (entry.entity_id, entry.position, entry.final_score, entry.status,
         entry.metadata["aspect_contributions"])
        for entry in result.ranking
    ]


def assert_same_alpha(evaluator, reference, result):
    parser = evaluator.parser
    original = parser.parse(reference.laf_program).to_request_payload()
    facts = {(f["name"], f["argument"]): f["attributes"][0] for f in original["facts"]}
    rules = {(r["headName"], tuple(r["bodyLiterals"])): r["attributes"][0] for r in original["rules"]}
    checked = 0
    for program in result.aspect_programs.values():
        parsed = parser.parse(program)
        assert parsed.attribute_count == 1
        payload = parsed.to_request_payload()
        for f in payload["facts"]:
            assert f["attributes"][0] == facts[f["name"], f["argument"]]
            checked += 1
        for r in payload["rules"]:
            assert r["attributes"][0] == rules[r["headName"], tuple(r["bodyLiterals"])]
            checked += 1
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("request", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source_bytes = args.source.read_bytes()
    source = json.loads(source_bytes)
    source["step_08"] = _load_step_08(str(settings.REPOSITORY_ROOT))
    request = EvaluationRequest(**json.loads(args.request.read_text(encoding="utf-8")))
    evaluator = get_evaluator()
    assert evaluator.results_validated, "La compuerta local debe estar validada."
    # Evita cualquier segunda lectura de datos durante la comparación.
    evaluator.laf1_programs._load_source = lambda request: source
    available = sorted({row["aspect"] for row in source["evidence"]})
    profiles = {"recorrido": request.preferences,
                "solo_sabor": {"sabor": 1.0},
                "solo_aroma": {"aroma": 1.0},
                "pesos_mixtos": {a: (0, 0.33, 0.67, 1)[i % 4] for i, a in enumerate(available)},
                "sin_aspectos": {a: 0.0 for a in available}}
    report = {"dataset_key": request.dataset_key,
              "input_sha256": hashlib.sha256(source_bytes).hexdigest(),
              "profiles": []}
    for name, preferences in profiles.items():
        variant = replace(request, preferences=preferences)
        before = evaluator._evaluate_products_multicriteria_reference(variant)
        after = evaluator.evaluate_products(variant)
        assert numerical_signature(before) == numerical_signature(after), f"Ranking distinto: {name}"
        assert before.evaluation_status == after.evaluation_status
        assert before.laf_program == after.laf_program, "Respaldo modificado"
        if any(preferences.values()):
            assert before.evaluation_status == "validated", f"No se pudo evaluar {name}"
            assert after.aspect_graphs.keys() == after.aspect_programs.keys()
        alpha_count = assert_same_alpha(evaluator, before, after)
        row = {"profile": name, "products": len(after.ranking),
               "aspect_programs": len(after.aspect_programs), "exact_match": True,
               "max_score_difference": 0.0, "alpha_values_checked": alpha_count,
               "ranking": numerical_signature(after)}
        report["profiles"].append(row)
        print(f"{name}: {row['products']} productos, {row['aspect_programs']} aspectos, igualdad exacta; {alpha_count} alpha intactos", flush=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
