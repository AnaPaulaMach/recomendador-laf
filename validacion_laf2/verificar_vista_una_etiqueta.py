"""Compara la vista «Ver por que» de una publicacion antes y despues del cambio.

Corre el flujo web real dos veces sobre el mismo producto y perfil: una con la
ruta nueva (seleccion explicita, una etiqueta) y otra forzando la ruta anterior
(mascara + dos etiquetas), y compara la oracion por condicion y el grafo que
devuelve `listing-condition-graph`.

Uso: venv\Scripts\python.exe validacion_laf2\verificar_vista_una_etiqueta.py [product_id]
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "webapp"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "laf_web.settings")
import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402
from recommender.services.laf2_programs import LAF2ProgramService  # noqa: E402

settings.ALLOWED_HOSTS = ["*"]
PRODUCT = sys.argv[1] if len(sys.argv) > 1 else "MLM19566313"
QUALITY = {k: "0.67" for k in [
    "sabor", "aroma", "intensidad", "dulzor", "tueste", "acidez", "presentacion",
    "rendimiento", "variedad", "preparacion", "molienda", "originalidad",
    "tamano", "caducidad",
]}
CONDITIONS = ("precio", "descuento", "cuotas", "garantia", "tienda_oficial", "factura", "envio")


def recorrer() -> dict:
    client = Client()
    r = client.post(reverse("recommender:start"), {
        "domain": "cafe", "dataset_key": os.environ["DATASET_KEY"], "strategy": "D",
    })
    flow_id = r["Location"].rstrip("/").split("/")[-2]
    client.post(reverse("recommender:quality", args=[flow_id]), QUALITY)
    client.post(reverse("recommender:select-product", args=[flow_id, PRODUCT]))
    prefs = {"budget_min": "", "budget_max": ""}
    prefs.update({k: "0.67" for k in CONDITIONS})
    client.post(reverse("recommender:purchase", args=[flow_id]), prefs)
    ranking = client.get(reverse("recommender:listing-ranking", args=[flow_id]))
    html = ranking.content.decode()
    entity = re.search(r'entity_id=([A-Za-z0-9%]+)', html).group(1)
    explanation = client.get(
        reverse("recommender:explanation", args=[flow_id]) + f"?entity_id={entity}"
    )
    page = explanation.content.decode()
    oraciones = dict(zip(
        re.findall(r'data-aspect-key="([^"]*)"', page),
        re.findall(r'data-aspect-narr="([^"]*)"', page),
    ))
    grafos = {}
    for condition in CONDITIONS:
        response = client.get(
            reverse("recommender:listing-condition-graph", args=[flow_id])
            + f"?entity_id={entity}&aspect={condition}"
        )
        grafos[condition] = json.loads(response.content.decode())
    return {"entity": entity, "oraciones": oraciones, "grafos": grafos}


def resumen_grafo(grafo: dict) -> list[dict]:
    # El motor no garantiza el orden de la lista de nodos entre corridas: se
    # compara el conjunto, ordenado por literal.
    return sorted((
        {
            "literal": n.get("literal"),
            "confidence": round(float(n.get("confidence") or 0.0), 6),
            "graph_label": (n.get("metadata") or {}).get("graph_label"),
            "hide_preference": (n.get("metadata") or {}).get("hide_preference"),
        }
        for n in grafo.get("nodes") or []
    ), key=lambda n: (str(n["literal"]), n["confidence"]))


def main() -> int:
    print("producto:", PRODUCT)
    nuevo = recorrer()
    with patch.object(LAF2ProgramService, "generate_conditions", None):
        viejo = recorrer()

    problemas = []
    if nuevo["oraciones"] != viejo["oraciones"]:
        for clave in sorted(set(nuevo["oraciones"]) | set(viejo["oraciones"])):
            a, b = viejo["oraciones"].get(clave), nuevo["oraciones"].get(clave)
            if a != b:
                problemas.append(f"oracion [{clave}]: {a!r} -> {b!r}")
    for condition in CONDITIONS:
        a, b = viejo["grafos"][condition], nuevo["grafos"][condition]
        ra, rb = resumen_grafo(a), resumen_grafo(b)
        print(f"  {condition:15s} nodos={len(rb):>3}  aristas={len(b.get('edges') or []):>3}  "
              f"hide_preference en todos="
              f"{all(y['hide_preference'] for y in rb) if rb else 'sin nodos'}")
        if len(a.get("edges") or []) != len(b.get("edges") or []):
            problemas.append(
                f"grafo [{condition}]: {len(a.get('edges') or [])} aristas -> "
                f"{len(b.get('edges') or [])}"
            )
        if [x["literal"] for x in ra] != [x["literal"] for x in rb]:
            problemas.append(
                f"grafo [{condition}]: literales {[x['literal'] for x in ra]} -> "
                f"{[x['literal'] for x in rb]}"
            )
            continue
        for x, y in zip(ra, rb, strict=True):
            if abs(x["confidence"] - y["confidence"]) > 1e-6:
                problemas.append(
                    f"grafo [{condition}] {x['literal']}: confianza "
                    f"{x['confidence']} -> {y['confidence']}"
                )
            if x["graph_label"] != y["graph_label"]:
                problemas.append(
                    f"grafo [{condition}] {x['literal']}: etiqueta "
                    f"{x['graph_label']!r} -> {y['graph_label']!r}"
                )
        ocultos = [y for y in rb if not y["hide_preference"]]
        if ocultos:
            problemas.append(
                f"grafo [{condition}]: {len(ocultos)} nodos sin hide_preference"
            )
    print("oraciones por condicion:")
    for clave, texto in sorted(nuevo["oraciones"].items()):
        print(f"  {clave:15s} {texto[:100]}")
    if problemas:
        print(f"DIFERENCIAS: {len(problemas)}")
        for linea in problemas[:30]:
            print("  ", linea)
        return 1
    print("IDENTICO: misma oracion por condicion y mismo grafo por condicion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
