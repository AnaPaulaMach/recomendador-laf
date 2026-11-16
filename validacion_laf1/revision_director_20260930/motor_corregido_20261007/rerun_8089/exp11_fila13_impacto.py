"""EXP 11 - Fila 13: cuanto cambia el ranking si valor y elaboracion pueden concluir ~recomendar.

Hoy las dimensiones "valor" (rendimiento, tamano) y "elaboracion" (preparacion, molienda)
no tienen bloque not_recommend en config/domains/cafe.json, asi que 08_laf1_generate.py
no emite la regla `~recomendar(X) :- ~valorBueno(X)` ni `~recomendar(X) :- ~elaboracionBueno(X)`.
Sus hechos negativos llegan a ~valorBueno / ~elaboracionBueno y ahi mueren.

Este script NO modifica nada: carga el dominio real, construye una copia con las dos reglas
agregadas (confianza = la de la regla positiva de la misma dimension, y una variante con 0,90
como las demas dimensiones), y compara el ranking del camino de produccion
(LAF por aspecto + suma ponderada) en varios perfiles. Reutiliza la infraestructura verificada
de validacion_robustez/bootstrap_ranking.py (control 18/18 contra la bateria).

Uso:  venv/Scripts/python validacion_laf1/exp11_fila13_impacto.py
"""
from __future__ import annotations

import collections
import copy
import io
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "validacion_robustez"))
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import bootstrap_ranking as br  # noqa: E402

ASPECTOS = br.ASPECTOS
PERFILES = {
    "neutro": {a: 0.67 for a in ASPECTOS},
    "solo_sabor": {**{a: 0.0 for a in ASPECTOS}, "sabor": 1.0},
    "solo_rendimiento": {**{a: 0.0 for a in ASPECTOS}, "rendimiento": 1.0},
    "solo_preparacion": {**{a: 0.0 for a in ASPECTOS}, "preparacion": 1.0},
    "solo_molienda": {**{a: 0.0 for a in ASPECTOS}, "molienda": 1.0},
    "solo_tamano": {**{a: 0.0 for a in ASPECTOS}, "tamano": 1.0},
}
FALTANTES = ("valor", "elaboracion")
AFECTADOS = ("rendimiento", "tamano", "preparacion", "molienda")
NOMBRES: dict = {}


def dominio_con_fila13(dom: dict, modo: str) -> dict:
    d = copy.deepcopy(dom)
    dims = d["laf1_rule_structure"]["dimensions"]
    for k in FALTANTES:
        # 2026-09-10: tras el recongelado (fila 13 ADOPTADA) el dominio real YA trae not_recommend en
        # valor/elaboracion; la variante se construye igual (sobrescribe) y "actual" debe dar rho=1.000
        # contra "fila13_simetrico". Antes del recongelado este bloque era un assert de ausencia.
        if "not_recommend" in dims[k]:
            print(f"  aviso: {k} ya tiene not_recommend={dims[k]['not_recommend']} (dominio recongelado); se sobrescribe en la variante")
        conf = dims[k]["recommend"]["confidence"] if modo == "simetrico" else 0.90
        dims[k]["not_recommend"] = {"confidence": conf, "preference": 1.0}
    return d


def ranking_con_dominio(trust06, gen08, laf, productos, filas, trust_map, dominio):
    evidencia: dict = {}
    menciones = collections.Counter()
    trust06.add_aspect_evidence(filas, trust_map, evidencia, menciones)
    hechos = trust06.build_product_aspect_rows(
        trust06.group_review_evidence(evidencia), menciones, {}, br.ESTRATEGIA, br.DATASET_KEY
    )
    por_aspecto = {}
    for aspecto in ASPECTOS:
        prefs = {a: 0.0 for a in ASPECTOS}
        prefs[aspecto] = 1.0
        programa = gen08.build_laf1(productos, hechos, prefs, br.ESTRATEGIA,
                                    domain=dominio, dataset_key=br.DATASET_KEY)
        payload = laf["zero"](laf["parser"].parse(programa).to_request_payload())
        por_aspecto[aspecto] = laf["mapper"].map(laf["client"].build_graph(payload), [])
    rankings = {}
    for nombre, prefs in PERFILES.items():
        evals = [laf["Eval"](aspect=a, weight=float(prefs[a]), ranking=por_aspecto[a])
                 for a in ASPECTOS if prefs[a] > 0]
        combinado = laf["combinar"](por_aspecto["sabor"], evals, prefs)
        rankings[nombre] = [(e.entity_id, float(e.final_score)) for e in combinado]
        for e in combinado:
            NOMBRES[e.entity_id] = str(e.entity_name or e.entity_id)[:45]
    # score por aspecto de recomendar (post-conflicto) por producto
    por_aspecto_scores = {a: {e.entity_id: float(e.confidence) for e in por_aspecto[a]} for a in ASPECTOS}
    return rankings, hechos, por_aspecto_scores


