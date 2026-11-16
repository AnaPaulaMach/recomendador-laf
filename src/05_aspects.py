"""
05_aspects.py - Extraccion de aspectos y polaridad (ABSA).

Para cada resena en reviews_clean, identifica que aspectos del dominio activo
menciona y con que polaridad (positiva, negativa, neutral). Escribe en
review_aspects.

Algoritmo:
    1. Tokenizacion con spaCy (modelo es_core_news_md).
    2. Division en oraciones (cada oracion es una unidad de analisis).
    3. Para cada oracion:
       a. Detectar aspectos: matching del lexicon sobre lemas y tokens.
       b. Detectar polaridad: contar palabras positivas vs negativas.
       c. Detectar negacion: si hay una palabra de negacion a <=3 tokens
          antes de una palabra de polaridad, se invierte esa polaridad.
       d. Calcular confianza de extraccion.
    4. Emitir una fila por (aspecto, polaridad) detectado en la oracion.

Notas de diseno:
    - El analisis es por oracion para mantener contexto local.
    - El sistema es basado en reglas, por eso es auditable para la defensa.
    - La confianza es una puntuacion heuristica exploratoria; no representa una
      probabilidad estadisticamente calibrada.
    - Las frases multi-palabra se detectan con PhraseMatcher, no con substring.
    - La salida se escribe primero en staging y se activa con una transaccion;
      una interrupcion no deja review_aspects vacia o parcialmente reconstruida.

reviews_clean
      ↓
spaCy: oraciones, tokens y lemas
      ↓
Detección de aspectos
      ↓
Detección de palabras positivas, negativas y negaciones
      ↓
Asociación local entre opinión y aspecto
      ↓
review_aspects_staging
      ↓
Reemplazo transaccional
      ↓
review_aspects

Uso:
    python src/05_aspects.py
    .\venv\Scripts\python.exe src\05_aspects.py
"""

import argparse
import os
import re
import sys
import time
import unicodedata
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import httpx
import spacy
from dotenv import load_dotenv
from postgrest.exceptions import APIError
from spacy.matcher import PhraseMatcher
from supabase import create_client

from domain_config import load_domain_config
from product_scope import (
    ProductReviewPendingError,
    ProductReviewSetupError,
    require_included_product_ids,
)


# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
# La ruta explicita permite ejecutar el script desde cualquier directorio.
load_dotenv(REPO_ROOT / ".env")

NEGATION_WINDOW = 3 # Una negacion afecta a una polaridad si esta a 3 tokens o menos de distancia.
NEGATED_PREDICATE_WINDOW = 4
# Los conectores separan clausulas que pueden expresar opiniones opuestas.
ADVERSATIVE_CONNECTORS = [
    "sin embargo",
    "no obstante",
    "eso si",
    "pero",
    "aunque",
    "sino",
    "excepto",
    "salvo",
]
NEGATION_BOUNDARIES = { #Limites que la negacion no puede cruzar para afectar una polaridad
    ",",
    ";",
    ":",
    ".",
    "!",
    "?",
    "y",
    "e",
    "o",
    "u",
    "pero",
    "aunque",
}
NEGATION_IDIOMS = {
    ("sin", "duda"),
    # Locuciones positivas donde ``no`` no niega el descriptor que sigue.
    # ``no tiene pierde`` = "no falla"; sin esta excepcion ``no`` invertia
    # ``excelente`` en "no tiene pierde excelente sabor".
    ("no", "tiene", "pierde"),
    ("no", "tiene", "perdida"),
    ("no", "hay", "pierde"),
}
NEGATIVE_ANSWER_PREFIXES = {
    ("no",),
    ("de", "ninguna", "manera"),
    ("para", "nada"),
    ("nunca",),
}
COORDINATION_TOKENS = { # Tokens que conectan clausulas
    ",",
    "/",
    "-",
    "y",
    "e",
    "o",
    "u",
    "tanto",
    "como",
    "de",
    "del",
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "su",
    "si",
    "trae",
    "contiene",
    "incluye",
}
MAX_LOCAL_SIGNAL_DISTANCE = 4 # Una polaridad se asigna a un aspecto si esta a 4 tokens o menos de distancia.
IGNORABLE_PHRASE_PUNCTUATION = {
    '"',
    "'",
    "“",
    "”",
    "‘",
    "’",
}
UNIQUE_FIELDS = ( #Si se repite un aspecto en la misma resena, se conserva solo una fila por (aspecto, polaridad)
    "dataset_key",
    "review_id",
    "product_id",
    "aspect",
    "polarity",
    "sentence_excerpt",
)
# Los tamanos pequenos limitan el uso de memoria y el payload de cada request;
# ``nlp.pipe`` conserva, aun asi, el procesamiento vectorizado de spaCy.
WRITE_BATCH_SIZE = 100
MAX_WRITE_RETRIES = 4
NLP_PIPE_BATCH_SIZE = 64
STAGING_TABLE = "review_aspects_staging"
FINALIZE_RPC = "replace_review_aspects"
STAGING_MIGRATION_PATH = "database/20260805_aspect_staging.sql"
STAGING_UNIQUE_FIELDS = ("run_id", *UNIQUE_FIELDS)
STAGING_ON_CONFLICT = ",".join(STAGING_UNIQUE_FIELDS)


# ---------------------------------------------------------------------------
# Recursos de analisis
# ---------------------------------------------------------------------------

# Se inicializan dentro de ``main``. Esto evita cargar spaCy, el dominio y las
# variables de entorno al importar el modulo, lo que facilita las pruebas y
# permite mostrar errores de configuracion controlados.
nlp = None
DOMAIN: dict[str, Any] = {}
LEX: dict[str, Any] = {}
ASPECTS: dict[str, set[str]] = {}
POSITIVE: set[str] = set()
NEGATIVE: set[str] = set()
NEGATION: set[str] = set()
ASPECTS_NORM: dict[str, set[str]] = {}
POSITIVE_NORM: set[str] = set()
NEGATIVE_NORM: set[str] = set()
NEGATION_NORM: set[str] = set()
SINGLE_ASPECT_INDEX: dict[str, set[str]] = {}
MULTI_POS_NORM: list[list[str]] = []
MULTI_NEG_NORM: list[list[str]] = []
MULTI_ASP_NORM: dict[str, list[list[str]]] = {}
ASPECT_EXCLUSIONS_NORM: dict[str, list[list[str]]] = {}
ASPECT_POLARITY_LINKS: dict[str, set[str]] = {}
POLARITY_ASPECT_HINTS_NORM: dict[str, set[str]] = {}
COMPARISON_MARKERS_NORM: list[list[str]] = []
ASP_MATCHER = None
ASP_MATCH_ID_TO_NAME: dict[str, str] = {}


