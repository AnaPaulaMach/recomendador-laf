"""
00_category_score.py - Indice de priorizacion para elegir el dominio del TFG.

Reconstruye el calculo que produjo la Tabla 3.1 del Capitulo 3. El script
original (`paso0_score_v2.py`) se perdio: quedaba en un scratchpad y solo
sobrevivio su documentacion en `RANKINGS_CATEGORIAS.md` (raiz del proyecto),
con la formula y el ranking de los 38 conjuntos. Este script vuelve a hacer el
calculo reproducible desde Supabase.

    P = 0,40 C + 0,35 B + 0,25 V

    C = productos del conjunto semilla con al menos MIN_REVIEWS resenas limpias
        -------------------------------------------------------------------
                        productos del conjunto semilla

    B = 1 - Gini(resenas por producto semilla)

    V = min(1, ln(N + 1) / ln(CEILING + 1)),  N = total de resenas limpias

El cociente de logaritmos no depende de la base: `log` y `ln` dan el mismo
valor. `RANKINGS_CATEGORIAS.md` lo escribe como `log`; la tesis usa `ln`.

El Gini se calcula sobre los productos QUE TIENEN resenas limpias, no sobre
toda la semilla. Asi lo hizo el calculo original (verificado: reproduce las
cinco filas de la Tabla 3.1) y asi lo enuncia la tesis, "el equilibrio de la
cantidad de resenas entre los productos que disponen de ellas". El reparto y
la ausencia se miden por separado: B mide como se distribuye la evidencia
entre los productos que la tienen, y C penaliza a los que no la tienen. En
Celulares de Argentina la diferencia es grande: cinco de sus quince productos
semilla no tienen ninguna resena limpia, y su B pasa de 0,858 a 0,572 si esos
ceros entran al Gini. Con --include-zeros se calcula la otra variante.

Uso:

    .\\venv\\Scripts\\python.exe src\\00_category_score.py            # las 5 de la Tabla 3.1
    .\\venv\\Scripts\\python.exe src\\00_category_score.py --all      # los 43 conjuntos
    .\\venv\\Scripts\\python.exe src\\00_category_score.py --dataset-key mlm_mlm194329_20260528_142014
"""
from __future__ import annotations

import argparse
import csv
import math
import os
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

# Parametros del indice, tal como se documentaron en RANKINGS_CATEGORIAS.md.
MIN_REVIEWS = 30
CEILING = 15000
W_COVERAGE = 0.40
W_BALANCE = 0.35
W_VOLUME = 0.25

# Conjuntos que informa la Tabla 3.1 del Capitulo 3.
TABLA_3_1 = (
    "mlm_mlm194329_20260528_142014",   # Cafe - Mexico
    "mlu_mlu1055_20260616_154220",     # Celulares y Smartphones - Uruguay
    "mla_mla401457_20260430_201454",   # Celulares - Argentina
    "mlm_mlm158487_20260529_125715",   # Hornos electricos - Mexico
    "mlc_mlc1055_20260616_154959",     # Celulares y Smartphones - Chile
)

DEFAULT_OUT = REPO_ROOT / "artifacts_por_dominio" / "seleccion_dominio"


def gini(values: list[int]) -> float:
    """Desigualdad del reparto: 0 si todos reciben lo mismo, ~1 si uno concentra."""
    ordered = sorted(values)
    n = len(ordered)
    total = sum(ordered)
    if n == 0 or total == 0:
        return 0.0
    # Formula por rangos: sum((2i - n - 1) * x_i) / (n * sum(x))
    weighted = sum((2 * (index + 1) - n - 1) * value for index, value in enumerate(ordered))
    return weighted / (n * total)


def volume_term(total_reviews: int, ceiling: int = CEILING) -> float:
    """Volumen normalizado con rendimientos decrecientes y techo en `ceiling`."""
    return min(1.0, math.log(total_reviews + 1) / math.log(ceiling + 1))


