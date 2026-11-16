"""06_trust.py - Confianza por resena y evidencia agregada por aspecto.

El script produce dos salidas:

1. ``review_trust``: confiabilidad individual de cada resena limpia.
2. ``product_aspect_trust``: fuerza de cada postura positiva o negativa para
   un producto y un aspecto. A, B, D y E son alternativas comparables basadas
   en resenas; C es un experimento separado que conserva datos de catalogo.

La polaridad no forma parte del trust individual. Una critica negativa puede
ser tan confiable como una opinion positiva. La confianza de extraccion de 05
solo interviene despues, al ponderar la evidencia de cada aspecto.

Estrategias de agregacion:

* A: proporcion ponderada por trust, penalizada por bajo volumen logaritmico.
* B: proporcion ponderada, emitida solo si la postura alcanza MIN_REVIEWS.
* C: proporcion ponderada; usa catalogo positivo solo si el aspecto no tiene
  ninguna evidencia de resenas.
* D: proporcion ponderada regularizada hacia un prior simetrico. Es la
  estrategia principal recomendada para el TFG.
* E: proporcion ponderada sin contraccion; conserva cobertura explicita.

Para D tambien se guarda la descomposicion que explica la proyeccion:
``evidence_weight`` contiene la evidencia de la postura, ``belief_mass`` la
parte de esa evidencia en el total regularizado y ``uncertainty`` la parte que
todavia corresponde al prior. Se mantiene ``agg_confidence`` como salida para
LAF, de modo que esta ampliacion agrega trazabilidad sin cambiar el ranking.

A, B, D y E forman el analisis de sensibilidad; C se publica en la misma
generacion solo para conservar trazabilidad, pero se analiza por separado.
Estas estrategias construyen etiquetas iniciales del proyecto: no son formulas
propuestas por Budan ni modifican los operadores LAF. Los resultados se crean
primero en staging y se activan con una unica transaccion PostgreSQL, de modo
que un fallo no deje tablas parciales.

Reseña limpia
   ↓
Trust individual
   ↓
Trust × confianza de extracción
   ↓
Evidencia positiva/negativa por aspecto
   ↓
Estrategias A–E
   ↓
Publicación segura en Supabase

Uso:
    python src/06_trust.py --strategy D
    python src/06_trust.py --strategy all
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx
from dotenv import load_dotenv
from postgrest.exceptions import APIError
from supabase import create_client

from domain_config import load_domain_config
from product_scope import (
    ProductReviewPendingError,
    ProductReviewSetupError,
    require_included_product_ids,
)


# ---------------------------------------------------------------------------
# Configuracion metodologica y operativa
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

STRATEGIES = ("A", "B", "C", "D", "E")
# D es la decision metodologica principal; ``all`` es el modo operativo que
# garantiza que las alternativas se calculen sobre la misma corrida.
PRIMARY_STRATEGY = "D"
DEFAULT_STRATEGY = "all"

# Parametros de las estrategias. Se mantienen visibles para que el analisis de
# sensibilidad pueda declarar exactamente que valores se compararon.
LOG_REF = 200
MIN_REVIEWS = 15
CATALOG_CONF = 0.90
PRIOR_MEAN = 0.50
PRIOR_WEIGHT = 10.0

# Componentes del trust individual. Los aportes positivos suman como máximo
# 0.95; el castigo por brevedad puede reducir el resultado, que finalmente se
# limita a [0, 1]. Multimedia y brevedad usan magnitud moderada 0.15 desde la
# segunda validación humana y su análisis de sensibilidad post-fix.
W_BASE = 0.30
W_RELEVANCE = 0.30
W_MEDIA = 0.15
W_LIKES = 0.20
W_SHORT = -0.15
RELEVANCE_SATURATION = 30.0
SHORT_THRESHOLD = 20

# Parametros de paginacion y reintentos. La lectura de 05 se hace en paginas
READ_PAGE_SIZE = 1000
WRITE_BATCH_SIZE = 200
MAX_RETRIES = 4

# Parametros de staging y RPC
REVIEW_STAGING_TABLE = "review_trust_staging"
ASPECT_STAGING_TABLE = "product_aspect_trust_staging"
BEGIN_RPC = "begin_trust_rebuild"
FINALIZE_RPC = "replace_trust_outputs"
DISCARD_RPC = "discard_trust_rebuild"
STAGING_MIGRATION_PATH = "database/20260807_trust_uncertainty.sql"

REVIEW_STAGING_CONFLICT = "run_id,dataset_key,product_id,review_id"
ASPECT_STAGING_CONFLICT = (
    "run_id,dataset_key,product_id,aspect,polarity,strategy"
)

# Se completan al ejecutar ``initialize_runtime``. La importacion queda libre
# de credenciales y de lectura del perfil para facilitar pruebas unitarias.
SUPABASE_URL = ""
SUPABASE_KEY = ""
DATASET_KEY = ""
DOMAIN: dict[str, Any] = {}
CATALOG_ASPECT_MAP: dict[str, str] = {}


def load_settings(dataset_key: str | None = None) -> tuple[str, str, str]:
    """Lee las variables obligatorias y reporta todas las faltantes juntas."""
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


def validate_parameters(
    *,
    log_ref: int | None = None,
    min_reviews: int | None = None,
    catalog_confidence: float | None = None,
    prior_weight: float | None = None,
) -> None:
    """Detecta configuraciones no finitas o fuera de la escala esperada."""
    resolved_log_ref = LOG_REF if log_ref is None else log_ref
    resolved_min_reviews = MIN_REVIEWS if min_reviews is None else min_reviews
    resolved_catalog_confidence = (
        CATALOG_CONF if catalog_confidence is None else catalog_confidence
    )
    resolved_prior_weight = PRIOR_WEIGHT if prior_weight is None else prior_weight

    if (
        isinstance(resolved_log_ref, bool)
        or not isinstance(resolved_log_ref, int)
        or isinstance(resolved_min_reviews, bool)
        or not isinstance(resolved_min_reviews, int)
    ):
        raise RuntimeError("LOG_REF y MIN_REVIEWS deben ser enteros positivos.")
    try:
        catalog_value = float(resolved_catalog_confidence)
        prior_value = float(resolved_prior_weight)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "CATALOG_CONF y PRIOR_WEIGHT deben ser numeros finitos."
        ) from exc

    positive_weights = (W_BASE, W_RELEVANCE, W_MEDIA, W_LIKES)
    positive_total = sum(positive_weights)
    trust_parameters = (
        W_BASE,
        W_RELEVANCE,
        W_MEDIA,
        W_LIKES,
        W_SHORT,
        RELEVANCE_SATURATION,
    )
    if any(not math.isfinite(value) for value in trust_parameters):
        raise RuntimeError("Los parametros del trust deben ser finitos.")
    if (
        any(value < 0 for value in positive_weights)
        or not 0 < positive_total <= 1.0
        or W_SHORT > 0
    ):
        raise RuntimeError(
            "Los pesos positivos del trust deben sumar un valor de (0, 1] "
            "y W_SHORT no puede ser positivo."
        )
    if (
        resolved_log_ref <= 0
        or resolved_min_reviews <= 0
        or not math.isfinite(prior_value)
        or prior_value <= 0
    ):
        raise RuntimeError("LOG_REF, MIN_REVIEWS y PRIOR_WEIGHT deben ser positivos.")
    if (
        not math.isfinite(catalog_value)
        or not math.isfinite(PRIOR_MEAN)
        or not 0 <= catalog_value <= 1
        or not 0 <= PRIOR_MEAN <= 1
    ):
        raise RuntimeError("CATALOG_CONF y PRIOR_MEAN deben pertenecer a [0, 1].")


def configure_strategy_parameters(
    *,
    log_ref: int = LOG_REF,
    min_reviews: int = MIN_REVIEWS,
    catalog_confidence: float = CATALOG_CONF,
    prior_weight: float = PRIOR_WEIGHT,
) -> None:
    """Aplica parametros CLI antes de iniciar y valida su escala.

    Se exponen A, B, C y D porque la tesis necesita analizar sensibilidad sin
    editar el archivo. Cada valor queda registrado en ``trust_runs.parameters``.
    La media del prior permanece simetrica en 0.5 por decision metodologica.
    """
    # Primero se validan los argumentos locales. Asi, un error no deja los
    # valores globales parcialmente modificados para la siguiente operacion.
    validate_parameters(
        log_ref=log_ref,
        min_reviews=min_reviews,
        catalog_confidence=catalog_confidence,
        prior_weight=prior_weight,
    )
    global LOG_REF, MIN_REVIEWS, CATALOG_CONF, PRIOR_WEIGHT
    LOG_REF = log_ref
    MIN_REVIEWS = min_reviews
    CATALOG_CONF = float(catalog_confidence)
    PRIOR_WEIGHT = float(prior_weight)


def strategy_parameters() -> dict[str, Any]:
    """Devuelve los parametros que identifican metodologicamente una corrida."""
    return {
        "methodology_version": 4,
        "primary_strategy": PRIMARY_STRATEGY,
        "catalog_role": "separate_experiment",
        "catalog_aspect_map": dict(sorted(CATALOG_ASPECT_MAP.items())),
        "log_ref": LOG_REF,
        "min_reviews_per_polarity": MIN_REVIEWS,
        "catalog_confidence": CATALOG_CONF,
        "prior_mean_positive": PRIOR_MEAN,
        "prior_weight": PRIOR_WEIGHT,
        "d_decomposition": {
            "stored_for_strategy": "D",
            "projection": "belief_mass + prior_share * uncertainty",
            "evidence": "trust_score * extraction_confidence",
        },
        "trust_weights": {
            "base": W_BASE,
            "relevance": W_RELEVANCE,
            "media": W_MEDIA,
            "likes": W_LIKES,
            "short_penalty": W_SHORT,
        },
        "relevance_saturation": RELEVANCE_SATURATION,
        "short_threshold": SHORT_THRESHOLD,
    }


def initialize_runtime(
    domain: dict[str, Any] | None = None,
    dataset_key: str | None = None,
) -> None:
    """Carga entorno y dominio solamente cuando comienza una ejecucion real."""
    global SUPABASE_URL, SUPABASE_KEY, DATASET_KEY
    global DOMAIN, CATALOG_ASPECT_MAP

    SUPABASE_URL, SUPABASE_KEY, DATASET_KEY = load_settings(dataset_key)
    os.environ["DATASET_KEY"] = DATASET_KEY
    DOMAIN = domain or load_domain_config()
    raw_map = DOMAIN.get("catalog_aspect_map", {})
    if not isinstance(raw_map, dict):
        raise RuntimeError("catalog_aspect_map debe ser un objeto JSON.")
    CATALOG_ASPECT_MAP = {
        str(attribute_id): str(aspect)
        for attribute_id, aspect in raw_map.items()
        if str(attribute_id).strip() and str(aspect).strip()
    }
    validate_parameters()


# ---------------------------------------------------------------------------
# Trust individual
# ---------------------------------------------------------------------------

def nonnegative_number(value: Any) -> float:
    """Convierte valores numericos opcionales y evita evidencia negativa."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, number) if math.isfinite(number) else 0.0


