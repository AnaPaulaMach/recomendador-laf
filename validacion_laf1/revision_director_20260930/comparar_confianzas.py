"""Comparaciones de sensibilidad, sin escribir en Supabase ni cambiar producción.

Usa generador, agregador, operadores, mapper y combinación reales. Conserva
inputs mínimos locales para repetir; no almacena claves ni texto de reseñas.
La variante uniforme reemplaza todas las fuerzas de reglas, no los hechos.
"""
from __future__ import annotations

import collections
import copy
import csv
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "validacion_robustez"))
import bootstrap_ranking as br

PERFILES = {
    "neutro": {a: .67 for a in br.ASPECTOS},
    "solo_sabor": {a: float(a == "sabor") for a in br.ASPECTOS},
    "solo_aroma": {a: float(a == "aroma") for a in br.ASPECTOS},
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def uniform_domain(domain, value):
    d = copy.deepcopy(domain)
    structure = d["laf1_rule_structure"]
    structure["direct_recommendation_confidence"] = value
    for dimension in structure["dimensions"].values():
        for aspect in dimension.get("aspects", []):
            aspect["confidence"] = value
            aspect["negative_confidence"] = value
        for key in ("recommend", "not_recommend"):
            if key in dimension:
                dimension[key]["confidence"] = value
    return d


def compare(base, other):
    order0, order1 = [x[0] for x in base], [x[0] for x in other]
    if set(order0) != set(order1):
        raise ValueError("Cambió el universo de productos")
    pos0 = {p: i + 1 for i, p in enumerate(order0)}
    pos1 = {p: i + 1 for i, p in enumerate(order1)}
    scores0, scores1 = dict(base), dict(other)
    rho = br.spearman([pos0[p] for p in order0], [pos1[p] for p in order0])
    score_rho = br.spearman([scores0[p] for p in order0], [scores1[p] for p in order0])
    return {
        "rho_orden": rho if math.isfinite(rho) else None,
        "rho_scores_con_empates": score_rho if math.isfinite(score_rho) else None,
        "productos_cambian_puesto": sum(pos0[p] != pos1[p] for p in order0),
        "ganador_igual": order0[0] == order1[0],
        "top3_mismo_conjunto": set(order0[:3]) == set(order1[:3]),
        "top3_mismo_orden": order0[:3] == order1[:3],
        "max_delta_score": max(abs(scores1[p] - scores0[p]) for p in order0),
        "rango_scores": max(scores1.values()) - min(scores1.values()),
        "margen_primero_segundo": other[0][1] - other[1][1],
        "margen_primero_tercero": other[0][1] - other[2][1],
        "ganador": order1[0],
    }


def main():
    trust, gen, laf = br.cargar_modulos()
    cache = HERE / "inputs_minimos.json"
    if cache.exists():
        inputs = json.loads(cache.read_text(encoding="utf-8"))
        assert inputs["dataset_key"] == br.DATASET_KEY
    else:
        sb = br.conectar()
        trusts = br.leer_todo(sb, "review_trust", "id,review_id,product_id,trust_score", dataset_key=br.DATASET_KEY)
        mentions = br.leer_todo(sb, "review_aspects", "id,review_id,product_id,aspect,polarity,extraction_confidence", dataset_key=br.DATASET_KEY)
        from product_scope import require_included_product_ids
        included = require_included_product_ids(sb, br.DATASET_KEY, stage_name="revision_director_20260930")
        products = gen.load_products(sb, included, top_n=20)
        inputs = {"dataset_key": br.DATASET_KEY, "trust": trusts, "mentions": mentions, "products": products}
        cache.write_text(json.dumps(inputs, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    products, mentions = inputs["products"], inputs["mentions"]
    assert len(products) == 18, f"Se esperaban 18 productos, hay {len(products)}"
    trust_map = {(r["review_id"], r["product_id"]): float(r["trust_score"]) for r in inputs["trust"]}
    print(f"Inputs: {len(products)} productos, {len(mentions)} menciones, {len(inputs['trust'])} trusts", flush=True)
    domain = copy.deepcopy(gen.DOMAIN)
    names = {gen.product_atom(pid, p.get("name") or pid): p.get("name") or pid for pid, p in products.items()}
    initial_agg, initial_rec, initial_prior = gen.RULE_CONF_AGGREGATION, gen.RULE_CONF_RECOMMENDATION, trust.PRIOR_WEIGHT
    variants = [("vigente", None, 10), ("uniforme_085", .85, 10), ("uniforme_060", .60, 10),
                ("uniforme_100", 1., 10), ("lambda_5", None, 5), ("lambda_20", None, 20)]
    results = {"dataset_key": br.DATASET_KEY, "fecha_local": "2026-09-30", "generated_at": datetime.now().isoformat(),
               "inputs_sha256": digest(cache), "config_sha256": digest(ROOT / "config/domains/cafe.json"),
               "generador_sha256": digest(ROOT / "src/08_laf1_generate.py"),
               "trust_sha256": digest(ROOT / "src/06_trust.py"), "perfiles": PERFILES, "nombres": names,
               "method": "LAF una etiqueta por aspecto y suma ponderada de produccion; ninguna escritura DB", "variantes": {}}
    evidence_cache = {}
    try:
        for label, uniform, prior in variants:
            trust.configure_strategy_parameters(prior_weight=prior)
            if prior not in evidence_cache:
                evidence, counts = {}, collections.Counter()
                trust.add_aspect_evidence(mentions, trust_map, evidence, counts)
                evidence_cache[prior] = trust.build_product_aspect_rows(trust.group_review_evidence(evidence), counts, {}, "D", br.DATASET_KEY)
            facts = evidence_cache[prior]
            dom = uniform_domain(domain, uniform) if uniform is not None else domain
            gen.RULE_CONF_AGGREGATION = uniform if uniform is not None else initial_agg
            gen.RULE_CONF_RECOMMENDATION = uniform if uniform is not None else initial_rec
            folder = HERE / "programas" / label
            folder.mkdir(parents=True, exist_ok=True)
            aspect_rankings = {}
            hashes = {}
            for aspect in br.ASPECTOS:
                selected = [h for h in facts if h["aspect"] == aspect]
                program = gen.build_laf1(products, selected, PERFILES["neutro"], "D", domain=dom, dataset_key=br.DATASET_KEY)
                program = re.sub(r"\{([^;{}]+);[^{}]+\}", r"{\1}", program)
                path = folder / f"{aspect}.txt"
                path.write_text(program, encoding="utf-8")
                hashes[aspect] = digest(path)
                parsed = laf["parser"].parse(program)
                assert parsed.attribute_count == 1
                if uniform is not None:
                    assert all(abs(float(r["attributes"][0]) - uniform) < 1e-12 for r in parsed.rules)
                graph = laf["client"].build_graph(parsed.to_request_payload())
                (folder / f"{aspect}_grafo.json").write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
                aspect_rankings[aspect] = laf["mapper"].map(graph, [])
            rankings = {}
            for profile, prefs in PERFILES.items():
                evaluations = [laf["Eval"](aspect=a, weight=prefs[a], ranking=aspect_rankings[a]) for a in br.ASPECTOS if prefs[a] > 0]
                rows = laf["combinar"](aspect_rankings["sabor"], evaluations, prefs)
                rankings[profile] = [(e.entity_id, float(e.final_score)) for e in rows]
                assert len(rows) == 18
            results["variantes"][label] = {"lambda": prior, "uniforme": uniform, "programas_sha256": hashes,
                "hechos_D": len(facts), "rankings": rankings,
                "scores_por_aspecto": {a: {e.entity_id: e.confidence for e in rr} for a, rr in aspect_rankings.items()}}
            if label == "vigente":
                battery = json.loads((ROOT / "validacion_laf1/salidas/battery_multicriterio_mlm194329_20260528_142014.json").read_text(encoding="utf-8"))
                checks = {}
                for profile, key in (("neutro", "neutral"), ("solo_sabor", "solo_sabor")):
                    saved = [(r["product"], float(r["score"])) for r in battery[key]]
                    checks[profile] = compare(saved, rankings[profile])
                    assert [p for p, _ in saved] == [p for p, _ in rankings[profile]], "No reproduce orden de batería"
                    assert checks[profile]["max_delta_score"] <= 1e-6, "No reproduce scores de batería"
                results["control_bateria"] = checks
            results["variantes"][label]["comparacion_vigente"] = {p: compare(results["variantes"]["vigente"]["rankings"][p], rankings[p]) for p in PERFILES}
            (HERE / "resultados_confianzas.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            print(f"Completado: {label}", flush=True)
    finally:
        gen.RULE_CONF_AGGREGATION, gen.RULE_CONF_RECOMMENDATION = initial_agg, initial_rec
        trust.configure_strategy_parameters(prior_weight=initial_prior)
    rows = []
    for label, variant in results["variantes"].items():
        for profile, c in variant["comparacion_vigente"].items():
            rows.append({"variante": label, "perfil": profile, **c})
    with (HERE / "comparacion_confianzas.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
