"""¿Importan λ y π? — sensibilidad del ranking oficial a los parámetros del prior de la estrategia D.

α = (W⁺ + λπ)/(W + λ). Vigente: λ = 10, π = 0,5 (src/06_trust.py: PRIOR_WEIGHT, PRIOR_MEAN).
Grilla (11 configuraciones):
  - λ ∈ {0, 2, 5, 10, 20, 50} con π = 0,5            (6; λ = 0 = sin prior, α = W⁺/W)
  - π ∈ {0,3, 0,4, 0,6, 0,7, 0,8} con λ = 10           (5)
La única grilla previa del repo (revision_director_20260930/comparar_confianzas.py) solo tenía λ ∈ {5, 10, 20};
esta la extiende y queda contenida en ella.

Basado en comparar_confianzas.py (30/09, reejecutado 10/10 con el motor corregido): mismos inputs mínimos
locales (../../inputs_minimos.json, sin leer ni escribir Supabase), generador 08 real, LAF por aspecto en el
motor de producción corregido (localhost:8088) y combine_rankings de producción (post_laf_multicriteria_v1).
λ y π se cambian en memoria sobre el módulo 06_trust (λ = 0 se asigna directo porque la validación CLI exige λ > 0).
Control: la configuración vigente debe reproducir la batería oficial (orden idéntico, |Δscore| ≤ 1e-6) en
neutro y solo sabor; si no, el script aborta. No escribe en validacion_*/salidas/.
"""
from __future__ import annotations

import collections
import copy
import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "validacion_robustez"))
sys.path.insert(0, str(ROOT / "webapp"))
import bootstrap_ranking as br  # noqa: E402

INPUTS = HERE.parents[1] / "inputs_minimos.json"
BATERIA = ROOT / "validacion_laf1/salidas/battery_multicriterio_mlm194329_20260528_142014.json"
PERFILES = {
    "neutro": {a: .67 for a in br.ASPECTOS},
    "solo_sabor": {a: float(a == "sabor") for a in br.ASPECTOS},
}
GRILLA = ([(f"lambda_{l:g}_pi_0.5", float(l), .5) for l in (0, 2, 5, 10, 20, 50)]
          + [(f"lambda_10_pi_{p:g}", 10., p) for p in (.3, .4, .6, .7, .8)])
VIGENTE = "lambda_10_pi_0.5"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(base, other):
    order0, order1 = [x[0] for x in base], [x[0] for x in other]
    assert set(order0) == set(order1), "Cambió el universo de productos"
    pos0 = {p: i + 1 for i, p in enumerate(order0)}
    pos1 = {p: i + 1 for i, p in enumerate(order1)}
    s0, s1 = dict(base), dict(other)
    rho = br.spearman([pos0[p] for p in order0], [pos1[p] for p in order0])
    return {
        "ganador": order1[0], "top3": order1[:3],
        "rho_orden": rho if math.isfinite(rho) else None,
        "productos_cambian_puesto": sum(pos0[p] != pos1[p] for p in order0),
        "ganador_igual": order0[0] == order1[0],
        "top3_mismo_conjunto": set(order0[:3]) == set(order1[:3]),
        "top3_mismo_orden": order0[:3] == order1[:3],
        "max_delta_score": max(abs(s1[p] - s0[p]) for p in order0),
        "margen_primero_segundo": other[0][1] - other[1][1],
    }


def control_sintetico(laf):
    """Hecho a(x) 0,5 y regla b(X) :- a(X) 0,9 -> b(x) = 0,45 (soporte X*Y del perfil budan_2017)."""
    prog = "a(x). {0.5}\nb(X) :- a(X). {0.9}\n"
    graph = laf["client"].build_graph(laf["parser"].parse(prog).to_request_payload())
    vals = [float(n["deltaAttributes"][0]) for n in graph["nodes"] if n.get("type") == "FACT" and str(n.get("label", "")).startswith("b(")]
    return vals


