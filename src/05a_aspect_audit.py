"""
05a_aspect_audit.py - Auditoria reproducible de polaridad por aspecto.

Este script NO modifica Supabase. Lee ``review_aspects`` y:

1. agrupa las extracciones que nacieron del mismo segmento;
2. identifica segmentos multiaspecto con senales positivas y negativas;
3. agrega una muestra aleatoria deterministica de segmentos multiaspecto;
4. compara las predicciones con decisiones expertas, si existen;
5. guarda un snapshot JSON y un CSV auditable.

review_aspects
       ↓
Agrupar extracciones por fragmento
       ↓
Elegir una muestra reproducible
       ↓
Comparar con decisiones humanas
       ↓
Guardar before.json / after.json
       ↓
Comparar hechos y ranking proxy
       ↓
comparison.json

Uso:
    python src/05a_aspect_audit.py --phase before
    python src/05a_aspect_audit.py --phase after
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import random
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import create_client

from domain_config import artifact_path, load_domain_config
from product_scope import (
    ProductReviewPendingError,
    ProductReviewSetupError,
    require_included_product_ids,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
# La ruta explicita evita depender del directorio desde donde se ejecuta.
load_dotenv(REPO_ROOT / ".env")

DEFAULT_SAMPLE_SIZE = 40
DEFAULT_SEED = 20260730
PAGE_SIZE = 1000

# Estos valores se completan dentro de ``initialize_runtime``. Mantener la
# importacion libre de credenciales y archivos permite probar la logica pura.
SUPABASE_URL = ""
SUPABASE_KEY = ""
DATASET_KEY = ""
DOMAIN: dict[str, Any] = {}
DECISIONS_PATH: Path | None = None
REPORT_DIR: Path | None = None


def positive_int(value: str) -> int:
    """Valida argumentos de CLI que deben ser enteros mayores que cero."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("debe ser mayor que cero")
    return parsed