def unit_interval(value: Any, field_name: str) -> float:
    """Valida una confianza numerica para no ocultar datos corruptos."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{field_name} no es numerico: {value!r}") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise RuntimeError(f"{field_name} debe pertenecer a [0, 1]: {value!r}")
    return number


def compute_trust(row: dict[str, Any]) -> dict[str, float]:
    """Calcula la confiabilidad de una resena sin usar rating ni polaridad.

    ``relevance`` se satura en RELEVANCE_SATURATION, ``likes`` usa ``tanh``
    para limitar valores extremos, el contenido multimedia suma evidencia y
    una resena demasiado corta recibe una penalizacion explicita.

    ``rate_bonus`` y ``flag_penalty`` se conservan en cero por compatibilidad
    con el esquema historico y para que la decision metodologica sea auditable.
    """
    relevance = nonnegative_number(row.get("relevance"))
    likes = nonnegative_number(row.get("likes"))
    has_media = bool(row.get("has_media"))
    content_length = int(nonnegative_number(row.get("content_length")))
    too_short = content_length < SHORT_THRESHOLD

    base_score = W_BASE
    rate_bonus = 0.0
    relevance_bonus = W_RELEVANCE * min(
        relevance / RELEVANCE_SATURATION,
        1.0,
    )
    media_bonus = W_MEDIA if has_media else 0.0
    likes_bonus = W_LIKES * math.tanh(likes)
    flag_penalty = 0.0
    short_penalty = W_SHORT if too_short else 0.0

    trust_score = max(
        0.0,
        min(
            1.0,
            base_score
            + rate_bonus
            + relevance_bonus
            + media_bonus
            + likes_bonus
            + flag_penalty
            + short_penalty,
        ),
    )
    return {
        "trust_score": round(trust_score, 4),
        "base_score": round(base_score, 4),
        "rate_bonus": round(rate_bonus, 4),
        "relevance_bonus": round(relevance_bonus, 4),
        "media_bonus": round(media_bonus, 4),
        "likes_bonus": round(likes_bonus, 4),
        "flag_penalty": round(flag_penalty, 4),
        "short_penalty": round(short_penalty, 4),
    }


# ---------------------------------------------------------------------------
# Estrategias de agregacion
# ---------------------------------------------------------------------------

def validate_evidence_inputs(
    polarity: str,
    polarity_weight: float,
    positive_weight: float,
    negative_weight: float,
) -> float:
    """Valida las sumas de evidencia y devuelve su peso total."""
    if polarity not in {"pos", "neg"}:
        raise ValueError(f"Polaridad desconocida: {polarity!r}")
    weights = (polarity_weight, positive_weight, negative_weight)
    if any(not math.isfinite(weight) or weight < 0 for weight in weights):
        raise ValueError("Los pesos de evidencia deben ser finitos y no negativos.")

    expected_weight = positive_weight if polarity == "pos" else negative_weight
    if not math.isclose(polarity_weight, expected_weight, abs_tol=1e-12):
        raise ValueError("El peso de la postura no coincide con su suma agregada.")
    return positive_weight + negative_weight


def d_evidence_decomposition(
    polarity: str,
    polarity_weight: float,
    positive_weight: float,
    negative_weight: float,
) -> dict[str, float] | None:
    """Separa la evidencia observada de la incertidumbre regularizadora de D.

    Para una postura ``s`` se guardan:

    ``belief_mass = W_s / (lambda + W_total)``
    ``uncertainty = lambda / (lambda + W_total)``
    ``agg_confidence = belief_mass + prior_share * uncertainty``

    ``belief_mass`` significa la masa de la polaridad de la fila: para una fila
    negativa representa disbelief. No se devuelve una proyeccion cuando
    ``W_s`` vale cero, porque el prior no constituye evidencia de esa postura.
    """
    total_weight = validate_evidence_inputs(
        polarity,
        polarity_weight,
        positive_weight,
        negative_weight,
    )
    if polarity_weight <= 0 or total_weight <= 0:
        return None

    denominator = PRIOR_WEIGHT + total_weight
    prior_share = PRIOR_MEAN if polarity == "pos" else 1.0 - PRIOR_MEAN
    belief_mass = polarity_weight / denominator
    uncertainty = PRIOR_WEIGHT / denominator
    projected_confidence = belief_mass + prior_share * uncertainty
    return {
        # Se conserva double precision para poder recalcular otros lambda sin
        # perder evidencia pequena. Solo la proyeccion historica se redondea.
        "evidence_weight": polarity_weight,
        "total_evidence_weight": total_weight,
        "belief_mass": belief_mass,
        "uncertainty": uncertainty,
        "agg_confidence": round(projected_confidence, 4),
    }


def evidence_share(
    strategy: str,
    polarity: str,
    polarity_weight: float,
    positive_weight: float,
    negative_weight: float,
    total_reviews: int,
) -> float | None:
    """Calcula la fuerza de una postura segun la estrategia seleccionada.

    Los pesos son sumas de ``trust_score * extraction_confidence``. Para D, el
    prior es simetrico: PRIOR_WEIGHT se reparte con PRIOR_MEAN=0.5 entre ambas
    posturas. Cuando existen las dos, sus resultados suman uno.
    """
    if total_reviews < 0:
        raise ValueError("total_reviews no puede ser negativo.")
    total_weight = validate_evidence_inputs(
        polarity,
        polarity_weight,
        positive_weight,
        negative_weight,
    )
    if strategy == "D":
        decomposition = d_evidence_decomposition(
            polarity,
            polarity_weight,
            positive_weight,
            negative_weight,
        )
        return decomposition["agg_confidence"] if decomposition else None
    if total_weight <= 0 or polarity_weight <= 0:
        return None

    raw_share = polarity_weight / total_weight
    if strategy == "A":
        volume_factor = min(
            1.0,
            math.log(total_reviews + 1) / math.log(LOG_REF + 1),
        )
        return round(raw_share * volume_factor, 4)
    if strategy in {"B", "C", "E"}:
        return round(raw_share, 4)
    raise ValueError(f"Estrategia desconocida: {strategy}")


def add_aspect_evidence(
    rows: Iterable[dict[str, Any]],
    trust_map: dict[tuple[Any, str], float],
    review_evidence: dict[tuple[Any, str, str, str], float],
    mention_counts: dict[tuple[str, str, str], int],
) -> None:
    """Agrega una pagina de 05 sin contar dos veces la misma postura/usuario.

    Si una resena repite el mismo aspecto y postura, se conserva la extraccion
    efectiva mas clara. Una postura positiva y otra negativa de la misma resena
    permanecen separadas porque representan evidencia distinta.
    """
    missing: list[tuple[Any, str]] = []
    for row in rows:
        polarity = str(row.get("polarity") or "")
        if polarity == "neu":
            continue
        if polarity not in {"pos", "neg"}:
            raise RuntimeError(f"Polaridad inesperada en review_aspects: {polarity!r}")

        review_id = row.get("review_id")
        product_id = str(row.get("product_id") or "")
        aspect = str(row.get("aspect") or "")
        if not product_id or not aspect:
            raise RuntimeError(
                "review_aspects contiene product_id o aspect vacio: "
                f"review_id={review_id!r}"
            )
        trust_key = (review_id, product_id)
        trust_score = trust_map.get(trust_key)
        if trust_score is None:
            if len(missing) < 10:
                missing.append(trust_key)
            continue

        extraction_raw = row.get("extraction_confidence")
        extraction_confidence = (
            1.0
            if extraction_raw is None
            else unit_interval(extraction_raw, "extraction_confidence")
        )
        effective_score = trust_score * extraction_confidence
        group_key = (product_id, aspect, polarity)
        review_key = (review_id, product_id, aspect, polarity)
        mention_counts[group_key] += 1
        # La mencion sigue siendo auditable, pero una contribucion nula no
        # cuenta como reseña de apoyo ni puede originar un hecho por el prior.
        if effective_score <= 0:
            continue
        previous = review_evidence.get(review_key)
        if previous is None or effective_score > previous:
            review_evidence[review_key] = effective_score

    if missing:
        preview = ", ".join(f"{review_id}/{product_id}" for review_id, product_id in missing)
        raise RuntimeError(
            "review_aspects contiene resenas sin trust individual: " + preview
        )


def group_review_evidence(
    review_evidence: dict[tuple[Any, str, str, str], float],
) -> dict[tuple[str, str], dict[str, list[float]]]:
    """Agrupa contribuciones unicas por producto, aspecto y postura."""
    grouped: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
        lambda: {"pos": [], "neg": []}
    )
    for (_review_id, product_id, aspect, polarity), score in review_evidence.items():
        grouped[(product_id, aspect)][polarity].append(score)
    return grouped


def parse_catalog_attributes(raw_attributes: Any) -> list[dict[str, Any]]:
    """Convierte atributos JSON y rechaza estructuras imposibles de auditar."""
    if raw_attributes in (None, ""):
        return []
    try:
        parsed = (
            json.loads(raw_attributes)
            if isinstance(raw_attributes, str)
            else raw_attributes
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON de atributos invalido: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError("attributes debe contener una lista")
    return [item for item in parsed if isinstance(item, dict)]


def add_catalog_evidence(
    rows: Iterable[dict[str, Any]],
    catalog_aspects: dict[tuple[str, str, str], float],
) -> list[str]:
    """Extrae aspectos declarados y devuelve advertencias de datos invalidos."""
    warnings: list[str] = []
    for row in rows:
        product_id = str(row.get("product_id") or "")
        try:
            attributes = parse_catalog_attributes(row.get("attributes"))
        except ValueError as exc:
            warnings.append(f"product_id={product_id}: {exc}")
            continue
        for attribute in attributes:
            aspect = CATALOG_ASPECT_MAP.get(str(attribute.get("id") or ""))
            if aspect and attribute.get("value_name") not in (None, ""):
                catalog_aspects[(product_id, aspect, "pos")] = CATALOG_CONF
    return warnings


def build_product_aspect_rows(
    grouped: dict[tuple[str, str], dict[str, list[float]]],
    mention_counts: dict[tuple[str, str, str], int],
    catalog_aspects: dict[tuple[str, str, str], float],
    strategy: str,
    dataset_key: str,
) -> list[dict[str, Any]]:
    """Construye los hechos de una estrategia con reglas B/C coherentes.

    B exige MIN_REVIEWS para cada postura que pretende emitir. C solo introduce
    catalogo cuando no existe ninguna resena positiva ni negativa del aspecto.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Estrategia desconocida: {strategy}")

    keys = set(grouped)
    if strategy == "C":
        keys.update((product_id, aspect) for product_id, aspect, _ in catalog_aspects)
    max_reviews = max(
        (
            sum(score > 0 for score in scores)
            for polarities in grouped.values()
            for scores in polarities.values()
        ),
        default=1,
    ) or 1

    output: list[dict[str, Any]] = []
    for product_id, aspect in sorted(keys):
        polarities = grouped.get((product_id, aspect), {"pos": [], "neg": []})
        raw_positive_scores = polarities["pos"]
        raw_negative_scores = polarities["neg"]
        if any(
            not math.isfinite(score) or score < 0
            for score in [*raw_positive_scores, *raw_negative_scores]
        ):
            raise ValueError("Las contribuciones deben ser finitas y no negativas.")
        # El filtro tambien protege llamadas directas a esta funcion: una
        # extraccion de peso cero no cuenta para B, cobertura ni volumen de A.
        positive_scores = [score for score in raw_positive_scores if score > 0]
        negative_scores = [score for score in raw_negative_scores if score > 0]
        positive_weight = sum(positive_scores)
        negative_weight = sum(negative_scores)
        total_reviews = len(positive_scores) + len(negative_scores)

        # C representa presencia estructurada, no una refutacion de opiniones.
        # Por eso solo se usa cuando el aspecto carece totalmente de resenas.
        if strategy == "C" and total_reviews == 0:
            catalog_key = (product_id, aspect, "pos")
            if catalog_key in catalog_aspects:
                output.append(
                    {
                        "dataset_key": dataset_key,
                        "product_id": product_id,
                        "aspect": aspect,
                        "polarity": "pos",
                        "strategy": strategy,
                        "agg_confidence": CATALOG_CONF,
                        # El catalogo no es evidencia de reseñas y C no usa la
                        # descomposicion regularizada propia de D.
                        "evidence_weight": None,
                        "total_evidence_weight": None,
                        "belief_mass": None,
                        "uncertainty": None,
                        "n_reviews": 0,
                        "n_mentions": 0,
                        "coverage_ratio": 0.0,
                        "from_catalog": True,
                    }
                )
            continue

        for polarity, scores, polarity_weight in (
            ("pos", positive_scores, positive_weight),
            ("neg", negative_scores, negative_weight),
        ):
            review_count = len(scores)
            # Una extraccion con confianza cero no debe producir una postura
            # cuya unica fuerza proceda del prior neutral.
            if review_count == 0 or polarity_weight <= 0:
                continue
            if strategy == "B" and review_count < MIN_REVIEWS:
                continue
            diagnostics: dict[str, float | None] = {
                "evidence_weight": None,
                "total_evidence_weight": None,
                "belief_mass": None,
                "uncertainty": None,
            }
            if strategy == "D":
                decomposition = d_evidence_decomposition(
                    polarity,
                    polarity_weight,
                    positive_weight,
                    negative_weight,
                )
                if decomposition is None:
                    continue
                confidence = decomposition["agg_confidence"]
                diagnostics.update(
                    {
                        field: decomposition[field]
                        for field in diagnostics
                    }
                )
            else:
                confidence = evidence_share(
                    strategy,
                    polarity,
                    polarity_weight,
                    positive_weight,
                    negative_weight,
                    total_reviews,
                )
            if confidence is None:
                continue
            output.append(
                {
                    "dataset_key": dataset_key,
                    "product_id": product_id,
                    "aspect": aspect,
                    "polarity": polarity,
                    "strategy": strategy,
                    "agg_confidence": confidence,
                    # Solo D materializa estas cuatro magnitudes. Repetirlas en
                    # A, B, C y E multiplicaria el mismo dato sin explicar sus
                    # respectivas formulas de confianza.
                    **diagnostics,
                    "n_reviews": review_count,
                    "n_mentions": mention_counts.get(
                        (product_id, aspect, polarity),
                        0,
                    ),
                    "coverage_ratio": round(review_count / max_reviews, 4),
                    "from_catalog": False,
                }
            )
    return output


