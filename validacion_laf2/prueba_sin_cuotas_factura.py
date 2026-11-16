"""
prueba_sin_cuotas_factura.py - LAF2 con la configuracion actual (7 condiciones) vs.
una copia EN MEMORIA de cafe.json sin cuotas ni factura. No toca config/, src/ ni webapp/.

Para cada snapshot, cada producto con >= 2 publicaciones y cada perfil de compra:
  programa = build_laf2 REAL (src/10) -> LAFProgramParser -> LAFApiClient (Docker)
  -> LAFGraphRankingMapper (los tres del webapp).
Mide: puntajes distintos, cuantos saturan (pref = 1.0), si el orden cambia entre
configuraciones, y si el orden responde a los sliders.

Uso: venv\\Scripts\\python.exe validacion_laf2\\prueba_sin_cuotas_factura.py [historico|instantaneo|grano_molido ...]
"""
from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "webapp"))
import suficiencia_datos as S  # noqa: E402
from domain_config import load_domain_config_for_key  # noqa: E402
from recommender.services.laf_api import (  # noqa: E402
    LAFApiClient,
    LAFGraphRankingMapper,
    LAFProgramParser,
)

OUT = HERE / "salidas"
LAF_URL = os.environ.get("LAF_API_URL", "http://localhost:8088/api/graph")
REMOVED = ("cuotas", "factura")

PARSER = LAFProgramParser()
CLIENT = LAFApiClient(LAF_URL)
MAPPER = LAFGraphRankingMapper()


def variants():
    full = load_domain_config_for_key("cafe")
    if "cuotas" not in full["purchase_aspects"]:
        raise SystemExit("cafe.json ya no tiene 'cuotas': la prueba no aplica")
    slim = deepcopy(full)
    for k in REMOVED:
        slim["purchase_aspects"].pop(k, None)
        slim["laf2_rule_structure"]["conditions"].pop(k, None)
    rec = slim["laf2_rule_structure"]["recommendation"]
    rec["preference_keys"] = [k for k in rec["preference_keys"] if k not in REMOVED]
    return {"actual_7": full, "sin_cuotas_factura": slim}


def profiles(aspects):
    def prof(base, **o):
        p = {a: base for a in aspects}
        p.update({k: v for k, v in o.items() if k in aspects})
        return p
    return {
        "web_default_0.67": prof(0.67),
        "neutral_0.5": prof(0.5),
        "solo_precio": prof(0.0, precio=1.0),
        "solo_envio": prof(0.0, envio=1.0),
        "solo_oficial": prof(0.0, tienda_oficial=1.0),
        "solo_garantia": prof(0.0, garantia=1.0),
        "cuotas_1_resto_0.5": prof(0.5, cuotas=1.0),
        "todo_1": prof(1.0),
    }


def load_products(sb, dataset_key):
    """pid -> (nombre, [filas crudas ya unidas como en SupabaseRepository])."""
    seed = S.fetch_all(
        sb.table("products_seed").select("product_id,position,analysis_status")
        .eq("dataset_key", dataset_key).order("position")
    )
    pids = [r["product_id"] for r in seed
            if r.get("analysis_status") == "included" and int(r.get("position") or 99) <= 20]
    if not pids:
        raise RuntimeError(f"sin productos incluidos en {dataset_key}")
    names = {r["product_id"]: r.get("name") or r["product_id"] for r in S.fetch_all(
        sb.table("products_raw").select("product_id,name").eq("dataset_key", dataset_key).in_("product_id", pids))}
    clean = S.fetch_all(sb.table("items_clean")
        .select("item_id,product_id,price,original_price,listing_type,seller_id,official_store_id")
        .eq("dataset_key", dataset_key).in_("product_id", pids))
    raw = {r["item_id"]: r for r in S.fetch_all(sb.table("items_raw")
        .select("product_id," + S.RAW_COLS).eq("dataset_key", dataset_key).in_("product_id", pids))}
    out = {}
    for c in clean:
        r = raw.get(c["item_id"])
        if r is None:
            continue
        m = dict(r)
        m["price"] = c["price"]
        m["original_price"] = c["original_price"]
        m["seller_id"] = c.get("seller_id") or r.get("seller_id")
        m["official_store_id"] = c.get("official_store_id") or r.get("official_store_id")
        m["listing_type_id"] = r.get("listing_type_id") or c.get("listing_type")
        out.setdefault(c["product_id"], (names.get(c["product_id"], c["product_id"]), []))[1].append(m)
    return out


def evaluate(step10, cfg, items_parsed, prefs, name, dataset_key, pid):
    program = step10.build_laf2(items_parsed, prefs, name, domain=cfg,
                                dataset_key=dataset_key, product_id=pid)
    payload = PARSER.parse(program).to_request_payload()
    graph = CLIENT.build_graph(payload)
    entities = [{"argument": step10.safe_id(it["item_id"]), "entity_id": it["item_id"],
                 "entity_name": it["item_id"], "metadata": {}} for it in items_parsed]
    ranking = MAPPER.map(graph, entities)
    if len(ranking) != len(items_parsed):
        raise RuntimeError(f"{pid}: {len(ranking)} conclusiones para {len(items_parsed)} publicaciones")
    return program, [(e.entity_id, round(e.final_score, 4), round(e.confidence, 4), round(e.preference, 4))
                     for e in ranking]


