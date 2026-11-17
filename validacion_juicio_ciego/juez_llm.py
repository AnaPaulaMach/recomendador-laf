# -*- coding: utf-8 -*-
"""Experimento 1-bis: lector automatico (LLM) sobre los pares.

Implementa README_LLM.md. El prompt esta CONGELADO en el apendice de ese
documento y se transcribe aca literalmente; no se modifica despues de la primera
llamada.

NO es un juez humano. Es un instrumento de ampliacion cuya validez se comprueba
contra la lectura humana.

Fases:
  --fase solapamiento  los 20 pares que respondio la jueza, con SU misma evidencia
  --fase completa      los 151 pares elegibles (solo si el control del §6 pasa)

Usa urllib de la biblioteca estandar: no agrega dependencias al proyecto.

Uso:  python validacion_juicio_ciego/juez_llm.py --fase solapamiento
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import itertools
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SALIDAS = C.HERE / "salidas"
RESPUESTAS = C.HERE / "respuestas"
ENDPOINT = "https://api.openai.com/v1/chat/completions"

UMBRAL_INCONSISTENCIA = 0.20   # README_LLM §5
UMBRAL_EXTRAPOLACION = 0.70    # README_LLM §6

# Modelos y si admiten temperatura fija (comprobado 2026-09-10; ver enmienda).
MODELOS = [
    {"nombre": "gpt-5.4-mini", "temperatura": 0, "repeticion_control": False},
    {"nombre": "gpt-5.5", "temperatura": None, "repeticion_control": True},
]

# --------------------------------------------------------------------------
# PROMPT CONGELADO — apendice de README_LLM.md, fijado antes de ver las
# respuestas de la jueza. No se toca.
# --------------------------------------------------------------------------
SISTEMA = """Sos una persona que toma café y está ayudando a evaluar un sistema
informático. Vas a comparar dos productos de café a partir de opiniones
reales de personas que los compraron. No vas a ver el nombre ni la marca de
los productos, ni las estrellas que les pusieron: solo los pedacitos de
reseña donde se habla del sabor.

No hay respuesta correcta. No se está evaluando si acertás: se está
comparando tu lectura con la de un programa, y si no coinciden el que queda
en problemas es el programa.

Contestá solo con lo que leés. Si las opiniones no te alcanzan para decidir,
respondé "no_puedo_decidir": es una respuesta válida y esperada.

Los fragmentos están cortados y a veces se entienden a medias. Es así a
propósito: es el texto exacto que lee el programa.