def normalize_match_text(value):
    """Normaliza texto para matching robusto ante acentos y mayusculas.

    Las resenas de marketplace mezclan variantes como "enfria" / "enfría" o
    "instalacion" / "instalación". El lexicon sigue siendo legible para el
    experto, pero internamente comparamos una version sin diacriticos.
    """
    text = str(value or "").strip().lower()
    if text and not any(char.isalnum() for char in text):
        return text
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    return re.sub(r"^[^\w]+|[^\w]+$", "", normalized)


def _multi_word_terms(words_set):
    """Devuelve solo terminos formados por mas de una palabra."""
    return [w for w in words_set if " " in w]


def _phrase_parts(term):
    """Devuelve tokens normalizados de una frase del lexicon."""
    return normalize_match_text(term).split()


def _phrase_spans(tokens_norm, parts):
    """Spans de una frase, tolerando comillas internas del marketplace."""
    if not parts or len(parts) == 1:
        return []
    spans = []
    for start in range(len(tokens_norm)):
        token_index = start
        part_index = 0
        while token_index < len(tokens_norm) and part_index < len(parts):
            token = tokens_norm[token_index]
            if token in IGNORABLE_PHRASE_PUNCTUATION:
                token_index += 1
                continue
            if token != parts[part_index]:
                break
            token_index += 1
            part_index += 1
        if part_index == len(parts):
            spans.append((start, token_index))
    return spans


def _norm_tokens(sent):
    """Normaliza la forma escrita de todos los tokens del segmento."""
    return [normalize_match_text(tok.text) for tok in sent]


def _norm_lemmas(sent):
    """Normaliza lemas para reconocer variantes flexionadas del lexicon."""
    return [normalize_match_text(tok.lemma_) for tok in sent]


def initialize_analysis(
    domain: dict[str, Any] | None = None,
    nlp_instance: Any | None = None,
) -> None:
    """Carga spaCy y compila indices a partir del perfil del dominio.

    La funcion admite recursos inyectados para que las pruebas no dependan de
    variables de entorno ni tengan que reconstruir el pipeline innecesariamente.
    """
    global nlp, DOMAIN, LEX, ASPECTS, POSITIVE, NEGATIVE, NEGATION
    global ASPECTS_NORM, POSITIVE_NORM, NEGATIVE_NORM, NEGATION_NORM
    global SINGLE_ASPECT_INDEX, MULTI_POS_NORM, MULTI_NEG_NORM
    global MULTI_ASP_NORM, ASPECT_EXCLUSIONS_NORM, ASPECT_POLARITY_LINKS
    global POLARITY_ASPECT_HINTS_NORM, COMPARISON_MARKERS_NORM
    global ASP_MATCHER
    global ASP_MATCH_ID_TO_NAME

    if nlp_instance is None:
        print("Cargando modelo de spaCy es_core_news_md...")
        nlp_instance = spacy.load("es_core_news_md")
    if domain is None:
        domain = load_domain_config()

    lexicon = domain.get("lexicon")
    if not isinstance(lexicon, dict):
        raise RuntimeError("El perfil del dominio no contiene un lexicon valido.")

    nlp = nlp_instance
    DOMAIN = domain
    LEX = lexicon
    ASPECTS = {
        aspect: set(words)
        for aspect, words in LEX.get("aspects", {}).items()
    }
    POSITIVE = set(LEX.get("positive", []))
    NEGATIVE = set(LEX.get("negative", []))
    NEGATION = set(LEX.get("negation", []))

    ASPECTS_NORM = {
        aspect: {normalize_match_text(term) for term in terms}
        for aspect, terms in ASPECTS.items()
    }
    POSITIVE_NORM = {normalize_match_text(term) for term in POSITIVE}
    NEGATIVE_NORM = {normalize_match_text(term) for term in NEGATIVE}
    NEGATION_NORM = {normalize_match_text(term) for term in NEGATION}
    MULTI_POS_NORM = [
        _phrase_parts(term) for term in POSITIVE_NORM if " " in term
    ]
    MULTI_NEG_NORM = [
        _phrase_parts(term) for term in NEGATIVE_NORM if " " in term
    ]

    # El indice inverso reemplaza el recorrido completo del lexicon por cada
    # token: una busqueda directa devuelve todos los aspectos compatibles.
    indexed: dict[str, set[str]] = defaultdict(set)
    for aspect, terms in ASPECTS_NORM.items():
        for term in terms:
            if term and " " not in term:
                indexed[term].add(aspect)
    SINGLE_ASPECT_INDEX = dict(indexed)

    MULTI_ASP_NORM = {
        aspect: [_phrase_parts(term) for term in terms if " " in term]
        for aspect, terms in ASPECTS_NORM.items()
    }
    ASPECT_EXCLUSIONS_NORM = {
        aspect: [_phrase_parts(term) for term in terms if " " in term]
        for aspect, terms in domain.get("aspect_context_exclusions", {}).items()
        if aspect in ASPECTS
    }
    ASPECT_POLARITY_LINKS = {
        aspect: {
            target for target in targets if target in ASPECTS and target != aspect
        }
        for aspect, targets in domain.get("aspect_polarity_links", {}).items()
        if aspect in ASPECTS
    }
    POLARITY_ASPECT_HINTS_NORM = {
        aspect: {normalize_match_text(term) for term in terms}
        for aspect, terms in domain.get("polarity_aspect_hints", {}).items()
        if aspect in ASPECTS
    }
    COMPARISON_MARKERS_NORM = [
        _phrase_parts(marker)
        for marker in domain.get("comparison_reference_markers", [])
        if len(_phrase_parts(marker)) >= 2
    ]
    ASP_MATCHER = PhraseMatcher(nlp.vocab, attr="LOWER")
    ASP_MATCH_ID_TO_NAME = {}
    for aspect_name, terms in ASPECTS.items():
        phrases = _multi_word_terms(terms)
        if not phrases:
            continue
        match_label = f"ASP__{aspect_name}"
        ASP_MATCH_ID_TO_NAME[match_label] = aspect_name
        ASP_MATCHER.add(
            match_label,
            [nlp.make_doc(term) for term in phrases],
        )

    print(f"Cargando lexicon del dominio: {DOMAIN['display_name']}...")