# ---------------------------------------------------------------------------
# Acceso paginado y escritura resiliente
# ---------------------------------------------------------------------------

def iter_cursor_pages(
    page_loader: Callable[[int, int], list[dict[str, Any]]],
    page_size: int = READ_PAGE_SIZE,
) -> Iterable[list[dict[str, Any]]]:
    """Itera paginas ordenadas por id sin acumular todo el origen en memoria."""
    last_id = 0
    while True:
        page = page_loader(last_id, page_size)
        if not page:
            return
        page_ids = [int(row["id"]) for row in page]
        if page_ids != sorted(page_ids) or page_ids[0] <= last_id:
            raise RuntimeError(
                "La paginacion por cursor recibio ids fuera de orden."
            )
        yield page
        last_id = page_ids[-1]


def chunked(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    """Divide payloads grandes en solicitudes controladas."""
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def is_transient_error(exc: Exception) -> bool:
    """Reconoce errores de transporte o saturacion que permiten reintentar."""
    if isinstance(exc, httpx.TransportError):
        return True
    code = str(getattr(exc, "code", "") or "")
    status_code = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None),
        "status_code",
        None,
    )
    message = str(exc).lower()
    return (
        code.startswith("08")
        or code
        in {
            "40001",   # serializacion real de PostgreSQL
            "40P01",   # deadlock
            "53300",   # demasiadas conexiones
            "57014",   # timeout/cancelacion
            "57P01",   # servidor reiniciandose
            "57P02",
            "57P03",
            "PGRST000",
            "PGRST001",
            "PGRST002",
            "PGRST003",
        }
        or status_code in {408, 429, 502, 503, 504}
        or "timeout" in message
        or "timed out" in message
        or "connection reset" in message
        or "server disconnected" in message
        or "stream reset" in message
        or "streamreset" in message
    )


