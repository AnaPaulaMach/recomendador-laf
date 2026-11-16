"""
04_domain_review.py - Revision humana de aspectos de dominio.

Lee el reporte generado por 02_domain_discovery.py y, si existe, las
sugerencias de 03_llm_suggestions.py. La interfaz esta centrada en grupos:
que terminos van juntos, cuales quedan dudosos, cuales se descartan y que se
agrega al lexicon final.


Reporte de 02
     +
Sugerencias opcionales de 03
     +
Reglas humanas guardadas
     ↓
Tabla de revisión en Streamlit
     ↓
Aspectos + polaridad + negaciones
     ↓
config/domains/<dominio>.json
     ↓
05_aspects.py


Uso:
    streamlit run src/04_domain_review.py
    .\venv\Scripts\streamlit.exe run src\04_domain_review.py
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from domain_config import ARTIFACTS_DIR, domain_key_from_category_label


# Rutas y vocabularios base usados durante toda la revision.
REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "reports"
DOMAIN_DIR = REPO_ROOT / "config" / "domains"
BASE_LEXICON_PATH = REPO_ROOT / "config" / "lexicon.json"

# La ruta explícita evita depender del directorio desde el que se inicia Streamlit.
load_dotenv(REPO_ROOT / ".env")

PURCHASE_TERMS = {
    "precio", "descuento", "cuotas", "garantia", "factura", "envio",
    "tienda", "vendedor", "comprar", "compra", "pedido", "paquete",
    "barato", "barata", "economico", "economica", "accesible",
}

GENERIC_TERMS = {
    "producto", "productos", "equipo", "equipos", "cosa", "cosas",
    "calidad", "tiempo", "modelo", "marca", "funcion",
}

GENERAL_OPINION_TERMS = {
    "excelente", "exelente", "execelente", "bueno", "buena", "buen",
    "recomendado", "recomendable", "super", "adecuado", "adecuada",
    "contento", "contenta", "encantado", "encantada", "maravilla",
    "mejor", "perfecto", "perfecta", "practico",
    "practica", "unico", "unica",
}

TRANSACTION_OR_CONTEXT_TERMS = {
    "ano", "caja", "caso", "cuestion", "empacado", "empaquetado",
    "forma", "lugar", "minuto", "noche", "recibo", "semana",
    "servicio", "trabajo", "fecha", "hora", "sala", "casa",
}

ACTION_OPTIONS = ["aspecto", "positivo", "negativo", "negacion", "dudoso", "descartar"]
RULE_SCOPE_OPTIONS = ["no guardar", "global", "dominio"]


# ---------------------------------------------------------------------------
# Lectura, normalizacion y escritura segura de archivos
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict[str, Any]:
    """Carga un objeto JSON y conserva la ruta en cualquier error de lectura."""
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No se pudo leer JSON válido desde {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} debe contener un objeto JSON en la raíz.")
    return data


def save_json(path: Path, data: dict[str, Any]) -> None:
    """Guarda sin exponer el archivo final a una escritura parcial."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(data, temporary, ensure_ascii=False, indent=2)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def load_optional_json(path: Path) -> dict[str, Any] | None:
    """Devuelve None solo si el archivo no existe; un JSON dañado es un error."""
    if not path.exists():
        return None
    return load_json(path)


def stable_hash(value: Any) -> str:
    """Calcula la misma huella JSON utilizada por 03_llm_suggestions.py."""
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def normalize_term(value: Any) -> str:
    """Normaliza términos para detectar duplicados aunque cambien acentos o mayúsculas."""
    text = unicodedata.normalize("NFKD", clean_text(value))
    return " ".join(
        text.encode("ascii", "ignore").decode("ascii").lower().split()
    )


def key_to_label(key: str) -> str:
    """Convierte una clave interna como `facilidad_uso` en un rotulo legible."""
    return str(key).replace("_", " ").title()


def clean_text(value: Any) -> str:
    """Convierte valores opcionales en texto sin espacios en los extremos."""
    return str(value or "").strip()


def split_terms(value: Any) -> list[str]:
    """Acepta una lista o texto separado por comas y elimina duplicados exactos."""
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value or "").split(",")
    terms = []
    for item in raw:
        term = clean_text(item)
        if term and term not in terms:
            terms.append(term)
    return terms


def domain_rules_path(domain_key: str) -> Path:
    """Obtiene el sidecar donde se guarda la memoria exclusiva del dominio."""
    return DOMAIN_DIR / f"{domain_key}.curation_rules.json"


def load_global_curation_rules() -> dict[str, Any]:
    """Carga reglas globales; el lexicón base es obligatorio y debe ser válido."""
    return load_json(BASE_LEXICON_PATH).get("curation_rules", {})


def load_domain_curation_rules(domain_key: str) -> dict[str, Any]:
    """Carga reglas del dominio; solo la ausencia del sidecar es opcional."""
    path = domain_rules_path(domain_key)
    if not path.exists():
        return {}
    return load_json(path).get("curation_rules", {})


def merge_curation_rules(*rule_sets: dict[str, Any]) -> dict[str, Any]:
    """Une conjuntos manteniendo el orden, que tambien define su prioridad."""
    merged: dict[str, Any] = {"term_actions": []}
    for rules in rule_sets:
        merged["term_actions"].extend(rules.get("term_actions", []))
    return merged


def tag_curation_rules(rules: dict[str, Any], scope: str) -> dict[str, Any]:
    """Agrega origen visible a reglas sin cambiar su estructura publica."""
    tagged = []
    for rule in rules.get("term_actions", []):
        item = dict(rule)
        item["_scope"] = scope
        tagged.append(item)
    return {"term_actions": tagged}


def find_term_rule(term: str, curation_rules: dict[str, Any]) -> dict[str, Any] | None:
    """Busca una regla declarativa para el termino, si existe."""
    normalized = clean_text(term).lower()
    for rule in curation_rules.get("term_actions", []):
        terms = [clean_text(value).lower() for value in rule.get("terms", [])]
        if normalized in terms:
            return rule
    return None


def classify_candidate(term: str, curation_rules: dict[str, Any] | None = None) -> tuple[str, str, dict[str, Any] | None]:
    """Propone una accion inicial; la regla experta siempre gana a la heuristica."""
    term_rule = find_term_rule(term, curation_rules or {})
    if term_rule:
        return clean_text(term_rule.get("action")) or "dudoso", clean_text(term_rule.get("reason")), term_rule

    words = set(str(term).lower().split())
    if words & PURCHASE_TERMS:
        return "descartar", "Condicion de compra: corresponde a LAF 2, no a calidad", None
    if words & TRANSACTION_OR_CONTEXT_TERMS:
        return "descartar", "Contexto de compra/uso, no una caracteristica del producto", None
    if words & GENERAL_OPINION_TERMS:
        return "positivo", "Opinion general: sirve como polaridad, no como aspecto", None
    if words & GENERIC_TERMS:
        return "dudoso", "Termino general: revisar ejemplos antes de usarlo", None
    return "dudoso", "Revisar ejemplos y decidir si agrupa con otro aspecto", None


def report_options() -> list[Path]:
    """Busca reportes actuales y tambien el formato historico del proyecto."""
    paths = list(ARTIFACTS_DIR.glob("*/reportes/domain_discovery.json"))
    paths.extend(ARTIFACTS_DIR.glob("*/reportes/domain_discovery_*.json"))
    paths.extend(REPORTS_DIR.glob("domain_discovery_*.json"))
    return sorted(set(paths))


def suggestion_options() -> list[Path]:
    """Lista sugerencias terminadas y excluye checkpoints parciales de 03."""
    paths = list(ARTIFACTS_DIR.glob("*/reportes/llm_suggestions.json"))
    paths.extend(ARTIFACTS_DIR.glob("*/reportes/llm_suggestions_*.json"))
    paths.extend(REPORTS_DIR.glob("llm_suggestions_*.json"))
    paths = [p for p in paths if not p.name.endswith(".partial.json")]
    return sorted(set(paths))


def artifact_domain_key(path: Path) -> str | None:
    """Deduce el dominio desde `artifacts/<dominio>/reportes/<archivo>`."""
    if path.parent.name == "reportes":
        return path.parent.parent.name
    return None


