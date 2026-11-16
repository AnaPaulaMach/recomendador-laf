"""Conflicto on/off y regla del cero sobre la batería oficial (motor corregido, 8088).

Regenera `conflicto_onoff_regla_cero_20261014.json` (que solo traía el perfil neutro) y lo
amplía al perfil «solo sabor". Escribe `conflicto_onoff_regla_cero_20261017.json`; no
sobrescribe el del 14/10.

Programas: los 14 programas por aspecto de la batería oficial del corpus principal
(`salidas_8088/mc_asp_*.txt`, dataset mlm_mlm194329_20260528_142014, metodología 735f9b0c…).
Cada programa se procesa igual que en `battery_multicriterio_puerto.py` y en
`LAFHttpRecommendationEvaluator._evaluate_products_multicriteria`:
  parse -> zero_threshold_payload -> laf-api -> LAFGraphRankingMapper -> confianza por aspecto
y el ranking se combina con `normalized_multicriteria_ranking` (post_laf_multicriteria_v1;
suma ponderada, preferencia = peso, desempate por identificador).

(a) Conflicto on/off: se reevalúan los 14 programas quitando todas las reglas cuya cabeza es
    negada (`~...`); sin ellas ningún hecho negativo deriva nada y no hay conflicto.
(b) Regla del cero: Spearman entre el puntaje neutro y el número de aspectos con evidencia,
    con rangos promedio para los empates (como el resto del Cap. 6) y con rangos ordinales
    que rompen empates por identificador (la variante que dio 0,845 el 14/10).

Control: con la reglas completas, el puntaje de cada producto debe coincidir con la batería
oficial `validacion_laf1/salidas/battery_multicriterio_mlm194329_20260528_142014.json`.

Uso (desde la raíz del repo, con laf-api en 8088):
  venv/Scripts/python.exe validacion_laf1/revision_director_20260930/motor_corregido_20261007/conflicto_onoff_regla_cero.py
"""
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "webapp"))
from recommender.services.laf_api import LAFApiClient, LAFGraphRankingMapper, LAFProgramParser  # noqa: E402
from recommender.services.post_laf_decision import normalized_multicriteria_ranking, zero_threshold_payload  # noqa: E402

URL = "http://localhost:" + os.environ.get("LAF_PORT", "8088") + "/api/graph"
PROGRAMS = HERE / "salidas_8088"
OFFICIAL = ROOT / "validacion_laf1/salidas/battery_multicriterio_mlm194329_20260528_142014.json"
OLD = HERE / "conflicto_onoff_regla_cero_20261014.json"
OUT = HERE / "conflicto_onoff_regla_cero_20261017.json"
ASPECTS = ["sabor", "aroma", "intensidad", "dulzor", "tueste", "acidez", "presentacion",
           "rendimiento", "variedad", "preparacion", "molienda", "originalidad", "tamano", "caducidad"]
PROFILES = {
    "neutral": {a: 0.5 for a in ASPECTS},
    "solo_sabor": {a: (1.0 if a == "sabor" else 0.0) for a in ASPECTS},
}
PARSER, CLIENT, MAPPER = LAFProgramParser(), LAFApiClient(URL), LAFGraphRankingMapper()


def aspect_scores(conflict: bool) -> dict[str, dict[str, float]]:
    out = {}
    for a in ASPECTS:
        text = (PROGRAMS / f"mc_asp_{a}.txt").read_text(encoding="utf-8")
        payload = zero_threshold_payload(PARSER.parse(text).to_request_payload())
        if not conflict:
            payload["rules"] = [r for r in payload["rules"] if not str(r["headName"]).startswith("~")]
        ranking = MAPPER.map(CLIENT.build_graph(payload), [])
        out[a] = {e.entity_id: e.confidence for e in ranking}
    return out


def ranking(scores, prefs):
    return [(r["entity_id"], float(r["score"])) for r in normalized_multicriteria_ranking(scores, prefs, {})]


def avg_ranks(values: dict[str, float]) -> dict[str, float]:
    keys = sorted(values, key=lambda k: -values[k])
    ranks, i = {}, 0
    while i < len(keys):
        j = i
        while j + 1 < len(keys) and values[keys[j + 1]] == values[keys[i]]:
            j += 1
        for k in keys[i:j + 1]:
            ranks[k] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def ordinal_ranks(values: dict[str, float]) -> dict[str, float]:
    return {k: i + 1 for i, k in enumerate(sorted(values, key=lambda k: (-values[k], k)))}


def pearson(x: dict, y: dict) -> float:
    ks = sorted(set(x) & set(y)); n = len(ks)
    mx = sum(x[k] for k in ks) / n; my = sum(y[k] for k in ks) / n
    sxy = sum((x[k] - mx) * (y[k] - my) for k in ks)
    sx = math.sqrt(sum((x[k] - mx) ** 2 for k in ks)); sy = math.sqrt(sum((y[k] - my) ** 2 for k in ks))
    return sxy / (sx * sy)