def require_analysis_ready() -> Any:
    """Devuelve el pipeline activo o explica como inicializarlo."""
    if nlp is None or ASP_MATCHER is None:
        raise RuntimeError(
            "El analizador no esta inicializado. Ejecuta initialize_analysis()."
        )
    return nlp


# ---------------------------------------------------------------------------
# Funciones de analisis
# ---------------------------------------------------------------------------

def find_aspect_mentions(sent):
    """Devuelve posiciones de cada aspecto mencionado.

    Conservar las posiciones permite asociar una opinion al aspecto local en
    lugar de copiar una unica polaridad a todos los aspectos del segmento.
    Cada mencion se representa como ``(inicio, fin_exclusivo)``.
    """
    mentions = defaultdict(set)
    tokens_norm = _norm_tokens(sent)
    lemmas_norm = _norm_lemmas(sent)

    # Tokens y lemas consultan un indice precompilado. Por ejemplo, tanto
    # ``enfria`` como su lema pueden apuntar directamente a ``enfriamiento``.
    for index, (token, lemma) in enumerate(zip(tokens_norm, lemmas_norm)):
        matching_aspects = (
            SINGLE_ASPECT_INDEX.get(token, set())
            | SINGLE_ASPECT_INDEX.get(lemma, set())
        )
        for aspect in matching_aspects:
            mentions[aspect].add((index, index + 1))

    require_analysis_ready()
    assert ASP_MATCHER is not None
    span_offset = getattr(sent, "start", 0)
    for match_id, start, end in ASP_MATCHER(sent):
        label = nlp.vocab.strings[match_id]
        mentions[ASP_MATCH_ID_TO_NAME[label]].add(
            (start - span_offset, end - span_offset)
        )

    for aspect_name, phrases in MULTI_ASP_NORM.items():
        for parts in phrases:
            for start, end in _phrase_spans(tokens_norm, parts):
                mentions[aspect_name].add((start, end))

    for aspect, exclusion_phrases in ASPECT_EXCLUSIONS_NORM.items():
        if not mentions.get(aspect):
            continue
        exclusion_spans = [
            span
            for parts in exclusion_phrases
            for span in _phrase_spans(tokens_norm, parts)
        ]
        if exclusion_spans:
            mentions[aspect] = {
                mention
                for mention in mentions[aspect]
                if not any(
                    _spans_overlap(mention, exclusion)
                    for exclusion in exclusion_spans
                )
            }

    return {
        aspect: sorted(spans)
        for aspect, spans in mentions.items()
        if spans
    }


def _parts_have_negation(parts):
    """Indica si una frase normalizada ya incluye una negacion."""
    return any(part in NEGATION_NORM for part in parts)


def _spans_overlap(left, right):
    """Indica si dos intervalos de tokens comparten al menos una posicion."""
    return left[0] < right[1] and right[0] < left[1]


def _phrase_candidates(tokens_norm):
    """Encuentra frases de polaridad y prioriza la coincidencia mas larga.

    Esto evita contar a la vez ``no recomiendo`` (negativa) y
    ``recomiendo`` (positiva), o ``no me gusto`` y ``me gusto``.
    """
    candidates = []
    for polarity, phrases in (
        ("pos", MULTI_POS_NORM),
        ("neg", MULTI_NEG_NORM),
    ):
        for parts in phrases:
            for start, end in _phrase_spans(tokens_norm, parts):
                candidates.append(
                    {
                        "polarity": polarity,
                        "position": start,
                        "end": end,
                        "locked": _parts_have_negation(parts),
                        "source": "phrase",
                    }
                )

    selected = []
    for candidate in sorted(
        candidates,
        key=lambda match: (
            -(match["end"] - match["position"]),
            match["position"],
            match["polarity"],
        ),
    ):
        span = (candidate["position"], candidate["end"])
        if any(
            _spans_overlap(span, (other["position"], other["end"]))
            for other in selected
        ):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda match: match["position"])


def find_polarity_matches(sent):
    """Devuelve senales de polaridad sin duplicar frases y componentes."""
    tokens_norm = _norm_tokens(sent)
    phrases = _phrase_candidates(tokens_norm)
    covered = {
        index
        for match in phrases
        for index in range(match["position"], match["end"])
    }
    matches = list(phrases)

    for index, tok in enumerate(sent):
        if index in covered:
            continue
        lemma = normalize_match_text(tok.lemma_)
        text = normalize_match_text(tok.text)
        if lemma in POSITIVE_NORM or text in POSITIVE_NORM:
            polarity = "pos"
        elif lemma in NEGATIVE_NORM or text in NEGATIVE_NORM:
            polarity = "neg"
        else:
            continue
        matches.append(
            {
                "polarity": polarity,
                "position": index,
                "end": index + 1,
                "locked": False,
                "source": "token",
            }
        )

    return sorted(
        matches,
        key=lambda match: (
            match["position"],
            match["end"],
            match["polarity"],
        ),
    )


def find_negation_positions(sent):
    """Posiciones de negacion, excluyendo locuciones como ``sin duda``."""
    tokens = _norm_tokens(sent)
    lemmas = _norm_lemmas(sent)
    positions = []
    for index, (token, lemma) in enumerate(zip(tokens, lemmas)):
        if token not in NEGATION_NORM and lemma not in NEGATION_NORM:
            continue
        # Una locucion puede tener dos o mas palabras (``sin duda``,
        # ``no tiene pierde``); se compara la ventana completa desde el token.
        if any(
            tokens[index : index + len(idiom)] == list(idiom)
            for idiom in NEGATION_IDIOMS
        ):
            continue
        positions.append(index)
    return positions


