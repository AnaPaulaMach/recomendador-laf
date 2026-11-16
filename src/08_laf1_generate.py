"""
08_laf1_generate.py â€” Generador del programa LAF 1 (ranking de PRODUCTOS).

Lee prefs_laf1.json y product_aspect_trust para construir el programa
argumentativo que rankea los productos del top-20.

El usuario NO ha elegido producto ni presupuesto todavÃ­a. El output es
un ranking de productos que el usuario ve para tomar su decisiÃ³n.

Uso:
    python src/08_laf1_generate.py
    python src/08_laf1_generate.py --strategy D
    python src/08_laf1_generate.py --strategy all
"""

import argparse, json, math, os, re, sys, unicodedata
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from domain_config import (
    artifact_path,
    load_domain_config,
    load_domain_config_for_key,
)
from methodology_freeze import (
    canonical_methodology_hash,
    load_and_validate_freeze,
    validate_freeze_manifest,
)
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
DEFAULT_TOP_N = 20

RULE_CONF_AGGREGATION    = 0.85
RULE_CONF_RECOMMENDATION = 0.90

STRATEGY_DESC = {
    "A": "Normalizacion logaritmica",
    "B": "Umbral minimo",
    "C": "Experimento separado de catalogo",
    "D": "Contraccion hacia una media a priori",
    "E": "Sin ajuste - metadatos de cobertura",
}

PRODUCT_NAME_STOPWORDS = {
    "aire", "acondicionado", "mini", "split", "minisplit",
    "solo", "frio", "calor", "frio_calo", "ac",
}


def initialize_runtime(dataset_key=None):
    """Carga entorno y dominio solo para el recorrido real del usuario."""
    global SUPABASE_URL, SUPABASE_KEY, DATASET_KEY, DOMAIN, PREFS_FILE, DEFAULT_OUTPUT
    load_dotenv()
    if dataset_key:
        os.environ["DATASET_KEY"] = dataset_key
    SUPABASE_URL = os.environ["SUPABASE_URL"]
    SUPABASE_KEY = os.environ["SUPABASE_KEY"]
    DATASET_KEY = os.environ.get("DATASET_KEY")
    DOMAIN = load_domain_config()
    PREFS_FILE = artifact_path("prefs_laf1", ".json", DOMAIN)
    DEFAULT_OUTPUT = artifact_path("programa_laf1", ".txt", DOMAIN)

def safe_id(s): return atom_part(s)[:30]
def fmt(a, b):  return f"{{{a:.2f}; {b:.2f}}}"

def atom_part(s):
    ascii_s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_]", "_", ascii_s)).strip("_").lower()

def product_atom(pid, name):
    pid_atom = safe_id(pid)
    name_atom = atom_part(name)
    if not name_atom or name_atom == pid_atom or re.fullmatch(r"mlmu?\d+", name_atom):
        return pid_atom

    words = [w for w in name_atom.split("_") if w and w not in PRODUCT_NAME_STOPWORDS]
    slug = "_".join(words[:6]) or name_atom[:32].rstrip("_")
    return f"{pid_atom}_{slug}"[:60].rstrip("_")

def cap_atom(s):
    return atom_part(s).capitalize()

def ann(stmt, a, b):
    return f"{stmt}. {fmt(a, b)}"

def as_float(value, default):
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)

def aspect_rule(raw):
    if isinstance(raw, str):
        return {"aspect": raw}
    return dict(raw or {})

def normalize_prefs(raw_prefs, config):
    """Completa preferencias antiguas y valida el contrato de salida de 07."""
    if not isinstance(raw_prefs, dict):
        raise ValueError("El archivo de preferencias de LAF 1 debe ser un objeto JSON.")
    normalized = {}
    for aspect in config.get("quality_aspects", {}):
        raw_value = raw_prefs.get(aspect, 0.5)
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Preferencia invalida para {aspect!r}: {raw_value!r}") from exc
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(
                f"Preferencia fuera de [0,1] para {aspect!r}: {raw_value!r}"
            )
        normalized[aspect] = value
    return normalized


def load_prefs():
    if PREFS_FILE is None or not os.path.exists(PREFS_FILE):
        print(f"ERROR: no existe {PREFS_FILE}.", file=sys.stderr)
        print("CorrÃ© primero: streamlit run src/07_laf1_preferences.py", file=sys.stderr)
        sys.exit(1)
    with open(PREFS_FILE, encoding="utf-8") as f:
        return normalize_prefs(json.load(f), DOMAIN)

