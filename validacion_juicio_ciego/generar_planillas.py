# -*- coding: utf-8 -*-
"""Experimento 1, paso 2: muestrear la evidencia y armar el material de los jueces.

Implementa el README de pre-registro, secciones 4.2, 4.3, 4.6 y 5.2.

Primera corrida: si no existe materiales/marcas_a_enmascarar.csv, lo genera con
los candidatos y su frecuencia, y SE DETIENE. Ana revisa y aprueba ese archivo
antes de que se impriman planillas (README §4.6).

Salidas:
  materiales/INSTRUCCIONES.md
  materiales/planilla_juez_{1,2,3}.csv     <- lo que devuelve cada juez
  materiales/evidencia_juez_{1,2,3}.html   <- lo que lee cada juez
  salidas/fragmentos_usados_<fecha>.csv    <- privado, trazabilidad

Uso:  python validacion_juicio_ciego/generar_planillas.py [--jueces 3]
"""
from __future__ import annotations

import argparse
import collections
import csv
import html
import io
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import comun as C  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

MATERIALES = C.HERE / "materiales"
SALIDAS = C.HERE / "salidas"

# Terminos que identifican marca o linea de producto. Sugerencia inicial: se
# enmascaran. Ana revisa el CSV antes de imprimir.
SUGERIDOS_SI = {
    "blason", "nescafe", "nestle", "members mark", "members", "mark",
    "juan valdez", "valdez", "la parroquia", "parroquia",
    "taster's choice", "tasters choice", "taster", "tasters", "choice",
    "xiapan", "verarica", "tripack", "reserva", "clasico", "decaf", "taster's",
}
# Terminos genericos del dominio: NO se enmascaran, porque son la evidencia.
SUGERIDOS_NO = {
    "cafe", "molido", "tostado", "soluble", "polvo", "frasco", "bolsa", "bote",
    "granos", "grano", "puro", "capuccino", "cappuccino", "vainilla", "francesa",
    "moka", "canela", "piloncillo", "americano", "espresso", "robusto", "robusta",
    "arabico", "arabica", "liofilizado", "descafeinado", "sabores", "sabor",
    "olla", "ice", "frio", "gluten", "gourmet", "tradicional", "professional",
    "origen", "notas", "amaderadas", "afrutadas", "chiapaneco", "veracruzano",
    "caramel", "dark", "chocolate", "100", "sin", "con", "que", "por", "para",
    "del", "las", "los", "una", "muy", "mas", "esta", "este", "kilo",
}


def normaliza(texto: str) -> str:
    return C.sin_acentos((texto or "").lower())


def generar_csv_marcas(nombres: dict[str, str], menciones: list[dict], destino: Path) -> None:
    """Deriva candidatos de los nombres de producto y cuenta su frecuencia."""
    corpus = [normaliza(m["sentence_excerpt"]) for m in menciones]
    candidatos: dict[str, str] = {}
    # multipalabra curados a partir de los nombres reales del catalogo
    for frase in ("members mark", "juan valdez", "la parroquia", "taster's choice",
                  "tasters choice", "cafe de olla", "reserva xiapan", "reserva verarica",
                  "nestle professional"):
        candidatos[frase] = "frase"
    for nombre in nombres.values():
        for palabra in re.findall(r"[a-zñ']+", normaliza(nombre)):
            if len(palabra) >= 3:
                candidatos.setdefault(palabra, "palabra")

    filas = []
    for termino, tipo in sorted(candidatos.items()):
        patron = re.compile(r"\b" + re.escape(termino) + r"\b")
        frecuencia = sum(1 for t in corpus if patron.search(t))
        if termino in SUGERIDOS_SI:
            sugerido = "si"
        elif termino in SUGERIDOS_NO:
            sugerido = "no"
        else:
            sugerido = "no"
        filas.append({
            "termino": termino,
            "tipo": tipo,
            "frecuencia_en_menciones_sabor": frecuencia,
            "enmascarar": sugerido,
        })
    filas.sort(key=lambda f: (-f["frecuencia_en_menciones_sabor"], f["termino"]))
    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["termino", "tipo",
                                           "frecuencia_en_menciones_sabor", "enmascarar"])
        w.writeheader()
        w.writerows(filas)


