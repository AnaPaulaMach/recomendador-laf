# -*- coding: utf-8 -*-
"""Experimento 1, paso 3: analizar las respuestas de los jueces.

ESCRITO Y CONGELADO ANTES DE RECIBIR NINGUNA RESPUESTA (README §8).
Implementa exactamente las metricas del pre-registro; no agrega ninguna
metrica decidida despues de mirar los datos.

Entrada:  respuestas/planilla_juez_*.csv  (las que devuelven los jueces)
          salidas/tabla_pares_con_puntajes_<aspecto>_<fecha>.csv  (privada)
Salida:   RESULTADOS.md

Uso:  python validacion_juicio_ciego/analizar_respuestas.py
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import itertools
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

RESPUESTAS = C.HERE / "respuestas"
SALIDAS = C.HERE / "salidas"
CATEGORIAS = ("A", "B", "no_puedo_decidir")
UMBRAL_FRACASO = 0.70   # README §9


def normalizar_veredicto(valor: str) -> str | None:
    v = C.sin_acentos((valor or "").strip().lower())
    if v in ("a", "producto a", "el a"):
        return "A"
    if v in ("b", "producto b", "el b"):
        return "B"
    # "empate"/"empatados" se normaliza a la tercera categoria: enmienda del
    # 2026-09-10, declarada en README.md. No cambia ninguna cifra (con un solo
    # juez, ambos caminos excluyen el par igual), solo el motivo de exclusion.
    if (v in ("no_puedo_decidir", "no puedo decidir", "npd", "ninguno", "no se")
            or v.startswith("empat")):
        return "no_puedo_decidir"
    return None


def wilson(exitos: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confianza de Wilson al 95 % para una proporcion."""
    if total == 0:
        return (float("nan"), float("nan"))
    p = exitos / total
    denom = 1 + z * z / total
    centro = (p + z * z / (2 * total)) / denom
    margen = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def fleiss_kappa(conteos: list[list[int]]) -> float | None:
    """Fleiss kappa. conteos[i][j] = jueces que pusieron la categoria j en el item i."""
    n_items = len(conteos)
    if n_items == 0:
        return None
    n = sum(conteos[0])
    if n < 2 or any(sum(fila) != n for fila in conteos):
        return None
    p_i = [
        (sum(c * c for c in fila) - n) / (n * (n - 1))
        for fila in conteos
    ]
    p_barra = sum(p_i) / n_items
    p_j = [sum(fila[j] for fila in conteos) / (n_items * n) for j in range(len(conteos[0]))]
    p_e = sum(p * p for p in p_j)
    if abs(1 - p_e) < 1e-12:
        return None
    return (p_barra - p_e) / (1 - p_e)


def contar_ciclos(preferencias: list[tuple[str, str]]) -> int:
    """Ciclos de 3 productos (A>B, B>C, C>A) en las respuestas de un juez."""
    gana = collections.defaultdict(set)
    nodos = set()
    for mejor, peor in preferencias:
        gana[mejor].add(peor)
        nodos.update((mejor, peor))
    ciclos = 0
    for a, b, c in itertools.combinations(sorted(nodos), 3):
        for x, y, z in ((a, b, c), (a, c, b)):
            if y in gana[x] and z in gana[y] and x in gana[z]:
                ciclos += 1
    return ciclos