def load_products(sb, included_product_ids, top_n=DEFAULT_TOP_N):
    """Carga todos los productos del top-20 con sus nombres y precios mÃ­nimos."""
    # PosiciÃ³n en el ranking (products_seed)
    q = sb.table("products_seed").select("product_id, position")
    if DATASET_KEY:
        q = q.eq("dataset_key", DATASET_KEY)
    q = q.in_("product_id", sorted(included_product_ids))
    seed = {
        r["product_id"]: int(r["position"])
        for r in q.execute().data
        if int(r["position"]) <= top_n
    }

    # Nombres
    q2 = sb.table("products_raw").select("product_id, name, family_name")
    if DATASET_KEY:
        q2 = q2.eq("dataset_key", DATASET_KEY)
    q2 = q2.in_("product_id", sorted(included_product_ids))
    names = {}
    for r in q2.execute().data:
        pid = r["product_id"]
        names[pid] = r.get("name") or r.get("family_name") or pid

    # Precio mÃ­nimo por producto (de items_clean)
    q3 = sb.table("items_clean").select("product_id, price")
    if DATASET_KEY:
        q3 = q3.eq("dataset_key", DATASET_KEY)
    q3 = q3.in_("product_id", sorted(included_product_ids))
    price_min = defaultdict(list)
    for r in q3.execute().data:
        if r.get("price"):
            price = parse_money(r["price"])
            if price is not None:
                price_min[r["product_id"]].append(price)

    products = {}
    for pid, pos in seed.items():
        prices = price_min.get(pid, [])
        products[pid] = {
            "name":      names.get(pid, pid),
            "position":  pos,
            "price_min": min(prices) if prices else None,
            "price_max": max(prices) if prices else None,
            "n_items":   len(prices),
        }
    return products

def load_evidence(sb, strategy, included_product_ids):
    """Carga hechos agregados de TODOS los productos para la estrategia dada."""
    q = sb.table("product_aspect_trust") \
          .select("product_id,aspect,polarity,agg_confidence,n_reviews,coverage_ratio,from_catalog") \
          .eq("strategy", strategy)
    if DATASET_KEY:
        q = q.eq("dataset_key", DATASET_KEY)
    q = q.in_("product_id", sorted(included_product_ids))
    rows = q.execute().data
    return [r for r in rows if r.get("agg_confidence") is not None]