def _compose_negated_sabe_predicates(sent, matches):
    """Compone ``no sabe`` con el descriptor que gobierna su valoración.

    ``no sabe`` existe como frase negativa para casos como ``no sabe a café``.
    Cuando aparece un descriptor valorativo después (``rico`` o ``quemado``),
    conservar ambas señales produce una contradicción artificial. En ese caso
    la negación se aplica al descriptor y se emite una sola señal.
    """
    tokens = _norm_tokens(sent)
    lemmas = _norm_lemmas(sent)
    consumed: set[int] = set()
    composed = []

    for index, match in enumerate(matches):
        if index in consumed or match.get("polarity") != "neg" or not match.get("locked"):
            continue
        start = int(match["position"])
        end = int(match.get("end", start + 1))
        phrase_tokens = tokens[start:end]
        phrase_lemmas = lemmas[start:end]
        if not (
            len(phrase_tokens) == 2
            and phrase_tokens[0] == "no"
            and phrase_lemmas[1] == "saber"
        ):
            continue

        candidates = []
        for other_index, other in enumerate(matches):
            if other_index == index or other_index in consumed or other.get("locked"):
                continue
            other_start = int(other["position"])
            if not end <= other_start <= end + NEGATED_PREDICATE_WINDOW:
                continue
            between = tokens[end:other_start]
            if any(token in NEGATION_BOUNDARIES or token in NEGATION_NORM for token in between):
                continue
            candidates.append((other_start, other_index, other))
        if not candidates:
            continue

        _, other_index, descriptor = min(candidates, key=lambda item: item[0])
        effective = dict(descriptor)
        effective["polarity"] = "neg" if descriptor["polarity"] == "pos" else "pos"
        effective["locked"] = True
        effective["source"] = "negated_predicate"
        effective["negation_position"] = start
        consumed.update({index, other_index})
        composed.append(effective)

    return [
        match for index, match in enumerate(matches) if index not in consumed
    ] + composed


def is_negated(pol_pos, neg_positions, sent=None):
    """Indica si la senal esta dentro del alcance local de una negacion.

    La negacion no cruza puntuacion ni coordinaciones. Asi ``sin grumos y
    excelente sabor`` invierte ``grumos`` pero no ``excelente``.
    """
    for neg_pos in neg_positions:
        if not 0 < (pol_pos - neg_pos) <= NEGATION_WINDOW:
            continue
        if sent is None:
            return True
        between = [
            normalize_match_text(tok.text)
            for tok in sent[neg_pos + 1 : pol_pos]
        ]
        if any(token in NEGATION_BOUNDARIES for token in between):
            continue
        return True
    return False


def resolve_polarity_matches(sent):
    """Aplica negacion y devuelve las senales efectivas del segmento."""
    matches = _compose_negated_sabe_predicates(sent, find_polarity_matches(sent))
    neg_tokens = find_negation_positions(sent)
    locked_spans = [
        (match["position"], match.get("end", match["position"] + 1))
        for match in matches
        if match.get("locked")
    ]
    consumed_negations = {
        int(match["negation_position"])
        for match in matches
        if match.get("negation_position") is not None
    }
    neg_tokens = [
        position
        for position in neg_tokens
        if position not in consumed_negations
        and not any(start <= position < end for start, end in locked_spans)
    ]
    negated_keys = set()
    for neg_position in neg_tokens:
        candidates = [
            match
            for match in matches
            if not match.get("locked")
            and is_negated(match["position"], [neg_position], sent)
        ]
        if not candidates:
            continue
        closest_position = min(match["position"] for match in candidates)
        for match in candidates:
            if match["position"] == closest_position:
                negated_keys.add(
                    (
                        match["polarity"],
                        match["position"],
                        match.get("end", match["position"] + 1),
                    )
                )
    resolved = []
    any_negation_applied = bool(locked_spans)
    for match in matches:
        effective = dict(match)
        match_key = (
            match["polarity"],
            match["position"],
            match.get("end", match["position"] + 1),
        )
        if match_key in negated_keys:
            effective["polarity"] = (
                "neg" if match["polarity"] == "pos" else "pos"
            )
            effective["negated"] = True
            any_negation_applied = True
        else:
            # Una frase cerrada como ``no recomiendo`` ya incorpora la
            # negacion en el propio lexicon y tambien debe quedar auditada.
            effective["negated"] = bool(match.get("locked"))
        resolved.append(effective)
    return resolved, any_negation_applied


def _span_distance(left, right):
    """Distancia en tokens entre dos spans ``(inicio, fin_exclusivo)``."""
    if left[1] <= right[0]:
        return right[0] - left[1]
    if right[1] <= left[0]:
        return left[0] - right[1]
    return 0


def _mentions_are_coordinated(sent, left_spans, right_spans):
    """Detecta listas simples como ``aroma y sabor`` o ``frasco de un kilo``."""
    tokens = _norm_tokens(sent)
    for left in left_spans:
        for right in right_spans:
            first, second = sorted((left, right), key=lambda span: span[0])
            if second[0] - first[1] > 4:
                continue
            between = tokens[first[1] : second[0]]
            if all(token in COORDINATION_TOKENS for token in between):
                return True
    return False


def _coordination_groups(sent, mentions):
    """Componentes de aspectos coordinados que comparten una opinion."""
    aspects = sorted(mentions)
    graph = {aspect: set() for aspect in aspects}
    for index, left in enumerate(aspects):
        for right in aspects[index + 1 :]:
            if _mentions_are_coordinated(
                sent, mentions[left], mentions[right]
            ):
                graph[left].add(right)
                graph[right].add(left)

    groups = {}
    for aspect in aspects:
        if aspect in groups:
            continue
        stack = [aspect]
        component = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(graph[current] - component)
        for current in component:
            groups[current] = component
    return groups