def seed_review_counts(sb: Any, dataset_key: str) -> dict[str, int]:
    """Cuenta resenas limpias de cada producto del conjunto semilla."""
    seed = (
        sb.table("products_seed")
        .select("product_id")
        .eq("dataset_key", dataset_key)
        .execute()
        .data
    )
    counts: dict[str, int] = {}
    for row in seed:
        product_id = row["product_id"]
        # count="exact" con limit 1 evita traer las filas: solo interesa el total.
        response = (
            sb.table("reviews_clean")
            .select("id", count="exact")
            .eq("dataset_key", dataset_key)
            .eq("product_id", product_id)
            .limit(1)
            .execute()
        )
        counts[product_id] = int(response.count or 0)
    return counts


def score_dataset(
    sb: Any,
    dataset: dict[str, Any],
    min_reviews: int,
    ceiling: int,
    include_zeros: bool = False,
) -> dict[str, Any]:
    dataset_key = dataset["dataset_key"]
    counts = seed_review_counts(sb, dataset_key)
    values = list(counts.values())
    seed_size = len(values)
    total_reviews = sum(values)

    coverage = (
        sum(1 for value in values if value >= min_reviews) / seed_size
        if seed_size
        else 0.0
    )
    # El reparto se mide entre los productos con evidencia; la ausencia la
    # penaliza `coverage`. Contarla dos veces castigaria lo mismo dos veces.
    spread_values = values if include_zeros else [value for value in values if value > 0]
    balance = 1 - gini(spread_values)
    volume = volume_term(total_reviews, ceiling)
    score = W_COVERAGE * coverage + W_BALANCE * balance + W_VOLUME * volume

    return {
        "dataset_key": dataset_key,
        "site_id": dataset.get("site_id"),
        "category_label": dataset.get("category_label"),
        "seed_products": seed_size,
        "products_over_min": sum(1 for value in values if value >= min_reviews),
        "reviews_clean": total_reviews,
        "coverage": round(coverage, 4),
        "balance": round(balance, 4),
        "products_with_reviews": sum(1 for value in values if value > 0),
        "gini": round(gini(spread_values), 4),
        "volume": round(volume, 4),
        "score": round(score, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-key", action="append", default=[])
    parser.add_argument("--all", action="store_true", help="Procesa todos los conjuntos.")
    parser.add_argument("--min-reviews", type=int, default=MIN_REVIEWS)
    parser.add_argument("--ceiling", type=int, default=CEILING)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--include-zeros",
        action="store_true",
        help="Incluye en el Gini los productos semilla sin resenas limpias.",
    )
    args = parser.parse_args()

    missing = [name for name in ("SUPABASE_URL", "SUPABASE_KEY") if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Faltan variables de entorno: " + ", ".join(missing))

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    datasets = (
        sb.table("datasets")
        .select("dataset_key,site_id,category_id,category_label")
        .order("id")
        .execute()
        .data
    )

    if args.dataset_key:
        wanted = set(args.dataset_key)
    elif args.all:
        wanted = {row["dataset_key"] for row in datasets}
    else:
        wanted = set(TABLA_3_1)

    selected = [row for row in datasets if row["dataset_key"] in wanted]
    unknown = wanted - {row["dataset_key"] for row in selected}
    for key in sorted(unknown):
        print(f"AVISO: {key} no figura en la tabla datasets")

    rows = []
    for dataset in selected:
        row = score_dataset(
            sb, dataset, args.min_reviews, args.ceiling, include_zeros=args.include_zeros
        )
        rows.append(row)
        print(
            f"{row['score']:.3f}  C={row['coverage']:.3f}  B={row['balance']:.3f}  "
            f"V={row['volume']:.3f}  n={row['reviews_clean']:6d}  "
            f"{row['products_over_min']:2d}/{row['seed_products']:2d}  "
            f"{row['site_id']} {row['category_label']}"
        )

    rows.sort(key=lambda item: item["score"], reverse=True)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"category_score_{date.today().isoformat()}.csv"
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nEscrito: {out_path}")


if __name__ == "__main__":
    main()
