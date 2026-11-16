# -*- coding: utf-8 -*-
"""Experimento 2: robustez del ranking ante el remuestreo de resenas (bootstrap).

Implementa el README de pre-registro de esta carpeta. Las formulas del trust y
la construccion del programa LAF se IMPORTAN de src/; aca no se reescribe
ninguna. Solo LECTURA de Supabase, una sola vez al inicio.

Unidad de remuestreo: la RESENA. Cada copia sorteada recibe un review_id
sintetico (r#k) para que el colapso por (review_id, product, aspect, polarity)
de 06_trust.py no la vuelva a fusionar (README §4.2).

Uso:
    python validacion_robustez/bootstrap_ranking.py
    python validacion_robustez/bootstrap_ranking.py --replicas 200
"""
from __future__ import annotations

import argparse
import collections
import csv
import importlib.util
import io
import json
import os
import random
import statistics
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SALIDAS = HERE / "salidas"
for _r in (ROOT / "src", ROOT / "webapp"):
    if str(_r) not in sys.path:
        sys.path.insert(0, str(_r))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DATASET_KEY = "mlm_mlm194329_20260528_142014"
ESTRATEGIA = "D"
LAF_API = "http://localhost:8088/api/graph"
SEMILLA = 20260910
REPLICAS = 200

ASPECTOS = [
    "sabor", "aroma", "intensidad", "dulzor", "tueste", "acidez", "presentacion",
    "rendimiento", "variedad", "preparacion", "molienda", "originalidad",
    "tamano", "caducidad",
]
BAJA_COBERTURA = ["tueste", "acidez"]
PERFILES = {
    "neutro": {a: 0.67 for a in ASPECTOS},
    "solo_sabor": {**{a: 0.0 for a in ASPECTOS}, "sabor": 1.0},
}
UMBRAL_FRACASO_RHO = 0.80


# --------------------------------------------------------------------------
# Carga de los componentes reales
# --------------------------------------------------------------------------

def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def cargar_modulos():
    trust06 = _load("trust06", ROOT / "src" / "06_trust.py")
    gen08 = _load("gen08", ROOT / "src" / "08_laf1_generate.py")
    gen08.initialize_runtime(DATASET_KEY)
    from recommender.services.laf_api import (
        LAFProgramParser, LAFApiClient, LAFGraphRankingMapper,
    )
    from recommender.services.post_laf_decision import (
        zero_threshold_payload, combine_rankings, AspectEvaluation,
    )
    laf = {
        "parser": LAFProgramParser(),
        "client": LAFApiClient(LAF_API),
        "mapper": LAFGraphRankingMapper(),
        "zero": zero_threshold_payload,
        "combinar": combine_rankings,
        "Eval": AspectEvaluation,
    }
    return trust06, gen08, laf


def conectar():
    from dotenv import load_dotenv
    from supabase import create_client
    load_dotenv(ROOT / ".env")
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def leer_todo(sb, tabla: str, columnas: str, **filtros) -> list[dict]:
    filas: list[dict] = []
    ultimo = 0
    while True:
        q = sb.table(tabla).select(columnas)
        for campo, valor in filtros.items():
            q = q.eq(campo, valor)
        pagina = q.gt("id", ultimo).order("id").limit(1000).execute().data
        if not pagina:
            return filas
        filas.extend(pagina)
        ultimo = pagina[-1]["id"]


# --------------------------------------------------------------------------
# Estadistica (sin dependencias nuevas)
# --------------------------------------------------------------------------

def rangos_promediados(valores: list[float]) -> list[float]:
    """Rangos con promedio en los empates (README §4.5)."""
    orden = sorted(range(len(valores)), key=lambda i: valores[i])
    rangos = [0.0] * len(valores)
    i = 0
    while i < len(orden):
        j = i
        while j + 1 < len(orden) and valores[orden[j + 1]] == valores[orden[i]]:
            j += 1
        promedio = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rangos[orden[k]] = promedio
        i = j + 1
    return rangos


def spearman(x: list[float], y: list[float]) -> float:
    rx, ry = rangos_promediados(x), rangos_promediados(y)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def percentil(datos: list[float], p: float) -> float:
    """Percentil por interpolacion lineal, con los datos ya ordenados o no."""
    if not datos:
        return float("nan")
    d = sorted(datos)
    if len(d) == 1:
        return d[0]
    pos = (len(d) - 1) * p
    bajo = int(pos)
    alto = min(bajo + 1, len(d) - 1)
    return d[bajo] + (d[alto] - d[bajo]) * (pos - bajo)


# --------------------------------------------------------------------------
# Nucleo: una replica
# --------------------------------------------------------------------------