def cargar_marcas(ruta: Path) -> list[str]:
    with open(ruta, encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    terminos = [f["termino"] for f in filas if (f.get("enmascarar") or "").strip().lower() == "si"]
    # las frases primero, para que "members mark" gane a "members"
    return sorted(terminos, key=lambda t: -len(t))


def enmascarar(texto: str, terminos: list[str]) -> str:
    """Reemplaza por [marca], sin acentos y sin mayusculas, sobre limite de palabra.

    Trabaja sobre la version normalizada para ubicar posiciones y aplica el
    reemplazo sobre el texto original, para no alterar el resto del fragmento.
    """
    original = texto or ""
    plano = normaliza(original)
    if len(plano) != len(original):
        # la normalizacion cambio la longitud (raro): se enmascara sobre el plano
        original = plano
    marcas = []
    for termino in terminos:
        for m in re.finditer(r"\b" + re.escape(termino) + r"\b", plano):
            marcas.append((m.start(), m.end()))
    if not marcas:
        return original
    marcas.sort()
    fusionadas = [marcas[0]]
    for ini, fin in marcas[1:]:
        if ini <= fusionadas[-1][1]:
            fusionadas[-1] = (fusionadas[-1][0], max(fusionadas[-1][1], fin))
        else:
            fusionadas.append((ini, fin))
    salida, cursor = [], 0
    for ini, fin in fusionadas:
        salida.append(original[cursor:ini])
        salida.append("[marca]")
        cursor = fin
    salida.append(original[cursor:])
    return re.sub(r"\s+", " ", "".join(salida)).strip()


CONSIGNA = """Te pedimos que compares productos de café a partir de opiniones reales de
personas que los compraron. No vas a ver el nombre ni la marca de los productos,
ni las estrellas que les pusieron: solo los pedacitos de reseña donde se habla
del **sabor**.

**Qué tenés que hacer.** Para cada uno de los 20 pares vas a leer 15 opiniones
del producto A y 15 del producto B. Después contestá una sola pregunta: según
esas opiniones, ¿cuál tiene mejor sabor? A, B, o «No puedo decidir».

**Cosas importantes:**

- **No hay respuesta correcta.** No estamos evaluando si acertás. Estamos
  comparando tu lectura con la de un programa, y si no coinciden el que queda en
  problemas es el programa.
- **No busques los productos en internet.** Si creés que reconociste alguno,
  marcá la casilla que dice «reconocí alguno» y contestá igual.
- **Contestá solo con lo que leés.** Si las opiniones no te alcanzan para
  decidir, poné «No puedo decidir»: es una respuesta válida y esperada.
- Los fragmentos están cortados y a veces se entienden a medias. Es así a
  propósito: es el texto exacto que lee el programa.
- Si querés, escribí en el comentario por qué elegiste. Nos sirve mucho.
- Te va a llevar entre 45 y 60 minutos. Podés parar y seguir después.

**Cómo entregarlo.** Abrí el archivo `evidencia_juez_N.html` en cualquier
navegador para leer los pares, y completá la planilla `planilla_juez_N.csv`
(se abre con Excel o Google Sheets). Completá una fila por par: en `veredicto`
poné `A`, `B` o `no_puedo_decidir`; en `reconoci_producto` poné `si` o `no`; y
el `comentario` es opcional.

**Participación.** Es voluntaria y podés dejarla por la mitad sin dar
explicaciones. No se registra tu nombre: las planillas se identifican solamente
como «juez 1», «juez 2» y «juez 3». Las respuestas se usan únicamente para
evaluar este sistema dentro de un Trabajo Final de Grado, y los comentarios se
citan sin atribución. No se te pide ningún dato personal.
"""


def escribir_instrucciones() -> None:
    (MATERIALES / "INSTRUCCIONES.md").write_text(
        "# Cómo completar la comparación de cafés\n\n" + CONSIGNA, encoding="utf-8"
    )


def html_evidencia(juez: int, pares_ordenados: list[dict], evidencia: dict) -> str:
    partes = [
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>",
        f"<title>Comparación de cafés — planilla {juez}</title>",
        "<style>",
        "body{font-family:Arial,Helvetica,sans-serif;color:#22292f;max-width:1000px;",
        "margin:0 auto;padding:24px 20px 80px;line-height:1.5;font-size:15px}",
        "h1{font-size:22px} h2{font-size:18px;margin-top:38px;border-top:2px solid #b9c0c5;padding-top:14px}",
        ".consigna{background:#f0f1ef;border:1px solid #d7dbde;padding:16px 20px;margin-bottom:10px}",
        ".consigna p,.consigna li{font-size:14px}",
        ".consigna ul{margin:8px 0;padding-left:20px}",
        ".par{display:flex;gap:22px;margin-top:10px}",
        ".lado{flex:1;border:1px solid #d7dbde;padding:12px 14px}",
        ".lado h3{margin:0 0 10px;font-size:16px;background:#294f6d;color:#fff;",
        "padding:5px 10px;letter-spacing:.06em}",
        "ol{margin:0;padding-left:22px} li{margin-bottom:7px;font-size:14px}",
        ".pregunta{margin-top:12px;background:#e8f0f5;border:1px solid #294f6d;padding:10px 14px;font-weight:bold}",
        "@media print{h2{page-break-before:always} .consigna{page-break-after:always}}",
        "</style></head><body>",
        f"<h1>Comparación de cafés — planilla {juez}</h1>",
        "<div class='consigna'>",
    ]
    def enriquecer(fragmento: str) -> str:
        texto = html.escape(" ".join(fragmento.split()))
        texto = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", texto)
        return re.sub(r"`(.+?)`", r"<code>\1</code>", texto)

    for bloque in CONSIGNA.strip().split("\n\n"):
        if bloque.lstrip().startswith("- "):
            partes.append("<ul>")
            for punto in bloque.lstrip()[2:].split("\n- "):
                partes.append(f"<li>{enriquecer(punto)}</li>")
            partes.append("</ul>")
        else:
            partes.append(f"<p>{enriquecer(bloque)}</p>")
    partes.append("</div>")

    for orden, par in enumerate(pares_ordenados, 1):
        pid = par["par_id"]
        partes.append(f"<h2>{orden} de {len(pares_ordenados)} &nbsp;·&nbsp; par {pid}</h2>")
        partes.append("<div class='par'>")
        for lado in ("A", "B"):
            partes.append(f"<div class='lado'><h3>Producto {lado}</h3><ol>")
            for frag in evidencia[(pid, lado)]:
                partes.append(f"<li>{html.escape(frag)}</li>")
            partes.append("</ol></div>")
        partes.append("</div>")
        partes.append(
            f"<div class='pregunta'>Par {pid}: según estas opiniones, ¿cuál tiene "
            "mejor sabor? &nbsp; A &nbsp;/&nbsp; B &nbsp;/&nbsp; No puedo decidir"
            f" &nbsp;→ anotalo en la fila <code>{pid}</code> de la planilla.</div>"
        )
    partes.append("</body></html>")
    return "\n".join(partes)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jueces", type=int, default=3)
    ap.add_argument("--aspecto", default=C.ASPECTO)
    ap.add_argument("--tabla-pares", default=None)
    args = ap.parse_args()

    tabla = Path(args.tabla_pares) if args.tabla_pares else next(
        iter(sorted(SALIDAS.glob(f"tabla_pares_con_puntajes_{args.aspecto}_*.csv"), reverse=True)),
        None,
    )
    if tabla is None:
        raise SystemExit("ERROR: falta la tabla de pares. Corré generar_pares.py primero.")
    with open(tabla, encoding="utf-8") as fh:
        pares = list(csv.DictReader(fh))

    sb = C.conectar()
    trust_rows, mention_rows, incluidos, nombres = C.cargar_corpus(sb)
    del_aspecto = [m for m in mention_rows if m["aspect"] == args.aspecto]

    C.encabezado(
        "generar_planillas.py", C.SEMILLA_FRAGMENTOS,
        n_resenas=len(trust_rows), n_menciones=len(del_aspecto),
        extra=f"tabla de pares: {tabla.name} ({len(pares)} pares)",
    )

    MATERIALES.mkdir(parents=True, exist_ok=True)
    csv_marcas = MATERIALES / "marcas_a_enmascarar.csv"
    if not csv_marcas.exists():
        generar_csv_marcas(nombres, del_aspecto, csv_marcas)
        print(f"  Generé {csv_marcas.relative_to(C.ROOT)} con los candidatos y su frecuencia.")
        print("  ME DETENGO ACA. El pre-registro (§4.6) pide que Ana revise y apruebe")
        print("  ese archivo ANTES de imprimir planillas. Revisá la columna 'enmascarar'")
        print("  y volvé a correr este script.")
        return

    terminos = cargar_marcas(csv_marcas)
    print(f"  términos a enmascarar aprobados: {len(terminos)}")

    # --- deduplicacion por producto (README §4.3) ---------------------------
    por_producto: dict[str, list[str]] = {}
    caidas = {}
    for pid in sorted({m["product_id"] for m in del_aspecto}):
        vistos, unicos = set(), []
        total = 0
        for m in del_aspecto:
            if m["product_id"] != pid:
                continue
            total += 1
            clave = C.normalizar_fragmento(m["sentence_excerpt"])
            if clave and clave not in vistos:
                vistos.add(clave)
                unicos.append(m["sentence_excerpt"])
        por_producto[pid] = unicos
        caidas[pid] = total - len(unicos)

    # --- muestreo (README §5.2): una muestra por par y por lado -------------
    rng = random.Random(C.SEMILLA_FRAGMENTOS)
    evidencia: dict[tuple[str, str], list[str]] = {}
    trazas = []
    for par in pares:
        for lado in ("A", "B"):
            pid = par[f"lado_{lado}_product_id"]
            pozo = por_producto[pid]
            n = min(C.FRAGMENTOS_POR_LADO, len(pozo))
            muestra = rng.sample(pozo, n)
            rng.shuffle(muestra)
            limpios = [enmascarar(f, terminos) for f in muestra]
            evidencia[(par["par_id"], lado)] = limpios
            for i, (crudo, limpio) in enumerate(zip(muestra, limpios), 1):
                trazas.append({
                    "par_id": par["par_id"], "lado": lado, "product_id": pid,
                    "orden": i, "fragmento_mostrado": limpio,
                    "fragmento_original": crudo,
                    "enmascarado": "si" if limpio != " ".join(crudo.split()) else "no",
                })

    # --- material por juez --------------------------------------------------
    escribir_instrucciones()
    for juez in range(1, args.jueces + 1):
        orden = list(pares)
        random.Random(C.SEMILLA_PARES + juez).shuffle(orden)
        (MATERIALES / f"evidencia_juez_{juez}.html").write_text(
            html_evidencia(juez, orden, evidencia), encoding="utf-8"
        )
        with open(MATERIALES / f"planilla_juez_{juez}.csv", "w", encoding="utf-8-sig",
                  newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["par_id", "veredicto", "reconoci_producto", "comentario"])
            for par in orden:
                w.writerow([par["par_id"], "", "", ""])

    SALIDAS.mkdir(exist_ok=True)
    traza_path = SALIDAS / f"fragmentos_usados_{args.aspecto}_{C.hoy()}.csv"
    with open(traza_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(trazas[0].keys()))
        w.writeheader()
        w.writerows(trazas)

    n_enmascarados = sum(1 for t in trazas if t["enmascarado"] == "si")
    print(f"  fragmentos mostrados: {len(trazas)}  |  con marca enmascarada: {n_enmascarados}"
          f" ({100*n_enmascarados/len(trazas):.1f} %)")
    print("  duplicados exactos descartados por producto (top 5):")
    for pid, n in sorted(caidas.items(), key=lambda kv: -kv[1])[:5]:
        print(f"    {n:3d}  {nombres.get(pid, pid)[:52]}")
    print("-" * 74)
    for juez in range(1, args.jueces + 1):
        print(f"  materiales/evidencia_juez_{juez}.html   +   materiales/planilla_juez_{juez}.csv")
    print(f"  materiales/INSTRUCCIONES.md")
    print(f"  PRIVADO -> {traza_path.relative_to(C.ROOT)}")
    print()
    print("  PROXIMO PASO: entregar materiales/ a los jueces. Cuando devuelvan las")
    print("  planillas, ponerlas en validacion_juicio_ciego/respuestas/ y correr")
    print("  analizar_respuestas.py")


if __name__ == "__main__":
    main()