def build_laf1(
    products,
    evidence,
    prefs,
    strategy,
    domain=None,
    dataset_key=None,
    methodology_sha256=None,
    frozen_at=None,
):
    cfg = domain or DOMAIN
    if not cfg:
        raise RuntimeError("Falta la configuracion del dominio para construir LAF 1.")
    laf = cfg["laf"]
    rule_structure = cfg.get("laf1_rule_structure", {}) or {}
    dimensions = rule_structure.get("dimensions", {}) if rule_structure.get("mode") == "hierarchical" else {}
    lines = []
    lines.append("% =====================================================================")
    lines.append("% PROGRAMA LAF 1 - RANKING DE PRODUCTOS")
    lines.append(f"% {laf.get('system_description', 'Sistema argumentativo de recomendacion')}")
    lines.append(f"% {laf.get('author_line', 'Trabajo Final')}")
    lines.append("% =====================================================================")
    lines.append("")
    lines.append(f"% Estrategia de balanceo: {strategy} - {STRATEGY_DESC[strategy]}")
    lines.append(f"% Dominio: {cfg['display_name']}")
    if dataset_key:
        lines.append(f"% Dataset key: {dataset_key}")
    if methodology_sha256:
        lines.append(f"% Metodologia congelada SHA-256: {methodology_sha256}")
    if frozen_at:
        lines.append(f"% Congelada en: {frozen_at}")
    lines.append(f"% Productos analizados: {len(products)}")
    lines.append("")

    lines.append("% Productos y rango de precios:")
    for pid, p in sorted(products.items(), key=lambda x: x[1]["position"]):
        pmin = f"${p['price_min']:,.0f}" if p["price_min"] else "?"
        pmax = f"${p['price_max']:,.0f}" if p["price_max"] else "?"
        atom = product_atom(pid, p.get("name") or pid)
        lines.append(f"%   #{p['position']:2d} {atom:45s}  {pmin}-{pmax}  ({p['n_items']} publicaciones)")
    lines.append("")

    lines.append("% Preferencias del usuario:")
    for asp, pref in sorted(prefs.items(), key=lambda x: -x[1]):
        lines.append(f"%   {asp}: {pref:.2f}")
    lines.append("")
    if dimensions:
        lines.append("% Estructura argumentativa LAF 1:")
        lines.append("%   resena -> aspecto -> dimension -> recomendar")
        if rule_structure.get("beta_semantics") == "user_only_structural_neutral":
            lines.append("%   beta de reglas = 1.00 (neutral); la preferencia proviene solo del usuario")
        for dim_key, dim_cfg in dimensions.items():
            aspect_names = [
                clean.get("aspect", "")
                for clean in (aspect_rule(item) for item in dim_cfg.get("aspects", []))
                if clean.get("aspect")
            ]
            lines.append(f"%   {dim_key}: {', '.join(aspect_names)}")
        lines.append("")

    # â”€â”€ HECHOS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    lines.append("% ============================================================")
    lines.append("% HECHOS - un hecho por (producto, aspecto, polaridad)")
    lines.append("% Variable X identifica al producto.")
    lines.append("% ============================================================")
    lines.append("")

    by_pid_asp = defaultdict(lambda: defaultdict(dict))
    for e in evidence:
        by_pid_asp[e["product_id"]][e["aspect"]][e["polarity"]] = e

    aspects_global = sorted(set(e["aspect"] for e in evidence))

    for pid, p in sorted(products.items(), key=lambda x: x[1]["position"]):
        pid_id = product_atom(pid, p.get("name") or pid)
        name   = str(p.get("name") or pid)[:40]
        lines.append(f"% {name}")
        asp_data = by_pid_asp.get(pid, {})

        for asp in aspects_global:
            pref = prefs.get(asp, 0.5)
            pol_data = asp_data.get(asp, {})
            for pol in ("pos", "neg"):
                e = pol_data.get(pol)
                if not e:
                    continue
                conf = e["agg_confidence"]
                n    = e.get("n_reviews", 0)
                if e.get("from_catalog"):
                    # El catalogo declara presencia, no una experiencia positiva.
                    # No hay una regla catalogoDeclara* -> aspectoBueno: en C el
                    # dato queda visible como contexto experimental, sin alterar
                    # el ranking principal basado en reseñas.
                    comment = "% [catalogo: contexto, no reseña]"
                    pred = "catalogoDeclara" + cap_atom(asp)
                else:
                    comment = f"% n={n}"
                    pred = (
                        "resenaPositiva" if pol == "pos" else "resenaNegativa"
                    ) + cap_atom(asp)
                lines.append(comment)
                lines.append(ann(f"{pred}({pid_id})", conf, pref))

        lines.append("")

    # â”€â”€ REGLAS DE AGREGACIÃ“N â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    lines.append("% ============================================================")
    lines.append("% REGLAS DE AGREGACION POR ASPECTO")
    lines.append("% ============================================================")
    lines.append("")
    for asp in aspects_global:
        c    = RULE_CONF_AGGREGATION
        asp_atom = atom_part(asp)
        lines.append(ann(f"{asp_atom}Bueno(X) :- resenaPositiva{cap_atom(asp)}(X)", c, 1.0))
        lines.append(ann(f"~{asp_atom}Bueno(X) :- resenaNegativa{cap_atom(asp)}(X)", c, 1.0))
    lines.append("")

    active_dimensions = []
    assigned_aspects = set()
    if dimensions:
        lines.append("% ============================================================")
        lines.append("% REGLAS INTERMEDIAS POR DIMENSION")
        lines.append("% Cada dimension agrupa aspectos relacionados antes de recomendar.")
        lines.append("% ============================================================")
        lines.append("")
        for dim_key, dim_cfg in dimensions.items():
            dim_atom = atom_part(dim_key)
            active_aspect_rules = []
            for item in dim_cfg.get("aspects", []):
                rule = aspect_rule(item)
                if rule.get("aspect") in aspects_global:
                    active_aspect_rules.append(rule)
            if not active_aspect_rules:
                continue
            active_dimensions.append((dim_key, dim_cfg))
            lines.append(f"% {dim_cfg.get('label') or dim_key}")
            for rule in active_aspect_rules:
                asp = rule["aspect"]
                assigned_aspects.add(asp)
                asp_atom = atom_part(asp)
                pos_conf = as_float(rule.get("confidence"), RULE_CONF_AGGREGATION)
                neg_conf = as_float(rule.get("negative_confidence"), pos_conf)
                lines.append(ann(f"{dim_atom}Bueno(X) :- {asp_atom}Bueno(X)", pos_conf, 1.0))
                lines.append(ann(f"~{dim_atom}Bueno(X) :- ~{asp_atom}Bueno(X)", neg_conf, 1.0))
            lines.append("")

    # â”€â”€ REGLAS DE RECOMENDACIÃ“N â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    lines.append("% ============================================================")
    lines.append("% REGLAS DE RECOMENDACION")
    lines.append("% X = producto candidato")
    lines.append("% ============================================================")
    lines.append("")
    if dimensions:
        for dim_key, dim_cfg in active_dimensions:
            dim_atom = atom_part(dim_key)
            rec = dim_cfg.get("recommend") or {}
            if rec:
                rec_conf = as_float(rec.get("confidence"), RULE_CONF_RECOMMENDATION)
                lines.append(ann(f"recomendar(X) :- {dim_atom}Bueno(X)", rec_conf, 1.0))
            neg = dim_cfg.get("not_recommend") or {}
            if neg:
                neg_conf = as_float(neg.get("confidence"), RULE_CONF_RECOMMENDATION)
                lines.append(ann(f"~recomendar(X) :- ~{dim_atom}Bueno(X)", neg_conf, 1.0))

        if rule_structure.get("unassigned_aspect_policy") == "direct":
            unassigned = [asp for asp in aspects_global if asp not in assigned_aspects]
            if unassigned:
                lines.append("")
                lines.append("% Aspectos no asignados a dimensiones: se conservan como apoyo directo.")
                for asp in unassigned:
                    c = as_float(rule_structure.get("direct_recommendation_confidence"), 0.80)
                    asp_atom = atom_part(asp)
                    lines.append(ann(f"recomendar(X) :- {asp_atom}Bueno(X)", c, 1.0))
                    lines.append(ann(f"~recomendar(X) :- ~{asp_atom}Bueno(X)", c, 1.0))
    else:
        for asp in aspects_global:
            c    = RULE_CONF_RECOMMENDATION
            asp_atom = atom_part(asp)
            lines.append(ann(f"recomendar(X) :- {asp_atom}Bueno(X)", c, 1.0))
            lines.append(ann(f"~recomendar(X) :- ~{asp_atom}Bueno(X)", c, 1.0))
    lines.append("")

    # â”€â”€ OPERADORES â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    lines.append("% ============================================================")
    lines.append("% ============================================================")
    lines.append("% Atributo 1 - Confianza:")
    lines.append("%   producto = X*Y     suma = X+Y-X*Y     debilitamiento = (X-Y)/(1-Y) si X>=Y, sino 0")
    lines.append("% Atributo 2 - Preferencia del usuario:")
    lines.append("%   producto = min(X,Y)     suma = min(X+Y,1)     debilitamiento = max(X-Y,0)")
    lines.append("%")
    lines.append("% Fuente: Budan et al. (2017) IJAR 82:242-269, Ejemplo 1 pp.249-250")

    return "\n".join(lines)

