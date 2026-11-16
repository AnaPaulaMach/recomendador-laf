"""Tablas del chequeo humano de LAF 2 con lo que la app muestra hoy.

Recorre el flujo web con el `.env` real (Supabase + Docker `laf-api`) para un
producto con muchas publicaciones y tres perfiles de condiciones de compra, y
toma **de la respuesta de las vistas**, publicación por publicación:

- el puesto, el puntaje y el rótulo del ranking de publicaciones;
- las condiciones que la publicación declara (`metadata`, datos del catálogo);
- la oración de cada condición (`reason_rows[…]["narrative"]`) y la oración de
  cierre de «Ver por qué». (La ecuación instanciada del puntaje ya no está en el
  contexto de la vista: se quitó del árbol el 2026-09-10.)

No calcula nada: lee el contexto que la vista `explanation` ya armó sobre el
`EvaluationResult` de `post_laf_multicriteria_v1`. Sólo lectura de Supabase.

Uso:  venv\\Scripts\\python.exe validacion_laf2\\tablas_chequeo_humano_laf2.py [MLM…]
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "webapp"))
os.chdir(ROOT / "webapp")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "laf_web.settings")
import django  # noqa: E402

django.setup()
from django.conf import settings  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import setup_test_environment  # noqa: E402
from django.urls import reverse  # noqa: E402

from recommender.models import RecommendationSession  # noqa: E402

settings.ALLOWED_HOSTS = ["*"]
setup_test_environment()

NEUTRAL = "0.67"
QUALITY = (
    "sabor", "aroma", "intensidad", "dulzor", "tueste", "acidez", "presentacion",
    "rendimiento", "variedad", "preparacion", "molienda", "originalidad",
    "tamano", "caducidad",
)
# Perfiles de condiciones de compra. Los valores son las claves de
# `forms.PREFERENCE_LEVELS`: "0" No me importa, "0.33" Poco, "0.67" Bastante,
# "1" Es prioridad. Se aplican sólo a las condiciones que el formulario ofrece.
PERFILES = {
    "todo_bastante": lambda ofrecidas: {key: NEUTRAL for key in ofrecidas},
    "solo_precio": lambda ofrecidas: {
        key: ("1" if key == "precio" else "0") for key in ofrecidas
    },
    "envio_y_oficial_prioridad": lambda ofrecidas: {
        key: ("1" if key in ("envio", "tienda_oficial") else NEUTRAL)
        for key in ofrecidas
    },
}
# Datos que la publicación declara, tal como los guarda el paso 10 y los muestra
# la explicación. Se copian crudos: el formato lo pone el generador de markdown.
DECLARADAS = (
    "price_label",
    "shipping",
    "warranty",
    "is_official_store",
    "has_discount",
    "discount_pct",
)


def recorrer(client: Client, dataset: str, producto_pedido: str | None) -> dict:
    response = client.post(
        reverse("recommender:start"),
        {"domain": "cafe", "dataset_key": dataset, "strategy": "D"},
    )
    flow_id = response["Location"].rstrip("/").split("/")[-2]
    client.post(
        reverse("recommender:quality", args=[flow_id]),
        {key: NEUTRAL for key in QUALITY},
    )
    flow = RecommendationSession.objects.get(id=flow_id)
    ranking = flow.laf1_result["ranking"]

    elegido = None
    for candidate in ranking:
        if producto_pedido and producto_pedido.upper() not in candidate["entity_id"].upper():
            continue
        client.post(
            reverse("recommender:select-product", args=[flow_id, candidate["entity_id"]])
        )
        purchase = client.get(
            reverse("recommender:purchase", args=[flow_id])
        ).content.decode()
        if "single-listing-page" in purchase:
            print(f"  ({candidate['entity_id']}: una sola publicación, LAF 2 no compara)")
            continue
        elegido = candidate
        break
    if elegido is None:
        raise SystemExit("no se encontró un producto comparable con ese filtro")

    ofrecidas = [
        key
        for key in dict.fromkeys(re.findall(r'id="label-([a-z_]+)"', purchase))
        if key not in ("budget_min", "budget_max")
    ]
    print(
        f"  producto: puesto {elegido['position']} | {elegido['entity_id']} | "
        f"{elegido['entity_name']}"
    )
    print(f"  condiciones ofrecidas: {', '.join(ofrecidas)}")
    return {"flow": flow_id, "producto": elegido, "ofrecidas": ofrecidas}


def evaluar(client: Client, flow_id: str, perfil: dict[str, str]) -> dict:
    payload = {"budget_min": "", "budget_max": ""}
    payload.update(perfil)
    client.post(reverse("recommender:purchase", args=[flow_id]), payload)
    flow = RecommendationSession.objects.get(id=flow_id)
    result = flow.laf2_result

    publicaciones = []
    for entry in result["ranking"]:
        response = client.get(
            reverse("recommender:explanation", args=[flow_id]),
            {"entity_id": entry["entity_id"]},
        )
        if response.status_code != 200 or response.context is None:
            raise SystemExit(
                f"explicación HTTP {response.status_code} ({entry['entity_id']})"
            )
        rows = response.context["reason_rows"]
        breakdown = response.context["breakdown"]
        # El rótulo y el precio formateado los agrega `attach_primary_copy` sobre
        # una copia del resultado: hay que leerlos del contexto de la vista, no
        # del JSON guardado.
        metadata = dict(response.context["selected"].metadata or {})
        mostrado = (
            breakdown.weighted_total / breakdown.weights_total
            if breakdown and breakdown.weights_total
            else 0.0
        )
        publicaciones.append(
            {
                "puesto": entry["position"],
                "entity_id": entry["entity_id"],
                "score": round(float(entry["final_score"]), 4),
                "score_exacto": float(entry["final_score"]),
                "score_formula": round(mostrado, 6),
                "desvio": round(abs(mostrado - float(entry["final_score"])), 6),
                "rotulo": metadata.get("match_label", ""),
                "nota_rotulo": metadata.get("shared_label_note", ""),
                "declaradas": {
                    clave: metadata.get(clave) for clave in DECLARADAS
                },
                "vendedor": metadata.get("seller", ""),
                "condiciones": [
                    {
                        "clave": row["key"],
                        "etiqueta": row["label"],
                        "estado": row["state"],
                        "peso": row["weight"],
                        "valor": row["value"],
                        "laf": row.get("laf_score"),
                        "oracion": row["narrative"],
                    }
                    for row in rows
                ],
                "cierre": response.context["score_story"],
                "desempate": response.context.get("tie_note") or "",
            }
        )
    primero = result["ranking"][0]["metadata"] or {}
    return {
        "evaluation_status": result.get("evaluation_status", ""),
        "decision_model": primero.get("decision_model", ""),
        "methodology_sha256": result.get("methodology_sha256", ""),
        "generated_at": result.get("generated_at", ""),
        "sin_evidencia": primero.get("conditions_without_evidence", []),
        "preferencias": flow.purchase_preferences,
        "publicaciones": publicaciones,
    }


def main() -> int:
    dataset = os.environ["DATASET_KEY"]
    pedido = sys.argv[1] if len(sys.argv) > 1 else "MLM19566313"
    destino = ROOT / "validacion_laf2" / "salidas" / "tablas_chequeo_humano_laf2.json"
    client = Client()
    print(f"dataset: {dataset} | producto pedido: {pedido}")
    base = recorrer(client, dataset, pedido)
    salida = {
        "dataset_key": dataset,
        "producto": base["producto"],
        "condiciones_ofrecidas": base["ofrecidas"],
        "perfiles": {},
    }
    for nombre, armar in PERFILES.items():
        perfil = armar(base["ofrecidas"])
        print(f"[{nombre}] {perfil}", flush=True)
        datos = evaluar(client, base["flow"], perfil)
        salida["perfiles"][nombre] = datos
        print(
            f"  {len(datos['publicaciones'])} publicaciones | "
            f"{datos['decision_model']} | hash {datos['methodology_sha256'][:8]}… | "
            f"sin evidencia: {datos['sin_evidencia']}"
        )
        for pub in datos["publicaciones"]:
            print(
                f"   {pub['puesto']:>2}. {pub['entity_id']:<14} {pub['score']:.4f} "
                f"desvío {pub['desvio']:.6f}  {pub['rotulo']}"
            )
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"-> {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