def _dedupe_assigned_signals(signals):
    """Conserva una sola asignacion por senal, priorizando la mas local."""
    priority = {"local": 0, "coordination": 1, "tie": 2, "fallback": 3}
    unique = {}
    for signal in signals:
        key = (
            signal["polarity"],
            signal["position"],
            signal.get("end", signal["position"] + 1),
        )
        previous = unique.get(key)
        if previous is None or priority[signal["assignment"]] < priority[
            previous["assignment"]
        ]:
            unique[key] = signal
    return sorted(unique.values(), key=lambda signal: signal["position"])


def _dependency_linked_aspects(sent, mentions, signal, max_edges=2):
    """Encuentra aspectos unidos sintácticamente a una señal que también es aspecto.

    En ``el empaque se ve pirata``, ``pirata`` pertenece a originalidad pero
    califica además al sujeto ``empaque``. La distancia lineal no basta cuando
    la señal solapada se restringe primero a originalidad.
    """
    graph = defaultdict(set)
    span_start = getattr(sent, "start", 0)
    for token in sent:
        token_index = token.i - span_start
        head_index = token.head.i - span_start
        if token_index == head_index or not 0 <= head_index < len(sent):
            continue
        graph[token_index].add(head_index)
        graph[head_index].add(token_index)

    starts = range(
        int(signal["position"]),
        int(signal.get("end", signal["position"] + 1)),
    )
    distances = {position: 0 for position in starts}
    queue = list(starts)
    while queue:
        current = queue.pop(0)
        if distances[current] >= max_edges:
            continue
        for neighbor in graph[current]:
            if neighbor in distances:
                continue
            distances[neighbor] = distances[current] + 1
            queue.append(neighbor)

    return {
        aspect
        for aspect, aspect_mentions in mentions.items()
        if any(
            any(position in distances for position in range(start, end))
            for start, end in aspect_mentions
        )
    }


def _explicit_signal_targets(sent, mentions, signal):
    """Restringe frases cerradas al aspecto que forma parte de la expresión."""
    signal_span = (
        signal["position"],
        signal.get("end", signal["position"] + 1),
    )
    tokens = _norm_tokens(sent)
    lemmas = _norm_lemmas(sent)
    start, end = signal_span

    signal_terms = {
        " ".join(tokens[start:end]),
        " ".join(lemmas[start:end]),
    }
    hinted = {
        aspect
        for aspect, hints in POLARITY_ASPECT_HINTS_NORM.items()
        if aspect in mentions and bool(signal_terms & hints)
    }
    if hinted:
        return hinted

    # ``no sabe ... a dulce`` valora el complemento (dulzor), no el verbo
    # genérico ``sabe`` que también figura como sinónimo de sabor.
    if (
        signal.get("locked")
        and end - start == 2
        and tokens[start] == "no"
        and lemmas[start + 1] == "saber"
    ):
        following = []
        for aspect, aspect_mentions in mentions.items():
            if aspect == "sabor":
                continue
            for mention in aspect_mentions:
                if not end <= mention[0] <= end + NEGATED_PREDICATE_WINDOW:
                    continue
                between = tokens[end:mention[0]]
                if any(token in NEGATION_BOUNDARIES or token in NEGATION_NORM for token in between):
                    continue
                following.append((mention[0], aspect))
        if following:
            closest = min(position for position, _aspect in following)
            return {
                aspect for position, aspect in following if position == closest
            }

    overlapping = {
        aspect
        for aspect, aspect_mentions in mentions.items()
        if any(_spans_overlap(signal_span, mention) for mention in aspect_mentions)
    }
    if overlapping and not signal.get("locked"):
        allowed_links = {
            target
            for aspect in overlapping
            for target in ASPECT_POLARITY_LINKS.get(aspect, set())
        }
        linked = _dependency_linked_aspects(sent, mentions, signal)
        return overlapping | (linked & allowed_links)
    return overlapping


def _forward_scoped_signal_positions(sent, signals):
    """Posiciones de senales dentro del marco ``lo (unico) X es que ...``.

    En este marco la valoracion introduce la clausula que sigue a ``es que`` y
    no debe atribuirse a un aspecto anterior. En ``me encanto el sabor lo unico
    malo es que la publicidad`` el ``malo`` habla de la publicidad, no del
    sabor mencionado antes. Estas senales solo podran asignarse hacia adelante.
    """
    tokens = _norm_tokens(sent)
    forward = set()
    for signal in signals:
        position = int(signal["position"])
        end = int(signal.get("end", position + 1))
        if tokens[end : end + 2] != ["es", "que"]:
            continue
        if "lo" in tokens[max(0, position - 2) : position]:
            forward.add(position)
    return forward


