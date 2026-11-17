# -*- coding: utf-8 -*-
"""Experimento 1: analisis POST HOC del desacuerdo (NO pre-registrado).

Se escribe DESPUES de ver las respuestas y asi queda declarado. No cambia
ninguna metrica pre-registrada ni el criterio de fracaso: solo intenta explicar
POR QUE juez y sistema difieren, contrastando dos hipotesis sobre que criterio
esta usando cada uno.

  H1 (juez)    = gana el lado con MENOS menciones negativas entre los 15 mostrados.
  H2 (sistema) = gana el lado con MAS menciones de sabor en total en el corpus.

Uso:  python validacion_juicio_ciego/analisis_post_hoc.py
"""
from __future__ import annotations

import collections
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SALIDAS = C.HERE / "salidas"


def normalizar_veredicto(valor: str) -> str | None:
    v = C.sin_acentos((valor or "").strip().lower())
    if v in ("a", "producto a"):
        return "A"
    if v in ("b", "producto b"):
        return "B"
    if v.startswith("no_puedo") or v.startswith("no puedo") or v.startswith("empat"):
        return "no_puedo_decidir"
    return None


def main() -> None:
    tabla = sorted(SALIDAS.glob("tabla_pares_con_puntajes_sabor_*.csv"))[-1]
    frags = sorted(SALIDAS.glob("fragmentos_usados_sabor_*.csv"))[-1]
    pares = {r["par_id"]: r for r in csv.DictReader(open(tabla, encoding="utf-8"))}
    mostrados = list(csv.DictReader(open(frags, encoding="utf-8")))
    respuestas = {
        r["par_id"]: normalizar_veredicto(r.get("veredicto", ""))
        for r in csv.DictReader(
            open(C.HERE / "respuestas" / "planilla_juez_1.csv", encoding="utf-8-sig")
        )
    }

    sb = C.conectar()
    _trust, menciones, _inc, nombres = C.cargar_corpus(sb)
    sabor = [m for m in menciones if m["aspect"] == C.ASPECTO]

    C.encabezado(
        "analisis_post_hoc.py", "—",
        n_resenas=0, n_menciones=len(sabor),
        extra="POST HOC — declarado, no pre-registrado",
    )

    # polaridad de cada fragmento mostrado, por (producto, texto)
    polaridad = {}
    for m in sabor:
        polaridad[(m["product_id"], C.normalizar_fragmento(m["sentence_excerpt"]))] = m["polarity"]

    conteo = collections.defaultdict(collections.Counter)
    for f in mostrados:
        clave = (f["product_id"], C.normalizar_fragmento(f["fragmento_original"]))
        conteo[(f["par_id"], f["lado"])][polaridad.get(clave, "?")] += 1

    total_menciones = collections.Counter(m["product_id"] for m in sabor)

    filas = []
    for par_id in sorted(pares):
        p = pares[par_id]
        pa, pb = p["lado_A_product_id"], p["lado_B_product_id"]
        na, nb = conteo[(par_id, "A")]["neg"], conteo[(par_id, "B")]["neg"]
        ta, tb = total_menciones[pa], total_menciones[pb]
        h1 = None if na == nb else ("A" if na < nb else "B")     # menos criticas mostradas
        h2 = None if ta == tb else ("A" if ta > tb else "B")     # mas evidencia en el corpus
        filas.append({
            "par_id": par_id, "franja": p["franja"],
            "sistema": p["prediccion_sistema"], "ana": respuestas.get(par_id),
            "neg_A": na, "neg_B": nb, "tot_A": ta, "tot_B": tb,
            "h1_menos_criticas": h1, "h2_mas_evidencia": h2,
        })

    def acuerdo(campo_pred: str, campo_ref: str, filtro=lambda f: True) -> tuple[int, int]:
        sub = [
            f for f in filas
            if filtro(f) and f[campo_pred] in ("A", "B") and f[campo_ref] in ("A", "B")
        ]
        return sum(1 for f in sub if f[campo_pred] == f[campo_ref]), len(sub)

    print(f"  {'par':4s} {'franja':8s} {'sist':5s} {'ana':5s} "
          f"{'negA/negB':10s} {'totA/totB':12s} {'H1':4s} {'H2':4s}")
    for f in filas:
        ana = {"A": "A", "B": "B", "no_puedo_decidir": "—", None: "?"}[f["ana"]]
        print(f"  {f['par_id']:4s} {f['franja']:8s} {f['sistema']:5s} {ana:5s} "
              f"{f['neg_A']:4d}/{f['neg_B']:<5d} {f['tot_A']:5d}/{f['tot_B']:<6d} "
              f"{(f['h1_menos_criticas'] or '—'):4s} {(f['h2_mas_evidencia'] or '—'):4s}")

    print()
    ok, n = acuerdo("h2_mas_evidencia", "sistema")
    print(f"  H2: el sistema elige el lado con MAS menciones de sabor  -> {ok}/{n}"
          f" = {100*ok/n:.1f} %" if n else "  H2: sin pares comparables")
    ok, n = acuerdo("h1_menos_criticas", "ana")
    print(f"  H1: Ana elige el lado con MENOS criticas mostradas       -> {ok}/{n}"
          f" = {100*ok/n:.1f} %" if n else "  H1: sin pares comparables")
    ok, n = acuerdo("ana", "sistema")
    print(f"  Acuerdo Ana - sistema (referencia)                       -> {ok}/{n}"
          f" = {100*ok/n:.1f} %" if n else "")

    # ¿Ana dice "no puedo decidir" cuando no hay criticas en ninguno de los dos?
    sin_criticas = [f for f in filas if f["neg_A"] == 0 and f["neg_B"] == 0]
    npd_sin = sum(1 for f in sin_criticas if f["ana"] == "no_puedo_decidir")
    con_criticas = [f for f in filas if f["neg_A"] > 0 or f["neg_B"] > 0]
    npd_con = sum(1 for f in con_criticas if f["ana"] == "no_puedo_decidir")
    print()
    print(f"  pares SIN ninguna critica mostrada: {len(sin_criticas)}; "
          f"Ana respondio 'no puedo decidir' en {npd_sin}")
    print(f"  pares CON alguna critica mostrada : {len(con_criticas)}; "
          f"Ana respondio 'no puedo decidir' en {npd_con}")

    destino = SALIDAS / f"analisis_post_hoc_{C.hoy()}.csv"
    with open(destino, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    print(f"\n  -> {destino.relative_to(C.ROOT)}")


if __name__ == "__main__":
    main()
