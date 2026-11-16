"""EXP 12 - Sensibilidad del ranking a las confianzas de las reglas (Cap. 4, Tablas 4.X y 4.Y).

Perturba en bloque, sin tocar la configuracion congelada:
  A) RULE_CONF_AGGREGATION (nivel evidencia -> aspecto, 0,85 constante): 0,75 y 0,95.
  B) confianzas aspecto -> dimension (positivas y negativas): todas -0,10 y todas +0,10 (tope 1,0).
  C) confianzas dimension -> recomendar / ~recomendar: todas -0,10 y todas +0,10 (tope 1,0).
  D) aleatorio: 20 perturbaciones uniformes en [-0,05; +0,05] sobre todas las confianzas de B y C
     (semilla 20260913), para ver la dispersion tipica.
Compara cada variante con el ranking vigente en tres perfiles (neutro, solo sabor, solo aroma):
rho de Spearman, cuantos productos cambian de puesto, si cambia el top 3 y el ganador.

Reutiliza la infraestructura de exp11 / validacion_robustez (control 18/18 contra la bateria).
Uso: venv\Scripts\python.exe validacion_laf1\exp12_sensibilidad_confianzas_reglas.py
"""
from __future__ import annotations

import copy
import io
import json
import random
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "validacion_robustez"))
sys.path.insert(0, str(HERE))
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import bootstrap_ranking as br  # noqa: E402
import exp11_fila13_impacto as e11  # noqa: E402

ASPECTOS = br.ASPECTOS
PERFILES = {
    "neutro": {a: 0.67 for a in ASPECTOS},
    "solo_sabor": {**{a: 0.0 for a in ASPECTOS}, "sabor": 1.0},
    "solo_aroma": {**{a: 0.0 for a in ASPECTOS}, "aroma": 1.0},
}
e11.PERFILES = PERFILES


def clip(x: float) -> float:
    return max(0.0, min(1.0, round(x, 3)))


def perturb(dom: dict, *, dims_delta: float | None = None, rec_delta: float | None = None,
            rng: random.Random | None = None, amp: float = 0.05) -> dict:
    d = copy.deepcopy(dom)
    dims = d["laf1_rule_structure"]["dimensions"]
    for dim in dims.values():
        for asp in dim.get("aspects", []):
            for k in ("confidence", "negative_confidence"):
                if k in asp:
                    delta = dims_delta if dims_delta is not None else (rng.uniform(-amp, amp) if rng else 0.0)
                    asp[k] = clip(float(asp[k]) + delta)
        for k in ("recommend", "not_recommend"):
            if k in dim and "confidence" in dim[k]:
                delta = rec_delta if rec_delta is not None else (rng.uniform(-amp, amp) if rng else 0.0)
                dim[k]["confidence"] = clip(float(dim[k]["confidence"]) + delta)
    return d


def comparar(base: list, otro: list) -> dict:
    o0 = [p for p, _ in base]; o1 = [p for p, _ in otro]
    pos0 = {p: i + 1 for i, p in enumerate(o0)}; pos1 = {p: i + 1 for i, p in enumerate(o1)}
    rho = br.spearman([pos0[p] for p in o0], [pos1[p] for p in o0])
    return {"rho": round(rho, 3), "cambian": sum(1 for p in o0 if pos0[p] != pos1[p]),
            "top3_igual": set(o0[:3]) == set(o1[:3]), "ganador_igual": o0[0] == o1[0]}


