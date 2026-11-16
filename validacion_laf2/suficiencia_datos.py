"""
suficiencia_datos.py - Pregunta 1 de la validacion LAF2: hay datos para que
LAF2 decida algo?

Para cada snapshot:
  - productos incluidos (products_seed.analysis_status = included, position <= 20),
    igual que SupabaseRepository._laf_candidate_rows;
  - publicaciones por producto: items_clean (universo que usa 09/webapp) y su
    fila en items_raw (de donde 10 saca las condiciones);
  - hechos que produce parse_item() REAL de src/10_laf2_generate.py;
  - cobertura de cada campo crudo (esta informado o no) vs. condicion cumplida;
  - productos con 1 publicacion y productos donde todas las publicaciones
    tienen el mismo vector binario (LAF2 solo decidiria por precio).

Sin cache: si Supabase no responde, falla fuerte.
Uso: venv\\Scripts\\python.exe validacion_laf2\\suficiencia_datos.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
OUT_DIR = Path(__file__).resolve().parent / "salidas"
SNAPSHOTS = {
    "historico": "mlm_mlm194329_20260528_142014",
    "instantaneo": "mlm_mlm194329_20260805_191308",
    "grano_molido": "mlm_mlm194335_20260805_185233",
}
RAW_COLS = (
    "item_id,price,original_price,official_store_id,listing_type_id,"
    "tags,sale_terms,seller_id,shipping_free_shipping,"
    "shipping_logistic_type,shipping_mode"
)
BINARY_KEYS = [
    "has_discount",
    "has_cuotas",
    "has_long_warranty",
    "is_official_store",
    "has_invoice",
    "has_free_shipping",
]


def load_step_10():
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    spec = importlib.util.spec_from_file_location(
        "laf2_step_10", SRC / "10_laf2_generate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rule_structure():
    with open(REPO_ROOT / "config" / "laf2_rule_structure.json", encoding="utf-8") as f:
        return json.load(f)


def fetch_all(query, page=1000):
    """Paginacion simple con range(); Supabase corta en 1000 por defecto."""
    rows = []
    start = 0
    while True:
        chunk = query.range(start, start + page - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < page:
            return rows
        start += page


def raw_field_informed(raw, key):
    """Esta informado el campo crudo del que 10 saca la condicion?"""
    def parse(v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return None
        return v

    if key == "has_discount":
        return raw.get("original_price") not in (None, "", 0, "0", "0.00")
    if key == "has_cuotas":
        tags = parse(raw.get("tags"))
        return isinstance(tags, list) and len(tags) > 0
    if key in ("has_long_warranty", "has_invoice"):
        terms = parse(raw.get("sale_terms")) or []
        wanted = "WARRANTY_TIME" if key == "has_long_warranty" else "INVOICE"
        return any(isinstance(t, dict) and t.get("id") == wanted for t in terms)
    if key == "is_official_store":
        return raw.get("official_store_id") is not None
    if key == "has_free_shipping":
        return raw.get("shipping_free_shipping") is not None
    raise KeyError(key)


def analyze_snapshot(sb, step10, rs, label, dataset_key):
    seed = fetch_all(
        sb.table("products_seed")
        .select("product_id,position,analysis_status")
        .eq("dataset_key", dataset_key)
        .order("position")
    )
    if not seed:
        raise RuntimeError(f"products_seed vacio para {dataset_key}")
    pending = [r for r in seed if (r.get("analysis_status") or "pending") == "pending"]
    if pending:
        raise RuntimeError(f"{dataset_key}: {len(pending)} productos pendientes")
    included = [
        r for r in seed
        if r.get("analysis_status") == "included" and int(r.get("position") or 99) <= 20
    ]
    pids = [r["product_id"] for r in included]
    names = {
        r["product_id"]: r.get("name") or r.get("family_name") or r["product_id"]
        for r in fetch_all(
            sb.table("products_raw")
            .select("product_id,name,family_name")
            .eq("dataset_key", dataset_key)
            .in_("product_id", pids)
        )
    }
    clean = fetch_all(
        sb.table("items_clean")
        .select("item_id,product_id,price,original_price,listing_type,seller_id,official_store_id")
        .eq("dataset_key", dataset_key)
        .in_("product_id", pids)
    )
    raw = fetch_all(
        sb.table("items_raw")
        .select("product_id," + RAW_COLS)
        .eq("dataset_key", dataset_key)
        .in_("product_id", pids)
    )
    raw_by_id = {r["item_id"]: r for r in raw}

    per_product = {}
    all_items = []
    for row in clean:
        pid = row["product_id"]
        r = raw_by_id.get(row["item_id"])
        entry = per_product.setdefault(
            pid, {"clean": 0, "raw_ok": 0, "items": [], "raws": []}
        )
        entry["clean"] += 1
        if r is None:
            continue
        # mismo merge que SupabaseRepository.laf2_generation_items
        merged = dict(r)
        merged["price"] = row.get("price")
        merged["original_price"] = row.get("original_price")
        merged["seller_id"] = row.get("seller_id") or r.get("seller_id")
        merged["official_store_id"] = row.get("official_store_id") or r.get("official_store_id")
        merged["listing_type_id"] = r.get("listing_type_id") or row.get("listing_type")
        parsed = step10.parse_item(merged, rs)
        entry["raw_ok"] += 1
        entry["items"].append(parsed)
        entry["raws"].append(merged)
        all_items.append((pid, parsed, merged))

    # ---- tabla por producto
    rows_out = []
    for pid in pids:
        e = per_product.get(pid, {"clean": 0, "raw_ok": 0, "items": [], "raws": []})
        items = e["items"]
        vectors = Counter(tuple(int(it[k]) for k in BINARY_KEYS) for it in items)
        prices = [it["price"] for it in items]
        pos = next(r["position"] for r in included if r["product_id"] == pid)
        rows_out.append({
            "position": pos,
            "product_id": pid,
            "name": names.get(pid, pid)[:45],
            "pubs_clean": e["clean"],
            "pubs_con_raw": e["raw_ok"],
            "vectores_binarios_distintos": len(vectors),
            "precio_min": float(min(prices)) if prices else None,
            "precio_max": float(max(prices)) if prices else None,
            "precios_distintos": len(set(prices)),
            **{f"n_{k}": sum(int(it[k]) for it in items) for k in BINARY_KEYS},
        })

    # ---- cobertura global
    n = len(all_items)
    coverage = {}
    for k in BINARY_KEYS:
        informed = sum(raw_field_informed(m, k) for _, _, m in all_items)
        true_ = sum(int(p[k]) for _, p, _ in all_items)
        coverage[k] = {
            "informado": informed,
            "informado_pct": round(100 * informed / n, 1) if n else None,
            "cumple": true_,
            "cumple_pct": round(100 * true_ / n, 1) if n else None,
        }
    # detalle de valores crudos para leer que significa "informado"
    detail = {
        "shipping_free_shipping": Counter(str(m.get("shipping_free_shipping")) for _, _, m in all_items),
        "official_store_id_null": sum(m.get("official_store_id") is None for _, _, m in all_items),
        "tags_top": Counter(
            t for _, _, m in all_items
            for t in (json.loads(m["tags"]) if isinstance(m.get("tags"), str) else (m.get("tags") or []))
        ).most_common(12),
        "sale_terms_ids": Counter(
            t.get("id") for _, _, m in all_items
            for t in (json.loads(m["sale_terms"]) if isinstance(m.get("sale_terms"), str) else (m.get("sale_terms") or []))
            if isinstance(t, dict)
        ).most_common(12),
        "warranty_values": Counter(
            json.dumps(t.get("value_struct"), ensure_ascii=False) for _, _, m in all_items
            for t in (json.loads(m["sale_terms"]) if isinstance(m.get("sale_terms"), str) else (m.get("sale_terms") or []))
            if isinstance(t, dict) and t.get("id") == "WARRANTY_TIME"
        ).most_common(8),
        "invoice_values": Counter(
            str(t.get("value_name")) for _, _, m in all_items
            for t in (json.loads(m["sale_terms"]) if isinstance(m.get("sale_terms"), str) else (m.get("sale_terms") or []))
            if isinstance(t, dict) and t.get("id") == "INVOICE"
        ).most_common(8),
    }

    summary = {
        "snapshot": label,
        "dataset_key": dataset_key,
        "productos_incluidos_top20": len(pids),
        "publicaciones_clean": sum(r["pubs_clean"] for r in rows_out),
        "publicaciones_con_raw": n,
        "productos_con_1_publicacion": sum(r["pubs_con_raw"] == 1 for r in rows_out),
        "productos_con_0_publicaciones": sum(r["pubs_con_raw"] == 0 for r in rows_out),
        "productos_todos_mismo_vector": sum(
            r["vectores_binarios_distintos"] <= 1 and r["pubs_con_raw"] >= 2 for r in rows_out
        ),
        "productos_decide_solo_precio": sum(
            r["vectores_binarios_distintos"] <= 1 and r["pubs_con_raw"] >= 2 and r["precios_distintos"] >= 2
            for r in rows_out
        ),
        "productos_con_mas_de_1_vector": sum(r["vectores_binarios_distintos"] >= 2 for r in rows_out),
        "cobertura": coverage,
        "detalle_crudo": {k: (dict(v) if isinstance(v, Counter) else v) for k, v in detail.items()},
    }
    return summary, rows_out


def main():
    load_dotenv(REPO_ROOT / ".env")
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    step10 = load_step_10()
    rs = rule_structure()
    OUT_DIR.mkdir(exist_ok=True)
    report = {}
    for label, key in SNAPSHOTS.items():
        summary, rows = analyze_snapshot(sb, step10, rs, label, key)
        report[label] = {"summary": summary, "productos": rows}
        print(f"\n=== {label} ({key}) ===")
        for k, v in summary.items():
            if k in ("cobertura", "detalle_crudo"):
                continue
            print(f"  {k}: {v}")
        print("  cobertura (informado% / cumple%):")
        for k, c in summary["cobertura"].items():
            print(f"    {k:20s} {c['informado_pct']!s:>6} / {c['cumple_pct']!s:>6}   (n={c['cumple']})")
        print("  detalle crudo:")
        for k, v in summary["detalle_crudo"].items():
            print(f"    {k}: {v}")
        print("  por producto:")
        hdr = "pos pubs vec prec  disc cuot gar ofic fact env  nombre"
        print("   ", hdr)
        for r in rows:
            print(
                f"    {r['position']:>2} {r['pubs_con_raw']:>4} {r['vectores_binarios_distintos']:>3} "
                f"{r['precios_distintos']:>4}  {r['n_has_discount']:>4} {r['n_has_cuotas']:>4} "
                f"{r['n_has_long_warranty']:>3} {r['n_is_official_store']:>4} {r['n_has_invoice']:>4} "
                f"{r['n_has_free_shipping']:>3}  {r['name']}"
            )
    with open(OUT_DIR / "suficiencia_datos.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nOK -> {OUT_DIR / 'suficiencia_datos.json'}")


if __name__ == "__main__":
    main()
