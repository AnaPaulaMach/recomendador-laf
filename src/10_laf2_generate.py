"""
10_laf2_generate.py - Generador del programa LAF 2 (ranking de PUBLICACIONES).

Lee prefs_laf2.json (producto elegido + presupuesto + preferencias de compra)
y construye el programa LAF que compara las publicaciones del producto
en base a: precio/descuento, cuotas, garantia, tienda oficial, factura y envio gratuito.

A diferencia del LAF 1 (que usa reseÃ±as + NLP), el LAF 2 usa solo datos
estructurados de items_clean: todos los hechos son deterministas (0 o 1)
salvo el precio, que se normaliza dentro del rango filtrado.

Uso:
    python src/10_laf2_generate.py
    python src/10_laf2_generate.py --output mi_programa_laf2.txt
"""

import argparse, json, os, sys, unicodedata
from decimal import Decimal
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from domain_config import artifact_path, load_domain_config
from methodology_freeze import load_and_validate_freeze
from money import parse_money
from product_scope import (
    ProductReviewPendingError,
    ProductReviewSetupError,
    require_included_product_ids,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SUPABASE_URL = ""
SUPABASE_KEY = ""
DATASET_KEY = None
DOMAIN = {}
PREFS_FILE = None
DEFAULT_OUTPUT = None

# Confianza base para hechos binarios de condiciones de compra.
# Son deterministas (la tienda o tiene official_store o no), por eso alta.
BINARY_CONF = 0.95

# GarantÃ­as largas (â‰¥ 6 meses) vs cortas
LONG_WARRANTY_MONTHS = 6


def initialize_runtime(dataset_key=None):
    """Carga entorno y dominio solo para la ejecucion online del usuario."""
    global SUPABASE_URL, SUPABASE_KEY, DATASET_KEY, DOMAIN, PREFS_FILE, DEFAULT_OUTPUT
    global BINARY_CONF, LONG_WARRANTY_MONTHS
    load_dotenv()
    if dataset_key:
        os.environ["DATASET_KEY"] = dataset_key
    SUPABASE_URL = os.environ["SUPABASE_URL"]
    SUPABASE_KEY = os.environ["SUPABASE_KEY"]
    DATASET_KEY = os.environ.get("DATASET_KEY")
    DOMAIN = load_domain_config()
    fact_parameters = DOMAIN["laf2_rule_structure"].get("fact_parameters", {})
    BINARY_CONF = float(fact_parameters.get("binary_confidence", BINARY_CONF))
    LONG_WARRANTY_MONTHS = int(
        fact_parameters.get("long_warranty_months", LONG_WARRANTY_MONTHS)
    )
    PREFS_FILE = artifact_path("prefs_laf2", ".json", DOMAIN)
    DEFAULT_OUTPUT = artifact_path("programa_laf2", ".txt", DOMAIN)

def safe_id(s): return str(s).replace("-","_").lower()[:30]
def fmt(a, b):  return f"{{{a:.2f}; {b:.2f}}}"
def ann(stmt, a, b): return f"{stmt}. {fmt(a, b)}"

def load_prefs():
    if PREFS_FILE is None or not os.path.exists(PREFS_FILE):
        print(f"ERROR: no existe {PREFS_FILE}.", file=sys.stderr)
        print("Corre primero: streamlit run src/09_laf2_preferences.py", file=sys.stderr)
        sys.exit(1)
    return json.load(open(PREFS_FILE, encoding="utf-8"))

def load_item_details(sb, product_id, item_ids):
    """Carga detalles completos de los items filtrados por presupuesto."""
    q = sb.table("items_raw") \
          .select("item_id,price,original_price,official_store_id,listing_type_id,tags,sale_terms,seller_id,shipping_free_shipping,shipping_logistic_type,shipping_mode") \
          .eq("product_id", product_id) \
          .in_("item_id", item_ids)
    if DATASET_KEY:
        q = q.eq("dataset_key", DATASET_KEY)
    return q.execute().data

def parse_item(raw, rule_structure=None):
    """Extrae los hechos argumentativos de un item crudo."""
    import json as _json

    warranty_threshold = int(
        (rule_structure or {}).get("fact_parameters", {}).get(
            "long_warranty_months",
            LONG_WARRANTY_MONTHS,
        )
    )

    price = parse_money(raw.get("price"), Decimal("0.00"))
    orig = parse_money(raw.get("original_price"), Decimal("0.00"))

    # Tags â†’ cuotas
    tags = raw.get("tags") or "[]"
    try:
        tag_list = _json.loads(tags) if isinstance(tags, str) else tags
    except Exception:
        tag_list = []

    has_3x  = "3x_campaign"  in tag_list
    has_9x  = "9x_campaign"  in tag_list
    has_12x = ("12x_campaign" in tag_list or "1p_12x_campaign" in tag_list)

    # sale_terms â†’ garantÃ­a, factura
    terms = raw.get("sale_terms") or "[]"
    try:
        term_list = _json.loads(terms) if isinstance(terms, str) else terms
    except Exception:
        term_list = []

    warranty_months = 0
    has_invoice     = False
    for t in (term_list or []):
        if t.get("id") == "WARRANTY_TIME":
            val = t.get("value_struct") or {}
            num  = val.get("number", 0) or 0
            unit = val.get("unit", "")
            normalized_unit = "".join(
                char
                for char in unicodedata.normalize("NFKD", str(unit).casefold())
                if not unicodedata.combining(char)
            )
            if "mes" in normalized_unit or "month" in normalized_unit:
                warranty_months = num
            elif "ano" in normalized_unit or "year" in normalized_unit:
                warranty_months = num * 12
            elif "dia" in normalized_unit or "day" in normalized_unit:
                warranty_months = num / 30
        if t.get("id") == "INVOICE":
            invoice_name = "".join(
                char
                for char in unicodedata.normalize(
                    "NFKD",
                    str(t.get("value_name") or "").casefold(),
                )
                if not unicodedata.combining(char)
            )
            has_invoice = (
                "factura" in invoice_name
                and "no factura" not in invoice_name
                and "sin factura" not in invoice_name
            )

    free_shipping = raw.get("shipping_free_shipping")
    if isinstance(free_shipping, str):
        free_shipping = free_shipping.strip().lower() in {"true", "1", "yes", "si"}

    return {
        "item_id":          raw["item_id"],
        "price":            price,
        "has_discount":     orig > 0 and orig > price,
        "discount_pct": float(
            ((orig - price) / orig).quantize(Decimal("0.001"))
        ) if orig > price else 0.0,
        "has_3x":           has_3x,
        "has_9x":           has_9x,
        "has_12x":          has_12x,
        "has_cuotas":       has_3x or has_9x or has_12x,
        "warranty_months":  warranty_months,
        "has_long_warranty":warranty_months >= warranty_threshold,
        "is_official_store":bool(raw.get("official_store_id")),
        "has_invoice":      has_invoice,
        "has_free_shipping":free_shipping is True,
        "shipping_logistic_type": raw.get("shipping_logistic_type"),
        "shipping_mode":    raw.get("shipping_mode"),
        "is_gold_pro":      (raw.get("listing_type_id") or "") == "gold_pro",
    }

def price_confidence(price, min_p, max_p, rule_structure=None):
    """
    Convierte el precio en confianza para el hecho 'precioBueno'.
    El precio mÃ¡s bajo â†’ conf=0.95, el mÃ¡s alto â†’ conf=0.30.
    Escala lineal invertida dentro del rango filtrado.
    """
    price_cfg = (rule_structure or {}).get("fact_parameters", {}).get("price_confidence", {})
    minimum = Decimal(str(price_cfg.get("minimum_price", 0.95)))
    maximum = Decimal(str(price_cfg.get("maximum_price", 0.30)))
    equal = float(price_cfg.get("equal_price", 0.70))
    if max_p == min_p:
        return equal
    ratio = (price - min_p) / (max_p - min_p)   # 0=barato, 1=caro
    confidence = minimum - ratio * (minimum - maximum)
    return float(confidence.quantize(Decimal("0.001")))  # 0.95â†’0.30

def build_laf2(
    items_parsed,
    prefs,
    product_name,
    strategy_note="",
    domain=None,
    *,
    dataset_key=None,
    product_id=None,
    budget_min=None,
    budget_max=None,
    methodology_sha256=None,
    frozen_at=None,
):
    cfg = domain or DOMAIN
    if not cfg:
        raise RuntimeError("Falta la configuracion del dominio para construir LAF 2.")
    if not items_parsed:
        raise ValueError("No hay publicaciones para construir LAF 2.")
    laf = cfg["laf"]
    rule_structure = cfg["laf2_rule_structure"]
    fact_parameters = rule_structure.get("fact_parameters", {})
    binary_conf = float(fact_parameters.get("binary_confidence", BINARY_CONF))
    conditions = rule_structure.get("conditions", {})

    def fact_predicate(key, fallback):
        return (conditions.get(key) or {}).get("fact_predicate", fallback)
    lines = []
    lines.append("% =====================================================================")
    lines.append("% PROGRAMA LAF 2 â€” RANKING DE PUBLICACIONES")
    lines.append(f"% {laf.get('system_description', 'Sistema argumentativo de recomendacion')}")
    lines.append(f"% {laf.get('author_line', 'Trabajo Final')}")
    lines.append("% =====================================================================")
    lines.append("")
    lines.append(f"% DOMINIO: {cfg['display_name']}")
    if dataset_key:
        lines.append(f"% Dataset key: {dataset_key}")
    if methodology_sha256:
        lines.append(f"% Configuracion congelada SHA-256: {methodology_sha256}")
    if frozen_at:
        lines.append(f"% Congelada: {frozen_at}")
    lines.append(f"% PRODUCTO: {product_name}")
    if product_id:
        lines.append(f"% Product ID: {product_id}")
    if budget_min is not None or budget_max is not None:
        lower = "sin minimo" if budget_min is None else str(budget_min)
        upper = "sin maximo" if budget_max is None else str(budget_max)
        lines.append(f"% Presupuesto solicitado: {lower} a {upper}")
    lines.append(f"% Publicaciones analizadas: {len(items_parsed)}")
    if strategy_note:
        lines.append(f"% Nota: {strategy_note}")
    lines.append("")

    lines.append("% Publicaciones incluidas:")
    for it in items_parsed:
        disc = f"  descuento {it['discount_pct']*100:.0f}%" if it["has_discount"] else ""
        cuot = "  cuotas" if it["has_cuotas"] else ""
        ofic = "  [oficial]" if it["is_official_store"] else ""
        ship = "  [envio gratis]" if it.get("has_free_shipping") else ""
        lines.append(f"%   {safe_id(it['item_id']):30s}  ${it['price']:>10,.0f}{disc}{cuot}{ofic}{ship}")
    lines.append("")

    lines.append("% Preferencias de compra del usuario:")
    skip = {"product_id","product_name","budget_min","budget_max","items_in_budget"}
    for k, v in sorted(((k,v) for k,v in prefs.items() if k not in skip), key=lambda x: -x[1]):
        lines.append(f"%   {k}: {v:.2f}")
    lines.append("")

    # â”€â”€ HECHOS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    lines.append("% ============================================================")
    lines.append("% HECHOS â€” uno por (publicaciÃ³n, condiciÃ³n)")
    lines.append("% Variable X identifica la publicaciÃ³n (item).")
    lines.append("% ============================================================")
    lines.append("")

    prices  = [it["price"] for it in items_parsed]
    min_p   = min(prices)
    max_p   = max(prices)

    for it in items_parsed:
        iid    = safe_id(it["item_id"])
        lines.append(f"% {it['item_id']}  (${it['price']:,.0f})")

        # Precio
        pc = price_confidence(it["price"], min_p, max_p, rule_structure)
        pref_precio = prefs.get("precio", 0.5)
        lines.append(ann(f"{fact_predicate('precio', 'precioBueno')}({iid})", pc, pref_precio))
        lines.append(f"% precio ${it['price']:,.0f} â†’ confianza {pc:.2f} dentro del rango")

        # Descuento
        if it["has_discount"]:
            dc   = round(0.60 + it["discount_pct"] * 0.40, 3)  # 0.60â€“1.00 segÃºn %
            pref = prefs.get("descuento", 0.5)
            lines.append(ann(f"{fact_predicate('descuento', 'tieneDescuento')}({iid})", dc, pref))
            lines.append(f"% descuento {it['discount_pct']*100:.0f}%")

        # Cuotas
        if it["has_12x"]:
            pref = prefs.get("cuotas", 0.5)
            lines.append(ann(f"{fact_predicate('cuotas', 'tieneCuotas')}({iid})", binary_conf, pref))
            lines.append(f"% 12 cuotas sin interÃ©s")
        elif it["has_9x"]:
            pref = prefs.get("cuotas", 0.5)
            lines.append(ann(f"{fact_predicate('cuotas', 'tieneCuotas')}({iid})", 0.80, pref))
            lines.append(f"% 9 cuotas sin interÃ©s")
        elif it["has_3x"]:
            pref = prefs.get("cuotas", 0.5)
            lines.append(ann(f"{fact_predicate('cuotas', 'tieneCuotas')}({iid})", 0.65, pref))
            lines.append(f"% 3 cuotas sin interÃ©s")

        # GarantÃ­a
        if it["has_long_warranty"]:
            pref = prefs.get("garantia", 0.5)
            gc   = round(min(0.95, 0.70 + it["warranty_months"] / 24 * 0.25), 3)
            lines.append(ann(f"{fact_predicate('garantia', 'tieneGarantiaLarga')}({iid})", gc, pref))
            lines.append(f"% garantÃ­a {it['warranty_months']} meses")

        # Tienda oficial
        if it["is_official_store"]:
            pref = prefs.get("tienda_oficial", 0.5)
            lines.append(ann(f"{fact_predicate('tienda_oficial', 'esTiendaOficial')}({iid})", binary_conf, pref))

        # Factura A
        if it["has_invoice"]:
            pref = prefs.get("factura", 0.5)
            lines.append(ann(f"{fact_predicate('factura', 'tieneFactura')}({iid})", binary_conf, pref))

        # Envio gratuito. Se usa el booleano estructurado de items_raw; no se
        # infiere rapidez porque el dataset no contiene un plazo estable.
        if it.get("has_free_shipping"):
            pref = prefs.get("envio", 0.5)
            lines.append(ann(f"{fact_predicate('envio', 'tieneEnvioGratis')}({iid})", binary_conf, pref))
            logistic = it.get("shipping_logistic_type") or "modalidad no informada"
            lines.append(f"% envio gratuito; logistica={logistic}")

        lines.append("")

    # â”€â”€ REGLAS DE AGREGACIÃ“N â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    lines.append("% ============================================================")
    lines.append("% REGLAS DE AGREGACIÃ“N")
    lines.append("% ============================================================")
    lines.append("")

    for pref_key, condition in rule_structure.get("conditions", {}).items():
        if pref_key not in cfg["purchase_aspects"]:
            continue
        if condition.get("status") != "implemented":
            reason = condition.get("reason", "implementacion pendiente")
            lines.append(f"% PENDIENTE {pref_key}: {reason}")
            continue
        pred_body = condition["fact_predicate"]
        pref = prefs.get(pref_key, 0.5)
        c = float(condition.get("rule_confidence", 0.85))
        lines.append(ann(f"compraBuena(X) :- {pred_body}(X)", c, pref))
    lines.append("")

    # â”€â”€ REGLAS DE RECOMENDACIÃ“N â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    lines.append("% ============================================================")
    lines.append("% REGLAS DE RECOMENDACIÃ“N")
    lines.append("% X = publicaciÃ³n candidata")
    lines.append("% ============================================================")
    lines.append("")
    recommendation = rule_structure.get("recommendation", {})
    recommendation_keys = [
        k for k in recommendation.get("preference_keys", ["precio"])
        if k in cfg["purchase_aspects"]
    ] or ["precio"]
    pref_avg = sum(prefs.get(k, 0.5) for k in recommendation_keys) / len(recommendation_keys)
    c = float(recommendation.get("confidence", 0.90))
    head = recommendation.get("head_predicate", "recomendar")
    body = recommendation.get("body_predicate", "compraBuena")
    lines.append(ann(f"{head}(X) :- {body}(X)", c, round(pref_avg, 2)))
    lines.append("")

    # â”€â”€ OPERADORES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    lines.append("% ============================================================")
    lines.append("% OPERADORES (configurar en el Argumentation Studio)")
    lines.append("% ============================================================")
    lines.append("% Atributo 1 â€” Confianza:")
    lines.append("%   âŠ™ = X*Y     âŠ• = X+Y-X*Y     âŠ– = (X-Y)/(1-Y) si Xâ‰¥Y, sino 0")
    lines.append("% Atributo 2 â€” Preferencia del usuario:")
    lines.append("%   âŠ™ = min(X,Y)     âŠ• = min(X+Y,1)     âŠ– = max(X-Y,0)")
    lines.append("%")
    lines.append("% Fuente: BudÃ¡n et al. (2017) IJAR 82:242-269, Ejemplo 1 pp.249-250")

    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-key", default=os.environ.get("DATASET_KEY"))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    initialize_runtime(args.dataset_key)

    sb    = create_client(SUPABASE_URL, SUPABASE_KEY)
    included_product_ids = require_included_product_ids(
        sb,
        DATASET_KEY,
        stage_name="10_laf2_generate.py",
    )
    prefs = load_prefs()

    product_id   = prefs["product_id"]
    if product_id not in included_product_ids:
        raise ProductReviewPendingError(
            "10_laf2_generate.py: el producto guardado en prefs_laf2.json "
            f"no esta incluido en el corpus analitico: {product_id}. "
            "Vuelve a ejecutar src/09_laf2_preferences.py."
        )
    product_name = prefs.get("product_name", product_id)
    item_ids     = [i["item_id"] for i in prefs["items_in_budget"]]

    print(f"Producto: {product_name}")
    print(f"Items en presupuesto: {len(item_ids)}")

    freeze_manifest, methodology_sha256 = load_and_validate_freeze(DOMAIN)
    rule_structure = DOMAIN["laf2_rule_structure"]
    raw_items    = load_item_details(sb, product_id, item_ids)
    items_parsed = [parse_item(r, rule_structure) for r in raw_items]

    program = build_laf2(
        items_parsed,
        prefs,
        product_name,
        domain=DOMAIN,
        dataset_key=DATASET_KEY,
        product_id=product_id,
        budget_min=prefs.get("budget_min"),
        budget_max=prefs.get("budget_max"),
        methodology_sha256=methodology_sha256,
        frozen_at=freeze_manifest.get("frozen_at"),
    )

    output_path = args.output or DEFAULT_OUTPUT

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(program)

    print(f"\nOK Programa LAF 2 escrito en: {output_path}")
    print()
    print("Hechos generados por item:")
    for it in items_parsed:
        facts = []
        if it["has_discount"]:  facts.append(f"descuento {it['discount_pct']*100:.0f}%")
        if it["has_cuotas"]:    facts.append("cuotas")
        if it["has_long_warranty"]: facts.append(f"garantÃ­a {it['warranty_months']}m")
        if it["is_official_store"]: facts.append("oficial")
        if it["has_invoice"]:   facts.append("factura")
        print(f"  {it['item_id'][:20]:20s}  ${it['price']:>10,.0f}  [{', '.join(facts) or 'solo precio'}]")

    print()
    print("PRÃ“XIMO PASO: pegÃ¡ el programa en el Argumentation Studio y correlo.")

if __name__ == "__main__":
    try:
        main()
    except KeyError as e:
        print(f"ERROR: falta variable de entorno {e}.", file=sys.stderr)
        sys.exit(1)
    except (ProductReviewSetupError, ProductReviewPendingError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