def assign_signals_to_aspects(sent, mentions, signals):
    """Asocia cada senal al aspecto mas cercano y a sus coordinados.

    Si el segmento solo contiene una polaridad pero una relacion local no se
    puede establecer, se conserva un fallback global con menor confianza.
    """
    assigned = defaultdict(list)
    groups = _coordination_groups(sent, mentions)
    forward_positions = _forward_scoped_signal_positions(sent, signals)
    signal_polarities = {signal["polarity"] for signal in signals}
    earliest_aspect_start = min(
        span[0]
        for aspect_mentions in mentions.values()
        for span in aspect_mentions
    )
    latest_aspect_end = max(
        span[1]
        for aspect_mentions in mentions.values()
        for span in aspect_mentions
    )

    def is_global_scope(signal):
        """Reconoce opiniones al inicio o final que pueden abarcar la lista."""
        is_prefix = (
            signal.get("end", signal["position"] + 1)
            <= earliest_aspect_start
            and signal["position"] <= 5
        )
        is_suffix = (
            signal["position"] >= latest_aspect_end
            and signal["position"] - latest_aspect_end
            <= MAX_LOCAL_SIGNAL_DISTANCE
        )
        return is_prefix or is_suffix

    for signal in signals:
        signal_span = (
            signal["position"],
            signal.get("end", signal["position"] + 1),
        )
        # Una senal con alcance hacia adelante solo ve los aspectos que
        # aparecen despues de ``es que``; los previos no son su objetivo.
        is_forward = signal["position"] in forward_positions
        active_mentions = mentions
        if is_forward:
            active_mentions = {
                aspect: [span for span in spans if span[0] >= signal_span[1]]
                for aspect, spans in mentions.items()
            }
            active_mentions = {
                aspect: spans for aspect, spans in active_mentions.items() if spans
            }

        explicit_targets = _explicit_signal_targets(sent, active_mentions, signal)
        if explicit_targets:
            for aspect in explicit_targets:
                copied = dict(signal)
                copied["assignment"] = "local"
                assigned[aspect].append(copied)
            continue

        distances = {
            aspect: min(
                _span_distance(signal_span, mention)
                for mention in aspect_mentions
            )
            for aspect, aspect_mentions in active_mentions.items()
        }
        if not distances:
            continue
        min_distance = min(distances.values())
        closest = [
            aspect
            for aspect, distance in distances.items()
            if distance == min_distance
        ]

        if min_distance <= MAX_LOCAL_SIGNAL_DISTANCE:
            assignment = "tie" if len(closest) > 1 else "local"
            targets = set(closest)
            if not is_forward:
                for aspect in closest:
                    targets.update(groups.get(aspect, {aspect}))
            for aspect in targets:
                copied = dict(signal)
                copied["assignment"] = (
                    assignment
                    if aspect in closest
                    else "coordination"
                )
                assigned[aspect].append(copied)
        elif len(signal_polarities) == 1 and is_global_scope(signal):
            for aspect in closest:
                copied = dict(signal)
                copied["assignment"] = "fallback"
                assigned[aspect].append(copied)

    # Un unico tono global puede gobernar aspectos sin senal local. Se conserva
    # como evidencia debil, no como una deteccion igualmente segura.
    if signals and len(signal_polarities) == 1:
        usable_signals = [
            signal for signal in signals
            if signal["position"] not in forward_positions
        ]
        global_signals = [
            signal for signal in usable_signals if is_global_scope(signal)
        ]
        fallback_signals = global_signals
        if len(mentions) == 1:
            # En una cláusula sin contraste y con un único aspecto, una
            # recomendación final puede estar a más de cuatro tokens:
            # ``si te gusta el café fuerte, es muy recomendable``.
            fallback_signals = usable_signals
        for aspect, aspect_mentions in mentions.items():
            if assigned.get(aspect):
                continue
            if not fallback_signals:
                continue
            closest_signal = min(
                fallback_signals,
                key=lambda signal: min(
                    _span_distance(
                        (
                            signal["position"],
                            signal.get("end", signal["position"] + 1),
                        ),
                        mention,
                    )
                    for mention in aspect_mentions
                ),
            )
            copied = dict(closest_signal)
            copied["assignment"] = "fallback"
            assigned[aspect].append(copied)

    return {
        aspect: _dedupe_assigned_signals(aspect_signals)
        for aspect, aspect_signals in assigned.items()
    }


def _aspect_polarity_results(signals):
    """Convierte senales locales en una o dos posturas auditables.

    ``has_negation`` se calcula con las senales asignadas a este aspecto, no
    con toda la oracion. Asi una negacion cercana a ``ruido`` no se atribuye
    tambien a ``sabor``.
    """
    aspect_has_negation = any(
        signal.get("negated") or signal.get("locked")
        for signal in signals
    )
    if not signals:
        return [
            {
                "polarity": "neu",
                "confidence": 0.3,
                "has_negation": False,
            }
        ]

    counts = {
        polarity: sum(
            1 for signal in signals if signal["polarity"] == polarity
        )
        for polarity in ("pos", "neg")
    }
    active = [polarity for polarity, count in counts.items() if count]
    mixed = len(active) > 1
    results = []
    for polarity in active:
        relevant = [
            signal for signal in signals if signal["polarity"] == polarity
        ]
        confidence = min(1.0, 0.5 + 0.15 * len(relevant))
        assignments = {signal["assignment"] for signal in relevant}
        if "fallback" in assignments:
            confidence *= 0.75
        elif "tie" in assignments:
            confidence *= 0.85
        if mixed:
            confidence *= 0.85
        results.append(
            {
                "polarity": polarity,
                "confidence": round(max(0.3, confidence), 3),
                "has_negation": aspect_has_negation,
            }
        )
    return results


def _comparison_clause_start(sent):
    """Posicion donde empieza una clausula sobre OTRO producto, o ``None``.

    Cuando una resena contrasta el producto reseñado con otro
    (``este cafe sabe bueno y el nescafe normal sabe malo``), la valoracion de
    la clausula comparativa pertenece a la otra entidad y no debe atribuirse al
    producto evaluado. Solo se corta si existe una clausula previa del producto
    reseñado (``start > 0``): asi nunca se descarta la opinion propia cuando la
    comparacion abre la oracion (``comparado con X, este cafe...``).
    """
    if not COMPARISON_MARKERS_NORM:
        return None
    tokens_norm = _norm_tokens(sent)
    starts = [
        start
        for parts in COMPARISON_MARKERS_NORM
        for start, _end in _phrase_spans(tokens_norm, parts)
        if start > 0
    ]
    return min(starts) if starts else None


def analyze_aspects_in_segment(sent):
    """Devuelve polaridad y confianza locales para cada aspecto detectado."""
    comparison_start = _comparison_clause_start(sent)
    if comparison_start is not None:
        sent = sent[:comparison_start]
    mentions = find_aspect_mentions(sent)
    if not mentions:
        return {}
    signals, _ = resolve_polarity_matches(sent)
    assigned = assign_signals_to_aspects(sent, mentions, signals)
    return {
        aspect: _aspect_polarity_results(assigned.get(aspect, []))
        for aspect in mentions
    }