def generate(
    sb,
    prefs,
    strategy,
    out_path,
    included_product_ids,
    top_n=DEFAULT_TOP_N,
    freeze_manifest=None,
    methodology_sha256=None,
):
    products = load_products(
        sb,
        included_product_ids,
        top_n=top_n,
    )
    evidence = load_evidence(sb, strategy, included_product_ids)
    if not evidence:
        print(f"  AVISO: sin hechos para estrategia {strategy}. Corriste src/06_trust.py?")
        return
    program = build_laf1(
        products,
        evidence,
        prefs,
        strategy,
        dataset_key=DATASET_KEY,
        methodology_sha256=methodology_sha256,
        frozen_at=(freeze_manifest or {}).get("frozen_at"),
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(program)

    n_facts = len(evidence)
    n_prods_con_hechos = len(set(e["product_id"] for e in evidence))
    print(f"  Estrategia {strategy}: {n_facts} hechos, {n_prods_con_hechos} productos -> {out_path}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-key", default=os.environ.get("DATASET_KEY"))
    parser.add_argument("--strategy", default="D",
                        choices=["A","B","C","D","E","all"])
    parser.add_argument("--output", default=None)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N,
                        help="Cantidad de productos de products_seed a rankear")
    args = parser.parse_args()
    initialize_runtime(args.dataset_key)

    sb    = create_client(SUPABASE_URL, SUPABASE_KEY)
    included_product_ids = require_included_product_ids(
        sb,
        DATASET_KEY,
        stage_name="08_laf1_generate.py",
    )
    prefs = load_prefs()
    freeze_manifest, methodology_sha256 = load_and_validate_freeze(DOMAIN)

    strategies = ["A","B","C","D","E"] if args.strategy == "all" else [args.strategy]
    for strat in strategies:
        out = artifact_path(f"programa_laf1_{strat}", ".txt", DOMAIN) if args.strategy == "all" else (args.output or DEFAULT_OUTPUT)
        generate(
            sb,
            prefs,
            strat,
            out,
            included_product_ids,
            top_n=args.top_n,
            freeze_manifest=freeze_manifest,
            methodology_sha256=methodology_sha256,
        )

    print()
    print("Programa LAF 1 generado con la categoria ya validada.")
    print("PROXIMO PASO: evaluarlo con el motor LAF.")
    print("Despues: streamlit run src/09_laf2_preferences.py")
    return

if __name__ == "__main__":
    try:
        main()
    except KeyError as e:
        print(f"ERROR: falta variable de entorno {e}.", file=sys.stderr)
        sys.exit(1)
    except (ProductReviewSetupError, ProductReviewPendingError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

