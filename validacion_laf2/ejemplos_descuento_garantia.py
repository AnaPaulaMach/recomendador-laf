"""Ejemplos reales de descuento (precio vs original_price) y garantia larga en items_clean/items_raw."""
import json, os, sys
from pathlib import Path
from dotenv import load_dotenv
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import suficiencia_datos as S
load_dotenv(S.REPO_ROOT / ".env")
from supabase import create_client
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
for label, key in S.SNAPSHOTS.items():
    clean = S.fetch_all(sb.table("items_clean").select("item_id,product_id,price,original_price").eq("dataset_key", key))
    disc = [c for c in clean if c.get("original_price") and float(c["original_price"]) > float(c["price"])]
    print(f"\n{label}: {len(disc)}/{len(clean)} publicaciones con original_price > price")
    for c in sorted(disc, key=lambda x: -(float(x["original_price"]) - float(x["price"])) / float(x["original_price"]))[:5]:
        pct = 100 * (float(c["original_price"]) - float(c["price"])) / float(c["original_price"])
        print(f"   {c['item_id']} producto {c['product_id']}: ${float(c['price']):,.0f} antes ${float(c['original_price']):,.0f} ({pct:.0f}%)")
    raw = S.fetch_all(sb.table("items_raw").select("item_id,product_id,price,warranty,sale_terms").eq("dataset_key", key))
    long_ = []
    for r in raw:
        terms = r.get("sale_terms"); terms = json.loads(terms) if isinstance(terms, str) else (terms or [])
        for t in terms:
            if isinstance(t, dict) and t.get("id") == "WARRANTY_TIME":
                v = t.get("value_struct") or {}; n = v.get("number") or 0; u = str(v.get("unit") or "")
                months = n * 12 if "a" in u[:1] else (n if "mes" in u else n / 30)
                if months >= 6: long_.append((r["item_id"], r["product_id"], r.get("warranty")))
    print(f"   garantia >= 6 meses: {len(long_)} -> " + "; ".join(f"{i} ({w})" for i, _, w in long_[:6]))