def validate_report_identity(
    path: Path,
    report: dict[str, Any],
    domain_key: str,
) -> None:
    """Evita guardar un perfil bajo una carpeta que contradiga sus metadatos."""
    artifact_key = artifact_domain_key(path)
    category_label = (report.get("dataset", {}) or {}).get("category_label")
    metadata_key = (
        domain_key_from_category_label(str(category_label))
        if category_label
        else domain_key
    )
    if artifact_key and artifact_key != metadata_key:
        raise RuntimeError(
            f"El reporte está en el dominio {artifact_key!r}, pero sus metadatos "
            f"indican {metadata_key!r}."
        )


def load_llm_payload(
    path: Path | None,
    report: dict[str, Any] | None = None,
    domain_key: str | None = None,
) -> dict[str, Any]:
    """Carga sugerencias y verifica que correspondan al reporte seleccionado."""
    if not path:
        return {"suggestions": [], "groups": [], "domain_notes": []}
    raw = load_json(path)
    if domain_key and raw.get("domain_key") != domain_key:
        raise RuntimeError(
            f"Las sugerencias {path.name} pertenecen al dominio "
            f"{raw.get('domain_key')!r}, no a {domain_key!r}."
        )
    if raw.get("status") != "complete":
        raise RuntimeError(
            f"Las sugerencias {path.name} no están completas. Vuelve a ejecutar 03."
        )
    if report is not None:
        # El nombre del archivo no alcanza: la huella confirma que 03 leyo
        # exactamente el mismo contenido de 02 que se esta revisando ahora.
        signature = raw.get("run_signature")
        if not isinstance(signature, dict) or not signature.get("report_hash"):
            raise RuntimeError(
                f"{path.name} no tiene firma verificable. Vuelve a ejecutar 03."
            )
        if signature["report_hash"] != stable_hash(report):
            raise RuntimeError(
                f"{path.name} fue generado desde otra versión del reporte 02. "
                "Vuelve a ejecutar 03."
            )
    raw.setdefault("suggestions", [])
    raw.setdefault("groups", [])
    raw.setdefault("domain_notes", [])
    return raw