Respondé SIEMPRE en este formato exacto, sin nada más:
VEREDICTO: A | B | no_puedo_decidir
MOTIVO: <una o dos oraciones>"""


def usuario(frag_a: list[str], frag_b: list[str]) -> str:
    partes = ["Producto A:"]
    partes += [f"{i}. {f}" for i, f in enumerate(frag_a, 1)]
    partes += ["", "Producto B:"]
    partes += [f"{i}. {f}" for i, f in enumerate(frag_b, 1)]
    partes += ["", "Según estas opiniones, ¿cuál tiene mejor sabor?"]
    return "\n".join(partes)


# --------------------------------------------------------------------------

def llamar(modelo: dict, texto_usuario: str, intentos: int = 4) -> tuple[str, str]:
    cuerpo = {
        "model": modelo["nombre"],
        "messages": [{"role": "system", "content": SISTEMA},
                     {"role": "user", "content": texto_usuario}],
    }
    if modelo["temperatura"] is not None:
        cuerpo["temperature"] = modelo["temperatura"]
    datos = json.dumps(cuerpo).encode("utf-8")
    ultimo = ""
    for intento in range(intentos):
        req = urllib.request.Request(
            ENDPOINT, data=datos,
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
                return d["choices"][0]["message"]["content"], d.get("model", "")
        except urllib.error.HTTPError as e:
            cuerpo_error = e.read().decode("utf-8", "replace")[:200]
            ultimo = f"HTTP {e.code}: {cuerpo_error}"
            if e.code in (429, 500, 502, 503, 529):
                time.sleep(2 ** intento + random.random())
                continue
            break
        except Exception as e:  # timeout, red
            ultimo = f"{type(e).__name__}: {e}"
            time.sleep(2 ** intento + random.random())
    raise RuntimeError(f"llamada fallida tras {intentos} intentos: {ultimo}")


def parsear(texto: str) -> str | None:
    m = re.search(r"VEREDICTO\s*:\s*([A-Za-z_ ]+)", texto or "")
    bruto = (m.group(1) if m else (texto or "")).strip().lower()
    bruto = C.sin_acentos(bruto)
    if bruto.startswith("no_puedo") or bruto.startswith("no puedo"):
        return "no_puedo_decidir"
    if bruto.startswith("a"):
        return "A"
    if bruto.startswith("b"):
        return "B"
    return None


# --------------------------------------------------------------------------

def evidencia_solapamiento() -> tuple[dict, dict]:
    """La MISMA evidencia enmascarada que vio la jueza."""
    tabla = sorted(SALIDAS.glob("tabla_pares_con_puntajes_sabor_*.csv"))[-1]
    frags = sorted(SALIDAS.glob("fragmentos_usados_sabor_*.csv"))[-1]
    pares = {r["par_id"]: r for r in csv.DictReader(open(tabla, encoding="utf-8"))}
    evidencia = collections.defaultdict(list)
    for f in csv.DictReader(open(frags, encoding="utf-8")):
        evidencia[(f["par_id"], f["lado"])].append((int(f["orden"]), f["fragmento_mostrado"]))
    for clave in evidencia:
        evidencia[clave] = [t for _, t in sorted(evidencia[clave])]
    return pares, evidencia


def evidencia_completa(rng_semilla: int) -> tuple[dict, dict]:
    """Los 151 pares elegibles. Los 20 ya sorteados conservan su evidencia."""
    import generar_planillas as GP  # reutiliza enmascarado y muestreo

    pares20, ev20 = evidencia_solapamiento()
    ya = {frozenset((p["lado_A_product_id"], p["lado_B_product_id"])): pid
          for pid, p in pares20.items()}

    trust06, gen08, laf = C.cargar_modulos()
    sb = C.conectar()
    trust_rows, mention_rows, incluidos, nombres = C.cargar_corpus(sb)
    hechos = C.construir_hechos(trust06, trust_rows, mention_rows)
    productos = gen08.load_products(sb, incluidos, top_n=20)
    puntajes = {C.id_producto(k): v
                for k, v in C.puntaje_por_aspecto(gen08, laf, productos, hechos, C.ASPECTO).items()}

    del_aspecto = [m for m in mention_rows if m["aspect"] == C.ASPECTO]
    terminos = GP.cargar_marcas(C.HERE / "materiales" / "marcas_a_enmascarar.csv")
    pozo: dict[str, list[str]] = {}
    for pid in sorted({m["product_id"] for m in del_aspecto}):
        vistos, unicos = set(), []
        for m in del_aspecto:
            if m["product_id"] != pid:
                continue
            clave = C.normalizar_fragmento(m["sentence_excerpt"])
            if clave and clave not in vistos:
                vistos.add(clave)
                unicos.append(m["sentence_excerpt"])
        pozo[pid] = unicos

    elegibles = sorted(p for p in incluidos if len(pozo.get(p, [])) and p in puntajes
                       and sum(1 for m in del_aspecto if m["product_id"] == p) >= C.MIN_MENCIONES)
    rng = random.Random(rng_semilla)
    pares, evidencia = {}, {}
    n = 0
    for a, b in itertools.combinations(elegibles, 2):
        if puntajes[a] == puntajes[b]:
            continue                      # el sistema no los ordena (README §4.5)
        n += 1
        clave = frozenset((a, b))
        if clave in ya:
            pid = ya[clave]
            pares[pid] = pares20[pid]
            evidencia[(pid, "A")] = ev20[(pid, "A")]
            evidencia[(pid, "B")] = ev20[(pid, "B")]
            continue
        pid = f"C{n:03d}"
        pares[pid] = {
            "par_id": pid, "franja": "",
            "delta_laf": f"{abs(puntajes[a]-puntajes[b]):.6f}",
            "lado_A_product_id": a, "lado_B_product_id": b,
            "lado_A_nombre": nombres.get(a, a), "lado_B_nombre": nombres.get(b, b),
            "lado_A_puntaje_laf": f"{puntajes[a]:.6f}", "lado_B_puntaje_laf": f"{puntajes[b]:.6f}",
            "prediccion_sistema": "A" if puntajes[a] > puntajes[b] else "B",
        }
        for lado, prod in (("A", a), ("B", b)):
            muestra = rng.sample(pozo[prod], min(C.FRAGMENTOS_POR_LADO, len(pozo[prod])))
            rng.shuffle(muestra)
            evidencia[(pid, lado)] = [GP.enmascarar(f, terminos) for f in muestra]

    # franjas por terciles sobre los pares construidos (misma regla del README §4.5)
    deltas = sorted(float(p["delta_laf"]) for p in pares.values())
    c1, c2 = deltas[len(deltas) // 3], deltas[2 * len(deltas) // 3]
    for p in pares.values():
        d = float(p["delta_laf"])
        p["franja"] = "chica" if d <= c1 else ("mediana" if d <= c2 else "grande")
    return pares, evidencia


# --------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fase", default="solapamiento", choices=["solapamiento", "completa"])
    ap.add_argument("--hilos", type=int, default=6)
    ap.add_argument("--reanudar", default=None,
                    help="ruta de un llm_respuestas_*.csv previo: no repite lo ya pagado")
    args = ap.parse_args()

    if not (RESPUESTAS / "planilla_juez_1.csv").exists():
        raise SystemExit(
            "ERROR: no existe respuestas/planilla_juez_1.csv.\n"
            "README_LLM.md §7: el lector automatico se corre DESPUES de que la\n"
            "jueza entregue, para no romper su cegamiento. No se corre nada."
        )
    from dotenv import load_dotenv
    load_dotenv(C.ROOT / ".env")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("ERROR: falta OPENAI_API_KEY en el .env.")

    if args.fase == "solapamiento":
        pares, evidencia = evidencia_solapamiento()
    else:
        pares, evidencia = evidencia_completa(C.SEMILLA_FRAGMENTOS)

    C.encabezado(
        f"juez_llm.py --fase {args.fase}", C.SEMILLA_FRAGMENTOS,
        n_resenas=0, n_menciones=0,
        extra=f"pares: {len(pares)} · modelos: {', '.join(m['nombre'] for m in MODELOS)}",
    )
    print("  PROMPT CONGELADO en README_LLM.md (apendice), fijado antes de ver")
    print("  las respuestas de la jueza. Este script lo transcribe sin cambios.")

    # --- armado de las llamadas -------------------------------------------
    trabajos = []
    for modelo in MODELOS:
        for par_id, par in sorted(pares.items()):
            fa, fb = evidencia[(par_id, "A")], evidencia[(par_id, "B")]
            trabajos.append((modelo, par_id, "directa", usuario(fa, fb)))
            trabajos.append((modelo, par_id, "invertida", usuario(fb, fa)))
            if modelo["repeticion_control"]:
                trabajos.append((modelo, par_id, "repetida", usuario(fa, fb)))
    print(f"  llamadas a la API: {len(trabajos)}")

    # --- reanudacion: no volver a pagar llamadas ya hechas -----------------
    CAMPOS = ["modelo", "modelo_real", "temperatura", "par_id", "presentacion",
              "veredicto", "crudo", "error"]
    sello = datetime.now().strftime("%Y%m%d_%H%M")
    filas: list[dict] = []
    hechas: set[tuple[str, str, str]] = set()
    if args.reanudar:
        previo = Path(args.reanudar)
        if not previo.exists():
            raise SystemExit(f"ERROR: no existe {previo}")
        for r in csv.DictReader(open(previo, encoding="utf-8")):
            if r.get("veredicto"):           # solo se reusa lo que salio bien
                filas.append(r)
                hechas.add((r["modelo"], r["par_id"], r["presentacion"]))
        crudo_path = previo
        print(f"  reanudando desde {previo.name}: {len(hechas)} llamadas ya hechas")
    else:
        crudo_path = SALIDAS / f"llm_respuestas_{args.fase}_{sello}.csv"

    pendientes = [t for t in trabajos
                  if (t[0]["nombre"], t[1], t[2]) not in hechas]
    print(f"  llamadas pendientes: {len(pendientes)}")

    # Se escribe INCREMENTALMENTE: si la corrida se corta (sin credito, red,
    # limite de tasa), lo ya pagado queda en disco y se reanuda con --reanudar.
    fh = open(crudo_path, "a" if args.reanudar else "w", encoding="utf-8", newline="")
    escritor = csv.DictWriter(fh, fieldnames=CAMPOS)
    if not args.reanudar:
        escritor.writeheader()
    candado = threading.Lock()
    estado = {"n": 0, "errores": 0}

    def ejecutar(t):
        modelo, par_id, presentacion, texto = t
        base = {"modelo": modelo["nombre"], "modelo_real": "",
                "temperatura": ("por_defecto" if modelo["temperatura"] is None
                                else modelo["temperatura"]),
                "par_id": par_id, "presentacion": presentacion,
                "veredicto": None, "crudo": "", "error": ""}
        try:
            crudo, modelo_real = llamar(modelo, texto)
            base.update({"modelo_real": modelo_real, "veredicto": parsear(crudo),
                         "crudo": " ".join((crudo or "").split())})
        except Exception as e:               # la corrida NO se cae por una llamada
            base["error"] = f"{type(e).__name__}: {e}"[:300]
        with candado:
            escritor.writerow(base)
            fh.flush()
            filas.append(base)
            estado["n"] += 1
            if base["error"]:
                estado["errores"] += 1
            if estado["n"] % 25 == 0:
                print(f"    {estado['n']}/{len(pendientes)}"
                      f"  (errores: {estado['errores']})", flush=True)
        return base

    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=args.hilos) as pool:
            list(pool.map(ejecutar, pendientes))
    finally:
        fh.close()
    print(f"  {estado['n']} llamadas en {time.time()-t0:.0f} s "
          f"({estado['errores']} con error)")

    fallidas = [f for f in filas if f.get("error")]
    if fallidas:
        motivos = collections.Counter(f["error"].split(":")[0] + ": "
                                      + f["error"][:60] for f in fallidas)
        print("  AVISO: llamadas fallidas; las metricas se calculan sobre lo obtenido.")
        for m, n in motivos.most_common(3):
            print(f"    {n}x  {m}")
        print(f"  Para completar cuando se pueda: --reanudar {crudo_path.name}")
    filas = [f for f in filas if f.get("veredicto") or not f.get("error")]

    # --- normalizacion a producto elegido ---------------------------------
    def producto(par_id: str, presentacion: str, veredicto: str | None) -> str | None:
        if veredicto not in ("A", "B"):
            return None
        par = pares[par_id]
        izq, der = par["lado_A_product_id"], par["lado_B_product_id"]
        if presentacion == "invertida":
            izq, der = der, izq
        return izq if veredicto == "A" else der

    por_modelo = collections.defaultdict(dict)
    for f in filas:
        por_modelo[f["modelo"]][(f["par_id"], f["presentacion"])] = f["veredicto"]

    # --- respuestas de la jueza (solo para la fase de solapamiento) --------
    ana = {}
    if args.fase == "solapamiento":
        import analizar_respuestas as AR
        for r in csv.DictReader(open(RESPUESTAS / "planilla_juez_1.csv", encoding="utf-8-sig")):
            v = AR.normalizar_veredicto(r.get("veredicto", ""))
            if r["par_id"] in pares and v in ("A", "B"):
                ana[r["par_id"]] = pares[r["par_id"]][f"lado_{v}_product_id"]

    resumen = {"fase": args.fase, "fecha": datetime.now().isoformat(timespec="seconds"),
               "pares": len(pares), "llamadas": len(filas),
               "prompt": "congelado en README_LLM.md (apendice)", "modelos": {}}

    print("-" * 74)
    for modelo in MODELOS:
        nombre = modelo["nombre"]
        v = por_modelo[nombre]
        consistentes, inconsistentes, ruido = [], [], 0
        for par_id in pares:
            d = producto(par_id, "directa", v.get((par_id, "directa")))
            i = producto(par_id, "invertida", v.get((par_id, "invertida")))
            npd_d = v.get((par_id, "directa")) == "no_puedo_decidir"
            npd_i = v.get((par_id, "invertida")) == "no_puedo_decidir"
            if (d is not None and d == i) or (npd_d and npd_i):
                consistentes.append(par_id)
            else:
                inconsistentes.append(par_id)
            if modelo["repeticion_control"]:
                r = producto(par_id, "repetida", v.get((par_id, "repetida")))
                npd_r = v.get((par_id, "repetida")) == "no_puedo_decidir"
                if not ((d is not None and d == r) or (npd_d and npd_r)):
                    ruido += 1

        tasa_inc = len(inconsistentes) / len(pares)
        descartado = tasa_inc > UMBRAL_INCONSISTENCIA
        d_modelo = {
            "modelo_real": next((f["modelo_real"] for f in filas if f["modelo"] == nombre), ""),
            "temperatura": ("por_defecto" if modelo["temperatura"] is None else modelo["temperatura"]),
            "inconsistentes": len(inconsistentes),
            "tasa_inconsistencia": round(tasa_inc, 4),
            "descartado_por_sesgo_de_posicion": descartado,
            "pares_inconsistentes": sorted(inconsistentes),
        }
        if modelo["repeticion_control"]:
            d_modelo["ruido_de_muestreo"] = ruido
            d_modelo["tasa_ruido"] = round(ruido / len(pares), 4)

        print(f"\n  [{nombre}]  temperatura="
              f"{'por defecto' if modelo['temperatura'] is None else modelo['temperatura']}")
        print(f"    inconsistentes (sesgo de posicion): {len(inconsistentes)}/{len(pares)}"
              f" = {100*tasa_inc:.1f} %  -> "
              f"{'DESCARTADO (>20 %)' if descartado else 'pasa el control'}")
        if modelo["repeticion_control"]:
            print(f"    ruido de muestreo (misma presentacion 2 veces): "
                  f"{ruido}/{len(pares)} = {100*ruido/len(pares):.1f} %")

        if not descartado:
            # acuerdo con el sistema, sobre los pares consistentes con veredicto
            ok = tot = 0
            por_franja = collections.defaultdict(lambda: [0, 0])
            npd = 0
            for par_id in consistentes:
                elegido = producto(par_id, "directa", v.get((par_id, "directa")))
                if elegido is None:
                    npd += 1
                    continue
                par = pares[par_id]
                gana = (par["lado_A_product_id"]
                        if par["prediccion_sistema"] == "A" else par["lado_B_product_id"])
                tot += 1
                acierto = int(elegido == gana)
                ok += acierto
                por_franja[par["franja"]][0] += acierto
                por_franja[par["franja"]][1] += 1
            d_modelo["acuerdo_sistema"] = {"ok": ok, "n": tot,
                                           "prop": round(ok / tot, 4) if tot else None}
            d_modelo["no_puedo_decidir"] = npd
            d_modelo["por_franja"] = {f: {"ok": a, "n": b} for f, (a, b) in por_franja.items()}
            if tot:
                print(f"    acuerdo sistema-LLM: {ok}/{tot} = {100*ok/tot:.1f} %"
                      f"   (no puedo decidir: {npd})")
                for f in ("grande", "mediana", "chica"):
                    if por_franja[f][1]:
                        a, b = por_franja[f]
                        print(f"      {f:8s}: {a}/{b} = {100*a/b:.1f} %")

            if ana:
                oka = tota = 0
                for par_id, prod_ana in ana.items():
                    if par_id not in consistentes:
                        continue
                    elegido = producto(par_id, "directa", v.get((par_id, "directa")))
                    if elegido is None:
                        continue
                    tota += 1
                    oka += int(elegido == prod_ana)
                prop = oka / tota if tota else None
                d_modelo["acuerdo_con_jueza"] = {"ok": oka, "n": tota,
                                                 "prop": round(prop, 4) if prop is not None else None}
                d_modelo["habilita_extrapolacion"] = bool(prop is not None
                                                          and prop >= UMBRAL_EXTRAPOLACION)
                print(f"    acuerdo LLM-jueza: {oka}/{tota}"
                      f" = {100*prop:.1f} %" if tota else "    acuerdo LLM-jueza: sin pares")
                if tota:
                    print(f"    -> extrapolar a los 151: "
                          f"{'SI' if d_modelo['habilita_extrapolacion'] else 'NO (<70 %)'}")
        resumen["modelos"][nombre] = d_modelo

    # acuerdo entre modelos (descriptivo)
    if len(MODELOS) == 2:
        a, b = MODELOS[0]["nombre"], MODELOS[1]["nombre"]
        iguales = comparables = 0
        for par_id in pares:
            pa = producto(par_id, "directa", por_modelo[a].get((par_id, "directa")))
            pb = producto(par_id, "directa", por_modelo[b].get((par_id, "directa")))
            if pa and pb:
                comparables += 1
                iguales += int(pa == pb)
        resumen["acuerdo_entre_modelos"] = {"ok": iguales, "n": comparables}
        if comparables:
            print(f"\n  acuerdo entre los dos modelos (descriptivo): "
                  f"{iguales}/{comparables} = {100*iguales/comparables:.1f} %")

    with open(SALIDAS / f"llm_resumen_{args.fase}_{sello}.json", "w", encoding="utf-8") as fh:
        json.dump(resumen, fh, ensure_ascii=False, indent=1)
    print(f"\n  -> {crudo_path.relative_to(C.ROOT)}")
    print(f"  -> {(SALIDAS / f'llm_resumen_{args.fase}_{sello}.json').relative_to(C.ROOT)}")


if __name__ == "__main__":
    main()
