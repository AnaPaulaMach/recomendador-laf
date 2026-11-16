"""Vuelca el ranking LAF2 de produccion para dos productos y tres perfiles.

Uso: venv\Scripts\python.exe validacion_laf2\dump_unificacion_una_etiqueta.py <antes|despues>

Corre el evaluador real (get_evaluator con settings/.env y Docker), no una replica.
Guarda puntajes a 6 decimales para comparar identidad antes/despues del cambio.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "webapp"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "laf_web.settings")
import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from recommender.domain.contracts import EvaluationRequest  # noqa: E402
from recommender.services.use_cases import get_evaluator  # noqa: E402

ASPECTS = ("precio", "descuento", "cuotas", "garantia", "tienda_oficial", "factura", "envio")
SNAPSHOTS = {
    "historico": "mlm_mlm194329_20260528_142014",
    "instantaneo": "mlm_mlm194329_20260805_191308",
    "grano_molido": "mlm_mlm194335_20260805_185233",
}
# Cada producto se toma del snapshot donde tiene la cantidad de publicaciones
# que pide la verificacion: 26 y 9. En "historico" MLM41148521 tiene solo 7.
PRODUCTS = (
    ("MLM19566313", "historico", 26),
    ("MLM41148521", "grano_molido", 9),
)
PROFILES = {
    "todo_bastante": {k: 0.67 for k in ASPECTS},
    "solo_precio": {k: (1.0 if k == "precio" else 0.0) for k in ASPECTS},
    "envio_y_oficial_prioridad": {
        k: (1.0 if k in ("envio", "tienda_oficial") else 0.0) for k in ASPECTS
    },
}
OUT = HERE / "salidas" / "unificacion_una_etiqueta"


def main() -> int:
    fase = sys.argv[1] if len(sys.argv) > 1 else "antes"
    if fase not in ("antes", "despues"):
        print("fase invalida: usar 'antes' o 'despues'")
        return 2
    destino = OUT / fase
    destino.mkdir(parents=True, exist_ok=True)
    evaluator = get_evaluator()
    print("evaluador:", settings.RECOMMENDATION_EVALUATOR)
    print("validated:", settings.LAF_API_RESULTS_VALIDATED,
          "| decision model:", settings.LAF_PRODUCT_DECISION_MODEL)
    report: dict[str, object] = {
        "fase": fase,
        "snapshots": SNAPSHOTS,
        "evaluator_setting": settings.RECOMMENDATION_EVALUATOR,
        "decision_model": settings.LAF_PRODUCT_DECISION_MODEL,
        "productos": {},
    }
    for product_id, snapshot, esperadas in PRODUCTS:
        dataset_key = SNAPSHOTS[snapshot]
        report["productos"][product_id] = {
            "snapshot": snapshot,
            "dataset_key": dataset_key,
            "publicaciones_esperadas": esperadas,
        }
        for profile, preferences in PROFILES.items():
            result = evaluator.evaluate_listings(EvaluationRequest(
                domain="cafe",
                dataset_key=dataset_key,
                strategy="D",
                preferences=dict(preferences),
                selected_entity_id=product_id,
            ))
            filas = [
                {
                    "posicion": entry.position,
                    "entity_id": entry.entity_id,
                    "final_score": round(float(entry.final_score), 6),
                    "status": entry.status,
                    "confidence": round(float(entry.confidence), 6),
                    "preference": round(float(entry.preference), 6),
                    "label_count": entry.metadata.get("label_count"),
                    "score_projection": entry.metadata.get("score_projection"),
                    "contribuciones": [
                        {
                            "aspect": c["aspect"],
                            "normalized_weight": round(float(c["normalized_weight"]), 6),
                            "laf_score": round(float(c["laf_score"]), 6),
                            "contribution": round(float(c["contribution"]), 6),
                        }
                        for c in entry.metadata.get("aspect_contributions", [])
                    ],
                }
                for entry in result.ranking
            ]
            report["productos"][product_id][profile] = {
                "evaluation_status": result.evaluation_status,
                "evaluator_version": result.evaluator_version,
                "publicaciones": len(filas),
                "condiciones_sin_evidencia": (
                    result.ranking[0].metadata.get("conditions_without_evidence")
                    if result.ranking else None
                ),
                "condiciones_con_programa": sorted(result.aspect_programs or {}),
                "ranking": filas,
            }
            marca = "OK " if len(filas) == esperadas else "!! "
            print(f"  {marca}{product_id:14s} {snapshot:13s} {profile:26s} n={len(filas):>3}  "
                  f"{result.evaluation_status}  {result.evaluator_version}")
    path = destino / "ranking_laf2.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("escrito:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
