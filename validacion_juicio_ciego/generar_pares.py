# -*- coding: utf-8 -*-
"""Experimento 1, paso 1: elegir los 20 pares y guardar la tabla PRIVADA.

Implementa el README de pre-registro, secciones 4.4, 4.5, 4.7 y 5.1. No se
desvia de ese documento: si algo no se puede cumplir (cuotas, tope de
apariciones), el script falla y no produce nada.

SALIDA PRIVADA: salidas/tabla_pares_con_puntajes_<fecha>.csv
Este archivo NO se le muestra a los jueces: contiene los puntajes LAF.

Uso:  python validacion_juicio_ciego/generar_pares.py
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SALIDAS = C.HERE / "salidas"


def clasificar_franjas(diferencias: list[float]) -> tuple[float, float]:
    """Cortes en terciles de las diferencias posibles (README §4.5)."""
    ordenadas = sorted(diferencias)
    n = len(ordenadas)
    return ordenadas[n // 3], ordenadas[(2 * n) // 3]


def franja_de(delta: float, corte1: float, corte2: float) -> str:
    if delta <= corte1:
        return "chica"
    if delta <= corte2:
        return "mediana"
    return "grande"


def elegir_pares(candidatos_por_franja: dict[str, list], rng: random.Random):
    """Selecciona respetando cuotas y tope de apariciones (README §5.1).

    Determinista dada la semilla. Falla con error si no lo logra en MAX_INTENTOS.
    """
    for intento in range(1, C.MAX_INTENTOS + 1):
        elegidos: list = []
        apariciones: collections.Counter = collections.Counter()
        completo = True
        for franja in ("grande", "mediana", "chica"):
            disponibles = list(candidatos_por_franja[franja])
            rng.shuffle(disponibles)
            tomados = 0
            for par in disponibles:
                if tomados == C.CUOTAS[franja]:
                    break
                a, b = par["producto_a"], par["producto_b"]
                if apariciones[a] >= C.TOPE_APARICIONES or apariciones[b] >= C.TOPE_APARICIONES:
                    continue
                elegidos.append(dict(par, franja=franja))
                apariciones[a] += 1
                apariciones[b] += 1
                tomados += 1
            if tomados < C.CUOTAS[franja]:
                completo = False
                break
        if completo:
            return elegidos, apariciones, intento
    raise SystemExit(
        f"ERROR: no se pudo armar el conjunto de pares en {C.MAX_INTENTOS} intentos "
        f"con cuotas {C.CUOTAS} y tope {C.TOPE_APARICIONES}. "
        "No se relaja ninguna restriccion: revisar el pre-registro."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aspecto", default=C.ASPECTO,
                    help="sabor (principal) o aroma (repeticion, README §11)")
    args = ap.parse_args()
    aspecto = args.aspecto

    trust06, gen08, laf = C.cargar_modulos()
    sb = C.conectar()
    trust_rows, mention_rows, incluidos, nombres = C.cargar_corpus(sb)

    del_aspecto = [r for r in mention_rows if r["aspect"] == aspecto]
    C.encabezado(
        "generar_pares.py", C.SEMILLA_PARES,
        n_resenas=len(trust_rows), n_menciones=len(del_aspecto),
        extra=f"productos incluidos: {len(incluidos)}",
    )

    # --- puntaje LAF del aspecto -------------------------------------------
    hechos = C.construir_hechos(trust06, trust_rows, mention_rows)
    productos = gen08.load_products(sb, incluidos, top_n=20)
    puntajes_atomo = C.puntaje_por_aspecto(gen08, laf, productos, hechos, aspecto)
    puntajes = {C.id_producto(k): v for k, v in puntajes_atomo.items()}
    print(f"  hechos D reconstruidos: {len(hechos)}")
    print(f"  productos con puntaje LAF de {aspecto}: {len(puntajes)}")

    # --- elegibilidad -------------------------------------------------------
    menciones_por_producto = collections.Counter(r["product_id"] for r in del_aspecto)
    polaridad = collections.Counter((r["product_id"], r["polarity"]) for r in del_aspecto)
    unicos = collections.defaultdict(set)
    for r in del_aspecto:
        unicos[r["product_id"]].add(C.normalizar_fragmento(r["sentence_excerpt"]))

    elegibles = sorted(
        p for p in incluidos
        if menciones_por_producto[p] >= C.MIN_MENCIONES and p in puntajes
    )
    no_elegibles = sorted(set(incluidos) - set(elegibles))
    print(f"  elegibles (>= {C.MIN_MENCIONES} menciones de {aspecto}): "
          f"{len(elegibles)} de {len(incluidos)}")
    if no_elegibles:
        for p in no_elegibles:
            print(f"    excluido {p}: {menciones_por_producto[p]} menciones")
    if len(elegibles) < 2:
        raise SystemExit("ERROR: menos de dos productos elegibles.")

    # --- pares, franjas -----------------------------------------------------
    todos = []
    for a, b in itertools.combinations(elegibles, 2):
        todos.append({
            "producto_a": a, "producto_b": b,
            "delta": abs(puntajes[a] - puntajes[b]),
        })
    empatados = [p for p in todos if p["delta"] == 0.0]
    utiles = [p for p in todos if p["delta"] > 0.0]
    print(f"  pares posibles: {len(todos)}  |  descartados por empate exacto: {len(empatados)}")
    for p in empatados:
        print(f"    empate {p['producto_a']} = {p['producto_b']} ({puntajes[p['producto_a']]:.4f})")

    corte1, corte2 = clasificar_franjas([p["delta"] for p in utiles])
    print(f"  cortes de tercil: chica <= {corte1:.4f} < mediana <= {corte2:.4f} < grande")
    print(f"  delta maximo: {max(p['delta'] for p in utiles):.4f}")

    por_franja = collections.defaultdict(list)
    for p in utiles:
        por_franja[franja_de(p["delta"], corte1, corte2)].append(p)
    for f in ("grande", "mediana", "chica"):
        print(f"    {f:8s}: {len(por_franja[f])} pares candidatos "
              f"(se necesitan {C.CUOTAS[f]})")

    # --- seleccion ----------------------------------------------------------
    rng_pares = random.Random(C.SEMILLA_PARES)
    elegidos, apariciones, intento = elegir_pares(por_franja, rng_pares)
    print(f"  seleccion lograda en el intento {intento}; "
          f"{len(elegidos)} pares, max apariciones de un producto: {max(apariciones.values())}")

    # --- rotacion A/B -------------------------------------------------------
    rng_rot = random.Random(C.SEMILLA_ROTACION)
    filas = []
    for i, par in enumerate(sorted(elegidos, key=lambda p: (p["franja"], p["producto_a"], p["producto_b"])), 1):
        p1, p2 = par["producto_a"], par["producto_b"]
        if rng_rot.random() < 0.5:
            lado_a, lado_b = p1, p2
        else:
            lado_a, lado_b = p2, p1
        sa, sb_ = puntajes[lado_a], puntajes[lado_b]
        filas.append({
            "par_id": f"P{i:02d}",
            "franja": par["franja"],
            "delta_laf": round(par["delta"], 6),
            "lado_A_product_id": lado_a,
            "lado_A_nombre": nombres.get(lado_a, lado_a),
            "lado_A_puntaje_laf": round(sa, 6),
            "lado_A_menciones": menciones_por_producto[lado_a],
            "lado_A_fragmentos_unicos": len(unicos[lado_a]),
            "lado_A_pos": polaridad[(lado_a, "pos")],
            "lado_A_neu": polaridad[(lado_a, "neu")],
            "lado_A_neg": polaridad[(lado_a, "neg")],
            "lado_B_product_id": lado_b,
            "lado_B_nombre": nombres.get(lado_b, lado_b),
            "lado_B_puntaje_laf": round(sb_, 6),
            "lado_B_menciones": menciones_por_producto[lado_b],
            "lado_B_fragmentos_unicos": len(unicos[lado_b]),
            "lado_B_pos": polaridad[(lado_b, "pos")],
            "lado_B_neu": polaridad[(lado_b, "neu")],
            "lado_B_neg": polaridad[(lado_b, "neg")],
            "prediccion_sistema": "A" if sa > sb_ else "B",
        })

    SALIDAS.mkdir(exist_ok=True)
    destino = SALIDAS / f"tabla_pares_con_puntajes_{aspecto}_{C.hoy()}.csv"
    with open(destino, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)

    print("-" * 74)
    print(f"  PRIVADO -> {destino.relative_to(C.ROOT)}")
    print("  (contiene los puntajes LAF: NO se entrega a los jueces)")
    print()
    print(f"  {'par':4s} {'franja':9s} {'delta':7s} {'pred':4s}  A  vs  B")
    for f in filas:
        print(f"  {f['par_id']:4s} {f['franja']:9s} {f['delta_laf']:.4f}  {f['prediccion_sistema']:3s}  "
              f"{f['lado_A_nombre'][:30]:30s} | {f['lado_B_nombre'][:30]}")
    print()
    print("  apariciones por producto:")
    for pid, n in apariciones.most_common():
        print(f"    {n}x  {nombres.get(pid, pid)[:55]}")
    print()
    print("  PROXIMO PASO: python validacion_juicio_ciego/generar_planillas.py")


if __name__ == "__main__":
    main()
