"""
detalle_campos_crudos.py - Complemento de la pregunta 1: que hay en los campos
crudos que 10 ignora o que nunca se cumplen (WARRANTY_TYPE, tags de cuotas), y
un ejemplo publicacion por publicacion de dos productos del historico.

Uso: venv\\Scripts\\python.exe validacion_laf2\\detalle_campos_crudos.py [pos1 pos2 ...]
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import suficiencia_datos as S  # noqa: E402


def main():
    load_dotenv(S.REPO_ROOT / ".env")
    from supabase import create_client

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    st = S.load_step_10()
    rs = S.rule_structure()

    for label, key in S.SNAPSHOTS.items():
        raw = S.fetch_all(
            sb.table("items_raw")
            .select("product_id,item_id,sale_terms,tags")
            .eq("dataset_key", key)
        )
        wt = Counter()
        for r in raw:
            terms = r.get("sale_terms")
            terms = json.loads(terms) if isinstance(terms, str) else (terms or [])
            for t in terms:
                if isinstance(t, dict) and t.get("id") == "WARRANTY_TYPE":
                    wt[t.get("value_name")] += 1
        camp = Counter(
            t
            for r in raw
            for t in (json.loads(r["tags"]) if isinstance(r.get("tags"), str) else (r.get("tags") or []))
            if "campaign" in t or "install" in t.lower() or "cuota" in t.lower()
        )
        print(f"{label}: items_raw={len(raw)}  WARRANTY_TYPE={dict(wt)}")
        print(f"   tags de cuotas/campaign: {dict(camp) or 'NINGUNO'}")

    positions = [int(a) for a in sys.argv[1:]] or [5, 8]
    key = S.SNAPSHOTS["historico"]
    seed = {
        r["position"]: r["product_id"]
        for r in S.fetch_all(
            sb.table("products_seed").select("product_id,position").eq("dataset_key", key)
        )
    }
    for pos in positions:
        pid = seed[pos]
        clean = S.fetch_all(
            sb.table("items_clean")
            .select("item_id,price,original_price,seller_id,official_store_id,listing_type")
            .eq("dataset_key", key)
            .eq("product_id", pid)
        )
        raw = {
            r["item_id"]: r
            for r in S.fetch_all(
                sb.table("items_raw").select(S.RAW_COLS).eq("dataset_key", key).eq("product_id", pid)
            )
        }
        print(f"\n--- historico pos {pos} {pid} ({len(clean)} publicaciones)")
        for c in sorted(clean, key=lambda x: float(x["price"])):
            m = dict(raw[c["item_id"]])
            m["price"] = c["price"]
            m["original_price"] = c["original_price"]
            m["official_store_id"] = c.get("official_store_id") or m.get("official_store_id")
            p = st.parse_item(m, rs)
            print(
                f"  {p['item_id']:14s} ${float(p['price']):>8.0f} "
                f"disc={int(p['has_discount'])} gar_meses={p['warranty_months']!s:>5} "
                f"ofic={int(p['is_official_store'])} env={int(p['has_free_shipping'])} "
                f"raw_ship={m.get('shipping_free_shipping')!r} seller={c.get('seller_id')}"
            )


if __name__ == "__main__":
    main()
