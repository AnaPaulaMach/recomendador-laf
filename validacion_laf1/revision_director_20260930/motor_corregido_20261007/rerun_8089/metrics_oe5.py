"""Tarea 3 OE5: comparar el ranking ARGUMENTATIVO (multicriterio real del webapp)
contra las lineas base cuantitativas, con las 4 metricas acordadas.

PROVISIONAL (version de trust actual, previo a R3/fila 13).

Que hace, en orden, para un --dataset-key:
  1. Regenera el ranking argumentativo FRESCO llamando al battery REAL
     (validacion_laf1/battery_multicriterio.py), que reusa los componentes del
     webapp (laf_api + post_laf_decision) contra la laf-api en Docker. No lee
     cache: si el battery o la API fallan, corta.
  2. Exige el JSON de baselines (validacion_oe5/baselines.py) del mismo dataset.
  3. Lee review_aspects (pos/neg por producto x aspecto) para la coherencia.
  4. Calcula, por perfil (neutral, solo_sabor, solo_aroma):
       PRECISION  - acuerdo del top LAF con cada referencia (B1/B2/B3): Spearman
                    y precision@k (solapamiento de conjuntos top-k).
       COBERTURA  - sentido catalogo: puntajes distintos, productos en 0,
                    rango util, y poder de desempate (pares que una base empata
                    y LAF separa).
       NOVEDAD    - sesgo de popularidad: Spearman(score, nº reseñas) y
                    popularidad media del top-3. Se compara con B2 (volumen) y
                    B3 (calidad).
       COHERENCIA - (i) interna: Spearman(score LAF, evidencia pos-neg) e
                    inversiones duras; (ii) explicacion/posicion (proxy): top-k
                    con evidencia del aspecto activo negativa; (iii) estabilidad:
                    Spearman(neutral, perturbado) y responsividad al perfil.

Uso:
  python validacion_oe5/metrics.py --dataset-key mlm_mlm194329_20260528_142014
  (--skip-battery para reusar la ultima salida del battery, solo al iterar)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUT = HERE / "oe5_8089"; OUT.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)
PY = str(ROOT / "venv/Scripts/python.exe")
BATTERY = ROOT / "validacion_laf1/battery_multicriterio.py"
BATTERY_OUT = HERE.parent / "salidas_8089"
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402
from supabase import create_client  # noqa: E402

load_dotenv(ROOT / ".env")

PROFILES = ["neutral", "solo_sabor", "solo_aroma"]
ACTIVE_ASPECTS = {"neutral": None, "solo_sabor": ["sabor"], "solo_aroma": ["aroma"]}
PERT_PROFILE = "pert_sabor_0.6"  # ya lo produce el battery, para estabilidad


# ----------------------------- utilidades ---------------------------------

def mlm_id(entity_or_pid: str) -> str:
    """Normaliza a 'MLM<digitos>' desde entity_id LAF o product_id base."""
    m = re.match(r"(?i)(ml[am]\d+)", entity_or_pid)
    if not m:
        raise ValueError(f"no pude extraer id MLM de {entity_or_pid!r}")
    return m.group(1).upper()


def spearman(order_a: list[str], order_b: list[str]) -> float:
    ra = {p: i for i, p in enumerate(order_a)}
    rb = {p: i for i, p in enumerate(order_b)}
    common = [p for p in order_a if p in rb]
    n = len(common)
    if n < 2:
        return float("nan")
    d2 = sum((ra[p] - rb[p]) ** 2 for p in common)
    return 1 - 6 * d2 / (n * (n * n - 1))


def spearman_vals(pairs: list[tuple[float, float]]) -> float:
    """Spearman entre dos series numericas (via rangos)."""
    if len(pairs) < 2:
        return float("nan")
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    return spearman_from_ranks(rx, ry)


def spearman_from_ranks(rx, ry) -> float:
    n = len(rx)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    if dx == 0 or dy == 0:
        return float("nan")
    return num / (dx * dy)


def precision_at_k(order_laf: list[str], order_ref: list[str], k: int) -> float:
    top_l = set(order_laf[:k])
    top_r = set(order_ref[:k])
    return len(top_l & top_r) / k


# ----------------------------- carga de datos -----------------------------

def run_battery(dataset_key: str) -> dict:
    suffix = dataset_key.replace("mlm_", "").replace("mco_", "").replace("mla_", "")
    outfile = BATTERY_OUT / f"battery_multicriterio_{suffix}.json"
    if outfile.exists():
        outfile.unlink()  # nunca reutilizar salida vieja
    r = subprocess.run([PY, str(BATTERY), "--dataset-key", dataset_key],
                       cwd=str(ROOT), capture_output=True, text=True)
    if not outfile.exists():
        raise SystemExit(f"battery no genero {outfile.name}: {r.stderr[-1000:]}")
    return json.loads(outfile.read_text(encoding="utf-8"))


def load_battery_existing(dataset_key: str) -> dict:
    suffix = dataset_key.replace("mlm_", "").replace("mco_", "").replace("mla_", "")
    outfile = BATTERY_OUT / f"battery_multicriterio_{suffix}.json"
    if not outfile.exists():
        raise SystemExit(f"no existe {outfile}; corre sin --skip-battery.")
    return json.loads(outfile.read_text(encoding="utf-8"))


def load_baselines(dataset_key: str) -> dict:
    suffix = dataset_key.replace("mlm_", "").replace("mco_", "").replace("mla_", "")
    f = OUT / f"baselines_{suffix}.json"
    if not f.exists():
        raise SystemExit(f"falta {f}; corre primero validacion_oe5/baselines.py --dataset-key {dataset_key}")
    return json.loads(f.read_text(encoding="utf-8"))


def fetch_aspect_counts(sb, dataset_key: str, product_ids: list[str]) -> dict:
    """{MLMid: {aspect: {'pos':int,'neg':int}}} desde review_aspects."""
    counts: dict = defaultdict(lambda: defaultdict(lambda: {"pos": 0, "neg": 0}))
    last_id = 0
    got = 0
    while True:
        resp = (
            sb.table("review_aspects")
            .select("id,product_id,aspect,polarity")
            .eq("dataset_key", dataset_key)
            .in_("product_id", product_ids)
            .gt("id", last_id)
            .order("id")
            .limit(1000)
            .execute()
        )
        page = resp.data or []
        if not page:
            break
        for row in page:
            pid = mlm_id(str(row["product_id"]))
            pol = row["polarity"]
            if pol in ("pos", "neg"):
                counts[pid][row["aspect"]][pol] += 1
        got += len(page)
        last_id = page[-1]["id"]
    if got == 0:
        raise SystemExit(f"review_aspects vacio para {dataset_key}; no hay evidencia para coherencia.")
    return counts


def evidence_net(counts: dict, pid: str, aspects) -> int:
    """pos - neg sobre los aspectos activos (None = todos)."""
    per = counts.get(pid, {})
    items = per.items() if aspects is None else [(a, per.get(a, {"pos": 0, "neg": 0})) for a in aspects]
    return sum(c["pos"] - c["neg"] for _, c in items)


def evidence_pos(counts: dict, pid: str, aspects) -> int:
    per = counts.get(pid, {})
    items = per.items() if aspects is None else [(a, per.get(a, {"pos": 0, "neg": 0})) for a in aspects]
    return sum(c["pos"] for _, c in items)


# ----------------------------- metricas -----------------------------------

def laf_order(battery: dict, profile: str):
    """Devuelve (orden_ids, {id:score}, {id:reviews}) para un perfil."""
    rows = battery[profile]
    ids, score, reviews = [], {}, {}
    for r in rows:
        pid = mlm_id(r["product"])
        ids.append(pid)
        score[pid] = r["score"]
        reviews[pid] = r["reviews"]
    return ids, score, reviews


def compute(dataset_key: str, battery: dict, baselines: dict, counts: dict) -> dict:
    pp = baselines["por_producto"]
    pop = {mlm_id(pid): m["n_rate"] for pid, m in pp.items()}  # popularidad = nº reseñas con rate
    base_order = {k: [mlm_id(x) for x in baselines["orden"][k]] for k in baselines["orden"]}
    names = {mlm_id(pid): m["nombre"] for pid, m in pp.items()}

    result = {"dataset_key": dataset_key, "provisional": "trust actual, previo a R3/fila 13",
              "nombres": names, "por_perfil": {}}

    for profile in PROFILES:
        ids, score, reviews = laf_order(battery, profile)
        aspects = ACTIVE_ASPECTS[profile]
        n = len(ids)

        # --- PRECISION: acuerdo con cada referencia ---
        prec = {}
        for ref in ("b1_estrella_media", "b2_positivas_conteo", "b3_positivas_prop"):
            ro = [p for p in base_order[ref] if p in score]
            prec[ref] = {
                "spearman": round(spearman(ids, ro), 3),
                "prec@3": round(precision_at_k(ids, ro, 3), 3),
                "prec@5": round(precision_at_k(ids, ro, 5), 3),
            }

        # --- COBERTURA: catalogo + desempate ---
        laf_scores = [round(score[p], 3) for p in ids]
        n_distinct_laf = len(set(laf_scores))
        n_zero_laf = sum(1 for s in laf_scores if s == 0.0)
        # poder de desempate vs B1 (estrellas): pares "empatados" en estrellas que LAF separa
        star = {mlm_id(pid): m["b1_estrella_media"] for pid, m in pp.items()}
        pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]]
        star_ties = [(a, b) for (a, b) in pairs if abs(star[a] - star[b]) < 0.01]
        laf_breaks = sum(1 for (a, b) in star_ties if abs(score[a] - score[b]) >= 0.001)
        cobertura = {
            "laf_scores_distintos": n_distinct_laf, "laf_en_cero": n_zero_laf, "n": n,
            "laf_rango": [round(min(score[p] for p in ids), 3), round(max(score[p] for p in ids), 3)],
            "estrella_rango": [round(min(star.values()), 3), round(max(star.values()), 3)],
            "pares_empatados_en_estrellas": len(star_ties),
            "de_esos_LAF_separa": laf_breaks,
        }

        # --- NOVEDAD: sesgo de popularidad ---
        def pop_bias(order_ids):
            # Spearman(score-rank, popularidad): +1 = los mas rankeados son los mas populares
            vals = [(n - i, pop[p]) for i, p in enumerate(order_ids)]  # rank alto = mejor
            return round(spearman_vals(vals), 3)

        top3_pop = lambda order: round(sum(pop[p] for p in order[:3]) / 3, 1)
        novedad = {
            "laf_sesgo_popularidad": pop_bias(ids),
            "b2_sesgo_popularidad": pop_bias([p for p in base_order["b2_positivas_conteo"] if p in pop]),
            "b3_sesgo_popularidad": pop_bias([p for p in base_order["b3_positivas_prop"] if p in pop]),
            "laf_pop_media_top3": top3_pop(ids),
            "b2_pop_media_top3": top3_pop([p for p in base_order["b2_positivas_conteo"] if p in pop]),
            "b3_pop_media_top3": top3_pop([p for p in base_order["b3_positivas_prop"] if p in pop]),
        }

        # --- COHERENCIA ---
        ev_net = {p: evidence_net(counts, p, aspects) for p in ids}
        ev_pos = {p: evidence_pos(counts, p, aspects) for p in ids}
        # (i) interna: Spearman(score, evidencia) + inversiones duras
        coh_i_net = round(spearman_vals([(score[p], ev_net[p]) for p in ids]), 3)
        coh_i_pos = round(spearman_vals([(score[p], ev_pos[p]) for p in ids]), 3)
        hard_inv = []
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if ev_net[a] < ev_net[b] - 3:  # a esta arriba pero su balance es peor por >3
                    hard_inv.append((a, b, ev_net[a], ev_net[b]))
        # (ii) explicacion/posicion (proxy): top-5 con evidencia del aspecto activo negativa
        top5_neg = [p for p in ids[:5] if ev_net[p] < 0]
        # (iii) estabilidad: Spearman(neutral base, perturbado) + responsividad
        coherencia = {
            "i_interna_spearman_net": coh_i_net,
            "i_interna_spearman_pos": coh_i_pos,
            "i_inversiones_duras": len(hard_inv),
            "i_peor_inversion": (hard_inv[0] if hard_inv else None),
            "ii_top5_con_evidencia_negativa": [names[p] for p in top5_neg],
        }

        result["por_perfil"][profile] = {
            "top5": [names[p] for p in ids[:5]],
            "precision": prec, "cobertura": cobertura,
            "novedad": novedad, "coherencia": coherencia,
        }

    # estabilidad LAF (transversal): neutral vs perturbado, y responsividad neutral vs solo_sabor/aroma
    neu_ids, _, _ = laf_order(battery, "neutral")
    pert_ids = [mlm_id(r["product"]) for r in battery.get(PERT_PROFILE, [])]
    ss_ids, _, _ = laf_order(battery, "solo_sabor")
    sa_ids, _, _ = laf_order(battery, "solo_aroma")
    result["estabilidad_laf"] = {
        "neutral_vs_perturbado_sabor0.6": round(spearman(neu_ids, pert_ids), 3) if pert_ids else None,
        "responsividad_neutral_vs_solo_sabor": round(spearman(neu_ids, ss_ids), 3),
        "responsividad_neutral_vs_solo_aroma": round(spearman(neu_ids, sa_ids), 3),
        "nota": "las bases son perfectamente estables (rho=1) pero perfectamente NO responsivas (rho=1): no dependen del perfil.",
    }
    return result


# ----------------------------- impresion ----------------------------------

def show(res: dict):
    print("\n" + "#" * 80)
    print(f"# OE5 Tarea 3 — {res['dataset_key']}  (PROVISIONAL: {res['provisional']})")
    print("#" * 80)
    for profile in PROFILES:
        d = res["por_perfil"][profile]
        print(f"\n{'='*80}\nPERFIL: {profile}\n{'='*80}")
        print("top-5 LAF: " + " | ".join(s[:26] for s in d["top5"]))

        print("\n  PRECISION (acuerdo del orden LAF con cada referencia):")
        print(f"    {'referencia':22s} {'Spearman':>9} {'prec@3':>7} {'prec@5':>7}")
        etq = {"b1_estrella_media": "B1 estrellas (calidad)", "b2_positivas_conteo": "B2 conteo (volumen)",
               "b3_positivas_prop": "B3 proporcion (calidad)"}
        for ref, m in d["precision"].items():
            print(f"    {etq[ref]:22s} {m['spearman']:>9.3f} {m['prec@3']:>7.2f} {m['prec@5']:>7.2f}")

        c = d["cobertura"]
        print("\n  COBERTURA (catalogo + desempate):")
        print(f"    LAF: {c['laf_scores_distintos']}/{c['n']} puntajes distintos, {c['laf_en_cero']} en 0, "
              f"rango {c['laf_rango']}")
        print(f"    Estrellas: rango {c['estrella_rango']} (ancho {round(c['estrella_rango'][1]-c['estrella_rango'][0],3)})")
        print(f"    Desempate: de {c['pares_empatados_en_estrellas']} pares empatados en estrellas (<0.01), "
              f"LAF separa {c['de_esos_LAF_separa']}")

        nv = d["novedad"]
        print("\n  NOVEDAD (sesgo de popularidad; +1 = premia a los mas reseñados):")
        print(f"    LAF={nv['laf_sesgo_popularidad']:+.3f}  B2(volumen)={nv['b2_sesgo_popularidad']:+.3f}  "
              f"B3(calidad)={nv['b3_sesgo_popularidad']:+.3f}")
        print(f"    reseñas medias del top-3:  LAF={nv['laf_pop_media_top3']}  "
              f"B2={nv['b2_pop_media_top3']}  B3={nv['b3_pop_media_top3']}")

        co = d["coherencia"]
        print("\n  COHERENCIA:")
        print(f"    (i) interna  Spearman(score, evidencia neta pos-neg)={co['i_interna_spearman_net']:+.3f}; "
              f"vs solo positivas={co['i_interna_spearman_pos']:+.3f}")
        print(f"        inversiones duras (arriba pero peor balance por >3): {co['i_inversiones_duras']}")
        if co["i_peor_inversion"]:
            a, b, ea, eb = co["i_peor_inversion"]
            print(f"        peor: {res['nombres'][a][:30]} (ev {ea}) sobre {res['nombres'][b][:30]} (ev {eb})")
        print(f"    (ii) top-5 con evidencia negativa del aspecto activo: "
              f"{co['ii_top5_con_evidencia_negativa'] or 'ninguno'}")

    e = res["estabilidad_laf"]
    print(f"\n{'='*80}\nESTABILIDAD / RESPONSIVIDAD (LAF, transversal)\n{'='*80}")
    print(f"  (iii) estabilidad: neutral vs perturbado(sabor 0.6) Spearman={e['neutral_vs_perturbado_sabor0.6']}")
    print(f"        responsividad: neutral vs solo_sabor={e['responsividad_neutral_vs_solo_sabor']}, "
          f"vs solo_aroma={e['responsividad_neutral_vs_solo_aroma']}")
    print(f"        {e['nota']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-key", required=True)
    ap.add_argument("--skip-battery", action="store_true", help="reusar ultima salida del battery (solo al iterar)")
    args = ap.parse_args()

    battery = load_battery_existing(args.dataset_key) if args.skip_battery else run_battery(args.dataset_key)
    baselines = load_baselines(args.dataset_key)
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    product_ids = sorted(baselines["por_producto"].keys())
    counts = fetch_aspect_counts(sb, args.dataset_key, product_ids)

    res = compute(args.dataset_key, battery, baselines, counts)
    show(res)
    suffix = args.dataset_key.replace("mlm_", "").replace("mco_", "").replace("mla_", "")
    (OUT / f"metrics_{suffix}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nguardado: validacion_oe5/salidas/metrics_{suffix}.json")


if __name__ == "__main__":
    main()
