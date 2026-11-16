"""
09_laf2_preferences.py - Preferencias del usuario para LAF 2.

El usuario ya eligiÃ³ un producto. Ahora indica:
  - Su presupuesto mÃ¡ximo (filtra publicaciones)
  - QuÃ© condiciones de COMPRA le importan (cuotas, garantÃ­a, tienda oficial,
    descuento, etc.)

Uso:
    streamlit run src/09_laf2_preferences.py
    â†’ guarda prefs_laf2.json
    -> correr src/10_laf2_generate.py para generar el programa LAF 2
"""

import json, os, sys
from decimal import Decimal
from pathlib import Path
import streamlit as st
from supabase import create_client
from dotenv import load_dotenv
from domain_config import artifact_path, load_domain_config
from money import money_for_storage, parse_money
from product_scope import (
    ProductReviewPendingError,
    ProductReviewSetupError,
    require_included_product_ids,
)

load_dotenv()
REPO_ROOT = Path(__file__).resolve().parents[1]
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
DATASET_KEY  = os.environ.get("DATASET_KEY")
DOMAIN = load_domain_config()

PREFS_LAF1_FILE = artifact_path("prefs_laf1", ".json", DOMAIN)
PREFS_LAF2_FILE = artifact_path("prefs_laf2", ".json", DOMAIN)
DEFAULT_TOP_N = 20

# Aspectos de COMPRA para LAF 2 (distintos a los de calidad del LAF 1)
PURCHASE_ASPECTS = {
    key: meta["label"]
    for key, meta in DOMAIN["purchase_aspects"].items()
}

ui = DOMAIN["ui"]
st.set_page_config(page_title=ui.get("laf2_page_title", "Preferencias de compra"), layout="centered")
st.title(ui.get("laf2_title", "Preferencias de compra"))

# â”€â”€ Mostrar quÃ© producto eligiÃ³ el usuario â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if os.path.exists(PREFS_LAF1_FILE):
    laf1 = json.load(open(PREFS_LAF1_FILE, encoding="utf-8"))
else:
    laf1 = {}

@st.cache_resource
def get_sb():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

try:
    INCLUDED_PRODUCT_IDS = require_included_product_ids(
        get_sb(),
        DATASET_KEY,
        stage_name="09_laf2_preferences.py",
    )
except (ProductReviewSetupError, ProductReviewPendingError) as exc:
    st.error(str(exc))
    st.stop()

@st.cache_data(ttl=300)
def load_products(top_n=DEFAULT_TOP_N):
    sb = get_sb()
    q_seed = sb.table("products_seed").select("product_id, position")
    if DATASET_KEY:
        q_seed = q_seed.eq("dataset_key", DATASET_KEY)
    q_seed = q_seed.in_("product_id", sorted(INCLUDED_PRODUCT_IDS))
    seed = {
        r["product_id"]: int(r["position"])
        for r in q_seed.execute().data
        if int(r["position"]) <= top_n
    }

    q_raw = sb.table("products_raw").select("product_id, name")
    if DATASET_KEY:
        q_raw = q_raw.eq("dataset_key", DATASET_KEY)
    q_raw = q_raw.in_("product_id", sorted(INCLUDED_PRODUCT_IDS))
    names = {r["product_id"]: r.get("name", r["product_id"]) for r in q_raw.execute().data}

    return {
        pid: f"#{pos:02d} - {names.get(pid, pid)}"
        for pid, pos in sorted(seed.items(), key=lambda x: x[1])
    }

@st.cache_data(ttl=300)
def load_items(product_id):
    sb = get_sb()
    q  = sb.table("items_clean") \
           .select("item_id,price,original_price,condition,listing_type,seller_id,official_store_id") \
           .eq("product_id", product_id)
    if DATASET_KEY:
        q = q.eq("dataset_key", DATASET_KEY)
    return sorted(
        q.execute().data,
        key=lambda x: parse_money(x.get("price"), Decimal("Infinity")),
    )

