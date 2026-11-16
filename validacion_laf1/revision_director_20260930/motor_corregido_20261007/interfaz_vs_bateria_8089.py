# Copia de salidas/recongelado_20260910/interfaz_vs_bateria.py: produccion (LAF_API_URL=8089) vs bateria corrida contra 8089.
"""Camino de PRODUCCION (get_evaluator() del webapp, LAF_API_RESULTS_VALIDATED=1) vs bateria.
Uso: venv/Scripts/python validacion_laf1/salidas/recongelado_20260910/interfaz_vs_bateria.py

2026-09-11: dos arreglos del script, ninguno del ranking.

1. La bateria guarda el producto como slug (`mlm26912881_cafe_blason_...`) y el
   evaluador de produccion devuelve el id del catalogo (`MLM26912881`), asi que
   la comparacion literal daba 0/18 en los cinco perfiles aunque el orden fuera
   identico. Se normaliza con `_id()` antes de comparar. Con eso: 18/18 en los
   cinco perfiles y max|dscore| <= 1e-6.
2. Escribia su salida sobre `despues/interfaz_vs_bateria.json`, el artefacto
   versionado del 2026-09-10, y correrlo lo perdia. Ahora escribe en
   `despues/interfaz_vs_bateria_<fecha de corrida>.json`.
"""
import io, json, os, re, sys
from datetime import date
from pathlib import Path
HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[2]
os.environ["LAF_API_RESULTS_VALIDATED"] = "1"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "laf_web.settings")
os.environ["RECOMMENDATION_EVALUATOR"] = "recommender.services.evaluators.LAFHttpRecommendationEvaluator"
sys.path.insert(0, str(ROOT / "webapp"))
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import django; django.setup()
from django.conf import settings
from recommender.services.use_cases import get_evaluator
from recommender.domain.contracts import EvaluationRequest
DS = "mlm_mlm194329_20260528_142014"
ASPECTS = ["sabor","aroma","intensidad","dulzor","tueste","acidez","presentacion","rendimiento","variedad","preparacion","molienda","originalidad","tamano","caducidad"]
def _id(value):
    """El id del catalogo, venga como slug de la bateria o como entity_id."""
    m = re.match(r"^(mlm\d+)_", str(value).lower())
    return (m.group(1) if m else str(value)).upper()


def prof(base, **o):
    p = {a: base for a in ASPECTS}; p.update(o); return p
PROFILES = {"neutral": prof(0.67), "solo_sabor": prof(0.0, sabor=1.0), "solo_aroma": prof(0.0, aroma=1.0),
            "sensorial": prof(0.0, sabor=1.0, aroma=1.0, intensidad=1.0, dulzor=1.0, tueste=1.0, acidez=1.0),
            "pert_sabor_0.6": prof(0.5, sabor=0.6)}
ev = get_evaluator()
print("evaluator:", type(ev).__name__, "| results_validated:", settings.LAF_API_RESULTS_VALIDATED,
      "| decision model:", settings.LAF_PRODUCT_DECISION_MODEL, "| api:", settings.LAF_API_URL)
bat = json.load(open(HERE / "salidas_8089/battery_multicriterio_mlm194329_20260528_142014.json", encoding="utf-8"))
salida = {"dataset_key": DS, "evaluator": type(ev).__name__, "perfiles": {}}
ok_total = True
for name, P in PROFILES.items():
    res = ev.evaluate_products(EvaluationRequest(domain="cafe", dataset_key=DS, strategy="D", preferences=P))
    ids = [_id(e.entity_id) for e in res.ranking]
    esperado = [_id(x["product"]) for x in bat[name]]
    iguales = sum(a == b for a, b in zip(ids, esperado))
    ok = ids == esperado; ok_total &= ok
    sc_bat = {_id(x["product"]): x["score"] for x in bat[name]}
    dmax = max(abs(float(e.final_score) - sc_bat[_id(e.entity_id)]) for e in res.ranking) if ok else None
    print(f"{name:15s} status={res.evaluation_status:10s} sha={res.methodology_sha256[:12]} n={len(ids)} "
          f"orden = bateria {iguales}/{len(esperado)} {'OK' if ok else 'DIFIERE'}  max|dscore|={dmax}")
    salida["perfiles"][name] = {"evaluation_status": res.evaluation_status, "methodology_sha256": res.methodology_sha256,
        "orden_interfaz": ids, "orden_bateria": esperado, "iguales": iguales, "identico": ok, "max_diff_score": dmax,
        "ranking": [{"position": e.position, "entity_id": e.entity_id, "entity_name": e.entity_name,
                     "final_score": float(e.final_score), "status": e.status} for e in res.ranking]}
    if name == "neutral":
        salida["programa_sha_header"] = [l for l in res.laf_program.splitlines() if "SHA" in l or "recomendar(X) :- ~" in l]
        print("   programa:", salida["programa_sha_header"])
destino = HERE / f"interfaz_vs_bateria_8089_{date.today():%Y%m%d}.json"
json.dump(salida, open(destino, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("salida:", destino.name)
print("RESULTADO GLOBAL:", "interfaz = bateria en todos los perfiles" if ok_total else "HAY DIFERENCIAS")