def split_adversative_segments(sent):
    """Divide una oracion en segmentos por conectores adversativos.

    Esto evita mezclar polaridades de frases como:
    "enfria bien pero hace ruido".
    Los segmentos reutilizan los tokens y lemas del Doc original para evitar
    una segunda ejecucion de spaCy.
    """
    if not sent.text.strip():
        return []

    tokens = _norm_tokens(sent)
    connector_parts = sorted(
        (connector.split() for connector in ADVERSATIVE_CONNECTORS),
        key=len,
        reverse=True,
    )
    connector_spans = []
    index = 0
    while index < len(tokens):
        matched = None
        for parts in connector_parts:
            if tokens[index : index + len(parts)] == parts:
                matched = (index, index + len(parts))
                break
        if matched is None:
            index += 1
            continue
        connector_spans.append(matched)
        index = matched[1]

    if not connector_spans:
        return [sent]

    # Se devuelven Spans del Doc original. De este modo se conservan lemas y
    # dependencias y se evita ejecutar el costoso pipeline de spaCy otra vez.
    segments = []
    start = 0
    for connector_start, connector_end in connector_spans:
        end = connector_start
        while end > start and tokens[end - 1] in {",", ";", ":", "."}:
            end -= 1
        if end > start:
            segments.append(sent[start:end])
        start = connector_end
        while start < len(tokens) and tokens[start] in {",", ";", ":", "."}:
            start += 1
    if start < len(tokens):
        segments.append(sent[start:])
    return segments


def _has_negative_answer(sent) -> bool:
    """Reconoce respuestas breves que niegan la pregunta inmediatamente anterior."""
    tokens = [
        token
        for token in _norm_tokens(sent)
        if token and any(character.isalnum() for character in token)
    ]
    return any(tokens[:len(prefix)] == list(prefix) for prefix in NEGATIVE_ANSWER_PREFIXES)


def process_doc(doc):
    """Extrae aspectos desde un Doc ya procesado por spaCy."""
    results = []
    sentences = list(doc.sents)
    for sentence_index, sent in enumerate(sentences):
        negative_answer = (
            sent.text.rstrip().endswith("?")
            and sentence_index + 1 < len(sentences)
            and _has_negative_answer(sentences[sentence_index + 1])
        )
        for segment in split_adversative_segments(sent):
            aspect_results = analyze_aspects_in_segment(segment)
            if not aspect_results:
                continue
            excerpt = segment.text.strip()[:200]

            # Un aspecto puede producir una postura positiva y otra negativa
            # si el texto expresa ambas. 06_trust.py ya conserva las dos ramas
            # sin contar dos veces al mismo usuario dentro de cada postura.
            for aspect, polarities in aspect_results.items():
                for result in polarities:
                    polarity = result["polarity"]
                    if negative_answer and polarity in {"pos", "neg"}:
                        polarity = "neg" if polarity == "pos" else "pos"
                    results.append(
                        {
                            "aspect": aspect,
                            "polarity": polarity,
                            "extraction_confidence": result["confidence"],
                            "sentence_excerpt": excerpt,
                            "has_negation": result["has_negation"] or negative_answer,
                        }
                    )
    return results


def process_review(text):
    """Procesa una resena individual; es la API comoda para pruebas y uso manual."""
    if not text or not text.strip():
        return []
    pipeline = require_analysis_ready()
    return process_doc(pipeline(text))


def process_reviews(texts: Iterable[str]):
    """Procesa muchas resenas con ``nlp.pipe`` para aprovechar el batching."""
    pipeline = require_analysis_ready()
    safe_texts = [str(text or "") for text in texts]
    return [
        process_doc(doc) if text.strip() else []
        for text, doc in zip(
            safe_texts,
            pipeline.pipe(safe_texts, batch_size=NLP_PIPE_BATCH_SIZE),
        )
    ]


# ---------------------------------------------------------------------------
# Escritura en Supabase
# ---------------------------------------------------------------------------

def staging_setup_error(exc):
    """Crea un error accionable cuando todavia no se instalo el staging."""
    return RuntimeError(
        "Falta instalar la reconstruccion atomica de review_aspects. "
        f"Ejecuta {STAGING_MIGRATION_PATH} en Supabase SQL Editor."
    )


def begin_extraction_run(sb, dataset_key, run_id):
    """Registra una reconstruccion sin tocar todavia el resultado vigente."""
    try:
        (
            sb.table("review_aspect_runs")
            .insert({"run_id": run_id, "dataset_key": dataset_key})
            .execute()
        )
    except APIError as exc:
        if "review_aspect_runs" in str(exc):
            raise staging_setup_error(exc) from exc
        raise


def discard_extraction_run(sb, run_id):
    """Elimina staging incompleto; la cascada conserva limpia la tabla auxiliar."""
    sb.table("review_aspect_runs").delete().eq("run_id", run_id).execute()


def dedupe_rows(rows):
    """Evita duplicados dentro del mismo lote antes del upsert/insert."""
    unique = []
    seen = set()
    for row in rows:
        key = tuple(row.get(field) for field in UNIQUE_FIELDS)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def chunked(rows, size):
    """Divide la escritura para reducir payloads y cortes HTTP/2."""
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def is_transient_write_error(exc):
    """Identifica errores de red/timeout que permiten repetir un upsert."""
    if isinstance(exc, httpx.TransportError):
        return True

    code = str(getattr(exc, "code", "") or "")
    message = str(exc).lower()
    return (
        code in {"57014", "PGRST003"}
        or "streamreset" in message
        or "stream reset" in message
        or "timed out" in message
        or "timeout" in message
        or "connection reset" in message
        or "server disconnected" in message
    )


def upsert_chunk_with_retry(
    sb,
    chunk,
    *,
    table_name=STAGING_TABLE,
    on_conflict=STAGING_ON_CONFLICT,
):
    """Reintenta de forma segura: el upsert es idempotente por su clave unica."""
    for attempt in range(1, MAX_WRITE_RETRIES + 1):
        try:
            (
                sb.table(table_name)
                .upsert(chunk, on_conflict=on_conflict)
                .execute()
            )
            return
        except APIError as exc:
            if exc.code == "42P10":
                raise RuntimeError(
                    f"{table_name} no tiene el indice unico requerido para el "
                    f"upsert ({on_conflict}). Ejecuta {STAGING_MIGRATION_PATH} "
                    "en Supabase antes de reintentar."
                ) from exc
            if table_name in str(exc) and "does not exist" in str(exc).lower():
                raise staging_setup_error(exc) from exc
            if not is_transient_write_error(exc) or attempt == MAX_WRITE_RETRIES:
                raise
        except Exception as exc:
            if not is_transient_write_error(exc) or attempt == MAX_WRITE_RETRIES:
                raise

        wait_seconds = min(8, 2 ** (attempt - 1))
        print(
            "  AVISO: corte transitorio guardando review_aspects. "
            f"Reintento {attempt}/{MAX_WRITE_RETRIES} en {wait_seconds}s...",
            file=sys.stderr,
        )
        time.sleep(wait_seconds)