def main():
    trust, gen, laf = br.cargar_modulos()
    sint = control_sintetico(laf)
    print("control sintético b(x):", sint, flush=True)
    assert sint and all(abs(v - .45) < 1e-9 for v in sint), f"Control sintético distinto de 0,45: {sint}"

    inputs = json.loads(INPUTS.read_text(encoding="utf-8"))
    assert inputs["dataset_key"] == br.DATASET_KEY
    products, mentions = inputs["products"], inputs["mentions"]
    assert len(products) == 18
    trust_map = {(r["review_id"], r["product_id"]): float(r["trust_score"]) for r in inputs["trust"]}
    names = {gen.product_atom(pid, p.get("name") or pid): p.get("name") or pid for pid, p in products.items()}
    domain = copy.deepcopy(gen.DOMAIN)
    w0, m0 = trust.PRIOR_WEIGHT, trust.PRIOR_MEAN
    assert (w0, m0) == (10.0, 0.5), f"Parámetros vigentes inesperados en 06_trust: λ={w0}, π={m0}"
    battery = json.loads(BATERIA.read_text(encoding="utf-8"))
    res = {"dataset_key": br.DATASET_KEY, "generated_at": datetime.now().isoformat(), "laf_api": br.LAF_API,
           "control_sintetico_b": sint, "inputs_sha256": digest(INPUTS), "bateria_oficial": str(BATERIA.relative_to(ROOT)),
           "bateria_sha256": digest(BATERIA), "trust_sha256": digest(ROOT / "src/06_trust.py"),
           "generador_sha256": digest(ROOT / "src/08_laf1_generate.py"),
           "config_sha256": digest(ROOT / "config/domains/cafe.json"),
           "formula": "alpha = (W+ + lambda*pi)/(W + lambda); negativo usa 1-pi",
           "perfiles": PERFILES, "nombres": names, "configuraciones": {}}
    try:
        for label, lam, pi in GRILLA:
            trust.PRIOR_WEIGHT, trust.PRIOR_MEAN = lam, pi
            evidence, counts = {}, collections.Counter()
            trust.add_aspect_evidence(mentions, trust_map, evidence, counts)
            facts = trust.build_product_aspect_rows(trust.group_review_evidence(evidence), counts, {}, "D", br.DATASET_KEY)
            aspect_rankings = {}
            for aspect in br.ASPECTOS:
                sel = [h for h in facts if h["aspect"] == aspect]
                program = gen.build_laf1(products, sel, PERFILES["neutro"], "D", domain=domain, dataset_key=br.DATASET_KEY)
                program = re.sub(r"\{([^;{}]+);[^{}]+\}", r"{\1}", program)
                parsed = laf["parser"].parse(program)
                assert parsed.attribute_count == 1
                aspect_rankings[aspect] = laf["mapper"].map(laf["client"].build_graph(parsed.to_request_payload()), [])
            rankings = {}
            for prof, prefs in PERFILES.items():
                ev = [laf["Eval"](aspect=a, weight=prefs[a], ranking=aspect_rankings[a]) for a in br.ASPECTOS if prefs[a] > 0]
                rows = laf["combinar"](aspect_rankings["sabor"], ev, prefs)
                assert len(rows) == 18
                rankings[prof] = [(e.entity_id, float(e.final_score)) for e in rows]
            res["configuraciones"][label] = {"lambda": lam, "pi": pi, "hechos_D": len(facts), "rankings": rankings}
            if label == VIGENTE:
                chk = {}
                for prof, key in (("neutro", "neutral"), ("solo_sabor", "solo_sabor")):
                    saved = [(r["product"], float(r["score"])) for r in battery[key]]
                    c = compare(saved, rankings[prof])
                    if [p for p, _ in saved] != [p for p, _ in rankings[prof]] or c["max_delta_score"] > 1e-6:
                        raise SystemExit(f"CONTROL FALLA en {prof}: la vigente no reproduce la batería oficial: {c}")
                    chk[prof] = {"orden_identico": True, "max_delta_score": c["max_delta_score"]}
                res["control_bateria"] = chk
                print("control batería OK:", chk, flush=True)
            print(f"listo {label}", flush=True)
    finally:
        trust.PRIOR_WEIGHT, trust.PRIOR_MEAN = w0, m0
    base = res["configuraciones"][VIGENTE]["rankings"]
    for label, v in res["configuraciones"].items():
        v["comparacion_vigente"] = {p: compare(base[p], v["rankings"][p]) for p in PERFILES}
    alt = [l for l in res["configuraciones"] if l != VIGENTE]
    res["resumen"] = {p: {
        "ganador_cambia_en": [l for l in alt if not res["configuraciones"][l]["comparacion_vigente"][p]["ganador_igual"]],
        "top3_conjunto_cambia_en": [l for l in alt if not res["configuraciones"][l]["comparacion_vigente"][p]["top3_mismo_conjunto"]],
        "rho_min": min(res["configuraciones"][l]["comparacion_vigente"][p]["rho_orden"] for l in alt),
    } for p in PERFILES}
    (HERE / "resultados_lambda_pi.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    for label, v in res["configuraciones"].items():
        for p, c in v["comparacion_vigente"].items():
            print(f"{label:20s} {p:10s} gan={names.get(c['ganador'], c['ganador'])[:40]:40s} rho={c['rho_orden']:.3f} "
                  f"cambian={c['productos_cambian_puesto']:2d} top3igual={c['top3_mismo_conjunto']}")
    print(json.dumps(res["resumen"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