def suggestion_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Indexa sugerencias por termino para evitar una busqueda lineal por fila."""
    return {
        clean_text(item.get("term")).lower(): item
        for item in payload.get("suggestions", [])
        if clean_text(item.get("term"))
    }


def decision_to_action(decision: str, local_action: str) -> str:
    """Traduce el vocabulario del JSON de 03 al usado por la interfaz."""
    if decision == "include_aspect":
        return "aspecto"
    if decision == "positive_lexicon":
        return "positivo"
    if decision == "negative_lexicon":
        return "negativo"
    if decision == "negation_lexicon":
        return "negacion"
    if decision == "reject":
        return "descartar"
    if decision == "uncertain":
        return "dudoso"
    return local_action


def llm_label(decision: str) -> str:
    """Devuelve una etiqueta corta para mostrar la decision tecnica del LLM."""
    labels = {
        "include_aspect": "Aspecto",
        "uncertain": "Dudoso",
        "reject": "Descartar",
        "positive_lexicon": "Positiva",
        "negative_lexicon": "Negativa",
        "negation_lexicon": "Negacion",
    }
    return labels.get(decision, "")


def conflict_note(local_action: str, llm_action: str, confidence: float | None) -> str:
    """Resume desacuerdos que merecen atencion especial del revisor humano."""
    notes = []
    if confidence is not None and confidence < 0.72:
        notes.append("baja confianza LLM")
    if local_action == "descartar" and llm_action == "aspecto":
        notes.append("regla local descarta pero LLM incluye")
    if local_action in {"aspecto", "dudoso"} and llm_action == "descartar":
        notes.append("LLM descarta un termino revisable")
    return ", ".join(notes)


def rows_from_report(
    report: dict[str, Any],
    min_mentions: int,
    llm_payload: dict[str, Any],
    global_curation_rules: dict[str, Any] | None = None,
    domain_curation_rules: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Construye una fila auditable por candidato combinando 02, 03 y reglas."""
    llm_by_term = suggestion_map(llm_payload)
    meta = report.get("dataset", {})
    category_label = meta.get("category_label") or "Dominio"
    domain_key = domain_key_from_category_label(category_label)
    if global_curation_rules is None:
        global_curation_rules = load_global_curation_rules()
    if domain_curation_rules is None:
        domain_curation_rules = load_domain_curation_rules(domain_key)
    # La regla más específica debe encontrarse primero para poder reemplazar una
    # decisión global sobre el mismo término.
    curation_rules = merge_curation_rules(
        tag_curation_rules(domain_curation_rules, "dominio"),
        tag_curation_rules(global_curation_rules, "global"),
    )
    rows = []

    for item in report.get("candidates", []):
        mentions = int(item.get("reviews_mencion") or 0)
        if mentions < min_mentions:
            continue

        # Se conservan por separado la decision local y la del LLM para que el
        # experto pueda rastrear por que se precargo cada accion.
        term = clean_text(item.get("term"))
        local_action, local_reason, term_rule = classify_candidate(term, curation_rules)
        llm = llm_by_term.get(term.lower(), {})
        decision = clean_text(llm.get("decision"))
        llm_action = decision_to_action(decision, local_action)
        decision_source = "regla experta" if term_rule else ("LLM" if decision else "heuristica local")
        rule_scope = clean_text(term_rule.get("_scope")) if term_rule else ""
        rule_reason = clean_text(term_rule.get("reason")) if term_rule else ""
        confidence = llm.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None

        aspect_key = clean_text(llm.get("aspect_key")) or clean_text(item.get("aspect_key_sugerido")) or term
        aspect_label = clean_text(llm.get("aspect_label")) or key_to_label(aspect_key)

        # Las reglas declarativas del lexicon tienen prioridad sobre el LLM:
        # sirven para fijar criterios metodologicos sin hardcodearlos en Python.
        if term_rule:
            llm_action = clean_text(term_rule.get("action")) or llm_action
            aspect_key = clean_text(term_rule.get("group")) or aspect_key
            aspect_label = clean_text(term_rule.get("label")) or aspect_label

        if llm_action != "aspecto":
            if llm_action == "dudoso" and term_rule and clean_text(term_rule.get("group")):
                aspect_key = clean_text(term_rule.get("group"))
                aspect_label = clean_text(term_rule.get("label")) or key_to_label(aspect_key)
            else:
                aspect_key = ""
                aspect_label = ""

        group_terms = split_terms(llm.get("group_terms"))
        add_terms = split_terms(llm.get("add_terms"))
        if llm_action == "aspecto" and term not in group_terms:
            group_terms.insert(0, term)

        why_doubt = conflict_note(local_action, llm_action, confidence)
        if llm_action == "dudoso" and not why_doubt:
            why_doubt = clean_text(llm.get("reason")) or local_reason

        rows.append({
            "accion": llm_action,
            "guardar_regla": "no guardar",
            "termino": term,
            "fuente_decision": decision_source,
            "regla_usada": "si" if term_rule else "no",
            "alcance_regla": rule_scope,
            "motivo_regla": rule_reason,
            "grupo": aspect_key,
            "nombre_grupo": aspect_label,
            "terminos_grupo": ", ".join(group_terms),
            "agregar_terminos": ", ".join(add_terms),
            "menciones": mentions,
            "oraciones": int(item.get("oraciones_mencion") or 0),
            "polaridad": float(item.get("polaridad_neta") or 0),
            "pos": int(item.get("pos") or 0),
            "neg": int(item.get("neg") or 0),
            "neu": int(item.get("neu") or 0),
            "ejemplos": " | ".join(str(e) for e in item.get("examples", [])[:3]),
            "regla_local": local_action,
            "motivo_local": local_reason,
            "llm_decision": decision,
            "llm_sugerencia": llm_label(decision),
            "conf_llm": confidence,
            "motivo_llm": clean_text(llm.get("reason")),
            "motivo_descarte": clean_text(llm.get("discard_reason")) or (
                clean_text(llm.get("reason")) if llm_action == "descartar" else ""
            ),
            "motivo_duda": why_doubt,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["accion", "grupo", "menciones"], ascending=[True, True, False])


def group_summary_from_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Agrupa las filas aceptadas para previsualizar los aspectos resultantes."""
    aspect_rows = df[df["accion"] == "aspecto"].copy()
    if aspect_rows.empty:
        return pd.DataFrame(columns=["grupo", "nombre", "terminos", "menciones", "confianza_media", "ejemplos"])

    rows = []
    for group_key, group_df in aspect_rows.groupby("grupo", dropna=False):
        terms = []
        examples = []
        for _, row in group_df.iterrows():
            for term in [row["termino"], *split_terms(row.get("agregar_terminos")), *split_terms(row.get("terminos_grupo"))]:
                if term and term not in terms:
                    terms.append(term)
            if row.get("ejemplos") and len(examples) < 2:
                examples.append(str(row["ejemplos"]).split(" | ")[0])
        conf_values = [v for v in group_df["conf_llm"].tolist() if pd.notna(v)]
        rows.append({
            "grupo": group_key,
            "nombre": group_df["nombre_grupo"].dropna().astype(str).iloc[0] if not group_df.empty else key_to_label(group_key),
            "terminos": ", ".join(terms),
            "menciones": int(group_df["menciones"].sum()),
            "confianza_media": round(sum(conf_values) / len(conf_values), 2) if conf_values else None,
            "ejemplos": " | ".join(examples),
        })
    return pd.DataFrame(rows).sort_values("menciones", ascending=False)


def apply_seed_mode(df: pd.DataFrame, seed_mode: str) -> pd.DataFrame:
    """Aplica el grado de confianza elegido solo a la precarga de la tabla."""
    df = df.copy()
    if seed_mode == "Todo dudoso":
        df["accion"] = "dudoso"
        df["grupo"] = ""
        df["nombre_grupo"] = ""
    elif seed_mode == "Reglas locales":
        df["accion"] = df["regla_local"]
        mask = df["accion"] != "aspecto"
        df.loc[mask, ["grupo", "nombre_grupo"]] = ""
    elif seed_mode == "Conservador":
        low_conf_aspect = (df["accion"] == "aspecto") & (df["conf_llm"].notna()) & (df["conf_llm"] < 0.72)
        df.loc[low_conf_aspect, "accion"] = "dudoso"
    return df


def filter_candidate_rows(df: pd.DataFrame, search_text: str) -> pd.DataFrame:
    """Filtra solo la vista; el DataFrame completo sigue siendo la fuente de guardado."""
    needle = clean_text(search_text).lower()
    if not needle:
        return df.copy()
    mask = pd.Series(False, index=df.index)
    for column in ("termino", "grupo", "ejemplos", "motivo_llm"):
        if column in df:
            mask |= (
                df[column]
                .fillna("")
                .astype(str)
                .str.lower()
                .str.contains(needle, regex=False)
            )
    return df[mask].copy()


def merge_visible_edits(
    complete: pd.DataFrame,
    visible_edits: pd.DataFrame,
) -> pd.DataFrame:
    """Incorpora filas visibles editadas sin eliminar las ocultas por el buscador."""
    if complete.empty or visible_edits.empty:
        return complete.copy()
    merged = complete.copy().set_index("termino", drop=False)
    updates = visible_edits.copy().set_index("termino", drop=False)
    for term in updates.index:
        if term in merged.index:
            for column in updates.columns:
                merged.at[term, column] = updates.at[term, column]
    return merged.reset_index(drop=True)


def build_domain_config(
    report: dict[str, Any],
    edited: pd.DataFrame,
    base_lexicon: dict[str, Any] | None = None,
    domain_rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Genera el perfil operativo a partir de las decisiones humanas actuales."""
    base_lexicon = base_lexicon or load_json(BASE_LEXICON_PATH)
    aspects: dict[str, list[str]] = {}
    quality_aspects: dict[str, dict[str, str]] = {}

    # Se parte de copias para que las ediciones del dominio no muten el objeto
    # global que tambien se muestra y reutiliza durante este rerun.
    positives = list(base_lexicon["positive"])
    negatives = list(base_lexicon["negative"])
    negations = list(base_lexicon["negation"])

    for _, row in edited.iterrows():
        action = clean_text(row.get("accion"))
        term = clean_text(row.get("termino"))
        extra_terms = split_terms(row.get("agregar_terminos"))

        # Dudosos y descartados quedan fuera del perfil: siguen en la auditoria,
        # pero no afectan la extraccion posterior de 05_aspects.py.
        if action == "aspecto":
            aspect_key = clean_text(row.get("grupo"))
            if not aspect_key or not term:
                continue
            aspect_label = clean_text(row.get("nombre_grupo")) or key_to_label(aspect_key)
            quality_aspects.setdefault(aspect_key, {"label": aspect_label, "icon": ""})
            aspects.setdefault(aspect_key, [])
            for candidate in [term, *extra_terms]:
                if candidate and candidate not in aspects[aspect_key]:
                    aspects[aspect_key].append(candidate)

        elif action == "positivo":
            for candidate in [term, *extra_terms]:
                if candidate and candidate not in positives:
                    positives.append(candidate)
        elif action == "negativo":
            for candidate in [term, *extra_terms]:
                if candidate and candidate not in negatives:
                    negatives.append(candidate)
        elif action == "negacion":
            for candidate in [term, *extra_terms]:
                if candidate and candidate not in negations:
                    negations.append(candidate)

    meta = report.get("dataset", {})
    category_label = meta.get("category_label") or "Dominio"
    domain_key = domain_key_from_category_label(category_label)

    config = {
        "domain_key": domain_key,
        "display_name": category_label,
        "product_label": "producto",
        "item_label": "publicacion",
        "quality_aspects": quality_aspects,
        "purchase_aspects": {
            "precio": "Precio bajo (menor precio = mejor)",
            "descuento": "Descuento sobre precio original",
            "cuotas": "Financiacion (cuotas sin interes)",
            "garantia": "Garantia",
            "tienda_oficial": "Tienda oficial",
            "factura": "Factura",
            "envio": "Envio gratuito",
        },
        "catalog_aspect_map": {},
        "ui": {
            "laf1_page_title": f"Que buscas en {category_label}?",
            "laf1_title": f"Que buscas en {category_label}?",
            "laf1_caption": "Indica que tan importante es cada aspecto para vos.",
            "laf1_next_info": "Ahora corre `python src/08_laf1_generate.py` para ver el ranking de productos.",
            "laf2_page_title": "Como queres comprarlo?",
            "laf2_title": "Como queres comprarlo?",
            "laf2_purchase_title": "Que condiciones de compra te importan?",
            "laf2_next_info": "Ahora corre `python src/10_laf2_generate.py` para ver el ranking de publicaciones.",
        },
        "laf": {
            "system_description": f"Sistema argumentativo de recomendacion - {category_label}",
            "author_line": "Trabajo Final - Ana Paula Machado - UNSE",
        },
        "lexicon": {
            "aspects": aspects,
            "positive": positives,
            "negative": negatives,
            "negation": negations,
        },
    }
    if domain_rules is None:
        domain_rules = load_domain_curation_rules(domain_key)
    if domain_rules.get("term_actions"):
        config["curation_rules"] = domain_rules
    return config


def validate_domain_config(
    config: dict[str, Any],
    expected_domain_key: str,
) -> list[str]:
    """Devuelve problemas que harían ambiguo o inválido el perfil final."""
    errors: list[str] = []
    if config.get("domain_key") != expected_domain_key:
        errors.append("domain_key no coincide con el reporte seleccionado")

    quality = config.get("quality_aspects")
    lexicon = config.get("lexicon")
    if not isinstance(quality, dict):
        errors.append("quality_aspects debe ser un objeto")
        quality = {}
    if not isinstance(lexicon, dict):
        errors.append("lexicon debe ser un objeto")
        return errors

    aspects = lexicon.get("aspects")
    if not isinstance(aspects, dict) or not aspects:
        errors.append("debe existir al menos un aspecto con términos")
        aspects = {}

    # Un mismo termino en dos aspectos vuelve ambigua su asignacion posterior.
    owners: dict[str, str] = {}
    for aspect_key, raw_terms in aspects.items():
        if not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", str(aspect_key)):
            errors.append(f"clave de aspecto inválida: {aspect_key!r}")
        if aspect_key not in quality:
            errors.append(f"falta metadata visible para el aspecto {aspect_key!r}")
        if not isinstance(raw_terms, list) or not split_terms(raw_terms):
            errors.append(f"el aspecto {aspect_key!r} no tiene términos")
            continue
        for term in split_terms(raw_terms):
            normalized = normalize_term(term)
            previous = owners.get(normalized)
            if previous and previous != aspect_key:
                errors.append(
                    f"el término {term!r} aparece en {previous!r} y {aspect_key!r}"
                )
            owners[normalized] = str(aspect_key)

    # La misma palabra no debe sumar y restar polaridad, ni ser a la vez una
    # negacion; se comparan formas normalizadas para incluir tildes y mayusculas.
    polarity_sets: dict[str, set[str]] = {}
    for key in ("positive", "negative", "negation"):
        values = lexicon.get(key)
        if not isinstance(values, list):
            errors.append(f"lexicon.{key} debe ser una lista")
            values = []
        polarity_sets[key] = {normalize_term(term) for term in values if clean_text(term)}

    for left, right in (("positive", "negative"), ("positive", "negation"), ("negative", "negation")):
        overlap = sorted(polarity_sets[left] & polarity_sets[right])
        if overlap:
            errors.append(
                f"términos presentes a la vez en {left} y {right}: {', '.join(overlap)}"
            )
    return list(dict.fromkeys(errors))


def lexicon_diff(base: dict[str, Any], preview: dict[str, Any]) -> dict[str, list[str]]:
    """Muestra solo palabras de polaridad agregadas durante esta curaduria."""
    return {
        "positive": sorted(set(preview["lexicon"]["positive"]) - set(base["positive"])),
        "negative": sorted(set(preview["lexicon"]["negative"]) - set(base["negative"])),
        "negation": sorted(set(preview["lexicon"]["negation"]) - set(base["negation"])),
    }


def rule_from_row(row: pd.Series) -> dict[str, Any] | None:
    """Convierte una fila editada en una regla declarativa reutilizable."""
    term = clean_text(row.get("termino"))
    action = clean_text(row.get("accion"))
    if not term or action not in ACTION_OPTIONS:
        return None

    group = clean_text(row.get("grupo"))
    label = clean_text(row.get("nombre_grupo"))
    reason = (
        clean_text(row.get("motivo_llm"))
        or clean_text(row.get("motivo_local"))
        or "Regla guardada desde la revision humana del dominio."
    )
    terms = [term, *split_terms(row.get("agregar_terminos"))]

    return {
        "terms": list(dict.fromkeys(terms)),
        "action": action,
        "group": group,
        "label": label,
        "reason": reason,
    }


def rules_from_edited(edited: pd.DataFrame, scope: str) -> list[dict[str, Any]]:
    """Agrupa filas marcadas para recordar en reglas globales o de dominio."""
    selected = edited[edited.get("guardar_regla", "no guardar") == scope].copy()
    if selected.empty:
        return []

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for _, row in selected.iterrows():
        rule = rule_from_row(row)
        if not rule:
            continue
        key = (rule["action"], rule.get("group", ""), rule.get("label", ""))
        if key not in grouped:
            grouped[key] = rule
            continue
        grouped[key]["terms"] = list(dict.fromkeys([*grouped[key]["terms"], *rule["terms"]]))
    return list(grouped.values())


def upsert_term_rules(existing: dict[str, Any], new_rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Inserta reglas nuevas y reemplaza decisiones previas para esos terminos."""
    existing_rules = list(existing.get("term_actions", []))
    replacing_terms = {
        clean_text(term).lower()
        for rule in new_rules
        for term in rule.get("terms", [])
        if clean_text(term)
    }

    # Antes de agregar la decision nueva, se quitan esos terminos de reglas
    # anteriores para que nunca queden dos criterios activos en conflicto.
    kept = []
    for rule in existing_rules:
        terms = [
            term for term in rule.get("terms", [])
            if clean_text(term).lower() not in replacing_terms
        ]
        if terms:
            updated = dict(rule)
            updated["terms"] = terms
            kept.append(updated)

    return {"term_actions": [*kept, *new_rules]}


def save_global_rules(new_rules: list[dict[str, Any]]) -> Path:
    """Actualiza la memoria comun a todos los dominios."""
    lexicon = load_json(BASE_LEXICON_PATH)
    lexicon["curation_rules"] = upsert_term_rules(
        lexicon.get("curation_rules", {}),
        new_rules,
    )
    save_json(BASE_LEXICON_PATH, lexicon)
    return BASE_LEXICON_PATH


def save_domain_rules(domain_key: str, new_rules: list[dict[str, Any]]) -> Path:
    """Actualiza la memoria aplicable solo al dominio seleccionado."""
    path = domain_rules_path(domain_key)
    existing = load_domain_curation_rules(domain_key)
    payload = {"curation_rules": upsert_term_rules(existing, new_rules)}
    save_json(path, payload)
    return path


def rules_editor_rows(rules: dict[str, Any]) -> pd.DataFrame:
    """Adapta el JSON de reglas al formato tabular editable de Streamlit."""
    rows = []
    for rule in rules.get("term_actions", []):
        rows.append({
            "usar": True,
            "terminos": ", ".join(rule.get("terms", [])),
            "accion": clean_text(rule.get("action")) or "dudoso",
            "grupo": clean_text(rule.get("group")),
            "nombre_visible": clean_text(rule.get("label")),
            "motivo": clean_text(rule.get("reason")),
        })
    return pd.DataFrame(
        rows,
        columns=["usar", "terminos", "accion", "grupo", "nombre_visible", "motivo"],
    )


def rules_payload_from_editor(rows: pd.DataFrame) -> dict[str, Any]:
    """Reconstruye un JSON valido desde las filas habilitadas del editor."""
    term_actions = []
    for _, row in rows.iterrows():
        if not bool(row.get("usar", True)):
            continue
        terms = split_terms(row.get("terminos"))
        action = clean_text(row.get("accion")) or "dudoso"
        if not terms or action not in ACTION_OPTIONS:
            continue
        term_actions.append({
            "terms": terms,
            "action": action,
            "group": clean_text(row.get("grupo")),
            "label": clean_text(row.get("nombre_visible")),
            "reason": clean_text(row.get("motivo")) or "Regla definida por revision humana experta.",
        })
    return {"term_actions": term_actions}


def save_global_rules_payload(rules: dict[str, Any]) -> Path:
    """Reemplaza la memoria global completa tras editarla manualmente."""
    lexicon = load_json(BASE_LEXICON_PATH)
    lexicon["curation_rules"] = rules
    save_json(BASE_LEXICON_PATH, lexicon)
    return BASE_LEXICON_PATH


def save_domain_rules_payload(domain_key: str, rules: dict[str, Any]) -> Path:
    """Reemplaza la memoria completa del dominio tras editarla manualmente."""
    path = domain_rules_path(domain_key)
    save_json(path, {"curation_rules": rules})
    return path


def editor(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """Renderiza la tabla principal dejando editables solo decisiones humanas."""
    return st.data_editor(
        df,
        key=key,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        column_config={
            "accion": st.column_config.SelectboxColumn("Decision", options=ACTION_OPTIONS, required=True),
            "guardar_regla": st.column_config.SelectboxColumn("Recordar criterio", options=RULE_SCOPE_OPTIONS, required=True),
            "termino": st.column_config.TextColumn("Termino encontrado"),
            "fuente_decision": st.column_config.TextColumn("Fuente"),
            "regla_usada": st.column_config.TextColumn("Regla aplicada"),
            "alcance_regla": st.column_config.TextColumn("Alcance regla"),
            "grupo": st.column_config.TextColumn("Grupo/aspecto"),
            "nombre_grupo": st.column_config.TextColumn("Nombre para mostrar"),
            "terminos_grupo": st.column_config.TextColumn("Sugerencia de grupo"),
            "agregar_terminos": st.column_config.TextColumn("Sinonimos/frases extra"),
            "menciones": st.column_config.NumberColumn("Resenas"),
            "oraciones": st.column_config.NumberColumn("Oraciones"),
            "polaridad": st.column_config.NumberColumn("Polaridad", format="%.3f"),
            "conf_llm": st.column_config.NumberColumn("Confianza LLM", format="%.2f"),
            "ejemplos": st.column_config.TextColumn("Ejemplos reales"),
        },
        disabled=[
            "termino", "terminos_grupo", "menciones", "oraciones", "polaridad",
            "pos", "neg", "neu", "ejemplos", "regla_local", "motivo_local",
            "llm_decision", "llm_sugerencia", "conf_llm", "motivo_llm",
            "motivo_descarte", "motivo_duda", "fuente_decision", "regla_usada",
            "alcance_regla", "motivo_regla",
        ],
        column_order=[
            "accion", "termino", "conf_llm", "grupo", "nombre_grupo", "guardar_regla",
            "fuente_decision", "regla_usada", "alcance_regla", "terminos_grupo",
            "agregar_terminos", "menciones", "oraciones", "polaridad",
            "motivo_regla", "motivo_llm", "motivo_local", "motivo_descarte",
            "motivo_duda", "ejemplos",
        ],
    )


def lexicon_aspect_rows(preview: dict[str, Any]) -> pd.DataFrame:
    """Convierte los aspectos del perfil en filas para la edicion final."""
    rows = []
    for aspect_key, terms in preview["lexicon"]["aspects"].items():
        rows.append({
            "usar": True,
            "grupo": aspect_key,
            "nombre_visible": preview["quality_aspects"].get(aspect_key, {}).get("label", key_to_label(aspect_key)),
            "terminos": ", ".join(terms),
        })
    return pd.DataFrame(rows, columns=["usar", "grupo", "nombre_visible", "terminos"])


def lexicon_polarity_rows(preview: dict[str, Any], base_lexicon: dict[str, Any]) -> pd.DataFrame:
    """Prepara polaridad e indica si cada termino viene de base o de curaduria."""
    rows = []
    labels = {
        "positive": "positivo",
        "negative": "negativo",
        "negation": "negacion",
    }
    for key, label in labels.items():
        base_terms = set(base_lexicon.get(key, []))
        for term in preview["lexicon"].get(key, []):
            rows.append({
                "usar": True,
                "tipo": label,
                "termino": term,
                "origen": "base" if term in base_terms else "curado",
            })
    return pd.DataFrame(rows, columns=["usar", "tipo", "termino", "origen"])


def apply_lexicon_edits(
    preview: dict[str, Any],
    aspect_rows: pd.DataFrame,
    polarity_rows: pd.DataFrame,
) -> dict[str, Any]:
    """Aplica la segunda edicion visual sin modificar la previsualizacion fuente."""
    # La copia profunda separa el perfil fuente del resultado que el usuario
    # esta modificando en esta pantalla.
    edited_preview = json.loads(json.dumps(preview, ensure_ascii=False))
    edited_preview["quality_aspects"] = {}
    edited_preview["lexicon"]["aspects"] = {}
    edited_preview["lexicon"]["positive"] = []
    edited_preview["lexicon"]["negative"] = []
    edited_preview["lexicon"]["negation"] = []

    for _, row in aspect_rows.iterrows():
        if not bool(row.get("usar", True)):
            continue
        aspect_key = clean_text(row.get("grupo"))
        if not aspect_key:
            continue
        label = clean_text(row.get("nombre_visible")) or key_to_label(aspect_key)
        terms = split_terms(row.get("terminos"))
        if not terms:
            continue
        # Si el editor contiene dos filas con la misma clave, se fusionan sus
        # términos en vez de perder silenciosamente la primera fila.
        edited_preview["quality_aspects"].setdefault(
            aspect_key,
            {"label": label, "icon": ""},
        )
        existing_terms = edited_preview["lexicon"]["aspects"].setdefault(
            aspect_key,
            [],
        )
        for term in terms:
            if term not in existing_terms:
                existing_terms.append(term)

    target_by_type = {
        "positivo": "positive",
        "negativo": "negative",
        "negacion": "negation",
    }
    for _, row in polarity_rows.iterrows():
        if not bool(row.get("usar", True)):
            continue
        target = target_by_type.get(clean_text(row.get("tipo")))
        term = clean_text(row.get("termino"))
        if not target or not term:
            continue
        if term not in edited_preview["lexicon"][target]:
            edited_preview["lexicon"][target].append(term)

    return edited_preview


def render_workflow_header(
    category_label: str,
    domain_key: str,
    selected_llm: Path | None,
    output_path: Path,
) -> None:
    """Explica entradas, salida y los cuatro pasos principales de la pantalla."""
    st.caption(f"Dominio: {category_label} (`{domain_key}`)")
    st.markdown("**Flujo de trabajo del experto**")
    cols = st.columns(4)
    cols[0].markdown("**1. Revisar**  \nDecidi si cada termino es aspecto, polaridad, duda o descarte.")
    cols[1].markdown("**2. Lexicon**  \nAjusta los grupos y las palabras que usara `05_aspects.py`.")
    cols[2].markdown("**3. Guardar**  \nGenera el perfil estable del dominio.")
    cols[3].markdown("**4. Reutilizar**  \nGuarda reglas si queres recordar criterios para otros analisis.")

    llm_status = selected_llm.name if selected_llm else "No usado"
    st.info(
        f"Entrada: reporte `02_domain_discovery.py` + LLM opcional `{llm_status}`. "
        f"Salida principal: `{output_path}`. "
        "El LLM sugiere; la decision final es humana y queda auditable."
    )


def render_action_guide() -> None:
    """Muestra ejemplos breves para cada decision disponible."""
    st.markdown("**Como decidir una fila**")
    st.dataframe(
        pd.DataFrame([
            {
                "Decision": "aspecto",
                "Cuando usarla": "Es una caracteristica del producto.",
                "Ejemplo": "frio, enfria, ruido, instalacion",
                "Se guarda en": "lexicon.aspects",
            },
            {
                "Decision": "positivo / negativo",
                "Cuando usarla": "No es caracteristica, pero orienta la opinion.",
                "Ejemplo": "excelente, falla, no enfria",
                "Se guarda en": "lexicon.positive / negative",
            },
            {
                "Decision": "negacion",
                "Cuando usarla": "Invierte o cambia la polaridad cercana.",
                "Ejemplo": "no, sin, nunca",
                "Se guarda en": "lexicon.negation",
            },
            {
                "Decision": "dudoso",
                "Cuando usarla": "Todavia no queres decidir.",
                "Ejemplo": "expectativa, contento, confiable",
                "Se guarda en": "nada por ahora",
            },
            {
                "Decision": "descartar",
                "Cuando usarla": "Es contexto o no sirve para LAF 1.",
                "Ejemplo": "noche, semana, precio, envio",
                "Se guarda en": "nada; la resena no se elimina",
            },
        ]),
        width="stretch",
        hide_index=True,
    )


def render_lexicon_summary(preview: dict[str, Any], base_lexicon: dict[str, Any]) -> None:
    """Resume aspectos finales y cambios de polaridad respecto de la base."""
    diff = lexicon_diff(base_lexicon, preview)
    left, right = st.columns([1, 1])
    with left:
        st.markdown("**Aspectos que se guardan**")
        if preview["lexicon"]["aspects"]:
            for aspect_key, terms in preview["lexicon"]["aspects"].items():
                label = preview["quality_aspects"].get(aspect_key, {}).get("label", key_to_label(aspect_key))
                st.write(f"**{label}** (`{aspect_key}`): {', '.join(terms)}")
        else:
            st.info("Todavia no hay aspectos aceptados.")
    with right:
        st.markdown("**Polaridad agregada al dominio**")
        st.write(f"Positivas: {', '.join(diff['positive']) if diff['positive'] else 'sin cambios'}")
        st.write(f"Negativas: {', '.join(diff['negative']) if diff['negative'] else 'sin cambios'}")
        st.write(f"Negacion: {', '.join(diff['negation']) if diff['negation'] else 'sin cambios'}")


def render_polarity_usage(preview: dict[str, Any]) -> None:
    """Explica como 05 interpretara cada una de las listas de polaridad."""
    lexicon = preview["lexicon"]
    cols = st.columns(3)
    polarity_sets = [
        ("Positivas", lexicon.get("positive", []), "Si aparece cerca de un aspecto, suma evidencia positiva."),
        ("Negativas", lexicon.get("negative", []), "Si aparece cerca de un aspecto, suma evidencia negativa."),
        ("Negaciones", lexicon.get("negation", []), "Puede invertir una polaridad cercana, por ejemplo `no enfria`."),
    ]
    for col, (label, terms, explanation) in zip(cols, polarity_sets):
        col.metric(label, len(terms))
        sample = ", ".join(list(terms)[:18])
        col.caption(explanation)
        col.write(sample if sample else "sin terminos")


def applied_rules_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Extrae una vista compacta de las reglas que precargaron candidatos."""
    if "regla_usada" not in df:
        return pd.DataFrame(columns=["alcance", "termino", "decision", "grupo", "motivo"])
    applied = df[df["regla_usada"] == "si"].copy()
    if applied.empty:
        return pd.DataFrame(columns=["alcance", "termino", "decision", "grupo", "motivo"])
    return applied[[
        "alcance_regla", "termino", "accion", "grupo", "nombre_grupo", "motivo_regla", "ejemplos",
    ]].rename(columns={
        "alcance_regla": "alcance",
        "termino": "termino",
        "accion": "decision_inicial",
        "grupo": "grupo",
        "nombre_grupo": "nombre_visible",
        "motivo_regla": "motivo",
        "ejemplos": "ejemplos",
    })


def render_save_profile(
    preview: dict[str, Any],
    output_path: Path,
    expected_domain_key: str,
    button_key: str,
) -> None:
    """Valida y guarda el perfil; nunca persiste una configuracion ambigua."""
    if st.button("Guardar perfil final del dominio", type="primary", width="stretch", key=button_key):
        errors = validate_domain_config(preview, expected_domain_key)
        if errors:
            st.error("No se guardó el perfil porque necesita estas correcciones:")
            for error in errors:
                st.write(f"- {error}")
            st.stop()
        save_json(output_path, preview)
        st.success(f"Listo. Se guardo el perfil final en {output_path}")



def main() -> None:
    """Renderiza la interfaz; la lógica pura queda importable para las pruebas."""
    st.set_page_config(page_title="Curar aspectos del dominio", layout="wide")
    st.title("Panel experto: construir lexicon del dominio")

    options = report_options()
    if not options:
        st.error("No hay reportes. Corre primero `python src/02_domain_discovery.py`.")
        st.stop()

    # La barra lateral selecciona artefactos y parametros; el cuerpo se dedica
    # a revisar, ajustar y persistir el resultado.
    with st.sidebar:
        st.markdown("**Entrada del analisis**")
        selected_report = st.selectbox("Reporte de candidatos (02)", options, format_func=lambda p: p.name)
        try:
            report = load_json(selected_report)
        except RuntimeError as exc:
            st.error(str(exc))
            st.stop()
        meta = report.get("dataset", {})
        category_label = meta.get("category_label") or selected_report.stem.replace("domain_discovery_", "")
        domain_key = artifact_domain_key(selected_report) or domain_key_from_category_label(category_label)
        try:
            validate_report_identity(selected_report, report, domain_key)
        except RuntimeError as exc:
            st.error(str(exc))
            st.stop()

        llm_options = suggestion_options()
        matching_llm = [
            p for p in llm_options
            if artifact_domain_key(p) == domain_key or p.stem == f"llm_suggestions_{domain_key}"
        ]
        selected_llm = None
        if matching_llm:
            # Solo se ofrecen sugerencias del mismo dominio. La firma del reporte se
            # verifica después de elegir para impedir mezclar ejecuciones antiguas.
            llm_choices = [None] + matching_llm
        selected_llm = st.selectbox(
            "Sugerencias del LLM (03)",
            llm_choices,
            # Empezar sin LLM evita aplicar automáticamente un artefacto antiguo;
            # el experto lo activa de forma explícita después de ver su nombre.
            index=0,
            format_func=lambda p: "No usar LLM" if p is None else p.name,
        )

        st.markdown("**Como llenar la tabla**")
        min_mentions = st.slider("Mostrar si aparece en al menos", 1, 50, 5)
        seed_mode = st.radio(
            "Decision inicial",
            ["Conservador", "LLM como base", "Reglas locales", "Todo dudoso"],
            help="Solo cambia los valores iniciales. Siempre podes corregir a mano.",
        )
        search_text = st.text_input("Buscar termino o ejemplo", placeholder="enfria, frio, ruido...")

    # Todo artefacto externo se valida antes de construir la tabla editable.
    try:
        llm_payload = load_llm_payload(selected_llm, report, domain_key)
    except RuntimeError as exc:
        st.error(str(exc))
        st.info("Selecciona `No usar LLM` o vuelve a ejecutar `03_llm_suggestions.py`.")
        st.stop()
    try:
        base_lexicon = load_json(BASE_LEXICON_PATH)
        current_global_rules = base_lexicon.get("curation_rules", {})
        current_domain_rules = load_domain_curation_rules(domain_key)
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    # Estos archivos se cargan una sola vez por rerun y se comparten entre las
    # funciones puras que construyen tabla, perfil y pestaña de reglas.
    df = rows_from_report(
        report,
        min_mentions,
        llm_payload,
        current_global_rules,
        current_domain_rules,
    )
    if df.empty:
        st.warning("No hay candidatos con ese umbral.")
        st.stop()

    if seed_mode == "LLM como base":
        initial_seeded = df.copy()
    else:
        initial_seeded = apply_seed_mode(df, seed_mode)

    # La firma cambia cuando cambian reporte, reglas, LLM, umbral o modo inicial.
    # El texto de búsqueda queda afuera porque solo controla qué filas se ven.
    seed_signature = hashlib.sha256(
        initial_seeded.to_json(orient="records", force_ascii=False).encode("utf-8")
    ).hexdigest()
    candidate_state_key = f"candidate_review::{domain_key}::{seed_signature}"
    if candidate_state_key not in st.session_state:
        st.session_state[candidate_state_key] = initial_seeded.copy()
    complete_seeded = st.session_state[candidate_state_key].copy()
    visible_seeded = filter_candidate_rows(complete_seeded, search_text)

    output_path = DOMAIN_DIR / f"{domain_key}.json"
    render_workflow_header(category_label, domain_key, selected_llm, output_path)

    try:
        saved_profile = load_optional_json(output_path)
    except RuntimeError as exc:
        st.error(str(exc))
        st.info("Corrige o recupera el perfil antes de continuar para no sobrescribirlo.")
        st.stop()
    use_saved_profile = False
    if saved_profile:
        with st.sidebar:
            st.markdown("**Perfil final existente**")
            st.caption(
                "Ya hay un perfil guardado para este dominio. Activá esta opción "
                "para que las pestañas 2 y 3 muestren exactamente ese perfil, "
                "en vez de reconstruirlo desde 02/03."
            )
            use_saved_profile = st.checkbox(
                "Editar perfil guardado",
                value=True,
                help=(
                    "Si está activo, las pestañas de lexicon usan "
                    "config/domains/<dominio>.json. Si lo desactivás, se vuelve "
                    "a construir el lexicon desde la tabla de candidatos."
                ),
            )

    metric_placeholder = st.container()

    # Las pestanas separan la decision conceptual de la edicion tecnica final,
    # sin perder las vistas de auditoria, dudas y descartes.
    tabs = st.tabs([
        "1 Revisar candidatos",
        "2 Ajustar lexicon",
        "3 Guardar y continuar",
        "Reglas",
        "Dudas",
        "Descartes",
        "Ayuda",
        "Auditoria",
    ])

    with tabs[0]:
        st.subheader("1. Revisar candidatos")
        st.write(
            "Trabaja de izquierda a derecha: primero elegi la decision, despues el grupo/aspecto, "
            "y solo marca `Recordar criterio` si queres reutilizar esa decision en otro analisis."
        )
        with st.expander("Ver guia rapida de decisiones", expanded=True):
            render_action_guide()

        st.caption(
            "Columna **Confianza LLM** (0-1): que tan segura esta la IA de su sugerencia para ese termino. "
            "Mas abajo, en 'Lo que estas construyendo', **confianza_media** es el promedio de confianza LLM por grupo/aspecto."
        )

        edited_visible = editor(
            visible_seeded,
            key=f"groups_{selected_report.name}_{selected_llm}_{min_mentions}_{seed_mode}_{search_text}",
        )
        edited = merge_visible_edits(complete_seeded, edited_visible)
        st.session_state[candidate_state_key] = edited.copy()
        group_preview = group_summary_from_rows(edited)
        st.divider()
        st.subheader("Lo que estas construyendo")
        st.caption("Este resumen muestra como quedarian agrupados los aspectos si guardaras ahora.")
        if group_preview.empty:
            st.info("Todavia no hay grupos aceptados como aspecto.")
        else:
            st.dataframe(group_preview, width="stretch", hide_index=True)

    with metric_placeholder:
        metric_cols = st.columns(5)
        metric_cols[0].metric("Candidatos", len(edited))
        metric_cols[1].metric("Aspectos", int((edited["accion"] == "aspecto").sum()))
        metric_cols[2].metric("Por revisar", int((edited["accion"] == "dudoso").sum()))
        metric_cols[3].metric("Descartes", int((edited["accion"] == "descartar").sum()))
        metric_cols[4].metric(
            "Polaridad",
            int(edited["accion"].isin(["positivo", "negativo", "negacion"]).sum()),
        )

    candidate_preview = build_domain_config(
        report,
        edited,
        base_lexicon,
        current_domain_rules,
    )
    base_preview = saved_profile if use_saved_profile and saved_profile else candidate_preview
    preview = base_preview
    lexicon_source = "perfil_guardado" if use_saved_profile and saved_profile else "candidatos"

    with tabs[1]:
        st.subheader("2. Ajustar lexicon")
        st.write(
            "Esta es la version operativa que usara `05_aspects.py`. "
            "Aca podes corregir grupos, sinonimos y palabras de polaridad antes de guardar."
        )
        st.info(
            "El LLM de `03_llm_suggestions.py` no cambia retroactivamente: si ya generaste sus sugerencias, ese JSON queda igual. "
            "Tus cambios impactan al guardar el perfil del dominio y al correr `05_aspects.py`. "
            "Para que el LLM vea estos criterios, guardalos como reglas y vuelve a ejecutar `03_llm_suggestions.py`."
        )
        if use_saved_profile and saved_profile:
            st.success(
                "Estás editando el perfil final ya guardado. "
                "Las métricas de arriba siguen describiendo los candidatos 02/03, "
                "no el perfil final."
            )
        else:
            st.info(
                "Estás reconstruyendo el lexicon desde la tabla de candidatos. "
                "Si querés recuperar lo último guardado, activá `Editar perfil guardado` en la barra lateral."
            )

        st.markdown("**Aspectos del dominio**")
        st.caption(
            "Cada fila es un grupo de aspecto. En `terminos` van sinonimos o frases separadas por coma, "
            "por ejemplo `enfria, frio, enfriamiento, fresco`."
        )
        edited_aspect_rows = st.data_editor(
            lexicon_aspect_rows(base_preview),
            key=f"lexicon_aspects_{lexicon_source}_{selected_report.name}_{selected_llm}_{min_mentions}_{seed_mode}",
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "usar": st.column_config.CheckboxColumn("Usar", default=True),
                "grupo": st.column_config.TextColumn("Clave interna"),
                "nombre_visible": st.column_config.TextColumn("Nombre visible"),
                "terminos": st.column_config.TextColumn("Terminos"),
            },
        )

        st.markdown("**Polaridad y negacion**")
        st.caption(
            "Estas listas si se usan en `05_aspects.py`: despues de detectar un aspecto, "
            "el script busca estas palabras para asignar polaridad `pos`, `neg` o `neu`."
        )
        edited_polarity_rows = st.data_editor(
            lexicon_polarity_rows(base_preview, base_lexicon),
            key=f"lexicon_polarity_{lexicon_source}_{selected_report.name}_{selected_llm}_{min_mentions}_{seed_mode}",
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "usar": st.column_config.CheckboxColumn("Usar", default=True),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["positivo", "negativo", "negacion"], required=True),
                "termino": st.column_config.TextColumn("Termino"),
                "origen": st.column_config.TextColumn("Origen"),
            },
            disabled=["origen"],
        )

        preview = apply_lexicon_edits(base_preview, edited_aspect_rows, edited_polarity_rows)

        st.markdown("**Como se usara la polaridad en `05_aspects.py`**")
        render_polarity_usage(preview)

        st.divider()
        st.markdown("**Resultado que se guardaria**")
        render_lexicon_summary(preview, base_lexicon)

        with st.expander("Ver lexicon base global"):
            st.json({
                "positive": base_lexicon.get("positive", []),
                "negative": base_lexicon.get("negative", []),
                "negation": base_lexicon.get("negation", []),
                "curation_rules": base_lexicon.get("curation_rules", {}),
            })

    with tabs[2]:
        st.subheader("3. Guardar y continuar")
        st.write(
            "Cuando el resumen te parezca correcto, guarda el perfil final. "
            "Ese archivo es la entrada estable para extraer aspectos con `05_aspects.py`."
        )
        render_lexicon_summary(preview, base_lexicon)
        st.markdown("**Polaridad que usara `05_aspects.py`**")
        render_polarity_usage(preview)

        with st.expander("JSON tecnico que se va a guardar"):
            st.json(preview)

        render_save_profile(preview, output_path, domain_key, "save_domain_profile_main")
        st.markdown("**Despues de guardar**")
        st.code(".\\venv\\Scripts\\python.exe src\\05_aspects.py", language="powershell")
        st.caption(
            "Volves a esta pantalla solo si cambias de dominio, aparecen aspectos nuevos "
            "o queres mejorar el lexicon con mas revision humana."
        )

    with tabs[3]:
        st.subheader("Reglas / memoria experta")
        st.caption(
            "Las reglas guardan criterios humanos reutilizables. El LLM puede sugerir, "
            "pero estas decisiones quedan explicitadas para que el pipeline sea auditable y reproducible."
        )
        st.info(
            "Reglas globales: aplican a todos los dominios. "
            f"Reglas del dominio: aplican solo a `{domain_key}`. "
            "`03_llm_suggestions.py` y `04_domain_review.py` las usan para orientar la curaduria; `05_aspects.py` usa el lexicon final guardado."
        )

        used_rules = applied_rules_summary(edited)

        st.markdown("**Reglas aplicadas en esta revision**")
        st.caption(
            "Estas son las reglas que ya se usaron para completar la tabla inicial de candidatos. "
            "Si luego cambias una fila a mano, tu edicion humana es la que queda para el lexicon final."
        )
        if used_rules.empty:
            st.info("No se aplico ninguna regla guardada a los candidatos visibles con estos filtros.")
        else:
            st.dataframe(used_rules, width="stretch", hide_index=True)

        st.markdown("**Reglas disponibles para usar ahora o en futuros analisis**")
        available_cols = st.columns(2)
        available_cols[0].metric("Globales disponibles", len(current_global_rules.get("term_actions", [])))
        available_cols[1].metric("Del dominio disponibles", len(current_domain_rules.get("term_actions", [])))

        st.divider()
        global_rules = rules_from_edited(edited, "global")
        domain_rules = rules_from_edited(edited, "dominio")
        no_rule_count = int((edited["guardar_regla"] == "no guardar").sum()) if "guardar_regla" in edited else len(edited)

        st.markdown("**Guardar decisiones marcadas en la revision**")
        st.caption(
            "Esta seccion toma las filas donde elegiste `global` o `dominio` en la columna "
            "`Recordar criterio` de la pestana `1 Revisar candidatos`."
        )

        cols = st.columns(3)
        cols[0].metric("Nuevas globales", len(global_rules))
        cols[1].metric("Nuevas de dominio", len(domain_rules))
        cols[2].metric("Sin guardar", no_rule_count)

        left, right = st.columns(2)
        with left:
            st.markdown("**Reglas globales**")
            st.caption("Aplican a todos los dominios.")
            if global_rules:
                st.dataframe(pd.DataFrame(global_rules), width="stretch", hide_index=True)
            else:
                st.info("No marcaste filas como global.")
            if st.button("Guardar reglas globales", width="stretch", disabled=not bool(global_rules)):
                path = save_global_rules(global_rules)
                st.success(f"Reglas globales guardadas en {path}")

        with right:
            st.markdown(f"**Reglas del dominio `{domain_key}`**")
            st.caption("Aplican solo cuando revises este dominio.")
            if domain_rules:
                st.dataframe(pd.DataFrame(domain_rules), width="stretch", hide_index=True)
            else:
                st.info("No marcaste filas como dominio.")
            if st.button("Guardar reglas del dominio", width="stretch", disabled=not bool(domain_rules)):
                path = save_domain_rules(domain_key, domain_rules)
                st.success(f"Reglas del dominio guardadas en {path}")

        st.divider()
        st.markdown("**Editar reglas existentes**")
        st.caption(
            "Aca podes revisar toda la memoria experta ya guardada. "
            "Desmarca `Usar` para quitar una regla, edita una fila para corregirla o agrega una fila nueva."
        )

        global_existing_count = len(current_global_rules.get("term_actions", []))
        domain_existing_count = len(current_domain_rules.get("term_actions", []))
        count_cols = st.columns(2)
        count_cols[0].metric("Reglas globales guardadas", global_existing_count)
        count_cols[1].metric("Reglas de este dominio guardadas", domain_existing_count)

        rules_left, rules_right = st.columns(2)
        with rules_left:
            st.markdown("**Memoria global**")
            st.caption("Usala para decisiones que quieras repetir en cualquier rubro.")
            edited_global_rules = st.data_editor(
                rules_editor_rows(current_global_rules),
                key=f"global_rules_editor_{selected_report.name}",
                width="stretch",
                hide_index=True,
                num_rows="dynamic",
                column_config={
                    "usar": st.column_config.CheckboxColumn("Usar", default=True),
                    "terminos": st.column_config.TextColumn("Terminos"),
                    "accion": st.column_config.SelectboxColumn("Decision", options=ACTION_OPTIONS, required=True),
                    "grupo": st.column_config.TextColumn("Grupo sugerido"),
                    "nombre_visible": st.column_config.TextColumn("Nombre visible"),
                    "motivo": st.column_config.TextColumn("Justificacion"),
                },
            )
            if st.button("Guardar memoria global completa", width="stretch"):
                payload = rules_payload_from_editor(edited_global_rules)
                path = save_global_rules_payload(payload)
                st.success(f"Memoria global guardada en {path}")

        with rules_right:
            st.markdown(f"**Memoria del dominio `{domain_key}`**")
            st.caption("Usala para vocabulario tecnico o criterios propios de este dominio.")
            edited_domain_rules = st.data_editor(
                rules_editor_rows(current_domain_rules),
                key=f"domain_rules_editor_{domain_key}_{selected_report.name}",
                width="stretch",
                hide_index=True,
                num_rows="dynamic",
                column_config={
                    "usar": st.column_config.CheckboxColumn("Usar", default=True),
                    "terminos": st.column_config.TextColumn("Terminos"),
                    "accion": st.column_config.SelectboxColumn("Decision", options=ACTION_OPTIONS, required=True),
                    "grupo": st.column_config.TextColumn("Grupo sugerido"),
                    "nombre_visible": st.column_config.TextColumn("Nombre visible"),
                    "motivo": st.column_config.TextColumn("Justificacion"),
                },
            )
            if st.button("Guardar memoria del dominio completa", width="stretch"):
                payload = rules_payload_from_editor(edited_domain_rules)
                path = save_domain_rules_payload(domain_key, payload)
                st.success(f"Memoria del dominio guardada en {path}")

        st.markdown("**Criterio recomendado para el TFG**")
        st.write("Global: emociones, polaridad general, negaciones y terminos de compra que quieras excluir siempre de LAF 1.")
        st.write("Dominio: terminos tecnicos propios del rubro, como `frio`, `filtro`, `agua`, `ventilador`, `tuberia` en aires acondicionados.")
        st.write("El LLM asiste la calibracion, pero la regla guardada representa la decision humana trazable.")

    with tabs[4]:
        st.subheader("Dudas para revisar")
        st.write(
            "Aca aparecen terminos que quedaron dudosos o que tienen alguna advertencia. "
            "No se guardan en el lexicon final hasta que los conviertas en aspecto, polaridad o negacion."
        )
        doubtful = edited[(edited["accion"] == "dudoso") | (edited["motivo_duda"].astype(str) != "")].copy()
        if doubtful.empty:
            st.success("No quedaron palabras dudosas con los filtros actuales.")
        else:
            st.dataframe(
                doubtful[[
                    "termino", "grupo", "menciones", "conf_llm", "motivo_duda",
                    "motivo_local", "motivo_llm", "ejemplos",
                ]],
                width="stretch",
                hide_index=True,
            )

    with tabs[5]:
        st.subheader("Descartes auditables")
        st.write(
            "Descartar un termino no elimina la resena completa. Solo evita que esa palabra "
            "entre como aspecto o polaridad del dominio."
        )
        discarded = edited[edited["accion"] == "descartar"].copy()
        if discarded.empty:
            st.info("No hay descartes con los filtros actuales.")
        else:
            st.dataframe(
                discarded[[
                    "termino", "menciones", "motivo_descarte", "motivo_local",
                    "motivo_llm", "ejemplos",
                ]],
                width="stretch",
                hide_index=True,
            )

    with tabs[6]:
        st.subheader("Ayuda")
        st.caption("La decision define que pasa con cada termino candidato; no elimina resenas completas.")

        st.dataframe(
            pd.DataFrame([
                {
                    "accion": "aspecto",
                    "significa": "La palabra describe una caracteristica del producto y entra como aspecto.",
                    "ejemplos": "ruido, enfriamiento, wifi, consumo",
                    "resultado": "Se guarda en lexicon.aspects bajo el grupo elegido.",
                },
                {
                    "accion": "positivo",
                    "significa": "No es aspecto, pero sirve para detectar polaridad positiva.",
                    "ejemplos": "excelente, perfecto, recomendado",
                    "resultado": "Se agrega al lexicon positivo.",
                },
                {
                    "accion": "negativo",
                    "significa": "No es aspecto, pero sirve para detectar polaridad negativa.",
                    "ejemplos": "malo, defectuoso, falla",
                    "resultado": "Se agrega al lexicon negativo.",
                },
                {
                    "accion": "negacion",
                    "significa": "Sirve para invertir la polaridad cercana.",
                    "ejemplos": "no, nunca, sin",
                    "resultado": "Se agrega al lexicon de negacion.",
                },
                {
                    "accion": "dudoso",
                    "significa": "Todavia no se decide; puede depender del ejemplo o ser muy general.",
                    "ejemplos": "aire, modelo, funcion, completo",
                    "resultado": "No se guarda como final hasta cambiarlo a otra accion.",
                },
                {
                    "accion": "descartar",
                    "significa": "No entra al lexicon final. Es contexto, ruido o no aporta al ABSA.",
                    "ejemplos": "noche, semana, producto, precio",
                    "resultado": "Se ignora como termino, pero la resena completa se conserva.",
                },
            ]),
            width="stretch",
            hide_index=True,
        )

        st.markdown("**Ejemplo importante**")
        st.write(
            "Si una resena dice `enfria rapido mi cuarto y lo uso de noche`, "
            "`noche` puede ir como `descartar`, pero la resena sigue sirviendo para "
            "generar un argumento positivo de `enfriamiento`."
        )

        st.markdown("**Como pensar los casos comunes**")
        st.write("`frio`, `enfria`, `fresco` -> normalmente `aspecto`, agrupados como `enfriamiento`.")
        st.write("`excelente`, `perfecto`, `recomendado` -> normalmente `positivo`.")
        st.write("`expectativa`, `contento`, `satisfecho` -> si existe regla de curaduria, quedan como `dudoso` con grupo sugerido de satisfaccion/expectativas.")
        st.write("`precio`, `envio`, `factura` -> normalmente `descartar` para LAF 1; se usan despues en LAF 2.")
        st.write("`aire`, `modelo`, `marca` -> normalmente `dudoso`; revisar ejemplos antes de decidir.")

    with tabs[7]:
        st.subheader("Auditoria")
        st.caption("Vista completa de los candidatos iniciales. Para editar, usa `1 Revisar candidatos`.")
        st.dataframe(edited, width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
