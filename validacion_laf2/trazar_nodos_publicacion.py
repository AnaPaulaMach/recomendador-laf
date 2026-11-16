"""
trazar_nodos_publicacion.py - Muestra el programa LAF2 real y los nodos del grafo
(Docker) de una publicacion, para entender de donde sale [conf, pref] de recomendar.

Uso: venv\\Scripts\\python.exe validacion_laf2\\trazar_nodos_publicacion.py historico MLM16250244 MLM4127889302 [perfil]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prueba_sin_cuotas_factura as P  # noqa: E402
import suficiencia_datos as S  # noqa: E402


def main():
    snap, pid, item_id = sys.argv[1:4]
    profile = sys.argv[4] if len(sys.argv) > 4 else "web_default_0.67"
    load_dotenv(P.ROOT / ".env")
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    step10 = S.load_step_10()
    cfg = P.variants()["actual_7"]
    name, raws = P.load_products(sb, S.SNAPSHOTS[snap])[pid]
    items = sorted((step10.parse_item(r, cfg["laf2_rule_structure"]) for r in raws), key=lambda it: it["price"])
    prefs = P.profiles(list(cfg["purchase_aspects"]))[profile]
    program = step10.build_laf2(items, prefs, name, domain=cfg, dataset_key=S.SNAPSHOTS[snap], product_id=pid)
    arg = step10.safe_id(item_id)
    print("=== lineas del programa para", item_id, "y reglas ===")
    for line in program.splitlines():
        s = line.strip()
        if not s or s.startswith("%"):
            continue
        if arg in s or ":-" in s:
            print("  ", s)
    graph = P.CLIENT.build_graph(P.PARSER.parse(program).to_request_payload())
    print("\n=== nodos del grafo con", arg, "===")
    for n in graph["nodes"]:
        lab = str(n.get("label") or "")
        if arg in lab:
            print(f"  {n.get('id'):>6} {n.get('type'):5} {lab:45s} attr={n.get('attributes')} delta={n.get('deltaAttributes')}")
    print("\n=== ranking (mapper real) ===")
    ents = [{"argument": step10.safe_id(it["item_id"]), "entity_id": it["item_id"], "entity_name": it["item_id"], "metadata": {}} for it in items]
    for e in P.MAPPER.map(graph, ents):
        print(f"  {e.position:>2} {e.entity_id:14s} score={e.final_score:.3f} conf={e.confidence:.3f} pref={e.preference:.3f} {e.status}")


if __name__ == "__main__":
    main()
