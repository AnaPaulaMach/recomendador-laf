"""Comprueba la vista «Ver por qué» de publicaciones contra datos reales.

Recorre el flujo web con el `.env` real (Supabase + Docker `laf-api`) usando el
perfil **neutro** (todos los controles en su valor inicial, 0,67), toma el
producto ganador de LAF 1 y, para **cada** publicación de ese producto,
verifica que la fórmula que muestra la pantalla reproduce el puntaje que ordenó
el ranking y que ninguna condición con peso 0 entra en la cuenta.

Uso:  venv\\Scripts\\python.exe validacion_laf2\\explicacion_web_real.py
"""
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
# Sin esto el cliente de prueba no expone `response.context`, que es de
# donde se leen los valores que la pantalla realmente muestra.
setup_test_environment()
NEUTRAL = "0.67"
QUALITY = [
    "sabor", "aroma", "intensidad", "dulzor", "tueste", "acidez", "presentacion",
    "rendimiento", "variedad", "preparacion", "molienda", "originalidad",
    "tamano", "caducidad",
]


def main() -> int:
    client = Client()
    dataset = sys.argv[1] if len(sys.argv) > 1 else os.environ["DATASET_KEY"]
    response = client.post(
        reverse("recommender:start"),
        {"domain": "cafe", "dataset_key": dataset, "strategy": "D"},
    )
    flow_id = response["Location"].rstrip("/").split("/")[-2]
    print(f"dataset: {dataset}")
    print(f"flow:    {flow_id}")

    client.post(
        reverse("recommender:quality", args=[flow_id]),
        {key: NEUTRAL for key in QUALITY},
    )
    flow = RecommendationSession.objects.get(id=flow_id)
    ranking = flow.laf1_result["ranking"]
    print(
        f"ganador LAF1 (perfil neutro): {ranking[0]['entity_id']} | "
        f"{ranking[0]['entity_name']} | puntaje {ranking[0]['final_score']:.3f}"
    )

    # La pantalla que se está verificando sólo existe cuando LAF 2 compara: un
    # producto con una sola publicación tiene su propia plantilla. Se baja por
    # el ranking neutro hasta el primero que sí se compara.
    for candidate in ranking:
        client.post(
            reverse("recommender:select-product", args=[flow_id, candidate["entity_id"]])
        )
        purchase = client.get(
            reverse("recommender:purchase", args=[flow_id])
        ).content.decode()
        if "single-listing-page" not in purchase:
            product = candidate
            break
        print(
            f"  (puesto {candidate['position']} {candidate['entity_id']}: "
            "una sola publicación, LAF 2 no compara)"
        )
    else:
        print("Ningún producto de este snapshot tiene más de una publicación.")
        return 1

    print(
        f"producto verificado: puesto {product['position']} | "
        f"{product['entity_id']} | {product['entity_name']}"
    )
    # Un control por condición ofrecida; el formulario los rotula `label-<clave>`.
    offered = [
        key
        for key in dict.fromkeys(re.findall(r'id="label-([a-z_]+)"', purchase))
        if key not in ("budget_min", "budget_max")
    ]
    print("condiciones ofrecidas:", ", ".join(offered) or "(ninguna)")

    payload = {"budget_min": "", "budget_max": ""}
    payload.update({key: NEUTRAL for key in offered})
    client.post(reverse("recommender:purchase", args=[flow_id]), payload)

    flow = RecommendationSession.objects.get(id=flow_id)
    result = flow.laf2_result
    print(
        f"LAF2: {result['evaluation_status']} | "
        f"{result['ranking'][0]['metadata'].get('decision_model')} | "
        f"sin evidencia: "
        f"{result['ranking'][0]['metadata'].get('conditions_without_evidence')}"
    )

    problemas = 0
    for entry in result["ranking"]:
        response = client.get(
            reverse("recommender:explanation", args=[flow_id]),
            {"entity_id": entry["entity_id"]},
        )
        if response.status_code != 200 or response.context is None:
            print(
                f"  {entry['position']:>2} {entry['entity_id']:<14} "
                f"HTTP {response.status_code} -> {response.get('Location')}"
            )
            problemas += 1
            continue
        breakdown = response.context["breakdown"]
        rows = response.context["reason_rows"]
        equation = response.context["score_equation"]
        mostrado = breakdown.weighted_total / breakdown.weights_total
        # La cuenta de la pantalla usa los valores tal como se muestran (peso
        # con 2 decimales, resultado LAF con 3), así que reproduce el puntaje
        # del ranking a esa precisión, no bit a bit.
        desvio = abs(mostrado - entry["final_score"])
        coincide = desvio < 5e-4
        cero = [row["key"] for row in rows
                if row["state"] == "participa" and row["weight"] == 0]
        cierra = equation.endswith(
            "= " + f"{entry['final_score']:.2f}".replace(".", ",")
        )
        problemas += (not coincide) + bool(cero) + (not cierra)
        print(
            f"  {entry['position']:>2} {entry['entity_id']:<14} "
            f"ranking={entry['final_score']:.6f} "
            f"formula={mostrado:.6f} "
            f"desvio={desvio:.6f} "
            f"{'OK' if coincide else 'DISTINTO'}"
            f"{'' if not cero else ' peso0=' + ','.join(cero)}"
            f"{'' if cierra else ' ecuacion-no-cierra'}"
        )

    primera = result["ranking"][0]["entity_id"]
    print(
        "URL explicación de la ganadora: http://localhost:8001"
        + reverse("recommender:explanation", args=[flow_id])
        + f"?entity_id={primera}"
    )
    print("URL ranking: http://localhost:8001"
          + reverse("recommender:listing-ranking", args=[flow_id]))
    print("RESULTADO:", "todo coincide" if not problemas else f"{problemas} problemas")
    return 1 if problemas else 0


if __name__ == "__main__":
    raise SystemExit(main())
