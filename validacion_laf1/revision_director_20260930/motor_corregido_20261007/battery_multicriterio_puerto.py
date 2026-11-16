# Copia de validacion_laf1/battery_multicriterio.py para reproduccion contra otro puerto (LAF_PORT), sin tocar salidas/ oficiales.
"""Validacion LAF1 sobre el ranking PREVISTO: post_laf_multicriteria_v1.

Replica fielmente `LAFHttpRecommendationEvaluator._evaluate_products_multicriteria`
(evaluators.py) reutilizando los componentes REALES del webapp:
  - por cada aspecto activo: programa con {aspecto:1.0, resto:0.0} -> zero_threshold_payload
    (quita hechos con pref 0) -> laf-api -> LAFGraphRankingMapper -> score por aspecto
  - linea base: programa con las preferencias completas -> mapper
  - combine_rankings(baseline, evaluaciones, preferencias): suma ponderada, pref = PESO.

Las corridas por aspecto no dependen del perfil -> se cachean. Salidas en ./salidas/.
Uso: python validacion_laf1/battery_multicriterio.py [--dataset-key K]
"""
import argparse, collections, json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
import os
ROOT = HERE.parents[2]
OUT = HERE / ("salidas_" + os.environ.get("LAF_PORT","8089")); OUT.mkdir(exist_ok=True)
PY = str(ROOT / "venv/Scripts/python.exe")
PREFS = ROOT / "artifacts_por_dominio/cafe/preferencias/prefs_laf1.json"
ASPECTS = ["sabor","aroma","intensidad","dulzor","tueste","acidez","presentacion",
           "rendimiento","variedad","preparacion","molienda","originalidad","tamano","caducidad"]
sys.path.insert(0, str(ROOT / "webapp"))
from recommender.services.laf_api import LAFProgramParser, LAFApiClient, LAFGraphRankingMapper  # noqa
from recommender.services.post_laf_decision import combine_rankings, zero_threshold_payload, AspectEvaluation  # noqa

PARSER = LAFProgramParser(); CLIENT = LAFApiClient("http://localhost:" + os.environ.get("LAF_PORT","8089") + "/api/graph"); MAPPER = LAFGraphRankingMapper()

def prof(base, **o):
    p = {a: base for a in ASPECTS}; p.update(o); return p

PROFILES = {
    "neutral":        prof(0.5),
    "solo_sabor":     prof(0.0, sabor=1.0),
    "solo_aroma":     prof(0.0, aroma=1.0),
    "sensorial":      prof(0.0, sabor=1.0, aroma=1.0, intensidad=1.0, dulzor=1.0, tueste=1.0, acidez=1.0),
    "pert_sabor_0.6": prof(0.5, sabor=0.6),
}

def run_08(prefs, dataset, tag):
    PREFS.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
    out = OUT / f"mc_{tag}.txt"
    if out.exists(): out.unlink()   # nunca reutilizar una salida vieja de otro dataset
    r = subprocess.run([PY, "src/08_laf1_generate.py", "--dataset-key", dataset, "--strategy", "D", "--output", str(out)],
                   cwd=str(ROOT), capture_output=True, text=True)
    if not out.exists():
        raise SystemExit(f"08 no genero {out.name} para {dataset}: {r.stderr[-800:]}")
    return out.read_text(encoding="utf-8")

def short(a): return " ".join(str(a).split("_")[:3])

def reviews_and_neg(text):
    rev = collections.defaultdict(int); neg = collections.defaultdict(set)
    lines = text.splitlines()
    for i, l in enumerate(lines):
        m = re.match(r'(resenaPositiva|resenaNegativa)(\w+?)\((mlm\w+)\)\.', l.strip())
        if not m: continue
        nm = re.search(r'n=(\d+)', lines[i-1]) if i else None
        rev[m.group(3)] += int(nm.group(1)) if nm else 0
        if m.group(1) == 'resenaNegativa': neg[m.group(3)].add(m.group(2))
    return rev, neg

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dataset-key", default="mlm_mlm194329_20260528_142014")
    args = ap.parse_args()
    backup = PREFS.read_text(encoding="utf-8")
    results = {}
    try:
        # 1) corridas por aspecto (independientes del perfil) -> cache
        print("corridas por aspecto (14) ...", flush=True)
        aspect_rank = {}
        for a in ASPECTS:
            text = run_08(prof(0.0, **{a: 1.0}), args.dataset_key, f"asp_{a}")
            if not text: continue
            payload = zero_threshold_payload(PARSER.parse(text).to_request_payload())
            aspect_rank[a] = MAPPER.map(CLIENT.build_graph(payload), [])
        # 2) por perfil: linea base + combinar
        for name, P in PROFILES.items():
            print(f"perfil {name} ...", flush=True)
            base_text = run_08(P, args.dataset_key, f"base_{name.replace('.','')}")
            baseline = MAPPER.map(CLIENT.build_graph(PARSER.parse(base_text).to_request_payload()), [])
            evals = [AspectEvaluation(aspect=a, weight=float(P[a]), ranking=aspect_rank[a])
                     for a in ASPECTS if P[a] > 0 and a in aspect_rank]
            ranking = combine_rankings(baseline, evals, P)
            rev, neg = reviews_and_neg(base_text)
            def r(e):
                k = [x for x in rev if x.startswith(e.entity_id.split('_')[0])]
                return (rev[k[0]], len(neg[k[0]])) if k else (0, 0)
            results[name] = [{"product": e.entity_id, "score": e.final_score,
                              "reviews": r(e)[0], "neg_aspects": r(e)[1]} for e in ranking]
    finally:
        PREFS.write_text(backup, encoding="utf-8"); print("prefs originales restauradas.")

    suffix = args.dataset_key.replace("mlm_", "").replace("mco_", "")
    json.dump(results, open(OUT / f"battery_multicriterio_{suffix}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n" + "="*72); print("RANKING PREVISTO (multicriterio, pref=peso) — top-4 por perfil"); print("="*72)
    for name, rk in results.items():
        print(f"\n[{name}]")
        for i, row in enumerate(rk[:4], 1):
            print(f"  {i}. {short(row['product']):30s} score={row['score']:.3f}  reseñas={row['reviews']:4d} aspNeg={row['neg_aspects']}")
    w = {n: short(rk[0]["product"]) for n, rk in results.items() if rk}
    print("\nRESPONSIVIDAD: neutral=%s | solo_aroma=%s | solo_sabor=%s -> %s" % (
        w["neutral"], w["solo_aroma"], w["solo_sabor"],
        "RESPONDE" if len({w['neutral'], w['solo_aroma'], w['solo_sabor']}) > 1 else "NO"))
    print("ESTABILIDAD: neutral=%s | pert_sabor_0.6=%s -> %s" % (
        w["neutral"], w["pert_sabor_0.6"], "ESTABLE" if w["neutral"] == w["pert_sabor_0.6"] else "cambio"))
    # aplanamiento? scores distintos
    neu = results["neutral"]
    print(f"DISCRIMINACION (neutral): {len({round(r['score'],3) for r in neu})} scores distintos de {len(neu)} productos; "
          f"en 0: {sum(1 for r in neu if r['score']==0)}")

if __name__ == "__main__":
    main()
