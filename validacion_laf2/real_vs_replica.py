"""
real_vs_replica.py - Corre el evaluador de PRODUCCION del webapp (get_evaluator con la
configuracion real de settings/.env) para LAF2 y compara con la replica de
battery_multicriterio_laf2.py (variante C) producto por producto.

Uso: venv\\Scripts\\python.exe validacion_laf2\\real_vs_replica.py [historico|instantaneo|grano_molido]
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
import suficiencia_datos as S  # noqa: E402


def _grupos(pares):
    """Los puntajes en orden y, por puntaje, el conjunto de publicaciones."""
    orden, conjuntos = [], []
    for pid, score in pares:
        if not orden or orden[-1] != score:
            orden.append(score)
            conjuntos.append({pid})
        else:
            conjuntos[-1].add(pid)
    return orden, conjuntos


def _equivalentes(real, replica):
    return _grupos(real) == _grupos(replica)


def main():
    snap = sys.argv[1] if len(sys.argv) > 1 else "historico"
    key = S.SNAPSHOTS[snap]
    print("evaluador:", settings.RECOMMENDATION_EVALUATOR)
    print("validated:", settings.LAF_API_RESULTS_VALIDATED, "| decision model:", settings.LAF_PRODUCT_DECISION_MODEL)
    evaluator = get_evaluator()
    replica = json.load(open(HERE / "salidas" / "battery_multicriterio_laf2.json", encoding="utf-8"))[snap]
    profiles = {
        "neutral_0.5": lambda a: {k: 0.5 for k in a},
        "solo_precio": lambda a: {k: (1.0 if k == "precio" else 0.0) for k in a},
        "solo_envio": lambda a: {k: (1.0 if k == "envio" else 0.0) for k in a},
    }
    aspects = ["precio", "descuento", "cuotas", "garantia", "tienda_oficial", "factura", "envio"]
    agree = total = 0
    for row in replica:
        pid = row["product_id"]
        for pname, make in profiles.items():
            result = evaluator.evaluate_listings(EvaluationRequest(
                domain="cafe", dataset_key=key, strategy="D",
                preferences=make(aspects), selected_entity_id=pid,
            ))
            real = [(e.entity_id, round(e.final_score, 4)) for e in result.ranking]
            rep = [tuple(x) for x in row["perfiles"][pname]["mc_C"]]
            # La replica no completa con 0 las publicaciones ausentes: comparo la
            # parte comun. Y no modela el desempate de LAF 2 (-puntaje,
            # -confianza baseline, id): ordena los empates por id. Asi que la
            # comparacion es por puntaje en orden y, dentro de cada puntaje, por
            # conjunto de publicaciones. Comparar la secuencia literal contaba
            # como diferencia lo que solo es otro orden entre empatadas
            # (verificado el 2026-09-11: era el unico motivo de los DIF).
            real_head = real[: len(rep)]
            ok = _equivalentes(real_head, rep) and result.evaluation_status == "validated"
            agree += ok
            total += 1
            extra = len(real) - len(rep)
            flag = "OK " if ok else "DIF"
            if ok and real_head != rep:
                flag = "OK*"
            print(f"  {flag} {pid} {pname:12s} real={len(real)} replica={len(rep)} completadas_con_0={extra} "
                  f"status={result.evaluation_status} sin_evidencia={result.ranking[0].metadata.get('conditions_without_evidence') if result.ranking else None}")
            if not ok:
                print("      real   :", real[:5])
                print("      replica:", rep[:5])
    print(f"\n{snap}: coinciden {agree}/{total} (producto x perfil)")
    print("OK* = mismos puntajes en el mismo orden, distinto orden entre empatadas:")
    print("      la replica no modela el desempate de LAF 2 y ordena los empates por id.")


if __name__ == "__main__":
    main()
