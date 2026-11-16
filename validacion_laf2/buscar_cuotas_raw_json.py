"""
buscar_cuotas_raw_json.py - Expone Mercado Libre Mexico las cuotas en algun
campo distinto de tags? Revisa items_raw.raw_json (JSON completo del item).

Uso: venv\\Scripts\\python.exe validacion_laf2\\buscar_cuotas_raw_json.py
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

KEYWORDS = ("install", "cuota", "meses", "interes", "mercadopago", "financ")


def walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v, path + "[]")
    else:
        yield path, obj


def main():
    load_dotenv(S.REPO_ROOT / ".env")
    from supabase import create_client

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    for label, key in S.SNAPSHOTS.items():
        rows = S.fetch_all(
            sb.table("items_raw").select("item_id,raw_json").eq("dataset_key", key)
        )
        n = len(rows)
        with_payload = [r for r in rows if r.get("raw_json")]
        top_keys = Counter()
        hit_paths = Counter()
        hit_examples = {}
        for r in with_payload:
            p = r["raw_json"]
            if isinstance(p, str):
                try:
                    p = json.loads(p)
                except Exception:
                    continue
            if isinstance(p, dict):
                top_keys.update(p.keys())
            for path, val in walk(p):
                low = (path + " " + str(val)).lower()
                if any(k in low for k in KEYWORDS):
                    hit_paths[path] += 1
                    hit_examples.setdefault(path, str(val)[:120])
        print(f"\n=== {label}: items_raw={n}, con raw_json={len(with_payload)}")
        print("  claves de primer nivel:", sorted(top_keys))
        print("  rutas con cuotas/installments/meses/interes/mercadopago/financ:")
        for path, c in hit_paths.most_common(20):
            print(f"    {c:>4}  {path}  ej: {hit_examples[path]}")
        if not hit_paths:
            print("    NINGUNA")


if __name__ == "__main__":
    main()