# â”€â”€ SelecciÃ³n de producto â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
products = load_products()
if not products:
    st.error("No hay productos. Â¿Corriste src/01_clean.py?")
    sys.exit(1)

opts = {v: k for k, v in products.items()}
selected_name = st.selectbox(
    "Producto que elegiste (del ranking LAF 1)",
    list(opts.keys()),
    help="ElegÃ­ el producto que el sistema te recomendÃ³ en LAF 1"
)
selected_pid = opts[selected_name]

# â”€â”€ Rango de precios â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
items = load_items(selected_pid)
if not items:
    st.warning("No hay publicaciones para este producto.")
    st.stop()

prices = [
    price
    for i in items
    if (price := parse_money(i.get("price"))) is not None
]
min_p    = min(prices)
max_p    = max(prices)

st.caption(f"Publicaciones disponibles: {len(items)} Â· Precios: ${min_p:,.0f} â€“ ${max_p:,.0f}")

col1, col2 = st.columns(2)
with col1:
    budget_min = st.number_input(
        "Presupuesto mÃ­nimo (ARS)",
        min_value=0, max_value=int(max_p),
        value=int(min_p), step=10_000
    )
with col2:
    budget_max = st.number_input(
        "Presupuesto mÃ¡ximo (ARS)",
        min_value=0, max_value=int(max_p * 2),
        value=int(max_p), step=10_000
    )

budget_min_decimal = Decimal(budget_min)
budget_max_decimal = Decimal(budget_max)
items_in_budget = [
    i
    for i in items
    if (
        (price := parse_money(i.get("price"))) is not None
        and budget_min_decimal <= price <= budget_max_decimal
    )
]
st.metric("Publicaciones en tu rango", len(items_in_budget))

if not items_in_budget:
    st.error("Ninguna publicaciÃ³n entra en ese rango. AjustÃ¡ los valores.")
    st.stop()

st.divider()

# â”€â”€ Preferencias de compra â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.subheader(ui.get("laf2_purchase_title", "Condiciones de compra"))
st.caption("0 = no me importa Â· 1 = es lo mÃ¡s importante")

defaults2 = {k: 0.5 for k in PURCHASE_ASPECTS}
if os.path.exists(PREFS_LAF2_FILE):
    try:
        saved = json.load(open(PREFS_LAF2_FILE, encoding="utf-8"))
        defaults2.update({k: saved.get(k, 0.5) for k in PURCHASE_ASPECTS})
    except Exception:
        pass

prefs2 = {}
for key, label in PURCHASE_ASPECTS.items():
    prefs2[key] = st.slider(label, 0.0, 1.0, float(defaults2[key]), 0.05, key=f"laf2_{key}")

st.divider()

# â”€â”€ Guardar â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if st.button("Generar ranking de publicaciones â†’", type="primary", use_container_width=True):
    serialized_items = []
    for item in items_in_budget:
        price = parse_money(item.get("price"))
        if price is None:
            continue
        original_price = parse_money(item.get("original_price"))
        serialized_items.append(
            {
                "item_id": item["item_id"],
                # Los importes se guardan como texto decimal exacto. El paso
                # 11 acepta este formato y evita una ida y vuelta por float.
                "price": money_for_storage(price),
                "original_price": (
                    money_for_storage(original_price)
                    if original_price is not None
                    else None
                ),
                "condition": item.get("condition"),
                "listing_type": item.get("listing_type"),
                "seller_id": item.get("seller_id"),
                "official_store_id": item.get("official_store_id"),
            }
        )

    output = {
        "product_id":      selected_pid,
        "product_name":    selected_name,
        "budget_min":      int(budget_min),
        "budget_max":      int(budget_max),
        "items_in_budget": serialized_items,
    }
    output.update(prefs2)

    with open(PREFS_LAF2_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    st.success("âœ… Preferencias de compra guardadas.")
    st.info(ui.get("laf2_next_info", "Ahora corre `python src/10_laf2_generate.py` para ver el ranking de publicaciones."))
    st.json(output)