def main() -> None:
    trust06, gen08, laf = br.cargar_modulos()
    sb = br.conectar()
    trust_rows = br.leer_todo(sb, "review_trust", "id,review_id,product_id,trust_score", dataset_key=br.DATASET_KEY)
    mention_rows = br.leer_todo(sb, "review_aspects", "id,review_id,product_id,aspect,polarity,extraction_confidence",
                                dataset_key=br.DATASET_KEY)
    from product_scope import require_included_product_ids
    incluidos = require_included_product_ids(sb, br.DATASET_KEY, stage_name="exp12")
    productos = gen08.load_products(sb, incluidos, top_n=20)
    trust_map = {(r["review_id"], r["product_id"]): float(r["trust_score"]) for r in trust_rows}
    dom0 = gen08.DOMAIN

    def run(dom, agg=None):
        old = gen08.RULE_CONF_AGGREGATION
        if agg is not None:
            gen08.RULE_CONF_AGGREGATION = agg
        try:
            r, _, _ = e11.ranking_con_dominio(trust06, gen08, laf, productos, mention_rows, trust_map, dom)
        finally:
            gen08.RULE_CONF_AGGREGATION = old
        return r

    print("=" * 78)
    print("EXP 12 - sensibilidad a las confianzas de las reglas")
    print(f"  dataset_key: {br.DATASET_KEY}   fecha: {date.today().isoformat()}   productos: {len(productos)}")
    base = run(dom0)
    ref = HERE.parent / "salidas_8089/battery_multicriterio_mlm194329_20260528_142014.json"
    if ref.exists():
        bat = json.load(open(ref, encoding="utf-8"))
        for perfil, clave in {"neutro": "neutral", "solo_sabor": "solo_sabor"}.items():
            mio = [p for p, _ in base[perfil]]
            assert mio == [x["product"] for x in bat[clave]], f"control {perfil} NO reproduce la bateria"
            print(f"  control {perfil}: igual a la bateria {len(mio)}/{len(mio)}")

    variantes = {
        "A: agregacion 0,75 (base 0,85)": (dom0, 0.75),
        "A: agregacion 0,95": (dom0, 0.95),
        "B: aspecto->dimension -0,10": (perturb(dom0, dims_delta=-0.10), None),
        "B: aspecto->dimension +0,10": (perturb(dom0, dims_delta=+0.10), None),
        "C: dimension->recomendar -0,10": (perturb(dom0, rec_delta=-0.10), None),
        "C: dimension->recomendar +0,10": (perturb(dom0, rec_delta=+0.10), None),
    }
    salida = {"dataset_key": br.DATASET_KEY, "fecha": date.today().isoformat(), "variantes": {}, "aleatorio": {}}
    print("\n" + "-" * 78)
    print(f"{'variante':34s} {'perfil':11s} {'rho':>6s} {'cambian':>8s} {'top3':>6s} {'ganador':>8s}")
    for nombre, (dom, agg) in variantes.items():
        r = run(dom, agg)
        salida["variantes"][nombre] = {}
        for perfil in PERFILES:
            c = comparar(base[perfil], r[perfil])
            salida["variantes"][nombre][perfil] = c
            print(f"{nombre:34s} {perfil:11s} {c['rho']:6.3f} {c['cambian']:>5d}/18 {'igual' if c['top3_igual'] else 'CAMBIA':>6s} {'igual' if c['ganador_igual'] else 'CAMBIA':>8s}")

    print("\n" + "-" * 78)
    print("D: 20 perturbaciones aleatorias uniformes en [-0,05; +0,05] sobre B y C (semilla 20260913)")
    rng = random.Random(20260913)
    acc = {p: {"rho": [], "cambian": [], "top3": 0, "ganador": 0} for p in PERFILES}
    for i in range(20):
        r = run(perturb(dom0, rng=rng, amp=0.05))
        for perfil in PERFILES:
            c = comparar(base[perfil], r[perfil])
            acc[perfil]["rho"].append(c["rho"]); acc[perfil]["cambian"].append(c["cambian"])
            acc[perfil]["top3"] += c["top3_igual"]; acc[perfil]["ganador"] += c["ganador_igual"]
    for perfil, a in acc.items():
        rh = sorted(a["rho"])
        print(f"  {perfil:11s} rho media {sum(rh)/len(rh):.3f} (min {rh[0]:.3f})  cambian media {sum(a['cambian'])/20:.1f}/18  "
              f"top3 igual {a['top3']}/20  ganador igual {a['ganador']}/20")
        salida["aleatorio"][perfil] = {"rho_media": sum(rh) / len(rh), "rho_min": rh[0],
                                       "cambian_media": sum(a["cambian"]) / 20, "top3_igual": a["top3"], "ganador_igual": a["ganador"]}
    out = HERE / f"exp12_sensibilidad_confianzas_8089_{date.today().isoformat()}.json"
    json.dump(salida, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"\n  -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