def load_settings(dataset_key: str | None = None) -> tuple[str, str, str]:
    """Lee y valida las variables necesarias al comenzar la ejecucion real."""
    resolved_dataset_key = str(dataset_key or os.environ.get("DATASET_KEY") or "").strip()
    missing = [
        name
        for name, value in (
            ("SUPABASE_URL", os.environ.get("SUPABASE_URL")),
            ("SUPABASE_KEY", os.environ.get("SUPABASE_KEY")),
            ("DATASET_KEY", resolved_dataset_key),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Faltan variables de entorno: " + ", ".join(missing)
        )
    return (
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"],
        resolved_dataset_key,
    )


def initialize_runtime(
    domain: dict[str, Any] | None = None,
    dataset_key: str | None = None,
) -> None:
    """Configura credenciales, dominio y rutas sin efectos al importar."""
    global SUPABASE_URL, SUPABASE_KEY, DATASET_KEY
    global DOMAIN, DECISIONS_PATH, REPORT_DIR

    SUPABASE_URL, SUPABASE_KEY, DATASET_KEY = load_settings(dataset_key)
    os.environ["DATASET_KEY"] = DATASET_KEY
    DOMAIN = domain or load_domain_config()
    domain_key = str(DOMAIN.get("domain_key") or "").strip()
    if not domain_key:
        raise RuntimeError("El perfil activo no contiene domain_key.")

    DECISIONS_PATH = (
        REPO_ROOT
        / "config"
        / f"aspect_polarity_audit_decisions_{domain_key}.json"
    )
    REPORT_DIR = (
        Path(artifact_path("aspect_polarity_audit", ".json", DOMAIN)).parent
        / "aspect_polarity_audit"
    )


def require_runtime_paths() -> tuple[Path, Path]:
    """Devuelve rutas inicializadas o detecta un uso prematuro del modulo."""
    if DECISIONS_PATH is None or REPORT_DIR is None:
        raise RuntimeError(
            "La auditoria no esta inicializada. Ejecuta initialize_runtime()."
        )
    return DECISIONS_PATH, REPORT_DIR


def load_extractor_module():
    """Carga e inicializa 05_aspects.py aunque su nombre comience con numero."""
    module_path = REPO_ROOT / "src" / "05_aspects.py"
    spec = importlib.util.spec_from_file_location("aspect_extractor_05", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Se reutiliza exactamente el dominio de esta auditoria para impedir que
    # extractor y reporte trabajen con lexicones distintos.
    module.initialize_analysis(domain=DOMAIN)
    return module


def fetch_all(page_loader, page_size: int = PAGE_SIZE) -> list[dict[str, Any]]:
    """Pagina por cursor ``id`` usando una consulta nueva en cada vuelta."""
    rows: list[dict[str, Any]] = []
    last_id = 0
    while True:
        page = page_loader(last_id, page_size)
        if not page:
            break
        rows.extend(page)
        if len(page) < page_size:
            break
        last_id = int(page[-1]["id"])
    return rows


def stable_group_id(review_id: Any, product_id: str, excerpt: str) -> str:
    """Crea un identificador reproducible sin guardar el texto en la clave."""
    digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()[:12]
    return f"{review_id}|{product_id}|{digest}"


def effective_signals_from_doc(extractor, doc) -> list[dict[str, Any]]:
    """Obtiene las senales efectivas desde un Doc ya procesado por spaCy."""
    signals: list[dict[str, Any]] = []
    for sent in doc.sents:
        if hasattr(extractor, "resolve_polarity_matches"):
            matches, _negation_applied = extractor.resolve_polarity_matches(sent)
        else:
            matches = extractor.find_polarity_matches(sent)
            neg_positions = extractor.find_negation_positions(sent)
        for match in matches:
            polarity = match["polarity"]
            position = int(match["position"])
            if (
                not hasattr(extractor, "resolve_polarity_matches")
                and not match.get("locked")
                and extractor.is_negated(position, neg_positions)
            ):
                polarity = "neg" if polarity == "pos" else "pos"
            token = sent[position].text if position < len(sent) else ""
            signals.append(
                {
                    "polarity": polarity,
                    "position": position,
                    "token": token,
                }
            )
    return signals


def effective_signals(extractor, excerpt: str) -> list[dict[str, Any]]:
    """API individual usada para inspecciones puntuales y compatibilidad."""
    pipeline = extractor.require_analysis_ready()
    return effective_signals_from_doc(extractor, pipeline(excerpt))


def reevaluate_selected_sources(extractor, selected):
    """Reevalua la cohorte fija procesando cada texto una sola vez con spaCy."""
    reevaluated = []
    pipeline = extractor.require_analysis_ready()
    excerpts = [str(source.get("excerpt") or "") for source in selected]
    docs = pipeline.pipe(excerpts, batch_size=extractor.NLP_PIPE_BATCH_SIZE)
    for source, doc in zip(selected, docs):
        predictions: dict[str, list[str]] = defaultdict(list)
        for extraction in extractor.process_doc(doc):
            aspect = str(extraction["aspect"])
            polarity = str(extraction["polarity"])
            if polarity not in predictions[aspect]:
                predictions[aspect].append(polarity)
        group = dict(source)
        group["current_predictions"] = {
            aspect: sorted(values)
            for aspect, values in sorted(predictions.items())
        }
        # La union hace visibles aspectos nuevos que no existian en ``before``.
        group["aspects"] = sorted(
            set(group.get("aspects", [])) | set(predictions)
        )
        group["signals"] = effective_signals_from_doc(extractor, doc)
        reevaluated.append(group)
    return reevaluated


def fixed_audit_cohort(extractor):
    """Carga el conjunto seleccionado en la linea base para comparar igual."""
    _decisions_path, report_dir = require_runtime_paths()
    before_path = report_dir / "before.json"
    if not before_path.exists():
        return None
    with before_path.open(encoding="utf-8") as handle:
        before = json.load(handle)
    selected = before.get("selected_groups") or []
    if not selected:
        return None
    return reevaluate_selected_sources(extractor, selected)


def group_current_rows(rows: list[dict[str, Any]], extractor):
    """Agrupa extracciones del mismo segmento y recalcula sus senales."""
    grouped: dict[tuple[Any, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row["review_id"],
            row["product_id"],
            str(row.get("sentence_excerpt") or "").strip(),
        )
        grouped[key].append(row)

    group_sources = list(grouped.items())
    pipeline = extractor.require_analysis_ready()
    docs = pipeline.pipe(
        (key[2] for key, _members in group_sources),
        batch_size=extractor.NLP_PIPE_BATCH_SIZE,
    )
    groups = []
    for ((review_id, product_id, excerpt), members), doc in zip(
        group_sources,
        docs,
    ):
        predictions: dict[str, list[str]] = defaultdict(list)
        for row in members:
            polarity = str(row["polarity"])
            if polarity not in predictions[str(row["aspect"])]:
                predictions[str(row["aspect"])].append(polarity)

        aspects = sorted(predictions)
        signals = effective_signals_from_doc(extractor, doc)
        signal_polarities = sorted({signal["polarity"] for signal in signals})
        groups.append(
            {
                "group_id": stable_group_id(review_id, product_id, excerpt),
                "review_id": review_id,
                "product_id": product_id,
                "excerpt": excerpt,
                "aspects": aspects,
                "current_predictions": {
                    aspect: sorted(values)
                    for aspect, values in sorted(predictions.items())
                },
                "signals": signals,
                "is_multi_aspect": len(aspects) > 1,
                "is_mixed_signal_candidate": (
                    len(aspects) > 1
                    and "pos" in signal_polarities
                    and "neg" in signal_polarities
                ),
            }
        )
    return sorted(groups, key=lambda g: (str(g["review_id"]), g["excerpt"]))


def choose_audit_groups(groups, sample_size: int, seed: int):
    """Incluye todos los casos mixtos y suma una muestra reproducible."""
    mixed = [group for group in groups if group["is_mixed_signal_candidate"]]
    remaining = [
        group
        for group in groups
        if group["is_multi_aspect"] and not group["is_mixed_signal_candidate"]
    ]
    rng = random.Random(seed)
    sampled = rng.sample(remaining, min(sample_size, len(remaining)))
    selected = mixed + sampled
    selected_ids = {group["group_id"] for group in mixed}
    for group in selected:
        group["selection_reason"] = (
            "mixed_signals"
            if group["group_id"] in selected_ids
            else f"random_multi_aspect_seed_{seed}"
        )
    return sorted(
        selected,
        key=lambda g: (
            0 if g["selection_reason"] == "mixed_signals" else 1,
            str(g["review_id"]),
            g["excerpt"],
        ),
    )


def load_decisions() -> dict[str, Any]:
    """Carga etiquetas humanas indexadas por el identificador del segmento."""
    decisions_path, _report_dir = require_runtime_paths()
    if not decisions_path.exists():
        return {}
    with decisions_path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return {
        str(item["group_id"]): item
        for item in raw.get("decisions", [])
        if item.get("group_id")
    }


def normalized_prediction(values: list[str] | str | None) -> list[str]:
    """Normaliza etiquetas simples o multiples para compararlas como conjuntos."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    return sorted({str(value) for value in values})


def evaluate_decisions(selected, decisions):
    """Compara predicciones con etiquetas expertas sin ocultar falsos positivos."""
    aspect_rows = []
    groups_reviewed = 0
    groups_ambiguous = 0
    groups_labeled = 0
    groups_exact = 0
    for group in selected:
        decision = decisions.get(group["group_id"])
        decision_status = str(
            (decision or {}).get("decision_status") or "unreviewed"
        )
        ambiguous_aspects = {
            str(aspect)
            for aspect in (decision or {}).get("ambiguous_aspects", [])
        }
        if decision_status != "unreviewed":
            groups_reviewed += 1
        if decision_status == "ambiguous":
            groups_ambiguous += 1
        expected = (decision or {}).get("expected", {})
        use_for_metrics = decision_status == "included" and bool(expected)
        # Se evalua la union completa. Si la version nueva inventa un aspecto
        # que el experto no esperaba, queda registrado como falso positivo.
        evaluated_aspects = sorted(
            set(group.get("aspects", []))
            | set(group.get("current_predictions", {}))
            | set(expected)
        )
        comparable_aspects = [
            aspect
            for aspect in evaluated_aspects
            if aspect not in ambiguous_aspects
        ]
        group_exact = use_for_metrics and bool(comparable_aspects)
        if group_exact:
            groups_labeled += 1
        for aspect in evaluated_aspects:
            predicted = normalized_prediction(
                group["current_predictions"].get(aspect)
            )
            expected_polarity = normalized_prediction(expected.get(aspect))
            is_labeled = (
                use_for_metrics
                and aspect not in ambiguous_aspects
                and bool(predicted or expected_polarity)
            )
            is_correct = is_labeled and predicted == expected_polarity
            if group_exact and is_labeled and not is_correct:
                group_exact = False
            aspect_rows.append(
                {
                    **group,
                    "aspect": aspect,
                    "predicted": ",".join(predicted),
                    "expected": ",".join(expected_polarity),
                    "is_labeled": is_labeled,
                    "is_correct": is_correct if is_labeled else None,
                    "decision_status": (
                        "ambiguous_aspect"
                        if aspect in ambiguous_aspects
                        else decision_status
                    ),
                    "expert_note": (decision or {}).get("note", ""),
                }
            )
        if group_exact:
            groups_exact += 1

    labeled_aspects = [row for row in aspect_rows if row["is_labeled"]]
    correct_aspects = [row for row in labeled_aspects if row["is_correct"]]
    return aspect_rows, {
        "groups_reviewed": groups_reviewed,
        "groups_ambiguous": groups_ambiguous,
        "groups_labeled": groups_labeled,
        "groups_exact": groups_exact,
        "group_exact_accuracy": (
            groups_exact / groups_labeled if groups_labeled else None
        ),
        "aspects_labeled": len(labeled_aspects),
        "aspects_correct": len(correct_aspects),
        "aspect_accuracy": (
            len(correct_aspects) / len(labeled_aspects)
            if labeled_aspects
            else None
        ),
    }


def fact_snapshot(sb, included_product_ids):
    """Captura los hechos downstream usando cursor estable sobre ``id``."""
    def load_page(last_id, page_size):
        """Solicita una pagina de hechos posterior al ultimo id recibido."""
        return (
            sb.table("product_aspect_trust")
            .select(
                "id,product_id,aspect,polarity,strategy,agg_confidence,"
                "evidence_weight,total_evidence_weight,belief_mass,uncertainty,"
                "n_reviews,n_mentions,coverage_ratio,from_catalog"
            )
            .eq("dataset_key", DATASET_KEY)
            .in_("product_id", sorted(included_product_ids))
            .gt("id", last_id)
            .order("id")
            .limit(page_size)
            .execute()
            .data
        )

    return fetch_all(load_page)


def fact_key(row):
    """Define la identidad conceptual de un hecho entre ejecuciones."""
    return (
        str(row["strategy"]),
        str(row["product_id"]),
        str(row["aspect"]),
        str(row["polarity"]),
    )


def compare_facts(before_rows, after_rows):
    """Calcula altas, bajas y cambios de confianza por estrategia."""
    before = {fact_key(row): row for row in before_rows}
    after = {fact_key(row): row for row in after_rows}
    changes = []
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        if old is None:
            change_type = "added"
        elif new is None:
            change_type = "removed"
        else:
            comparable = (
                "agg_confidence",
                "evidence_weight",
                "total_evidence_weight",
                "belief_mass",
                "uncertainty",
                "n_reviews",
                "n_mentions",
                "coverage_ratio",
                "from_catalog",
            )
            if all(old.get(field) == new.get(field) for field in comparable):
                continue
            change_type = "changed"
        changes.append(
            {
                "change_type": change_type,
                "strategy": key[0],
                "product_id": key[1],
                "aspect": key[2],
                "polarity": key[3],
                "before_confidence": (
                    old.get("agg_confidence") if old else None
                ),
                "after_confidence": (
                    new.get("agg_confidence") if new else None
                ),
                "confidence_delta": (
                    round(
                        float(new.get("agg_confidence"))
                        - float(old.get("agg_confidence")),
                        6,
                    )
                    if old
                    and new
                    and old.get("agg_confidence") is not None
                    and new.get("agg_confidence") is not None
                    else None
                ),
                "before_uncertainty": old.get("uncertainty") if old else None,
                "after_uncertainty": new.get("uncertainty") if new else None,
                "uncertainty_delta": (
                    round(
                        float(new.get("uncertainty"))
                        - float(old.get("uncertainty")),
                        6,
                    )
                    if old
                    and new
                    and old.get("uncertainty") is not None
                    and new.get("uncertainty") is not None
                    else None
                ),
                "before_n_reviews": old.get("n_reviews") if old else None,
                "after_n_reviews": new.get("n_reviews") if new else None,
                "before_n_mentions": old.get("n_mentions") if old else None,
                "after_n_mentions": new.get("n_mentions") if new else None,
            }
        )

    by_strategy = {}
    strategies = sorted(
        {
            str(row["strategy"])
            for row in [*before_rows, *after_rows]
        }
    )
    for strategy in strategies:
        strategy_changes = [
            change for change in changes if change["strategy"] == strategy
        ]
        numeric_deltas = [
            abs(float(change["confidence_delta"]))
            for change in strategy_changes
            if change["confidence_delta"] is not None
        ]
        by_strategy[strategy] = {
            "facts_before": sum(
                1 for row in before_rows if row["strategy"] == strategy
            ),
            "facts_after": sum(
                1 for row in after_rows if row["strategy"] == strategy
            ),
            "added": sum(
                change["change_type"] == "added"
                for change in strategy_changes
            ),
            "removed": sum(
                change["change_type"] == "removed"
                for change in strategy_changes
            ),
            "changed": sum(
                change["change_type"] == "changed"
                for change in strategy_changes
            ),
            "mean_absolute_confidence_delta": (
                round(statistics.fmean(numeric_deltas), 6)
                if numeric_deltas
                else 0
            ),
            "median_absolute_confidence_delta": (
                round(statistics.median(numeric_deltas), 6)
                if numeric_deltas
                else 0
            ),
            "max_absolute_confidence_delta": (
                round(max(numeric_deltas), 6) if numeric_deltas else 0
            ),
            "confidence_changes_over_0_01": sum(
                delta > 0.01 for delta in numeric_deltas
            ),
            "confidence_changes_over_0_05": sum(
                delta > 0.05 for delta in numeric_deltas
            ),
        }
    return changes, by_strategy


def evidence_proxy_ranking(facts, preferences, product_names):
    """Ranking de sensibilidad; no sustituye la evaluacion algebraica LAF."""
    denominator = sum(float(value) for value in preferences.values()) or 1.0
    values = defaultdict(lambda: defaultdict(dict))
    for row in facts:
        if row["strategy"] != "D":
            continue
        values[str(row["product_id"])][str(row["aspect"])][
            str(row["polarity"])
        ] = float(row.get("agg_confidence") or 0)

    ranking = []
    # Todos los productos incluidos participan. Si uno no tiene hechos D,
    # recibe cero en lugar de desaparecer silenciosamente del ranking.
    for product_id in sorted(product_names):
        aspects = values.get(product_id, {})
        numerator = 0.0
        for aspect, preference in preferences.items():
            polarities = aspects.get(aspect, {})
            numerator += float(preference) * (
                polarities.get("pos", 0.0)
                - polarities.get("neg", 0.0)
            )
        ranking.append(
            {
                "product_id": product_id,
                "product_name": product_names.get(product_id, product_id),
                "proxy_score": round(numerator / denominator, 6),
            }
        )
    ranking.sort(key=lambda row: (-row["proxy_score"], row["product_id"]))
    for position, row in enumerate(ranking, start=1):
        row["position"] = position
    return ranking


def compare_rankings(before_facts, after_facts, product_names):
    """Compara el proxy con las mismas preferencias en ambas fases."""
    preferences = load_preferences()
    before = evidence_proxy_ranking(
        before_facts, preferences, product_names
    )
    after = evidence_proxy_ranking(after_facts, preferences, product_names)
    before_map = {row["product_id"]: row for row in before}
    after_map = {row["product_id"]: row for row in after}
    comparison = []
    for product_id in sorted(set(before_map) | set(after_map)):
        old = before_map.get(product_id, {})
        new = after_map.get(product_id, {})
        comparison.append(
            {
                "product_id": product_id,
                "product_name": product_names.get(product_id, product_id),
                "before_position": old.get("position"),
                "after_position": new.get("position"),
                "position_delta": (
                    old["position"] - new["position"]
                    if old.get("position") and new.get("position")
                    else None
                ),
                "before_score": old.get("proxy_score"),
                "after_score": new.get("proxy_score"),
                "score_delta": (
                    round(new["proxy_score"] - old["proxy_score"], 6)
                    if old.get("proxy_score") is not None
                    and new.get("proxy_score") is not None
                    else None
                ),
            }
        )
    comparison.sort(
        key=lambda row: (
            row["after_position"]
            if row["after_position"] is not None
            else 10**6
        )
    )
    return {
        "warning": (
            "Proxy de sensibilidad basado en la diferencia ponderada entre "
            "hechos positivos y negativos de la estrategia D. No es el "
            "ranking final LAF ni debe presentarse como tal."
        ),
        "before": before,
        "after": after,
        "comparison": comparison,
        "top_5_unchanged": (
            [row["product_id"] for row in before[:5]]
            == [row["product_id"] for row in after[:5]]
        ),
        "max_absolute_position_change": max(
            (
                abs(row["position_delta"])
                for row in comparison
                if row["position_delta"] is not None
            ),
            default=0,
        ),
    }


def fetch_product_names(sb, included_product_ids):
    """Carga nombres por cursor para que la paginacion sea determinista."""
    def load_page(last_id, page_size):
        """Solicita una pagina de productos posterior al ultimo id recibido."""
        return (
            sb.table("products_raw")
            .select("id,product_id,name,family_name")
            .eq("dataset_key", DATASET_KEY)
            .in_("product_id", sorted(included_product_ids))
            .gt("id", last_id)
            .order("id")
            .limit(page_size)
            .execute()
            .data
        )

    return {
        str(row["product_id"]): str(
            row.get("name") or row.get("family_name") or row["product_id"]
        )
        for row in fetch_all(load_page)
    }


def delta_number(after_value, before_value):
    """Calcula un delta conservando una unica convencion after - before."""
    return after_value - before_value


def stable_json_hash(value: Any) -> str:
    """Calcula una huella reproducible de cualquier estructura JSON."""
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_preferences() -> dict[str, Any]:
    """Carga las preferencias usadas por el proxy de sensibilidad."""
    path = Path(artifact_path("prefs_laf1", ".json", DOMAIN))
    with path.open(encoding="utf-8") as handle:
        preferences = json.load(handle)
    if not isinstance(preferences, dict):
        raise RuntimeError(f"{path} debe contener un objeto JSON.")
    return preferences


def build_run_signature(included_product_ids) -> dict[str, Any]:
    """Registra el contexto que debe permanecer igual entre before y after."""
    products = sorted(str(value) for value in included_product_ids)
    return {
        "dataset_key": DATASET_KEY,
        "domain_key": DOMAIN["domain_key"],
        "included_products_hash": stable_json_hash(products),
        "preferences_hash": stable_json_hash(load_preferences()),
    }


def validate_comparable_reports(before_report, after_report) -> None:
    """Impide comparar snapshots creados con contextos incompatibles."""
    before_signature = before_report.get("run_signature")
    after_signature = after_report.get("run_signature")
    if not isinstance(before_signature, dict):
        raise RuntimeError(
            "before.json no tiene firma verificable. Vuelve a ejecutar la "
            "fase --phase before con esta version del script."
        )
    if before_signature != after_signature:
        differing = sorted(
            key
            for key in set(before_signature) | set(after_signature or {})
            if before_signature.get(key) != (after_signature or {}).get(key)
        )
        raise RuntimeError(
            "Las fases before y after no son comparables; difieren en: "
            + ", ".join(differing)
        )


def optional_delta(after_value, before_value):
    """Devuelve None si alguna metrica todavia no puede calcularse."""
    if after_value is None or before_value is None:
        return None
    return round(float(after_value) - float(before_value), 6)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Guarda JSON sin exponer un archivo final escrito parcialmente."""
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
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def write_comparison_report(
    before_report,
    after_report,
    decisions,
    product_names,
):
    """Construye y guarda el informe metodologico entre ambas fases."""
    validate_comparable_reports(before_report, after_report)
    _before_rows, before_evaluation = evaluate_decisions(
        before_report["selected_groups"], decisions
    )
    changes, by_strategy = compare_facts(
        before_report.get("facts", []),
        after_report.get("facts", []),
    )
    before_metrics = before_report["metrics"]
    after_metrics = after_report["metrics"]
    comparison = {
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "dataset_key": DATASET_KEY,
        "domain_key": DOMAIN["domain_key"],
        "audit_provenance_status": (
            "provisional_ai_assisted_pending_author_confirmation"
        ),
        "extractions": {
            "before": before_metrics,
            "after": after_metrics,
            "deltas": {
                "extraction_rows": delta_number(
                    after_metrics["extraction_rows"],
                    before_metrics["extraction_rows"],
                ),
                "unique_segment_groups": delta_number(
                    after_metrics["unique_segment_groups"],
                    before_metrics["unique_segment_groups"],
                ),
                "multi_aspect_groups": delta_number(
                    after_metrics["multi_aspect_groups"],
                    before_metrics["multi_aspect_groups"],
                ),
                "mixed_signal_candidates": delta_number(
                    after_metrics["mixed_signal_candidates"],
                    before_metrics["mixed_signal_candidates"],
                ),
                "polarity_counts": {
                    polarity: delta_number(
                        after_metrics["polarity_counts"].get(polarity, 0),
                        before_metrics["polarity_counts"].get(polarity, 0),
                    )
                    for polarity in ("pos", "neg", "neu")
                },
            },
        },
        "manual_audit": {
            "before": before_evaluation,
            "after": after_report["manual_evaluation"],
            "aspect_accuracy_delta": optional_delta(
                after_report["manual_evaluation"]["aspect_accuracy"],
                before_evaluation["aspect_accuracy"],
            ),
        },
        "facts": {
            "by_strategy": by_strategy,
            "changes": changes,
        },
        "ranking_sensitivity": compare_rankings(
            before_report.get("facts", []),
            after_report.get("facts", []),
            product_names,
        ),
        "limitations": [
            "Las etiquetas fueron preauditadas por IA y requieren confirmacion de la autora para constituir gold standard humano.",
            "El ranking de sensibilidad no ejecuta la algebra LAF completa; solo comprueba estabilidad downstream de los hechos.",
            "La evaluacion conserva casos ambiguos fuera del denominador y documenta su exclusion.",
        ],
    }
    _decisions_path, report_dir = require_runtime_paths()
    path = report_dir / "comparison.json"
    write_json_atomic(path, comparison)
    return path, comparison


def summary_metrics(groups, rows):
    """Resume volumen, multiaspecto y distribucion de la extraccion."""
    polarity_counts = Counter(str(row["polarity"]) for row in rows)
    aspect_counts = Counter(str(row["aspect"]) for row in rows)
    multi = [group for group in groups if group["is_multi_aspect"]]
    mixed = [group for group in groups if group["is_mixed_signal_candidate"]]
    return {
        "extraction_rows": len(rows),
        "unique_segment_groups": len(groups),
        "multi_aspect_groups": len(multi),
        "multi_aspect_share": len(multi) / len(groups) if groups else 0,
        "mixed_signal_candidates": len(mixed),
        "mixed_share_all_groups": len(mixed) / len(groups) if groups else 0,
        "mixed_share_multi_aspect": len(mixed) / len(multi) if multi else 0,
        "polarity_counts": dict(sorted(polarity_counts.items())),
        "aspect_counts": dict(sorted(aspect_counts.items())),
    }


def write_csv(path: Path, aspect_rows):
    """Guarda el detalle tabular de forma atomica y compatible con Excel."""
    columns = [
        "group_id",
        "selection_reason",
        "review_id",
        "product_id",
        "excerpt",
        "aspect",
        "predicted",
        "expected",
        "is_labeled",
        "is_correct",
        "decision_status",
        "expert_note",
        "signals",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in aspect_rows:
                writer.writerow(
                    {
                        **{column: row.get(column, "") for column in columns},
                        "signals": json.dumps(
                            row.get("signals", []), ensure_ascii=False
                        ),
                    }
                )
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main():
    """Ejecuta una fase reproducible y genera sus artefactos auditables."""
    parser = argparse.ArgumentParser(
        description="Audita polaridad por aspecto antes o despues de un cambio.",
    )
    parser.add_argument("--phase", required=True, choices=["before", "after"])
    parser.add_argument(
        "--dataset-key",
        default=os.environ.get("DATASET_KEY"),
        help="Dataset a auditar. Si se omite, usa DATASET_KEY de .env.",
    )
    parser.add_argument(
        "--sample-size",
        type=positive_int,
        default=DEFAULT_SAMPLE_SIZE,
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    initialize_runtime(dataset_key=args.dataset_key)
    extractor = load_extractor_module()
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    included_product_ids = require_included_product_ids(
        sb,
        DATASET_KEY,
        stage_name="05a_aspect_audit.py",
    )

    def load_aspect_page(last_id, page_size):
        """Construye una consulta nueva para la siguiente pagina del cursor."""
        return (
            sb.table("review_aspects")
            .select(
                "id,review_id,product_id,aspect,polarity,"
                "extraction_confidence,sentence_excerpt"
            )
            .eq("dataset_key", DATASET_KEY)
            .in_("product_id", sorted(included_product_ids))
            .gt("id", last_id)
            .order("id")
            .limit(page_size)
            .execute()
            .data
        )

    rows = fetch_all(load_aspect_page)
    groups = group_current_rows(rows, extractor)
    if args.phase == "after":
        selected = fixed_audit_cohort(extractor)
        if selected is None:
            raise RuntimeError(
                "No existe una cohorte before verificable. Ejecuta primero "
                "05a_aspect_audit.py --phase before."
            )
    else:
        selected = choose_audit_groups(groups, args.sample_size, args.seed)
    decisions = load_decisions()
    aspect_rows, evaluation = evaluate_decisions(selected, decisions)
    facts = fact_snapshot(sb, included_product_ids)
    product_names = fetch_product_names(sb, included_product_ids)

    decisions_path, report_dir = require_runtime_paths()
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{args.phase}.json"
    csv_path = report_dir / f"{args.phase}_audit.csv"
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "phase": args.phase,
        "dataset_key": DATASET_KEY,
        "domain_key": DOMAIN["domain_key"],
        "included_products": len(included_product_ids),
        "run_signature": build_run_signature(included_product_ids),
        "selection": {
            "random_seed": args.seed,
            "random_sample_size": args.sample_size,
            "selected_groups": len(selected),
        },
        "metrics": summary_metrics(groups, rows),
        "manual_evaluation": evaluation,
        "decisions_file": str(decisions_path.relative_to(REPO_ROOT)),
        "selected_groups": selected,
        "facts": facts,
    }

    # Una fase ``after`` incompatible no debe sobrescribir un snapshot valido.
    before_report = None
    before_path = report_dir / "before.json"
    if args.phase == "after" and before_path.exists():
        with before_path.open(encoding="utf-8") as handle:
            before_report = json.load(handle)
        validate_comparable_reports(before_report, report)

    write_json_atomic(report_path, report)
    write_csv(csv_path, aspect_rows)
    comparison_path = None
    comparison = None
    if before_report is not None:
        comparison_path, comparison = write_comparison_report(
            before_report,
            report,
            decisions,
            product_names,
        )

    print(f"Fase: {args.phase}")
    print(f"Extracciones: {report['metrics']['extraction_rows']}")
    print(f"Grupos de segmento: {report['metrics']['unique_segment_groups']}")
    print(f"Grupos multiaspecto: {report['metrics']['multi_aspect_groups']}")
    print(
        "Candidatos mixtos: "
        f"{report['metrics']['mixed_signal_candidates']}"
    )
    print(f"Grupos seleccionados para auditoria: {len(selected)}")
    if evaluation["groups_labeled"]:
        print(
            "Exactitud por aspecto etiquetado: "
            f"{evaluation['aspects_correct']}/{evaluation['aspects_labeled']} "
            f"({evaluation['aspect_accuracy']:.1%})"
        )
    else:
        print(f"Sin decisiones expertas en {decisions_path}")
    print(f"Reporte: {report_path}")
    print(f"CSV:     {csv_path}")
    if comparison_path:
        print(f"Comparacion: {comparison_path}")
        ranking = comparison["ranking_sensitivity"]
        print(
            "Proxy ranking: top-5 "
            f"{'estable' if ranking['top_5_unchanged'] else 'con cambios'}; "
            "maximo movimiento "
            f"{ranking['max_absolute_position_change']} posiciones"
        )


if __name__ == "__main__":
    try:
        main()
    except (ProductReviewSetupError, ProductReviewPendingError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
