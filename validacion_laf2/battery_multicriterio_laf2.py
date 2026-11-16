"""
battery_multicriterio_laf2.py - Replica del fix (i) para LAF2: una corrida LAF por
condicion de compra + combine_rankings real (misma receta que
_evaluate_products_multicriteria en evaluators.py). NO toca webapp/ ni src/.

Por producto (>= 2 publicaciones) y perfil de sliders:
  baseline  = build_laf2(prefs completas) -> Docker -> mapper      (como hoy)
  por cond. = build_laf2({cond: 1.0, resto 0.0}) -> zero_threshold_payload -> Docker -> mapper
  ranking   = combine_rankings(baseline, [AspectEvaluation(cond, peso, ranking_cond)], prefs)
Dos variantes para la condicion sin evidencia en el producto (corrida vacia):
  "A_error"  : como LAF1 hoy -> LAFApiError -> sin ranking (se cuenta)
  "B_cero"   : contribucion 0, peso sigue en el denominador
  "C_quitar" : la condicion sale del denominador
Compara con el camino actual (min) y mide empates y respuesta a los sliders.

Uso: venv\\Scripts\\python.exe validacion_laf2\\battery_multicriterio_laf2.py [snapshots...]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prueba_sin_cuotas_factura as P  # noqa: E402
import suficiencia_datos as S  # noqa: E402
from recommender.services.post_laf_decision import (  # noqa: E402
    AspectEvaluation,
    combine_rankings,
    zero_threshold_payload,
)

OUT = HERE / "salidas"


def run_graph(step10, cfg, items, prefs, name, key, pid, *, zero_threshold):
    program = step10.build_laf2(items, prefs, name, domain=cfg, dataset_key=key, product_id=pid)
    payload = P.PARSER.parse(program).to_request_payload()
    if zero_threshold:
        payload = zero_threshold_payload(payload)
        if not payload.get("facts"):
            # El Docker responde HTTP 400 "facts: must not be empty" -> en produccion
            # seria LAFApiError y se perderia todo el ranking (variante A_error).
            return ()
    graph = P.CLIENT.build_graph(payload)
    entities = [{"argument": step10.safe_id(it["item_id"]), "entity_id": it["item_id"],
                 "entity_name": it["item_id"], "metadata": {}} for it in items]
    return P.MAPPER.map(graph, entities)


def multicriteria(step10, cfg, items, prefs, name, key, pid, variant):
    aspects = list(cfg["purchase_aspects"])
    active = sorted(a for a, w in prefs.items() if float(w) > 0)
    baseline = run_graph(step10, cfg, items, prefs, name, key, pid, zero_threshold=False)
    evaluations, empty = [], []
    for cond in active:
        one = {a: (1.0 if a == cond else 0.0) for a in aspects}
        rk = run_graph(step10, cfg, items, one, name, key, pid, zero_threshold=True)
        if not rk:
            empty.append(cond)
            if variant == "A_error":
                return None, baseline, empty
            if variant == "C_quitar":
                continue
        evaluations.append(AspectEvaluation(aspect=cond, weight=float(prefs[cond]), ranking=rk))
    eff_prefs = dict(prefs)
    if variant == "C_quitar":
        for cond in empty:
            eff_prefs[cond] = 0.0
    ranking = combine_rankings(baseline, evaluations, eff_prefs)
    return ranking, baseline, empty


def main():
    load_dotenv(P.ROOT / ".env")
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    step10 = S.load_step_10()
    cfg = P.variants()["actual_7"]
    rs = cfg["laf2_rule_structure"]
    profs = P.profiles(list(cfg["purchase_aspects"]))
    snaps = sys.argv[1:] or list(S.SNAPSHOTS)
    OUT.mkdir(exist_ok=True)
    report = {}
    for snap in snaps:
        key = S.SNAPSHOTS[snap]
        products = P.load_products(sb, key)
        print(f"\n=== {snap} ===")
        rows = []
        for pid, (name, raws) in products.items():
            if len(raws) < 2:
                continue
            items = sorted((step10.parse_item(r, rs) for r in raws), key=lambda it: it["price"])
            row = {"product_id": pid, "name": name[:40], "pubs": len(items), "perfiles": {}}
            for pname, prefs in profs.items():
                rk_B, baseline, empty = multicriteria(step10, cfg, items, prefs, name, key, pid, "B_cero")
                rk_C, _, _ = multicriteria(step10, cfg, items, prefs, name, key, pid, "C_quitar") if empty else (rk_B, None, None)
                a_fails = bool(empty)
                row["perfiles"][pname] = {
                    "min_actual": [(e.entity_id, round(e.final_score, 4), round(e.confidence, 4)) for e in baseline],
                    "mc_B": [(e.entity_id, round(e.final_score, 4)) for e in rk_B],
                    "mc_C": [(e.entity_id, round(e.final_score, 4)) for e in rk_C],
                    "condiciones_sin_evidencia": empty,
                    "A_error_falla": a_fails,
                }
            def top(p, k): return row["perfiles"][p][k][0][0] if row["perfiles"][p][k] else None
            def distinct(p, k): return len({s[1] for s in row["perfiles"][p][k]})
            row["neutral_distintos_min"] = distinct("neutral_0.5", "min_actual")
            row["neutral_distintos_mc"] = distinct("neutral_0.5", "mc_B")
            row["web067_distintos_mc"] = distinct("web_default_0.67", "mc_B")
            tops = {p: top(p, "mc_B") for p in ("solo_precio", "solo_envio", "solo_oficial", "solo_garantia")}
            row["tops_mc"] = tops
            row["top_responde"] = len({v for v in tops.values() if v}) > 1
            row["A_falla_en"] = sorted(p for p, v in row["perfiles"].items() if v["A_error_falla"])
            rows.append(row)
            print(f"  {pid} {row['name']:40s} pubs={row['pubs']:>2} | distintos neutral min={row['neutral_distintos_min']:>2} "
                  f"mc={row['neutral_distintos_mc']:>2} web0.67 mc={row['web067_distintos_mc']:>2} | "
                  f"top cambia entre sliders: {'SI' if row['top_responde'] else 'no'} | "
                  f"A(error) fallaria en {len(row['A_falla_en'])}/{len(profs)} perfiles")
        report[snap] = rows
        n = len(rows)
        print(f"  -- {n} productos | empates totales (1 puntaje) neutral: min {sum(r['neutral_distintos_min']==1 for r in rows)} "
              f"vs mc {sum(r['neutral_distintos_mc']==1 for r in rows)} | top responde a sliders: {sum(r['top_responde'] for r in rows)} "
              f"| productos donde A(error) falla en algun perfil: {sum(bool(r['A_falla_en']) for r in rows)}")
    with open(OUT / "battery_multicriterio_laf2.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    ex = next((r for rows in report.values() for r in rows if r["product_id"] == "MLM16250244"), None)
    if ex:
        print("\nTaster's Choice Caramel (historico) — multicriterio B_cero:")
        for p in ("neutral_0.5", "web_default_0.67", "solo_precio", "solo_envio", "solo_oficial", "solo_garantia"):
            v = ex["perfiles"][p]
            print(f"  {p:18s} sin evidencia={v['condiciones_sin_evidencia']}")
            for e in v["mc_B"]:
                print(f"      {e[0]:14s} {e[1]:.3f}")
            if p != "neutral_0.5":
                continue
            print("    (camino actual min):", [(e[0], e[1]) for e in v["min_actual"]])


if __name__ == "__main__":
    main()