def main():
    load_dotenv(ROOT / ".env")
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    step10 = S.load_step_10()
    cfgs = variants()
    snaps = sys.argv[1:] or list(S.SNAPSHOTS)
    OUT.mkdir(exist_ok=True)
    report = {}
    for snap in snaps:
        key = S.SNAPSHOTS[snap]
        products = load_products(sb, key)
        rs_full = cfgs["actual_7"]["laf2_rule_structure"]
        print(f"\n=== {snap} ({key}) ===")
        rows = []
        for pid, (name, raws) in products.items():
            if len(raws) < 2:
                continue
            items = [step10.parse_item(r, rs_full) for r in raws]
            items.sort(key=lambda it: it["price"])
            res = {}
            for cname, cfg in cfgs.items():
                for pname, prefs in profiles(list(cfg["purchase_aspects"])).items():
                    _, rk = evaluate(step10, cfg, items, prefs, name, key, pid)
                    res[(cname, pname)] = rk
            # metricas
            def order(rk): return [e[0] for e in rk]
            def scores(rk): return [e[1] for e in rk]
            same_order_cfg = all(order(res[("actual_7", p)]) == order(res[("sin_cuotas_factura", p)])
                                 for p in profiles(list(cfgs["sin_cuotas_factura"]["purchase_aspects"])))
            same_scores_cfg = all(scores(res[("actual_7", p)]) == scores(res[("sin_cuotas_factura", p)])
                                  for p in profiles(list(cfgs["sin_cuotas_factura"]["purchase_aspects"])))
            neu = res[("actual_7", "neutral_0.5")]
            web = res[("actual_7", "web_default_0.67")]
            placebo = order(res[("actual_7", "cuotas_1_resto_0.5")]) == order(neu) and \
                scores(res[("actual_7", "cuotas_1_resto_0.5")]) == scores(neu)
            row = {
                "product_id": pid, "name": name[:40], "pubs": len(items),
                "neutral_distintos": len(set(scores(neu))),
                "neutral_pref_sat_1": sum(e[3] >= 0.999 for e in neu),
                "web067_distintos": len(set(scores(web))),
                "web067_pref_sat_1": sum(e[3] >= 0.999 for e in web),
                "web067_score_1": sum(e[1] >= 0.999 for e in web),
                "top_precio": order(res[("actual_7", "solo_precio")])[0],
                "top_envio": order(res[("actual_7", "solo_envio")])[0],
                "top_oficial": order(res[("actual_7", "solo_oficial")])[0],
                "top_neutral": order(neu)[0],
                "mismo_orden_7_vs_5": same_order_cfg,
                "mismos_puntajes_7_vs_5": same_scores_cfg,
                "cuotas_slider_placebo": placebo,
                "rankings": {f"{c}|{p}": rk for (c, p), rk in res.items()},
            }
            rows.append(row)
            print(f"  {pid} {row['name']:40s} pubs={row['pubs']:>2} | neutral distintos={row['neutral_distintos']:>2} "
                  f"pref=1:{row['neutral_pref_sat_1']:>2} | web0.67 distintos={row['web067_distintos']:>2} "
                  f"pref=1:{row['web067_pref_sat_1']:>2} score=1:{row['web067_score_1']:>2} | "
                  f"orden 7=5:{'si' if same_order_cfg else 'NO'} puntajes 7=5:{'si' if same_scores_cfg else 'NO'} "
                  f"| placebo cuotas:{'si' if placebo else 'NO'} | top precio/envio/oficial "
                  f"{'igual' if row['top_precio']==row['top_envio']==row['top_oficial'] else 'CAMBIA'}")
        report[snap] = rows
        n = len(rows)
        print(f"  -- {n} productos con >=2 pubs | orden igual 7 vs 5 en {sum(r['mismo_orden_7_vs_5'] for r in rows)} "
              f"| puntajes iguales en {sum(r['mismos_puntajes_7_vs_5'] for r in rows)} "
              f"| slider cuotas placebo en {sum(r['cuotas_slider_placebo'] for r in rows)} "
              f"| top cambia con el slider en {sum(not (r['top_precio']==r['top_envio']==r['top_oficial']) for r in rows)} "
              f"| pubs con pref=1 (web 0.67): {sum(r['web067_pref_sat_1'] for r in rows)}/{sum(r['pubs'] for r in rows)}")
    with open(OUT / "prueba_sin_cuotas_factura.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    # ejemplo detallado
    ex = next((r for rows in report.values() for r in rows if r["product_id"] == "MLM16250244"), None)
    if ex:
        print("\nEjemplo Taster's Choice Caramel (historico), config actual:")
        for p in ("neutral_0.5", "web_default_0.67", "solo_precio", "solo_envio", "solo_garantia", "cuotas_1_resto_0.5"):
            print(f"  {p}:")
            for e in ex["rankings"][f"actual_7|{p}"]:
                print(f"     {e[0]:14s} score={e[1]:.3f} conf={e[2]:.3f} pref={e[3]:.3f}")
        print("  sin_cuotas_factura | web_default_0.67:")
        for e in ex["rankings"]["sin_cuotas_factura|web_default_0.67"]:
            print(f"     {e[0]:14s} score={e[1]:.3f} conf={e[2]:.3f} pref={e[3]:.3f}")


if __name__ == "__main__":
    main()