def pct(x: float) -> str:
    return "—" if x != x else f"{100 * x:.1f} %"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--aspecto", default=C.ASPECTO)
    ap.add_argument("--tabla-pares", default=None)
    args = ap.parse_args()

    tabla = Path(args.tabla_pares) if args.tabla_pares else next(
        iter(sorted(SALIDAS.glob(f"tabla_pares_con_puntajes_{args.aspecto}_*.csv"), reverse=True)),
        None,
    )
    if tabla is None:
        raise SystemExit("ERROR: falta la tabla de pares (corré generar_pares.py).")
    pares = {f["par_id"]: f for f in csv.DictReader(open(tabla, encoding="utf-8"))}

    planillas = sorted(RESPUESTAS.glob("planilla_juez_*.csv"))
    if not planillas:
        raise SystemExit(
            f"ERROR: no hay planillas en {RESPUESTAS}. Poné ahí las que devuelvan los jueces."
        )

    respuestas: dict[str, dict[str, dict]] = {}
    for ruta in planillas:
        juez = ruta.stem.replace("planilla_juez_", "juez_")
        with open(ruta, encoding="utf-8-sig") as fh:
            filas = list(csv.DictReader(fh))
        por_par = {}
        for fila in filas:
            par_id = (fila.get("par_id") or "").strip()
            if par_id not in pares:
                continue
            por_par[par_id] = {
                "veredicto": normalizar_veredicto(fila.get("veredicto", "")),
                "reconocio": C.sin_acentos((fila.get("reconoci_producto") or "").strip().lower()).startswith("s"),
                "comentario": (fila.get("comentario") or "").strip(),
                "crudo": (fila.get("veredicto") or "").strip(),
            }
        respuestas[juez] = por_par

    jueces = sorted(respuestas)
    C.encabezado(
        "analizar_respuestas.py", "—",
        n_resenas=0, n_menciones=0,
        extra=f"jueces: {len(jueces)} ({', '.join(jueces)}) · pares: {len(pares)}",
    )

    ilegibles = [
        (j, p, r["crudo"]) for j in jueces for p, r in respuestas[j].items()
        if r["veredicto"] is None
    ]
    faltantes = [(j, p) for j in jueces for p in pares if p not in respuestas[j]]
    if ilegibles:
        print("  AVISO: respuestas que no se pudieron interpretar (se tratan como faltantes):")
        for j, p, crudo in ilegibles[:20]:
            print(f"    {j} {p}: {crudo!r}")
    if faltantes:
        print(f"  AVISO: {len(faltantes)} celdas sin responder.")

    # --- veredicto mayoritario (README §4.9) --------------------------------
    resultados = []
    for par_id, par in pares.items():
        votos = [respuestas[j].get(par_id, {}).get("veredicto") for j in jueces]
        votos_validos = [v for v in votos if v is not None]
        conteo = collections.Counter(votos_validos)
        npd = conteo.get("no_puedo_decidir", 0)
        mayoria, motivo = None, ""
        if len(votos_validos) < len(jueces):
            motivo = "respuestas faltantes o ilegibles"
        else:
            # Regla del pre-registro §4.9 generalizada a n jueces: hay mayoria
            # cuando una de las dos alternativas supera la mitad de los votos.
            # Con n=3 equivale exactamente a la regla escrita (>=2 votos, y por
            # lo tanto quedan excluidos "los tres distintos" y ">=2 no puedo
            # decidir"). Con n=1 el veredicto del unico juez es la mayoria,
            # salvo que sea "no puedo decidir".
            for cat in ("A", "B"):
                if conteo.get(cat, 0) > len(jueces) / 2:
                    mayoria = cat
            if mayoria is None:
                if npd > len(jueces) / 2:
                    motivo = "mayoria de 'no puedo decidir'"
                elif len(jueces) >= 3 and len(set(votos_validos)) == len(votos_validos):
                    motivo = "los jueces respondieron todos distinto"
                else:
                    motivo = "sin mayoria en A ni en B"
        acierta = None if mayoria is None else (mayoria == par["prediccion_sistema"])
        resultados.append({
            "par_id": par_id,
            "franja": par["franja"],
            "delta": float(par["delta_laf"]),
            "prediccion": par["prediccion_sistema"],
            "votos": votos,
            "mayoria": mayoria,
            "motivo_exclusion": motivo,
            "acierta": acierta,
            "unanime": len(set(votos_validos)) == 1 and len(votos_validos) == len(jueces),
        })

    con_mayoria = [r for r in resultados if r["mayoria"] is not None]
    aciertos = sum(1 for r in con_mayoria if r["acierta"])
    lo, hi = wilson(aciertos, len(con_mayoria))

    por_franja = {}
    for franja in ("grande", "mediana", "chica"):
        sub = [r for r in con_mayoria if r["franja"] == franja]
        ok = sum(1 for r in sub if r["acierta"])
        flo, fhi = wilson(ok, len(sub))
        por_franja[franja] = {
            "n": len(sub), "ok": ok,
            "prop": (ok / len(sub)) if sub else float("nan"),
            "lo": flo, "hi": fhi,
            "excluidos": sum(1 for r in resultados if r["franja"] == franja and r["mayoria"] is None),
        }

    # --- acuerdo entre jueces ----------------------------------------------
    matriz = []
    for r in resultados:
        votos_validos = [v for v in r["votos"] if v is not None]
        if len(votos_validos) != len(jueces):
            continue
        matriz.append([sum(1 for v in votos_validos if v == cat) for cat in CATEGORIAS])
    kappa = fleiss_kappa(matriz)
    unanimes = sum(1 for r in resultados if r["unanime"])

    # --- ciclos y reconocimiento -------------------------------------------
    ciclos, reconocidos = {}, {}
    for j in jueces:
        prefs = []
        for par_id, par in pares.items():
            v = respuestas[j].get(par_id, {}).get("veredicto")
            if v in ("A", "B"):
                mejor = par[f"lado_{v}_product_id"]
                peor = par[f"lado_{'B' if v == 'A' else 'A'}_product_id"]
                prefs.append((mejor, peor))
        ciclos[j] = contar_ciclos(prefs)
        reconocidos[j] = sum(1 for p in pares if respuestas[j].get(p, {}).get("reconocio"))

    grande = por_franja["grande"]
    fracaso = grande["n"] > 0 and grande["prop"] < UMBRAL_FRACASO

    # --- impresion ----------------------------------------------------------
    print("-" * 74)
    print(f"  pares con mayoria: {len(con_mayoria)} de {len(pares)}")
    print(f"  ACUERDO SISTEMA-JUECES: {aciertos}/{len(con_mayoria)} = "
          f"{pct(aciertos/len(con_mayoria) if con_mayoria else float('nan'))} "
          f"(IC95 Wilson {pct(lo)}–{pct(hi)})")
    for f in ("grande", "mediana", "chica"):
        d = por_franja[f]
        print(f"    {f:8s}: {d['ok']}/{d['n']} = {pct(d['prop'])} "
              f"(IC95 {pct(d['lo'])}–{pct(d['hi'])}) · excluidos {d['excluidos']}")
    print(f"  Fleiss kappa: {kappa:.3f}" if kappa is not None
          else f"  Fleiss kappa: no aplica ({len(jueces)} juez/jueces)")
    if len(jueces) >= 2:
        print(f"  pares unanimes: {unanimes}/{len(pares)} = {pct(unanimes/len(pares))}")
    else:
        print("  pares unanimes: no aplica (un solo juez; seria 100 % por definicion)")
    print()
    print(f"  CRITERIO DE FRACASO (franja grande < {UMBRAL_FRACASO:.0%}): "
          f"{'SE CUMPLE — el ranking por aspecto NO refleja la lectura humana' if fracaso else 'no se cumple'}")

    # --- RESULTADOS.md ------------------------------------------------------
    md = []
    md.append("# Experimento 1 — Juicio ciego por pares · RESULTADOS\n")
    md.append(f"**Fecha del análisis:** {date.today().isoformat()}  ")
    md.append(f"**Snapshot:** `{C.DATASET_KEY}` · aspecto **{args.aspecto}** · estrategia D  ")
    md.append(f"**Tabla de pares:** `{tabla.name}` · semillas {C.SEMILLA_PARES} / "
              f"{C.SEMILLA_FRAGMENTOS} / {C.SEMILLA_ROTACION}  ")
    md.append(f"**Jueces:** {len(jueces)}\n")
    md.append("> Las definiciones, las métricas y el criterio de fracaso están fijados en\n"
              "> `README.md` **antes** de correr y antes de recibir respuestas. Este archivo\n"
              "> sólo los aplica.\n")

    md.append("## 1. Resultado principal\n")
    md.append(f"- Pares con veredicto mayoritario: **{len(con_mayoria)} de {len(pares)}**.")
    md.append(f"- **Acuerdo sistema–jueces: {aciertos}/{len(con_mayoria)} = "
              f"{pct(aciertos/len(con_mayoria) if con_mayoria else float('nan'))}** "
              f"(IC 95 % de Wilson: {pct(lo)} – {pct(hi)}).\n")
    md.append("| Franja | Pares con mayoría | Acuerdo | IC 95 % | Excluidos |")
    md.append("|---|---:|---:|---|---:|")
    for f in ("grande", "mediana", "chica"):
        d = por_franja[f]
        md.append(f"| {f} | {d['n']} | {d['ok']}/{d['n']} = {pct(d['prop'])} | "
                  f"{pct(d['lo'])} – {pct(d['hi'])} | {d['excluidos']} |")
    md.append("")
    md.append(f"**Criterio de fracaso pre-registrado** (acuerdo < 70 % en la franja grande): "
              f"**{'SE CUMPLE' if fracaso else 'no se cumple'}**.")
    if fracaso:
        md.append("\n> El ranking por aspecto no refleja la lectura humana de la evidencia.\n"
                  "> Así debe escribirse en la tesis. No se ajustó ningún parámetro.")
    md.append("")

    md.append("## 2. Acuerdo entre jueces\n")
    if len(jueces) >= 2:
        md.append(f"- Fleiss κ = **{kappa:.3f}**" if kappa is not None
                  else "- Fleiss κ: no calculable (faltan respuestas).")
        md.append(f"- Pares unánimes: **{unanimes} de {len(pares)}** ({pct(unanimes/len(pares))}).")
    else:
        md.append("- **No aplica: hay un solo juez.** Fleiss κ necesita al menos dos "
                  "personas, y la unanimidad de un juez consigo mismo es 100 % por "
                  "definición. Este experimento **no mide acuerdo entre jueces**; la "
                  "limitación está declarada en la enmienda del pre-registro.")
    md.append("")
    md.append("| Juez | A | B | No puedo decidir | Ciclos de preferencia | Dijo reconocer producto |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for j in jueces:
        c = collections.Counter(r["veredicto"] for r in respuestas[j].values())
        md.append(f"| {j} | {c.get('A',0)} | {c.get('B',0)} | {c.get('no_puedo_decidir',0)} | "
                  f"{ciclos[j]} | {reconocidos[j]} |")
    md.append("")

    md.append("## 3. Par por par\n")
    md.append("| Par | Franja | Δ LAF | Sistema | " + " | ".join(jueces) +
              " | Mayoría | ¿Coincide? |")
    md.append("|---|---|---:|---|" + "|".join(["---"] * len(jueces)) + "|---|---|")
    for r in sorted(resultados, key=lambda x: x["par_id"]):
        votos = " | ".join((v or "—") for v in r["votos"])
        coincide = "—" if r["acierta"] is None else ("sí" if r["acierta"] else "**no**")
        may = r["mayoria"] or f"excluido ({r['motivo_exclusion']})"
        md.append(f"| {r['par_id']} | {r['franja']} | {r['delta']:.4f} | {r['prediccion']} | "
                  f"{votos} | {may} | {coincide} |")
    md.append("")

    comentarios = [
        (j, p, respuestas[j][p]["comentario"])
        for j in jueces for p in sorted(respuestas[j])
        if respuestas[j][p]["comentario"]
    ]
    md.append("## 4. Comentarios de los jueces\n")
    if comentarios:
        for j, p, texto in comentarios:
            md.append(f"- **{j} · {p}:** {texto}")
    else:
        md.append("(Ningún juez dejó comentarios.)")
    md.append("")

    md.append("## 5. Limitaciones\n")
    md.append(f"- **{len(jueces)} jueces.** Fleiss κ sobre {len(jueces)} jueces y "
              f"{len(pares)} ítems tiene un error estándar grande.")
    md.append("- **Poca potencia.** Con ~7 pares por franja, el intervalo de confianza del "
              "acuerdo es muy ancho: este experimento detecta un fracaso grosero, no "
              "distingue un 70 % de un 90 %. Está declarado en el pre-registro, §9.")
    md.append(f"- **Un solo aspecto** (`{args.aspecto}`), no el ranking multicriterio de 14 "
              "aspectos que ve el usuario.")
    md.append("- **Los pares los eligió el sistema** a partir de su propio puntaje: el diseño "
              "garantiza cobertura de distancias, no representatividad del catálogo.")
    md.append("- **15 fragmentos por lado** son una muestra de hasta 477 menciones: el juez ve "
              "una ventana, el sistema ve todo.")
    md.append("- Los fragmentos vienen **truncados a 200 caracteres** desde la extracción, con "
              "casos conocidos de sentido invertido.")
    md.append("- La evidencia mostrada **incluye menciones `neu`** que el sistema descarta.")
    md.append("- **Anonimización imperfecta:** formatos y tipos de café quedan a la vista.")
    md.append("- Mide **acuerdo con una lectura humana de la evidencia**, no utilidad de la "
              "recomendación ni calidad de la explicación.")
    md.append("")

    md.append("## 6. Análisis posterior\n")
    md.append("El desacuerdo entre la jueza y el sistema resultó **sistemático, no "
              "aleatorio**. El contraste de hipótesis que lo explica se hizo "
              "**después** de ver estas respuestas y por lo tanto no está "
              "pre-registrado: vive aparte, en `RESULTADOS_POST_HOC.md`, con esa "
              "advertencia al frente. Las cifras de este archivo no dependen de él.")
    md.append("")
    md.append("Se corrió además un **lector automático (LLM)** sobre los mismos 20 "
              "pares, pre-registrado aparte en `README_LLM.md`. Es una observación "
              "**secundaria** —no es un juez humano— y se informa en "
              "`RESULTADOS_LLM.md`. Su ampliación a los 151 pares elegibles **no se "
              "realizó** por agotamiento del crédito de la API. Tampoco modifica las "
              "cifras de este archivo.")
    md.append("")

    destino = C.HERE / "RESULTADOS.md"
    destino.write_text("\n".join(md), encoding="utf-8")
    print(f"\n  -> {destino.relative_to(C.ROOT)}")


if __name__ == "__main__":
    main()
