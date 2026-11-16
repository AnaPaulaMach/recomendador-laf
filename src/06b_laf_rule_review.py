"""
06b_laf_rule_review.py - Revision experta de reglas argumentativas LAF.

Este paso revisa reglas como:

    recomendar(P) :- enfriamientoBueno(P). {0.90; 0.80}
    compraBuena(I) :- tieneCuotas(I). {0.85; 0.50}

No audita el lexicon ni las palabras de las resenas. Esa es otra capa.
Aqui se revisa si las reglas LAF, sus ataques/soportes y sus etiquetas son
metodologicamente defendibles. El LLM puede sugerir, pero el experto decide.

Uso:
    .\\venv\\Scripts\\streamlit.exe run src\\06b_laf_rule_review.py

Momento recomendado:
    - despues de 06a, antes de compilar y congelar la categoria;
    - 08 y 10 solo consumen las reglas ya validadas durante el recorrido real.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from domain_config import ARTIFACTS_DIR, domain_artifact_dir, load_domain_config_for_key


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "reports"
CONFIG_DIR = REPO_ROOT / "config"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

load_dotenv(REPO_ROOT / ".env")

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "rule_id": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["keep", "revise", "reject", "add_rule", "uncertain"],
                    },
                    "issue_type": {
                        "type": "string",
                        "enum": [
                            "semantics",
                            "weight",
                            "attack_support",
                            "preference",
                            "operator",
                            "laf1_laf2_boundary",
                            "traceability",
                            "redundancy",
                            "missing_rule",
                            "none",
                        ],
                    },
                    "current_rule": {"type": "string"},
                    "proposed_rule": {"type": "string"},
                    "proposed_confidence": {"type": "string"},
                    "proposed_preference": {"type": "string"},
                    "reason": {"type": "string"},
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },
                "required": [
                    "rule_id",
                    "verdict",
                    "issue_type",
                    "current_rule",
                    "proposed_rule",
                    "proposed_confidence",
                    "proposed_preference",
                    "reason",
                    "confidence",
                ],
            },
        },
        "global_notes": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["suggestions", "global_notes"],
}

VERDICTS = ["keep", "revise", "reject", "add_rule", "uncertain"]
EXPERT_DECISIONS = ["pendiente", "aceptar", "editar", "rechazar", "solo_anotar"]
PRIORITIES = ["alta", "media", "baja"]


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def program_options() -> list[Path]:
    files = list(ARTIFACTS_DIR.glob("*/programas_laf/programa_laf*.txt"))
    files.extend(REPO_ROOT.glob("programa_laf*.txt"))
    files = sorted(files)
    return files


def program_label(path: Path) -> str:
    try:
        return str(path.relative_to(ARTIFACTS_DIR))
    except ValueError:
        return path.name


def default_program_names(files: list[Path], config: dict[str, Any]) -> list[str]:
    """Prioriza los programas del dominio activo para evitar mezclar experimentos."""
    domain_key = clean_text(config.get("domain_key"))
    domain_files = [
        p for p in files
        if domain_key and (
            domain_key in p.stem
            or (len(p.parts) >= 3 and p.parent.name == "programas_laf" and p.parent.parent.name == domain_key)
        )
    ]
    candidates = domain_files or files
    preferred = [
        program_label(p) for p in candidates
        if "laf1_D" in p.name or "laf2" in p.name or p.name == "programa_laf1.txt"
    ]
    return preferred or ([program_label(candidates[0])] if candidates else [])


def classify_program(path: Path) -> str:
    name = path.name.lower()
    if "laf1" in name:
        return "LAF 1"
    if "laf2" in name:
        return "LAF 2"
    return "LAF"


def extract_annotation(line: str) -> tuple[str, str, str] | None:
    match = re.search(r"^(?P<stmt>.+?)\.\s*\{(?P<a>[^;{}]+);\s*(?P<b>[^{}]+)\}\s*$", line.strip())
    if not match:
        return None
    return (
        clean_text(match.group("stmt")),
        clean_text(match.group("a")),
        clean_text(match.group("b")),
    )


def split_rule(stmt: str) -> tuple[str, str]:
    if ":-" not in stmt:
        return clean_text(stmt), ""
    head, body = stmt.split(":-", 1)
    return clean_text(head), clean_text(body)


def parse_program(path: Path, include_facts: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    section = "Sin seccion"
    kind = "unknown"
    program_kind = classify_program(path)

    for line_no, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        if line.startswith("%"):
            marker = line.strip("% ").upper()
            if "HECHOS" in marker:
                section = "HECHOS"
            elif "REGLAS INTERMEDIAS" in marker:
                section = "REGLAS INTERMEDIAS POR DIMENSION"
            elif "REGLAS DE AGREGACION" in marker or "REGLAS DE AGREGACI" in marker:
                section = "REGLAS DE AGREGACION"
            elif "REGLAS DE RECOMENDACION" in marker or "REGLAS DE RECOMENDACI" in marker:
                section = "REGLAS DE RECOMENDACION"
            elif "OPERADORES" in marker:
                section = "OPERADORES"
            continue

        annotation = extract_annotation(line)
        if not annotation:
            continue

        stmt, conf, pref = annotation
        has_body = ":-" in stmt
        if not has_body and not include_facts:
            continue

        head, body = split_rule(stmt)
        if has_body:
            kind = "regla"
        else:
            kind = "hecho"

        rows.append({
            "rule_id": f"{path.stem}:{line_no}",
            "program": program_kind,
            "source_file": path.name,
            "line_no": line_no,
            "section": section,
            "kind": kind,
            "head": head,
            "body": body,
            "confidence_label": conf,
            "preference_label": pref,
            "raw_rule": line,
        })

    return rows


def load_rules(paths: list[Path], include_facts: bool) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(parse_program(path, include_facts=include_facts))
    return pd.DataFrame(rows)


def atom_part(value: Any) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_]", "_", ascii_value)).strip("_").lower()


def cap_atom(value: Any) -> str:
    return atom_part(value).capitalize()


def exact_rule(rules_df: pd.DataFrame, head: str, body: str) -> pd.DataFrame:
    if rules_df.empty:
        return rules_df
    return rules_df[(rules_df["head"] == head) & (rules_df["body"] == body)].copy()


def rule_status(rules_df: pd.DataFrame, head: str, body: str) -> tuple[str, str, str, str]:
    found = exact_rule(rules_df, head, body)
    if found.empty:
        return "no encontrada", "", "", ""
    row = found.iloc[0]
    return (
        "ok",
        clean_text(row.get("confidence_label")),
        clean_text(row.get("preference_label")),
        clean_text(row.get("raw_rule")),
    )


def configured_tree_rows(config: dict[str, Any], rules_df: pd.DataFrame) -> pd.DataFrame:
    structure = config.get("laf1_rule_structure") or {}
    dimensions = structure.get("dimensions") or {}
    rows: list[dict[str, Any]] = []

    for dim_key, dim in dimensions.items():
        dim_atom = atom_part(dim_key)
        dim_label = clean_text(dim.get("label")) or dim_key

        for item in dim.get("aspects", []):
            rule = {"aspect": item} if isinstance(item, str) else dict(item or {})
            aspect = clean_text(rule.get("aspect"))
            if not aspect:
                continue
            asp_atom = atom_part(aspect)

            checks = [
                (
                    "evidencia -> aspecto",
                    aspect,
                    aspect,
                    f"{asp_atom}Bueno(X)",
                    f"resenaPositiva{cap_atom(aspect)}(X)",
                ),
                (
                    "evidencia negativa -> aspecto",
                    aspect,
                    aspect,
                    f"~{asp_atom}Bueno(X)",
                    f"resenaNegativa{cap_atom(aspect)}(X)",
                ),
                (
                    "aspecto -> dimension",
                    aspect,
                    dim_key,
                    f"{dim_atom}Bueno(X)",
                    f"{asp_atom}Bueno(X)",
                ),
                (
                    "aspecto negativo -> dimension",
                    aspect,
                    dim_key,
                    f"~{dim_atom}Bueno(X)",
                    f"~{asp_atom}Bueno(X)",
                ),
            ]

            for nivel, desde, hacia, head, body in checks:
                estado, conf, pref, raw = rule_status(rules_df, head, body)
                rows.append({
                    "estado": estado,
                    "nivel": nivel,
                    "dimension": dim_key,
                    "dimension_nombre": dim_label,
                    "aspecto": aspect,
                    "desde": desde,
                    "hacia": hacia,
                    "confianza": conf,
                    "preferencia": pref,
                    "regla": raw or f"{head} :- {body}.",
                })

        rec = dim.get("recommend") or {}
        if rec:
            head = "recomendar(X)"
            body = f"{dim_atom}Bueno(X)"
            estado, conf, pref, raw = rule_status(rules_df, head, body)
            rows.append({
                "estado": estado,
                "nivel": "dimension -> recomendar",
                "dimension": dim_key,
                "dimension_nombre": dim_label,
                "aspecto": "",
                "desde": dim_key,
                "hacia": "recomendar",
                "confianza": conf,
                "preferencia": pref,
                "regla": raw or f"{head} :- {body}.",
            })

        neg = dim.get("not_recommend") or {}
        if neg:
            head = "~recomendar(X)"
            body = f"~{dim_atom}Bueno(X)"
            estado, conf, pref, raw = rule_status(rules_df, head, body)
            rows.append({
                "estado": estado,
                "nivel": "dimension negativa -> no recomendar",
                "dimension": dim_key,
                "dimension_nombre": dim_label,
                "aspecto": "",
                "desde": f"~{dim_key}",
                "hacia": "~recomendar",
                "confianza": conf,
                "preferencia": pref,
                "regla": raw or f"{head} :- {body}.",
            })

    return pd.DataFrame(rows)


def rules_by_view(rules_df: pd.DataFrame) -> pd.DataFrame:
    if rules_df.empty:
        return rules_df
    df = rules_df.copy()
    df["vista"] = "otras"
    df.loc[df["section"].str.contains("HECHOS", case=False, na=False), "vista"] = "hechos"
    df.loc[df["section"].str.contains("AGREGACION", case=False, na=False), "vista"] = "evidencia -> aspecto"
    df.loc[df["section"].str.contains("INTERMEDIAS", case=False, na=False), "vista"] = "aspecto -> dimension"
    df.loc[
        df["section"].str.contains("RECOMENDACION", case=False, na=False)
        & df["body"].str.contains("Bueno\\(X\\)", case=False, na=False),
        "vista",
    ] = "dimension/aspecto -> recomendar"
    return df


def build_prompt(config: dict[str, Any], rules_df: pd.DataFrame) -> str:
    rules_payload = rules_df.to_dict(orient="records")
    payload = {
        "task": "Revisar reglas argumentativas LAF de un TFG.",
        "important_boundary": (
            "No revisar palabras del lexicon ni extraccion de reseñas. "
            "Revisar solo reglas argumentativas, pesos, soportes, ataques y operadores."
        ),
        "project_context": {
            "domain": config.get("display_name"),
            "quality_aspects": list((config.get("quality_aspects") or {}).keys()),
            "configured_laf1_structure": config.get("laf1_rule_structure", {}),
            "laf1_goal": "rankear productos usando evidencia agregada de reseñas por aspecto y polaridad",
            "laf2_goal": "rankear publicaciones comprables del producto elegido usando condiciones de compra estructuradas",
            "evidence_before_laf": (
                "Antes de LAF, Python consolida evidencias por producto, aspecto y polaridad. "
                "Las reglas LAF reciben esas etiquetas como hechos iniciales."
            ),
            "catalog_decision": (
                "El catalogo se muestra como ficha tecnica/contexto, pero no se integra como evidencia del arbol LAF principal."
            ),
            "main_strategy": "D = regularizacion mediante contraccion hacia media a priori neutral.",
        },
        "review_criteria": [
            "Verificar si el consecuente de la regla se sigue razonablemente del antecedente.",
            "Verificar si las reglas positivas y negativas son simetricas o si hay una asimetria justificable.",
            "Verificar si la etiqueta de confianza de la regla es defendible como confiabilidad estructural de la regla.",
            "Verificar que la segunda etiqueta de las reglas sea neutral (1.0): la preferencia debe provenir exclusivamente de los sliders del usuario.",
            "Verificar si hay reglas que mezclan indebidamente LAF 1 producto con LAF 2 publicacion.",
            "Verificar si los ataques con negacion fuerte (~) estan justificados.",
            "Verificar si faltan reglas necesarias para resolver conflictos o para propagar soporte.",
            (
                "Si LAF 1 queda demasiado plano con reglas aspectoBueno(X) -> recomendar(X), "
                "proponer una arquitectura jerarquica dominio-especifica: aspecto -> dimension intermedia -> recomendar. "
                "La propuesta debe indicar nombres de dimensiones, aspectos incluidos y ejemplos de reglas LAF con etiquetas."
            ),
            (
                "Para dominios nuevos, no copiar dimensiones de otro dominio: inferir dimensiones desde quality_aspects "
                "y desde el objetivo de recomendacion del dominio."
            ),
            "No proponer cambios automaticos de codigo: devolver sugerencias para revision experta.",
        ],
        "rules_to_review": rules_payload,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    texts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                texts.append(content["text"])
    if texts:
        return "\n".join(texts)
    raise RuntimeError("No se encontro JSON textual en la respuesta de OpenAI.")


def call_openai_review(prompt: str, model: str, timeout: int) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta OPENAI_API_KEY en .env.")
    if not model:
        raise RuntimeError("Falta OPENAI_MODEL en .env o en la pantalla.")

    body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "Sos un revisor metodologico de programas LAF. "
                    "Revisas reglas argumentativas, no lexicon ni reseñas. "
                    "Responde solo JSON valido segun el schema."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "laf_rule_review",
                "strict": True,
                "schema": REVIEW_SCHEMA,
            }
        },
    }

    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API devolvio HTTP {exc.code}: {detail}") from exc

    return json.loads(extract_response_text(data))


def parse_manual_json(raw: str) -> dict[str, Any]:
    text = clean_text(raw)
    if not text:
        return {"suggestions": [], "global_notes": []}
    data = json.loads(text)
    if isinstance(data, list):
        return {"suggestions": data, "global_notes": []}
    data.setdefault("suggestions", [])
    data.setdefault("global_notes", [])
    return data


def suggestions_to_df(payload: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for item in payload.get("suggestions", []):
        verdict = clean_text(item.get("verdict")) or "uncertain"
        if verdict not in VERDICTS:
            verdict = "uncertain"
        rows.append({
            "aceptar_revision": False,
            "decision_experta": "pendiente",
            "prioridad": "media",
            "rule_id": clean_text(item.get("rule_id")),
            "veredicto_llm": verdict,
            "tipo_problema": clean_text(item.get("issue_type")),
            "regla_actual": clean_text(item.get("current_rule")),
            "regla_propuesta": clean_text(item.get("proposed_rule")),
            "confianza_propuesta": clean_text(item.get("proposed_confidence")),
            "preferencia_propuesta": clean_text(item.get("proposed_preference")),
            "confianza_llm": item.get("confidence"),
            "motivo": clean_text(item.get("reason")),
        })

    return pd.DataFrame(
        rows,
        columns=[
            "aceptar_revision",
            "decision_experta",
            "prioridad",
            "rule_id",
            "veredicto_llm",
            "tipo_problema",
            "regla_actual",
            "regla_propuesta",
            "confianza_propuesta",
            "preferencia_propuesta",
            "confianza_llm",
            "motivo",
        ],
    )


def decision_editor(df: pd.DataFrame, key: str) -> pd.DataFrame:
    return st.data_editor(
        df,
        key=key,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "aceptar_revision": st.column_config.CheckboxColumn(
                "Registrar",
                help="Marca la fila para guardarla como decision experta relevante. No modifica codigo automaticamente.",
            ),
            "decision_experta": st.column_config.SelectboxColumn("Decision experta", options=EXPERT_DECISIONS),
            "prioridad": st.column_config.SelectboxColumn("Prioridad", options=PRIORITIES),
            "rule_id": st.column_config.TextColumn("Regla ID"),
            "veredicto_llm": st.column_config.SelectboxColumn("Veredicto LLM", options=VERDICTS),
            "tipo_problema": st.column_config.TextColumn("Tipo problema"),
            "regla_actual": st.column_config.TextColumn("Regla actual"),
            "regla_propuesta": st.column_config.TextColumn("Regla propuesta"),
            "confianza_propuesta": st.column_config.TextColumn("Confianza propuesta"),
            "preferencia_propuesta": st.column_config.TextColumn("Preferencia propuesta"),
            "confianza_llm": st.column_config.NumberColumn("Confianza LLM", format="%.2f"),
            "motivo": st.column_config.TextColumn("Motivo"),
        },
    )


def save_review_report(
    config: dict[str, Any],
    selected_files: list[Path],
    rules_df: pd.DataFrame,
    prompt: str,
    llm_payload: dict[str, Any],
    decisions: pd.DataFrame,
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = domain_artifact_dir(config, "reportes") / f"laf_rule_review_{timestamp}.json"
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "selected_files": [str(path.name) for path in selected_files],
        "rules_reviewed": rules_df.to_dict(orient="records"),
        "prompt": prompt,
        "llm_payload": llm_payload,
        "expert_decisions": decisions.to_dict(orient="records"),
    }
    save_json(path, payload)
    return path


def append_decision_register(report_path: Path, decisions: pd.DataFrame) -> Path:
    register_path = CONFIG_DIR / "laf_rule_review_decisions.json"
    if register_path.exists():
        register = load_json(register_path)
    else:
        register = {"decisions": []}

    accepted = decisions[decisions["aceptar_revision"] == True].copy()  # noqa: E712
    for row in accepted.to_dict(orient="records"):
        row["source_report"] = str(report_path)
        row["accepted_at"] = datetime.now().isoformat(timespec="seconds")
        register["decisions"].append(row)

    save_json(register_path, register)
    return register_path


def main() -> None:
    st.set_page_config(page_title="Revision reglas LAF", layout="wide")

    st.title("Revision experta de reglas argumentativas LAF")
    st.caption(
        "Esta pantalla revisa reglas tipo `head(X) :- body(X). {confianza; preferencia}`. "
        "No revisa lexicon ni terminos de reseñas."
    )

    files = program_options()
    if not files:
        st.error("No encontre programas LAF. Genera primero 06a_generate_test_program.py.")
        return

    with st.sidebar:
        domain_keys = sorted(
            path.stem
            for path in (CONFIG_DIR / "domains").glob("*.json")
            if "." not in path.stem
        )
        domain_key = st.selectbox("Categoria", options=domain_keys)
        config = load_domain_config_for_key(domain_key)
        st.header("Programas a revisar")
        default_names = default_program_names(files, config)
        option_map = {program_label(p): p for p in files}
        selected_names = st.multiselect(
            "Archivos",
            options=list(option_map),
            default=default_names,
        )
        include_facts = st.checkbox("Incluir hechos además de reglas", value=False)
        only_recommendation = st.checkbox("Solo reglas de recomendacion", value=False)
        max_rules = st.slider("Max reglas a enviar al LLM", 5, 120, 60, step=5)
        model = st.text_input("Modelo OpenAI", value=os.environ.get("OPENAI_MODEL", ""))
        timeout = st.slider("Timeout LLM segundos", 30, 300, 180, step=30)

    selected_files = [option_map[name] for name in selected_names if name in option_map]
    rules_df = load_rules(selected_files, include_facts=include_facts)
    if rules_df.empty:
        st.warning("No hay reglas para revisar con esos filtros.")
        return

    if only_recommendation:
        rules_df = rules_df[rules_df["section"].str.contains("RECOMENDACION", case=False, na=False)].copy()

    st.subheader("1. Reglas detectadas")
    c1, c2, c3 = st.columns(3)
    c1.metric("Programas", len(selected_files))
    c2.metric("Reglas/hechos", len(rules_df))
    c3.metric("Reglas LAF", int((rules_df["kind"] == "regla").sum()))

    tab_tree, tab_type, tab_raw = st.tabs(["Vista arbol", "Por tipo", "Tabla completa"])

    with tab_tree:
        tree_df = configured_tree_rows(config, rules_df)
        if tree_df.empty:
            st.info("Este dominio no tiene `laf1_rule_structure`; se muestra como programa plano.")
        else:
            missing_count = int((tree_df["estado"] != "ok").sum())
            if missing_count:
                st.warning(
                    f"Hay {missing_count} reglas esperadas del arbol que no aparecen en el programa seleccionado. "
                    "Probablemente estas revisando un LAF viejo o falta regenerar con 08."
                )
            else:
                st.success("El programa seleccionado contiene las reglas esperadas del arbol configurado.")
            st.dataframe(
                tree_df[[
                    "estado",
                    "nivel",
                    "dimension",
                    "aspecto",
                    "confianza",
                    "preferencia",
                    "regla",
                ]],
                width="stretch",
                hide_index=True,
            )

    with tab_type:
        typed_df = rules_by_view(rules_df)
        counts = typed_df["vista"].value_counts().rename_axis("tipo").reset_index(name="cantidad")
        st.dataframe(counts, width="stretch", hide_index=True)
        selected_view = st.selectbox("Ver tipo", options=list(counts["tipo"]))
        st.dataframe(
            typed_df[typed_df["vista"] == selected_view][[
                "rule_id",
                "section",
                "head",
                "body",
                "confidence_label",
                "preference_label",
                "raw_rule",
            ]],
            width="stretch",
            hide_index=True,
        )

    with tab_raw:
        st.dataframe(
            rules_df[[
                "rule_id",
                "program",
                "section",
                "kind",
                "head",
                "body",
                "confidence_label",
                "preference_label",
                "raw_rule",
            ]],
            width="stretch",
            hide_index=True,
        )

    st.info(
        "Que se revisa aqui: semantica de la regla, soporte/ataque, pesos, "
        "uso de preferencias y separacion LAF 1/LAF 2. No se revisa si `helado` "
        "debe ser sinonimo de enfriamiento; eso era lexicon."
    )

    prompt_df = rules_df.head(max_rules).copy()
    prompt = build_prompt(config, prompt_df)

    with st.expander("Prompt para el LLM"):
        st.text_area("Prompt", value=prompt, height=360)

    st.subheader("2. Sugerencias del LLM")
    llm_payload = st.session_state.get("laf_rule_llm_payload", {"suggestions": [], "global_notes": []})

    col_api, col_manual = st.columns(2)
    with col_api:
        api_ready = bool(os.environ.get("OPENAI_API_KEY") and model)
        if st.button("Pedir revision al LLM", disabled=not api_ready):
            try:
                with st.spinner("Revisando reglas LAF con LLM..."):
                    llm_payload = call_openai_review(prompt, model=model, timeout=int(timeout))
                st.session_state["laf_rule_llm_payload"] = llm_payload
                st.success(f"Sugerencias recibidas: {len(llm_payload.get('suggestions', []))}")
            except Exception as exc:
                st.error(f"No pude consultar el LLM: {exc}")
    with col_manual:
        pasted = st.text_area(
            "O pega JSON de revision",
            height=130,
            placeholder='{"suggestions": [...], "global_notes": [...]}',
        )
        if st.button("Cargar JSON pegado"):
            try:
                llm_payload = parse_manual_json(pasted)
                st.session_state["laf_rule_llm_payload"] = llm_payload
                st.success(f"Sugerencias cargadas: {len(llm_payload.get('suggestions', []))}")
            except Exception as exc:
                st.error(f"JSON invalido: {exc}")

    if llm_payload.get("global_notes"):
        st.info("Notas globales: " + " | ".join(str(x) for x in llm_payload["global_notes"]))

    suggestions_df = suggestions_to_df(llm_payload)
    if suggestions_df.empty:
        st.warning("Todavia no hay sugerencias. Puedes pedirlas al LLM o agregar filas manuales abajo.")

    st.subheader("3. Decision experta")
    st.caption(
        "Registrar una fila no modifica codigo automaticamente. Guarda una decision auditada "
        "para que luego ajustes 08/10 o justifiques mantener la regla."
    )
    st.info(
        "El LLM agrupa reglas repetidas por rangos de lineas. Una fila como `684-715` "
        "puede representar muchas reglas del mismo tipo, por eso es normal que aparezcan pocas filas."
    )
    with st.expander("Como decidir cada fila"):
        st.markdown(
            """
            - `pendiente`: todavia no decidiste; no la marques para registrar.
            - `aceptar`: estas de acuerdo y luego vas a modificar codigo/configuracion.
            - `editar`: aceptas la idea, pero con cambios o matices propios.
            - `rechazar`: no compartes la sugerencia del LLM.
            - `solo_anotar`: sirve para justificar en la memoria, pero no cambia el programa.

            La columna `Registrar` solo guarda la decision en la auditoria. No aplica cambios automaticos.
            """
        )
    st.info(
        "Orden practico: revisa `tipo_problema` y `motivo`, decide si cambia el programa "
        "o solo se documenta, y registra solo las filas que quieras conservar como decision experta."
    )
    decisions = decision_editor(
        suggestions_df,
        key=f"laf_rule_decisions_{'_'.join(selected_names)}_{len(rules_df)}",
    )

    st.subheader("4. Guardar revision")
    if st.button("Guardar revision LAF", type="primary"):
        report_path = save_review_report(config, selected_files, rules_df, prompt, llm_payload, decisions)
        register_path = append_decision_register(report_path, decisions)
        st.success("Revision guardada.")
        st.write(f"- Reporte: `{report_path}`")
        st.write(f"- Registro de decisiones: `{register_path}`")
        st.warning(
            "Si aceptaste cambios de LAF 1, compila con `06c_compile_rules.py`, "
            "regenera 06a y vuelve a revisar. Los cambios de LAF 2 se registran "
            "para actualizar su estructura compartida antes de congelar."
        )


if __name__ == "__main__":
    main()