def main() -> None:
    trust06, gen08, laf = br.cargar_modulos()
    sb = br.conectar()
    trust_rows = br.leer_todo(sb, "review_trust", "id,review_id,product_id,trust_score",
                              dataset_key=br.DATASET_KEY)
    mention_rows = br.leer_todo(sb, "review_aspects",
                                "id,review_id,product_id,aspect,polarity,extraction_confidence",
                                dataset_key=br.DATASET_KEY)
    from product_scope import require_included_product_ids
    incluidos = require_included_product_ids(sb, br.DATASET_KEY, stage_name="exp11_fila13")
    productos = gen08.load_products(sb, incluidos, top_n=20)
    NOMBRES.update({pid: (p.get("name") or pid)[:45] for pid, p in productos.items()})
    trust_map = {(r["review_id"], r["product_id"]): float(r["trust_score"]) for r in trust_rows}

    print("=" * 78)
    print("EXP 11 - impacto de la fila 13 (reglas ~recomendar para valor y elaboracion)")
    print("=" * 78)
    print(f"  dataset_key: {br.DATASET_KEY}   fecha: {date.today().isoformat()}   productos: {len(productos)}")

    dom0 = gen08.DOMAIN
    variantes = {
        "actual": dom0,
        "fila13_simetrico(0,80/0,75)": dominio_con_fila13(dom0, "simetrico"),
        "fila13_0,90": dominio_con_fila13(dom0, "0.90"),
    }
    resultados = {}
    hechos_ref = None
    for nombre, dom in variantes.items():
        r, hechos, pa = ranking_con_dominio(trust06, gen08, laf, productos, mention_rows, trust_map, dom)
        resultados[nombre] = {"rankings": r, "por_aspecto": pa}
        hechos_ref = hechos
        print(f"  variante {nombre}: {len(hechos)} hechos D, rankings calculados")

    # control contra la bateria
    ref = HERE.parent / "salidas_8089/battery_multicriterio_mlm194329_20260528_142014.json"
    if ref.exists():
        bat = json.load(open(ref, encoding="utf-8"))
        for perfil, clave in {"neutro": "neutral", "solo_sabor": "solo_sabor"}.items():
            mio = [p for p, _ in resultados["actual"]["rankings"][perfil]]
            assert mio == [x["product"] for x in bat[clave]], f"control {perfil} NO reproduce la bateria"
            print(f"  control {perfil}: igual a la bateria {len(mio)}/{len(mio)}")

    # hechos negativos afectados
    neg_afectados = [h for h in hechos_ref if h.get("polarity") == "neg" and h.get("aspect") in AFECTADOS]
    print(f"\n  hechos negativos hoy sin consumidor ({'/'.join(AFECTADOS)}): {len(neg_afectados)}")
    for h in neg_afectados:
        print(f"      {NOMBRES.get(h.get('product_id'), h.get('product_id'))!s:45s} {h.get('aspect'):12s} "
              f"n={h.get('n_reviews')}  alpha-={float(h.get('agg_confidence', 0)):.3f}")

    salida = {"dataset_key": br.DATASET_KEY, "fecha": date.today().isoformat(),
              "hechos_negativos_sin_consumidor": len(neg_afectados), "perfiles": {}}
    for perfil in PERFILES:
        base = resultados["actual"]["rankings"][perfil]
        orden0 = [p for p, _ in base]
        print("\n" + "-" * 78)
        print(f"PERFIL {perfil}")
        for var in list(variantes)[1:]:
            rk = resultados[var]["rankings"][perfil]
            orden1 = [p for p, _ in rk]
            pos0 = {p: i + 1 for i, p in enumerate(orden0)}
            pos1 = {p: i + 1 for i, p in enumerate(orden1)}
            sc0 = dict(base); sc1 = dict(rk)
            rho = br.spearman([pos0[p] for p in orden0], [pos1[p] for p in orden0])
            cambian = [p for p in orden0 if pos0[p] != pos1[p]]
            top3_igual = orden0[:3] == orden1[:3]
            print(f"  {var:28s} rho={rho:.3f}  cambian de puesto: {len(cambian)}/18  "
                  f"top3 {'igual' if top3_igual else 'CAMBIA'}  "
                  f"ganador {'igual' if orden0[0] == orden1[0] else 'CAMBIA'}")
            for p in sorted(cambian, key=lambda q: -abs(pos0[q] - pos1[q]))[:6]:
                print(f"      {NOMBRES.get(p, p):45s} {pos0[p]:2d} -> {pos1[p]:2d}   "
                      f"score {sc0[p]:.3f} -> {sc1[p]:.3f}")
            salida["perfiles"].setdefault(perfil, {})[var] = {
                "rho": rho, "cambian": len(cambian), "top3_igual": top3_igual,
                "orden_actual": orden0, "orden_variante": orden1,
                "scores_actual": sc0, "scores_variante": sc1,
            }

    # efecto por aspecto: cuantos productos cambian su score de recomendar en los 4 aspectos
    print("\n" + "-" * 78)
    print("Score LAF de recomendar por aspecto (post-conflicto), variante 0,90: productos que cambian")
    for a in AFECTADOS:
        s0 = resultados["actual"]["por_aspecto"][a]
        s1 = resultados["fila13_0,90"]["por_aspecto"][a]
        dif = [(NOMBRES.get(p, p), s0[p], s1.get(p, s0[p])) for p in s0 if abs(s0[p] - s1.get(p, s0[p])) > 1e-9]
        print(f"  {a:12s}: {len(dif)} productos cambian")
        for n, x, y in dif:
            print(f"      {n:45s} {x:.3f} -> {y:.3f}")

    out = HERE / f"exp11_fila13_8089_{date.today().isoformat()}.json"
    out.parent.mkdir(exist_ok=True)
    json.dump(salida, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"\n  -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