def spearman(x, y, ranker):
    ks = sorted(set(x) & set(y))
    return pearson(ranker({k: x[k] for k in ks}), ranker({k: y[k] for k in ks}))


def main():
    on, off = aspect_scores(True), aspect_scores(False)
    official = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    result = {
        "generado_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": URL,
        "programas": str(PROGRAMS.relative_to(ROOT)).replace("\\", "/") + "/mc_asp_*.txt",
        "dataset": "mlm_mlm194329_20260528_142014",
        "modelo_decision": "post_laf_multicriteria_v1 (normalized_multicriteria_ranking)",
        "conflicto_off": "se quitan las reglas con cabeza negada (~) de los 14 programas por aspecto",
        "perfiles": {},
    }
    lines = []
    for name, prefs in PROFILES.items():
        r_on, r_off = ranking(on, prefs), ranking(off, prefs)
        s_on, s_off = dict(r_on), dict(r_off)
        off_ids = [p for p, _ in r_off]
        ref = {row["product"]: row["score"] for row in official[name]}
        max_dev = max(abs(ref[p] - s_on.get(p, 0.0)) for p in ref)
        moved = sum(1 for i in range(len(r_on)) if r_on[i][0] != r_off[i][0])
        rho_avg = spearman(s_on, s_off, avg_ranks)
        rho_ord = spearman(s_on, s_off, ordinal_ranks)
        prof = {
            "n": len(r_on),
            "control_reglas_completas_igual_bateria_oficial": max_dev < 1e-9,
            "max_desvio_vs_bateria_oficial": max_dev,
            "posiciones_que_cambian": moved,
            "spearman_on_off_rangos_promedio": rho_avg,
            "spearman_on_off_rangos_ordinales": rho_ord,
            "ganador_on": r_on[0][0], "ganador_off": r_off[0][0],
            "ganador_se_conserva": r_on[0][0] == r_off[0][0],
            "top3_on": [p for p, _ in r_on[:3]], "top3_off": off_ids[:3],
            "top3_mismo_conjunto": set(p for p, _ in r_on[:3]) == set(off_ids[:3]),
            "posiciones": [{"producto": p, "puesto_on": i + 1, "puesto_off": off_ids.index(p) + 1,
                            "puntaje_on": s_on[p], "puntaje_off": s_off[p]} for i, (p, _) in enumerate(r_on)],
        }
        result["perfiles"][name] = prof
        lines.append(f"[{name}] n={prof['n']} control={'OK' if prof['control_reglas_completas_igual_bateria_oficial'] else 'DIFIERE'} "
                     f"cambian={moved}/{prof['n']} rho_prom={rho_avg:.4f} rho_ord={rho_ord:.4f} "
                     f"ganador {r_on[0][0][:30]} -> {r_off[0][0][:30]} top3_mismo={prof['top3_mismo_conjunto']}")
        for row in prof["posiciones"][:6]:
            lines.append(f"    {row['puesto_on']:2d} -> {row['puesto_off']:2d}  {row['producto'][:45]:45s} {row['puntaje_on']:.4f} -> {row['puntaje_off']:.4f}")

    # (b) regla del cero: puntaje neutro vs número de aspectos con evidencia
    neutral = dict(ranking(on, PROFILES["neutral"]))
    n_asp = {p: sum(1 for a in ASPECTS if p in on[a]) for p in neutral}
    result["regla_del_cero"] = {
        "n_aspectos": n_asp,
        "rango_n_aspectos": [min(n_asp.values()), max(n_asp.values())],
        "spearman_rangos_promedio": spearman(neutral, n_asp, avg_ranks),
        "spearman_rangos_ordinales_por_identificador": spearman(neutral, n_asp, ordinal_ranks),
        "pearson": pearson(neutral, n_asp),
        "nota": "Spearman estándar = rangos promedio para los empates (los de n_aspectos son muchos). "
                "La variante ordinal rompe empates por identificador y es la que dio 0,845 el 14/10.",
    }

    # comparación con el JSON del 14/10 (solo neutro)
    if OLD.exists():
        old = json.loads(OLD.read_text(encoding="utf-8"))
        off_n = dict(ranking(off, PROFILES["neutral"]))
        result["reproduce_20261014"] = {
            "conflicto_on": max(abs(v - neutral[k]) for k, v in old["conflicto_on"].items()) < 1e-9,
            "conflicto_off": max(abs(v - off_n[k]) for k, v in old["conflicto_off"].items()) < 1e-9,
            "n_aspectos": old["n_aspectos"] == n_asp,
        }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    rz = result["regla_del_cero"]
    lines.append(f"[regla del cero] rho rangos promedio={rz['spearman_rangos_promedio']:.4f} "
                 f"ordinal={rz['spearman_rangos_ordinales_por_identificador']:.4f} pearson={rz['pearson']:.4f} "
                 f"aspectos {rz['rango_n_aspectos']}")
    lines.append(f"reproduce 14/10: {result.get('reproduce_20261014')}")
    print("\n".join(lines))
    print(f"-> {OUT.name}")


if __name__ == "__main__":
    main()
