"""Sensibilidad del indice de priorizacion de categorias (Tabla 3.1).

Pregunta: ¿el orden de las categorias, y en particular el primer puesto de Cafe MLM,
cambia al variar razonablemente los pesos (0,40/0,35/0,25), el minimo de resenas por
producto (30) y el techo de volumen (15.000)?

Entrada: los CSV de src/00_category_score.py corridos con --all para min-reviews 20, 30 y 50
(carpetas min20/, min30/, min50/). Los pesos y el techo se recalculan aca a partir de las
columnas coverage, balance y reviews_clean; el minimo requiere recorrer Supabase y por eso
viene de las tres corridas.

Uso: venv\Scripts\python.exe artifacts_por_dominio\seleccion_dominio\sensibilidad\sensibilidad_indice.py
"""
from __future__ import annotations

import csv
import glob
import itertools
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAFE = "mlm_mlm194329_20260528_142014"
BASE_W = (0.40, 0.35, 0.25)
BASE_CEILING = 15000


DECISION_CUTOFF = 20260701  # fecha de RANKINGS_CATEGORIAS.md: los 38 conjuntos que existian al decidir


def key_date(key: str) -> int:
    m = re.search(r"_(\d{8})_", key)
    return int(m.group(1)) if m else 0


def load(folder: str, cutoff: int | None = DECISION_CUTOFF) -> list[dict]:
    files = sorted(glob.glob(str(HERE / folder / "category_score_*.csv")))
    if not files:
        return []
    with open(files[-1], encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if cutoff:
        rows = [r for r in rows if key_date(r["dataset_key"]) <= cutoff]
    for r in rows:
        for k in ("coverage", "balance", "volume", "score"):
            r[k] = float(r[k])
        r["reviews_clean"] = int(float(r["reviews_clean"]))
    return rows


def score(r: dict, w: tuple[float, float, float], ceiling: int) -> float:
    v = min(1.0, math.log(r["reviews_clean"] + 1) / math.log(ceiling + 1))
    return w[0] * r["coverage"] + w[1] * r["balance"] + w[2] * v


def ranking(rows: list[dict], w, ceiling) -> list[tuple[str, float]]:
    return sorted(((r["dataset_key"], score(r, w, ceiling)) for r in rows), key=lambda x: -x[1])


def spearman(a: list[str], b: list[str]) -> float:
    pos_b = {k: i for i, k in enumerate(b)}
    n = len(a)
    d2 = sum((i - pos_b[k]) ** 2 for i, k in enumerate(a))
    return 1 - 6 * d2 / (n * (n * n - 1))


def label(rows, key):
    r = next(x for x in rows if x["dataset_key"] == key)
    return f"{r['category_label']} · {r['site_id']}"


def main() -> None:
    base_rows = load("min30")
    if not base_rows:
        raise SystemExit("Falta min30/category_score_*.csv")
    base = ranking(base_rows, BASE_W, BASE_CEILING)
    base_order = [k for k, _ in base]
    out = []
    out.append("# Sensibilidad del indice de priorizacion (Tabla 3.1)\n")
    todos = load("min30", cutoff=None)
    tarde = [r for r in todos if key_date(r["dataset_key"]) > DECISION_CUTOFF]
    out.append(f"Conjuntos evaluados: {len(base_rows)}, los que existian al {DECISION_CUTOFF} (fecha de RANKINGS_CATEGORIAS.md, el documento original de la decision). "
               f"Se excluyen {len(tarde)} conjuntos capturados despues: " + "; ".join(label(todos, r["dataset_key"]) + f" ({key_date(r['dataset_key'])})" for r in tarde) + ". "
               "Con los 43 actuales el 1.º seria Cafe instantaneo MLM, pero ese conjunto se recolecto en agosto como complemento del dominio ya elegido; incluirlo en la comparacion es circular.")
    out.append(f"Base: pesos {BASE_W}, minimo 30, techo {BASE_CEILING}.")
    out.append("Fechas de captura del top 5 al decidir: Cafe MLM 20260528, Celulares MLU 20260616, Celulares MLA 20260430, Hornos MLM 20260529, Celulares MLC 20260616: la comparacion formal se hizo con conjuntos capturados entre abril y junio, algunos posteriores al corpus de cafe.")
    out.append(f"Orden base, top 5: " + " > ".join(label(base_rows, k) for k in base_order[:5]) + "\n")

    # 1) Pesos: cada peso ±0,10 con renormalizacion, y grilla completa en pasos de 0,05
    out.append("## 1. Pesos\n")
    out.append("| wC | wB | wV | puesto de Cafe | 1.º | top 5 igual (conjunto) | rho vs base |")
    out.append("|---:|---:|---:|---:|---|---|---:|")
    grid = [w for w in itertools.product([x / 100 for x in range(20, 61, 5)], repeat=3) if abs(sum(w) - 1) < 1e-9]
    cafe_first = 0
    worst = 1.0
    for w in grid:
        rk = ranking(base_rows, w, BASE_CEILING)
        order = [k for k, _ in rk]
        pos = order.index(CAFE) + 1
        cafe_first += pos == 1
        rho = spearman(base_order, order)
        worst = min(worst, rho)
        if w == BASE_W or abs(w[0] - 0.40) >= 0.10 or abs(w[1] - 0.35) >= 0.10 or abs(w[2] - 0.25) >= 0.10:
            out.append(f"| {w[0]:.2f} | {w[1]:.2f} | {w[2]:.2f} | {pos} | {label(base_rows, order[0])} | {'si' if set(order[:5]) == set(base_order[:5]) else 'no'} | {rho:.3f} |")
    out.append(f"\nGrilla completa: {len(grid)} combinaciones de pesos en [0,20; 0,60] con paso 0,05 que suman 1. "
               f"Cafe queda 1.º en **{cafe_first} de {len(grid)}**. rho minimo contra la base: {worst:.3f}.\n")
    # Donde deja de ser primero
    losers = []
    for w in grid:
        order = [k for k, _ in ranking(base_rows, w, BASE_CEILING)]
        if order[0] != CAFE:
            losers.append((w, label(base_rows, order[0]), order.index(CAFE) + 1))
    if losers:
        out.append("Combinaciones donde Cafe NO es 1.º:")
        for w, who, pos in losers:
            out.append(f"- pesos {w}: gana {who}; Cafe queda {pos}.º")
        out.append("")

    # 2) Techo
    out.append("## 2. Techo de volumen\n")
    out.append("| techo | puesto de Cafe | 1.º | top 5 igual | rho vs base |")
    out.append("|---:|---:|---|---|---:|")
    for c in (5000, 10000, 15000, 20000, 30000, 50000):
        order = [k for k, _ in ranking(base_rows, BASE_W, c)]
        out.append(f"| {c} | {order.index(CAFE) + 1} | {label(base_rows, order[0])} | {'si' if set(order[:5]) == set(base_order[:5]) else 'no'} | {spearman(base_order, order):.3f} |")
    out.append("")

    # 3) Minimo de resenas
    out.append("## 3. Minimo de resenas por producto\n")
    out.append("| minimo | conjuntos | puesto de Cafe | 1.º | top 5 igual | rho vs base |")
    out.append("|---:|---:|---:|---|---|---:|")
    for folder, m in (("min20", 20), ("min30", 30), ("min50", 50)):
        rows = load(folder)
        if not rows:
            out.append(f"| {m} | — | (falta la corrida {folder}) | | | |")
            continue
        order = [k for k, _ in ranking(rows, BASE_W, BASE_CEILING)]
        common = [k for k in base_order if k in order]
        rho = spearman(common, [k for k in order if k in common]) if len(common) > 2 else float("nan")
        out.append(f"| {m} | {len(rows)} | {order.index(CAFE) + 1} | {label(rows, order[0])} | {'si' if set(order[:5]) == set(base_order[:5]) else 'no'} | {rho:.3f} |")
    out.append("")
    out.append("## Lectura\n")
    out.append("Se informa tal cual: si Cafe deja de ser 1.º en alguna variante, se dice en que variante y quien lo reemplaza. "
               "El indice es heuristico; esta tabla no lo vuelve 'robusto', muestra en que rango de parametros la decision se sostiene.")
    (HERE / "RESULTADOS.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