def save_batch(sb, batch):
    """Guarda staging por lotes pequenos, reintentables e idempotentes."""
    batch = dedupe_rows(batch)
    if not batch:
        return

    for chunk in chunked(batch, WRITE_BATCH_SIZE):
        upsert_chunk_with_retry(sb, chunk)


def finalize_extraction_run(sb, dataset_key, run_id):
    """Activa el resultado nuevo dentro de una unica transaccion PostgreSQL."""
    for attempt in range(1, MAX_WRITE_RETRIES + 1):
        try:
            (
                sb.rpc(
                    FINALIZE_RPC,
                    {"p_dataset_key": dataset_key, "p_run_id": run_id},
                )
                .execute()
            )
            return
        except APIError as exc:
            if FINALIZE_RPC in str(exc) or "PGRST202" in str(exc):
                raise staging_setup_error(exc) from exc
            if not is_transient_write_error(exc) or attempt == MAX_WRITE_RETRIES:
                raise
        except Exception as exc:
            if not is_transient_write_error(exc) or attempt == MAX_WRITE_RETRIES:
                raise

        wait_seconds = min(8, 2 ** (attempt - 1))
        print(
            "  AVISO: corte transitorio activando review_aspects. "
            f"Reintento {attempt}/{MAX_WRITE_RETRIES} en {wait_seconds}s...",
            file=sys.stderr,
        )
        time.sleep(wait_seconds)


def load_settings(dataset_key: str | None = None):
    """Valida las variables necesarias cuando comienza la ejecucion real."""
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


def fetch_review_page(sb, dataset_key, included_product_ids, last_id, page_size):
    """Lee la pagina siguiente mediante cursor estable sobre la clave ``id``."""
    return (
        sb.table("reviews_clean")
        .select("id,dataset_key,review_id,product_id,content")
        .eq("dataset_key", dataset_key)
        .in_("product_id", sorted(included_product_ids))
        .gt("id", last_id)
        .order("id")
        .limit(page_size)
        .execute()
        .data
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def main(argv: list[str] | tuple[str, ...] = ()):
    """Ejecuta la extraccion completa y activa el resultado solo al terminar."""
    parser = argparse.ArgumentParser(
        description="Extrae aspectos y polaridad para un dataset revisado.",
    )
    parser.add_argument(
        "--dataset-key",
        default=os.environ.get("DATASET_KEY"),
        help="Dataset a procesar. Si se omite, usa DATASET_KEY de .env.",
    )
    args = parser.parse_args(argv)
    supabase_url, supabase_key, dataset_key = load_settings(args.dataset_key)
    # load_domain_config resuelve el perfil a partir del dataset activo.
    os.environ["DATASET_KEY"] = dataset_key
    initialize_analysis()

    sb = create_client(supabase_url, supabase_key)
    included_product_ids = require_included_product_ids(
        sb,
        dataset_key,
        stage_name="05_aspects.py",
    )
    run_id = str(uuid.uuid4())
    begin_extraction_run(sb, dataset_key, run_id)

    print("Leyendo reviews_clean...")
    print(f"Productos incluidos por revision humana: {len(included_product_ids)}")

    page_size = 500
    last_id = 0
    total_reviews = 0
    total_extractions = 0
    by_aspect = {}
    by_polarity = {"pos": 0, "neg": 0, "neu": 0}

    try:
        while True:
            # La paginacion por cursor no se vuelve mas costosa al avanzar y
            # tampoco desplaza filas si cambia el numero total del dataset.
            rows = fetch_review_page(
                sb,
                dataset_key,
                included_product_ids,
                last_id,
                page_size,
            )
            if not rows:
                break

            batch = []
            page_extractions = process_reviews(
                row.get("content") or "" for row in rows
            )
            for row, extractions in zip(rows, page_extractions):
                total_reviews += 1
                for extraction in extractions:
                    staging_row = dict(extraction)
                    staging_row["run_id"] = run_id
                    staging_row["dataset_key"] = row["dataset_key"]
                    staging_row["review_id"] = row["review_id"]
                    staging_row["product_id"] = row["product_id"]
                    batch.append(staging_row)
                    total_extractions += 1
                    aspect = staging_row["aspect"]
                    polarity = staging_row["polarity"]
                    by_aspect[aspect] = by_aspect.get(aspect, 0) + 1
                    by_polarity[polarity] += 1

            save_batch(sb, batch)
            last_id = rows[-1]["id"]
            print(
                f"  reviews procesadas: {total_reviews}, "
                f"extracciones acumuladas: {total_extractions}"
            )

        # Solo al finalizar todas las paginas PostgreSQL reemplaza la version
        # anterior dentro de una transaccion. Un fallo previo no la modifica.
        finalize_extraction_run(sb, dataset_key, run_id)
    except Exception:
        try:
            discard_extraction_run(sb, run_id)
        except Exception as cleanup_error:
            print(
                "AVISO: no se pudo limpiar el staging fallido "
                f"{run_id}: {cleanup_error}",
                file=sys.stderr,
            )
        raise

    print()
    print("=" * 60)
    print(f"Resenas procesadas:        {total_reviews}")
    print(f"Total de extracciones:     {total_extractions}")
    print(f"Promedio aspectos/resena:  {total_extractions / max(1, total_reviews):.2f}")
    print()
    print("Por aspecto:")
    for asp, c in sorted(by_aspect.items(), key=lambda x: -x[1]):
        print(f"  {asp:15s}: {c:6d}  ({c / total_extractions * 100:.1f}%)")
    print()
    print("Por polaridad:")
    for pol, c in by_polarity.items():
        print(f"  {pol}: {c:6d}  ({c / max(1, total_extractions) * 100:.1f}%)")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main(tuple(sys.argv[1:]))
    except (ProductReviewSetupError, ProductReviewPendingError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except (OSError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if "es_core_news_md" in str(e):
            print(
                "Ejecuta: python -m spacy download es_core_news_md",
                file=sys.stderr,
            )
        sys.exit(1)