def remuestrear(menciones_por_resena: dict, universos: dict, rng: random.Random) -> list[dict]:
    """Devuelve las filas de menciones del corpus remuestreado.

    Cada copia k de la resena r pasa a llamarse "r#k" para que 06_trust.py la
    cuente como una contribucion propia (README §4.2).
    """
    filas: list[dict] = []
    for product_id, universo in universos.items():
        sorteadas = [rng.choice(universo) for _ in range(len(universo))]
        if len(sorteadas) != len(universo):          # control README §6.3
            raise RuntimeError(f"tamano de remuestreo incorrecto en {product_id}")
        repeticiones: collections.Counter = collections.Counter()
        for review_id in sorteadas:
            k = repeticiones[review_id]
            repeticiones[review_id] += 1
            sufijo = "" if k == 0 else f"#{k}"
            for fila in menciones_por_resena[(review_id, product_id)]:
                filas.append({**fila, "review_id": f"{fila['review_id']}{sufijo}"})
    return filas


def trust_map_replica(trust_base: dict, filas: list[dict]) -> dict:
    """Trust de cada copia: el de la resena original (README §4.3)."""
    mapa = {}
    for fila in filas:
        clave = (fila["review_id"], fila["product_id"])
        if clave not in mapa:
            original = str(fila["review_id"]).split("#")[0]
            mapa[clave] = trust_base[(_num(original), fila["product_id"])]
    return mapa


def _num(review_id: str):
    try:
        return int(review_id)
    except ValueError:
        return review_id


def ranking_de(trust06, gen08, laf, productos, filas, trust_map):
    """Hechos D -> 14 corridas por aspecto -> ranking por perfil."""
    evidencia: dict = {}
    menciones = collections.Counter()
    trust06.add_aspect_evidence(filas, trust_map, evidencia, menciones)
    hechos = trust06.build_product_aspect_rows(
        trust06.group_review_evidence(evidencia), menciones, {}, ESTRATEGIA, DATASET_KEY
    )
    por_aspecto = {}
    for aspecto in ASPECTOS:
        prefs = {a: 0.0 for a in ASPECTOS}
        prefs[aspecto] = 1.0
        programa = gen08.build_laf1(productos, hechos, prefs, ESTRATEGIA, dataset_key=DATASET_KEY)
        payload = laf["zero"](laf["parser"].parse(programa).to_request_payload())
        por_aspecto[aspecto] = laf["mapper"].map(laf["client"].build_graph(payload), [])

    rankings = {}
    for nombre, prefs in PERFILES.items():
        evaluaciones = [
            laf["Eval"](aspect=a, weight=float(prefs[a]), ranking=por_aspecto[a])
            for a in ASPECTOS if prefs[a] > 0
        ]
        base = por_aspecto["sabor"]        # solo aporta nombres/metadatos
        combinado = laf["combinar"](base, evaluaciones, prefs)
        rankings[nombre] = [(e.entity_id, float(e.final_score)) for e in combinado]
    return rankings, hechos


# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replicas", type=int, default=REPLICAS)
    ap.add_argument("--semilla", type=int, default=SEMILLA)
    args = ap.parse_args()

    t_inicio = time.time()
    trust06, gen08, laf = cargar_modulos()
    sb = conectar()

    trust_rows = leer_todo(sb, "review_trust", "id,review_id,product_id,trust_score",
                           dataset_key=DATASET_KEY)
    mention_rows = leer_todo(
        sb, "review_aspects",
        "id,review_id,product_id,aspect,polarity,extraction_confidence",
        dataset_key=DATASET_KEY,
    )
    from product_scope import require_included_product_ids
    incluidos = require_included_product_ids(sb, DATASET_KEY, stage_name="validacion_robustez")
    productos = gen08.load_products(sb, incluidos, top_n=20)

    print("=" * 74)
    print("bootstrap_ranking.py  |  experimento 2 — robustez del orden")
    print("=" * 74)
    print(f"  dataset_key : {DATASET_KEY}")
    print(f"  fecha       : {date.today().isoformat()}")
    print(f"  semilla     : {args.semilla}  (replica i usa {args.semilla}+i)")
    print(f"  replicas    : {args.replicas}")
    print(f"  estrategia  : {ESTRATEGIA}   perfiles: {', '.join(PERFILES)}")
    print(f"  resenas     : {len(trust_rows)} con trust individual")
    print(f"  menciones   : {len(mention_rows)} en review_aspects")
    print(f"  productos   : {len(productos)}")
    print("-" * 74)

    trust_base = {(r["review_id"], r["product_id"]): float(r["trust_score"]) for r in trust_rows}

    # universos de remuestreo: resenas con al menos una mencion, por producto
    menciones_por_resena = collections.defaultdict(list)
    for fila in mention_rows:
        menciones_por_resena[(fila["review_id"], fila["product_id"])].append(fila)
    universos = collections.defaultdict(list)
    for review_id, product_id in menciones_por_resena:
        universos[product_id].append(review_id)
    universos = {p: sorted(v) for p, v in sorted(universos.items())}
    print("  universo de remuestreo (resenas con >=1 mencion) por producto:")
    print(f"    total {sum(len(v) for v in universos.values())} resenas en "
          f"{len(universos)} productos; min {min(len(v) for v in universos.values())}, "
          f"max {max(len(v) for v in universos.values())}")

    # ---- replica 0: control sin remuestreo (README §6.2) -------------------
    trust_map_0 = {k: v for k, v in trust_base.items()}
    rankings_0, hechos_0 = ranking_de(trust06, gen08, laf, productos, mention_rows, trust_map_0)
    print(f"  control (replica 0, sin remuestreo): {len(hechos_0)} hechos D")

    ref = ROOT / "validacion_laf1/salidas/battery_multicriterio_mlm194329_20260528_142014.json"
    if ref.exists():
        bateria = json.load(open(ref, encoding="utf-8"))
        equivalencias = {"neutro": "neutral", "solo_sabor": "solo_sabor"}
        for perfil, clave in equivalencias.items():
            mio = [pid for pid, _ in rankings_0[perfil]]
            suyo = [r["product"] for r in bateria[clave]]
            if mio != suyo:
                for a, b in zip(mio, suyo):
                    if a != b:
                        print(f"    DIFIERE: {a}  vs  {b}")
                raise SystemExit(
                    f"ERROR: la replica sin remuestreo NO reproduce la bateria en '{perfil}'. "
                    "Se aborta antes de generar las replicas (README §6.2)."
                )
            print(f"    control {perfil:11s}: orden IGUAL a la bateria "
                  f"({len(mio)}/{len(mio)}) [bateria: {clave}]")
    else:
        print("    AVISO: no se encontro la salida de la bateria; control parcial.")

    base_scores = {p: dict(rankings_0[p]) for p in PERFILES}
    base_orden = {p: [pid for pid, _ in rankings_0[p]] for p in PERFILES}
    ids = base_orden["neutro"]
    alpha_0 = {
        (h["product_id"], h["aspect"]): h["agg_confidence"]
        for h in hechos_0 if h["polarity"] == "pos"
    }

    # ---- replicas ----------------------------------------------------------
    rho = {p: [] for p in PERFILES}
    puestos = {p: collections.defaultdict(list) for p in PERFILES}
    top3_base = {p: set(base_orden[p][:3]) for p in PERFILES}
    top3_ok = {p: 0 for p in PERFILES}
    ganador_ok = {p: 0 for p in PERFILES}
    alpha = {a: collections.defaultdict(list) for a in BAJA_COBERTURA}
    sin_hecho = {a: collections.Counter() for a in BAJA_COBERTURA}
    neg_presente = collections.Counter()
    filas_csv = {p: [] for p in PERFILES}

    t0 = time.time()
    for i in range(1, args.replicas + 1):
        rng = random.Random(args.semilla + i)
        filas = remuestrear(menciones_por_resena, universos, rng)
        tmap = trust_map_replica(trust_base, filas)
        rankings, hechos = ranking_de(trust06, gen08, laf, productos, filas, tmap)

        for perfil in PERFILES:
            scores = dict(rankings[perfil])
            x = [base_scores[perfil][pid] for pid in ids]
            y = [scores.get(pid, 0.0) for pid in ids]
            rho[perfil].append(spearman(x, y))
            orden = [pid for pid, _ in rankings[perfil]]
            for puesto, pid in enumerate(orden, 1):
                puestos[perfil][pid].append(puesto)
                filas_csv[perfil].append({
                    "replica": i, "semilla": args.semilla + i,
                    "puesto": puesto, "product_id": pid,
                    "score": round(scores.get(pid, 0.0), 6),
                })
            if set(orden[:3]) == top3_base[perfil]:
                top3_ok[perfil] += 1
            if orden[0] == base_orden[perfil][0]:
                ganador_ok[perfil] += 1

        con_hecho = {(h["product_id"], h["aspect"]): h for h in hechos if h["polarity"] == "pos"}
        for aspecto in BAJA_COBERTURA:
            for pid in productos:
                h = con_hecho.get((pid, aspecto))
                if h is None:
                    sin_hecho[aspecto][pid] += 1
                else:
                    alpha[aspecto][pid].append(float(h["agg_confidence"]))
        for h in hechos:
            if h["polarity"] == "neg":
                neg_presente[(h["product_id"], h["aspect"])] += 1

        if i % 25 == 0 or i == args.replicas:
            transcurrido = time.time() - t0
            print(f"    replica {i:3d}/{args.replicas}  ({transcurrido:.1f} s, "
                  f"{transcurrido/i:.2f} s por replica)")

    # ---- salidas -----------------------------------------------------------
    SALIDAS.mkdir(exist_ok=True)
    hoy = date.today().isoformat().replace("-", "")
    for perfil in PERFILES:
        destino = SALIDAS / f"rankings_{perfil}_{hoy}.csv"
        with open(destino, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["replica", "semilla", "puesto", "product_id", "score"])
            w.writeheader()
            w.writerows(filas_csv[perfil])

    with open(SALIDAS / f"alpha_baja_cobertura_{hoy}.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["aspecto", "product_id", "alpha_original", "n_replicas_con_hecho",
                    "media", "p5", "p95", "replicas_sin_hecho"])
        for aspecto in BAJA_COBERTURA:
            for pid in sorted(productos):
                vals = alpha[aspecto][pid]
                w.writerow([
                    aspecto, pid,
                    alpha_0.get((pid, aspecto), ""),
                    len(vals),
                    round(statistics.fmean(vals), 4) if vals else "",
                    round(percentil(vals, 0.05), 4) if vals else "",
                    round(percentil(vals, 0.95), 4) if vals else "",
                    sin_hecho[aspecto][pid],
                ])

    resumen = {
        "dataset_key": DATASET_KEY, "fecha": date.today().isoformat(),
        "semilla": args.semilla, "replicas": args.replicas,
        "estrategia": ESTRATEGIA,
        "resenas_con_trust": len(trust_rows), "menciones": len(mention_rows),
        "productos": len(productos),
        "segundos_por_replica": round((time.time() - t0) / args.replicas, 3),
        "perfiles": {},
    }
    for perfil in PERFILES:
        r = rho[perfil]
        resumen["perfiles"][perfil] = {
            "rho_media": round(statistics.fmean(r), 4),
            "rho_min": round(min(r), 4),
            "rho_p5": round(percentil(r, 0.05), 4),
            "rho_p95": round(percentil(r, 0.95), 4),
            "top3_conservado": round(top3_ok[perfil] / args.replicas, 4),
            "ganador_conservado": round(ganador_ok[perfil] / args.replicas, 4),
            "cumple_criterio_fracaso": bool(statistics.fmean(r) < UMBRAL_FRACASO_RHO),
            "puestos": {
                pid: {
                    "puesto_original": base_orden[perfil].index(pid) + 1,
                    "mediana": round(statistics.median(puestos[perfil][pid]), 1),
                    "p5": round(percentil(puestos[perfil][pid], 0.05), 1),
                    "p95": round(percentil(puestos[perfil][pid], 0.95), 1),
                }
                for pid in base_orden[perfil]
            },
        }
    resumen["hechos_negativos_inestables"] = sorted(
        [
            {"product_id": pid, "aspect": asp, "replicas_con_hecho_negativo": n,
             "presente_en_original": bool(any(
                 h["product_id"] == pid and h["aspect"] == asp and h["polarity"] == "neg"
                 for h in hechos_0))}
            for (pid, asp), n in neg_presente.items()
            if 0 < n < args.replicas
        ],
        key=lambda d: d["replicas_con_hecho_negativo"],
    )
    with open(SALIDAS / f"resumen_{hoy}.json", "w", encoding="utf-8") as fh:
        json.dump(resumen, fh, ensure_ascii=False, indent=1)

    # ---- impresion ---------------------------------------------------------
    print("-" * 74)
    for perfil in PERFILES:
        d = resumen["perfiles"][perfil]
        print(f"  [{perfil}]  rho media={d['rho_media']:.4f}  min={d['rho_min']:.4f}  "
              f"p5={d['rho_p5']:.4f}  p95={d['rho_p95']:.4f}")
        print(f"              top-3 conservado {100*d['top3_conservado']:.1f} %  |  "
              f"ganador {100*d['ganador_conservado']:.1f} %  |  "
              f"criterio de fracaso (rho<0,80): "
              f"{'SE CUMPLE' if d['cumple_criterio_fracaso'] else 'no se cumple'}")
    print(f"\n  total: {time.time() - t_inicio:.1f} s")
    print(f"  -> salidas/rankings_*_{hoy}.csv, alpha_baja_cobertura_{hoy}.csv, resumen_{hoy}.json")
    print("  PROXIMO PASO: python validacion_robustez/figura_intervalos.py")


if __name__ == "__main__":
    main()