def execute_with_retry(operation: Callable[[], Any], label: str) -> Any:
    """Ejecuta una operacion idempotente con backoff exponencial acotado."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return operation()
        except Exception as exc:
            if not is_transient_error(exc) or attempt == MAX_RETRIES:
                raise
        # Un jitter pequeno evita que dos procesos reintenten al mismo tiempo.
        wait_seconds = min(8.0, 2 ** (attempt - 1)) + random.uniform(0.0, 0.25)
        print(
            f"  AVISO: fallo transitorio en {label}. "
            f"Reintento {attempt}/{MAX_RETRIES} en {wait_seconds:.2f}s...",
            file=sys.stderr,
        )
        time.sleep(wait_seconds)
    raise AssertionError("Bucle de reintentos agotado sin retornar ni lanzar")


def is_missing_staging_setup(exc: Exception) -> bool:
    """Distingue una migracion ausente de un error real de los datos."""
    return str(getattr(exc, "code", "") or "") in {
        "42P01",   # tabla inexistente
        "42P10",   # falta indice unico para on_conflict
        "42703",   # columna inexistente
        "42883",   # funcion PostgreSQL inexistente
        "PGRST202",  # RPC no encontrada en la cache de PostgREST
        "PGRST204",  # columna no encontrada en la cache de PostgREST
        "PGRST205",  # tabla no encontrada en la cache de PostgREST
    }


def staging_setup_error(exc: Exception) -> RuntimeError:
    """Explica como instalar las tablas y la funcion transaccional requeridas."""
    return RuntimeError(
        "Falta instalar la reconstruccion atomica de trust. "
        f"Ejecuta {STAGING_MIGRATION_PATH} en Supabase SQL Editor. "
        f"Detalle original: {exc}"
    )


def begin_trust_run(
    sb: Any,
    dataset_key: str,
    run_id: str,
    strategies: list[str],
) -> None:
    """Registra una reconstruccion sin modificar las tablas publicadas."""
    try:
        execute_with_retry(
            lambda: (
                sb.rpc(
                    BEGIN_RPC,
                    {
                        "p_dataset_key": dataset_key,
                        "p_run_id": run_id,
                        "p_strategies": strategies,
                        "p_parameters": strategy_parameters(),
                    },
                ).execute()
            ),
            "inicio de staging trust",
        )
    except APIError as exc:
        if is_missing_staging_setup(exc):
            raise staging_setup_error(exc) from exc
        raise


def discard_trust_run(sb: Any, run_id: str) -> None:
    """Descarta staging solo si la ejecucion no fue activada."""
    execute_with_retry(
        lambda: sb.rpc(
            DISCARD_RPC,
            {"p_run_id": run_id},
        ).execute(),
        "limpieza de staging trust",
    )


def upsert_staging_rows(
    sb: Any,
    table_name: str,
    rows: list[dict[str, Any]],
    on_conflict: str,
) -> None:
    """Guarda filas de staging en lotes idempotentes y reintentables."""
    # El ultimo valor para una clave gana. Normalmente no hay duplicados, pero
    # esta defensa mantiene el payload valido si una fuente repite una fila.
    key_fields = on_conflict.split(",")
    unique_rows = {
        tuple(row.get(field) for field in key_fields): row
        for row in rows
    }
    for batch in chunked(list(unique_rows.values()), WRITE_BATCH_SIZE):
        try:
            execute_with_retry(
                lambda batch=batch: (
                    sb.table(table_name)
                    .upsert(batch, on_conflict=on_conflict)
                    .execute()
                ),
                f"upsert en {table_name}",
            )
        except APIError as exc:
            if is_missing_staging_setup(exc):
                raise staging_setup_error(exc) from exc
            raise


def finalize_trust_run(
    sb: Any,
    dataset_key: str,
    run_id: str,
    strategies: list[str],
    review_count: int,
    fact_counts_by_strategy: dict[str, int],
) -> None:
    """Publica trust individual y agregado en una transaccion PostgreSQL."""
    fact_count = sum(fact_counts_by_strategy.values())
    try:
        response = execute_with_retry(
            lambda: (
                sb.rpc(
                    FINALIZE_RPC,
                    {
                        "p_dataset_key": dataset_key,
                        "p_run_id": run_id,
                        "p_strategies": strategies,
                        "p_expected_review_rows": review_count,
                        "p_expected_fact_rows": fact_count,
                        "p_expected_fact_rows_by_strategy": (
                            fact_counts_by_strategy
                        ),
                    },
                )
                .execute()
            ),
            "activacion atomica de trust",
        )
        result = response.data or {}
        if isinstance(result, dict) and result.get("superseded"):
            raise RuntimeError(
                "La corrida termino, pero otra ejecucion mas nueva ya la "
                "reemplazo. Vuelve a ejecutar 06_trust.py."
            )
        if isinstance(result, dict) and result.get("source_changed"):
            raise RuntimeError(
                "La corrida se activo, pero sus fuentes cambiaron enseguida. "
                "Vuelve a ejecutar 06_trust.py para actualizarla."
            )
    except APIError as exc:
        if is_missing_staging_setup(exc):
            raise staging_setup_error(exc) from exc
        raise


def fetch_review_page(
    sb: Any,
    included_product_ids: list[str],
    last_id: int,
    page_size: int,
) -> list[dict[str, Any]]:
    """Lee solo las columnas necesarias para el trust individual."""
    response = execute_with_retry(
        lambda: (
            sb.table("reviews_clean")
            .select(
                "id,dataset_key,review_id,product_id,relevance,likes,"
                "has_media,content_length"
            )
            .eq("dataset_key", DATASET_KEY)
            .in_("product_id", included_product_ids)
            .gt("id", last_id)
            .order("id")
            .limit(page_size)
            .execute()
        ),
        "lectura paginada de reviews_clean",
    )
    return response.data


def fetch_aspect_page(
    sb: Any,
    included_product_ids: list[str],
    last_id: int,
    page_size: int,
) -> list[dict[str, Any]]:
    """Lee una pagina estable de extracciones publicadas por 05."""
    response = execute_with_retry(
        lambda: (
            sb.table("review_aspects")
            .select(
                "id,review_id,product_id,aspect,polarity,extraction_confidence"
            )
            .eq("dataset_key", DATASET_KEY)
            .in_("product_id", included_product_ids)
            .gt("id", last_id)
            .order("id")
            .limit(page_size)
            .execute()
        ),
        "lectura paginada de review_aspects",
    )
    return response.data


def fetch_catalog_page(
    sb: Any,
    included_product_ids: list[str],
    last_id: int,
    page_size: int,
) -> list[dict[str, Any]]:
    """Pagina atributos del catalogo para que C no dependa del limite API."""
    response = execute_with_retry(
        lambda: (
            sb.table("products_raw")
            .select("id,product_id,attributes")
            .eq("dataset_key", DATASET_KEY)
            .in_("product_id", included_product_ids)
            .gt("id", last_id)
            .order("id")
            .limit(page_size)
            .execute()
        ),
        "lectura paginada de products_raw",
    )
    return response.data


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def calculate_review_trust(
    sb: Any,
    included_product_ids: set[str],
    run_id: str,
) -> tuple[dict[tuple[Any, str], float], dict[float, int]]:
    """Calcula, guarda en staging y devuelve el mapa de trust en una pasada."""
    trust_map: dict[tuple[Any, str], float] = {}
    histogram: dict[float, int] = defaultdict(int)
    total = 0

    product_ids = sorted(included_product_ids)
    loader = lambda last_id, size: fetch_review_page(
        sb,
        product_ids,
        last_id,
        size,
    )
    for page in iter_cursor_pages(loader):
        staging_rows: list[dict[str, Any]] = []
        for row in page:
            components = compute_trust(row)
            review_id = row.get("review_id")
            product_id = str(row.get("product_id") or "")
            if review_id is None or not product_id:
                raise RuntimeError(
                    "reviews_clean contiene review_id o product_id vacio."
                )
            trust_key = (review_id, product_id)
            if trust_key in trust_map:
                raise RuntimeError(
                    "reviews_clean repite la identidad "
                    f"review_id={review_id!r}, product_id={product_id!r}."
                )
            trust_map[trust_key] = components["trust_score"]
            histogram[round(components["trust_score"], 1)] += 1
            staging_rows.append(
                {
                    "run_id": run_id,
                    "dataset_key": row["dataset_key"],
                    "review_id": review_id,
                    "product_id": product_id,
                    **components,
                }
            )
        upsert_staging_rows(
            sb,
            REVIEW_STAGING_TABLE,
            staging_rows,
            REVIEW_STAGING_CONFLICT,
        )
        total += len(page)
        print(f"  trust individuales procesados: {total}")
    return trust_map, histogram


def calculate_aspect_evidence(
    sb: Any,
    included_product_ids: set[str],
    trust_map: dict[tuple[Any, str], float],
) -> tuple[
    dict[tuple[str, str], dict[str, list[float]]],
    dict[tuple[str, str, str], int],
]:
    """Combina trust individual y confianza de extraccion sin releer trust."""
    review_evidence: dict[tuple[Any, str, str, str], float] = {}
    mention_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    product_ids = sorted(included_product_ids)
    loader = lambda last_id, size: fetch_aspect_page(
        sb,
        product_ids,
        last_id,
        size,
    )
    for page in iter_cursor_pages(loader):
        add_aspect_evidence(
            page,
            trust_map,
            review_evidence,
            mention_counts,
        )
    print(
        "  menciones no neutrales: "
        f"{sum(mention_counts.values())}; contribuciones unicas: "
        f"{len(review_evidence)}"
    )
    return group_review_evidence(review_evidence), mention_counts


def load_catalog_evidence(
    sb: Any,
    included_product_ids: set[str],
) -> dict[tuple[str, str, str], float]:
    """Carga catalogo paginado y hace visibles los atributos invalidos."""
    catalog_aspects: dict[tuple[str, str, str], float] = {}
    if not CATALOG_ASPECT_MAP:
        print(
            "  AVISO: catalog_aspect_map esta vacio; C no agregara hechos "
            "sin resenas.",
            file=sys.stderr,
        )
        return catalog_aspects

    warnings: list[str] = []
    product_ids = sorted(included_product_ids)
    loader = lambda last_id, size: fetch_catalog_page(
        sb,
        product_ids,
        last_id,
        size,
    )
    for page in iter_cursor_pages(loader):
        warnings.extend(add_catalog_evidence(page, catalog_aspects))
    for warning in warnings[:20]:
        print(f"  AVISO catalogo: {warning}", file=sys.stderr)
    if len(warnings) > 20:
        print(
            f"  AVISO catalogo: {len(warnings) - 20} errores adicionales.",
            file=sys.stderr,
        )
    return catalog_aspects


def run(strategy: str, dataset_key: str | None = None) -> None:
    """Construye las salidas y solo las publica cuando todo termina bien."""
    initialize_runtime(dataset_key=dataset_key)
    # Se publican siempre las cinco estrategias en la misma generacion. El
    # argumento individual se conserva por compatibilidad y solo identifica la
    # alternativa de interes; nunca deja comparaciones de corridas distintas.
    strategies = list(STRATEGIES)
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    run_id = str(uuid.uuid4())
    try:
        # El run se registra antes de leer el alcance. Los triggers SQL guardan
        # una revision global y la activacion se rechaza si alguna fuente cambia
        # mientras Python pagina reviews, aspectos, alcance o catalogo.
        begin_trust_run(sb, DATASET_KEY, run_id, strategies)
        included_product_ids = require_included_product_ids(
            sb,
            DATASET_KEY,
            stage_name="06_trust.py",
        )

        if strategy != "all":
            print(
                f"Nota: {strategy} es la estrategia de interes, pero se "
                "reconstruyen A-E juntas para mantener una generacion "
                "comparable."
            )
        print(f"Estrategias publicadas: {', '.join(strategies)}")
        print(f"Productos incluidos: {len(included_product_ids)}")

        trust_map, histogram = calculate_review_trust(
            sb,
            included_product_ids,
            run_id,
        )
        grouped, mention_counts = calculate_aspect_evidence(
            sb,
            included_product_ids,
            trust_map,
        )
        catalog_aspects = (
            load_catalog_evidence(sb, included_product_ids)
            if "C" in strategies
            else {}
        )

        generated_counts: dict[str, int] = {}
        for current_strategy in strategies:
            rows = build_product_aspect_rows(
                grouped,
                mention_counts,
                catalog_aspects,
                current_strategy,
                DATASET_KEY,
            )
            staging_rows = [
                {"run_id": run_id, **row}
                for row in rows
            ]
            upsert_staging_rows(
                sb,
                ASPECT_STAGING_TABLE,
                staging_rows,
                ASPECT_STAGING_CONFLICT,
            )
            generated_counts[current_strategy] = len(rows)

        finalize_trust_run(
            sb,
            DATASET_KEY,
            run_id,
            strategies,
            len(trust_map),
            generated_counts,
        )
    except Exception:
        try:
            discard_trust_run(sb, run_id)
        except Exception as cleanup_error:
            print(
                f"AVISO: no se pudo limpiar staging {run_id}: {cleanup_error}",
                file=sys.stderr,
            )
        raise

    print()
    print("=" * 60)
    print(f"Trust individuales calculados: {len(trust_map)}")
    print("Distribucion del trust individual:")
    total = max(1, len(trust_map))
    for bucket, count in sorted(histogram.items()):
        bar = "#" * int(count / total * 40)
        print(f"  [{bucket:.1f}] {count:5d} {bar}")
    for current_strategy in strategies:
        print(
            f"Estrategia {current_strategy}: "
            f"{generated_counts[current_strategy]} hechos"
        )
    print("Salidas publicadas atomica y conjuntamente.")
    print("=" * 60)


def main() -> None:
    """Valida argumentos de consola y ejecuta la estrategia solicitada."""
    parser = argparse.ArgumentParser(
        description="Calcula trust individual y agregado por aspecto.",
    )
    parser.add_argument(
        "--strategy",
        default=DEFAULT_STRATEGY,
        choices=[*STRATEGIES, "all"],
        help=(
            "Alternativa de interes. Por consistencia siempre se recalculan "
            "y publican A-E en una misma generacion."
        ),
    )
    parser.add_argument(
        "--dataset-key",
        default=os.environ.get("DATASET_KEY"),
        help="Dataset a procesar. Si se omite, usa DATASET_KEY de .env.",
    )
    parser.add_argument(
        "--a-log-ref",
        type=int,
        default=LOG_REF,
        help="Volumen de referencia donde A deja de penalizar (default: 200).",
    )
    parser.add_argument(
        "--b-min-reviews",
        type=int,
        default=MIN_REVIEWS,
        help="Resenas distintas minimas por postura para B (default: 15).",
    )
    parser.add_argument(
        "--c-catalog-confidence",
        type=float,
        default=CATALOG_CONF,
        help="Confianza del contexto de catalogo en C (default: 0.90).",
    )
    parser.add_argument(
        "--d-prior-weight",
        type=float,
        default=PRIOR_WEIGHT,
        help="Peso lambda de la regularizacion D (default: 10).",
    )
    args = parser.parse_args()
    configure_strategy_parameters(
        log_ref=args.a_log_ref,
        min_reviews=args.b_min_reviews,
        catalog_confidence=args.c_catalog_confidence,
        prior_weight=args.d_prior_weight,
    )
    run(args.strategy, dataset_key=args.dataset_key)


if __name__ == "__main__":
    try:
        main()
    except (ProductReviewSetupError, ProductReviewPendingError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
