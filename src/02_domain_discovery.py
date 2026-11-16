"""
02_domain_discovery.py - Descubrimiento asistido de aspectos para un dominio.

Lee las resenas del DATASET_KEY activo, obtiene la categoria desde datasets y
calcula terminos candidatos con metricas simples:
  - cantidad de resenas que mencionan el termino
  - cantidad de oraciones donde aparece
  - polaridad aproximada por lexicon
  - ejemplos de frases para auditoria del experto

El resultado no reemplaza al experto: produce evidencia para decidir que
aspectos finales entran en config/domains/<dominio>.json.

Uso:
    # Desde PowerShell, usar el Python del entorno virtual del proyecto.
    .\venv\Scripts\python.exe src\02_domain_discovery.py
    .\venv\Scripts\python.exe src\02_domain_discovery.py --limit 3000 --top-terms 120
    
    Se sube el limit en caso de muchas resenias
    Se sube el top-terms si se quiere mas evidencia para el experto
    se agrega draft-aspects para generar mas candidatos en el borrador config/domains/<dominio>.draft.json

    # Si aparece "ModuleNotFoundError: No module named 'supabase'",
    # falta instalar dependencias en ese entorno o se esta usando otro Python:
    .\venv\Scripts\python.exe -m pip install -r requirements.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
try:
    from supabase import create_client
except ModuleNotFoundError:
    print(
        "ERROR: falta el modulo 'supabase'.\n"
        "Instala dependencias con:\n"
        r"  .\venv\Scripts\python.exe -m pip install -r requirements.txt" "\n"
        "Y ejecuta este script con:\n"
        r"  .\venv\Scripts\python.exe src\02_domain_discovery.py",
        file=sys.stderr,
    )
    sys.exit(1)

from domain_config import DATASETS_TABLE, domain_artifact_dir, domain_key_from_category_label
from product_scope import (
    ProductReviewPendingError,
    ProductReviewSetupError,
    require_included_product_ids,
)


# ---------------------------------------------------------------------------
# Rutas y configuración general
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_LEXICON_PATH = REPO_ROOT / "config" / "lexicon.json"
DOMAIN_DIR = REPO_ROOT / "config" / "domains"

# La ruta explícita permite ejecutar el script desde cualquier directorio.
load_dotenv(REPO_ROOT / ".env")

# Stopwords comunes del espanol usadas para filtrar terminos candidatos.
# Justificacion metodologica: estas palabras tienen alta frecuencia gramatical,
# pero baja capacidad descriptiva del dominio; por eso no sirven para construir
# aspectos de calidad. No se eliminan de la base limpia, solo de esta etapa de
# descubrimiento de candidatos.
STOPWORDS = {
    "ahi", "algo", "algun", "alguna", "algunas", "alguno", "algunos", "ante",
    "antes", "asi", "aunque", "bien", "cada", "casi", "como", "con", "contra",
    "cual", "cuando", "de", "del", "desde", "despues", "donde", "dos", "el",
    "ella", "ellas", "ellos", "en", "entre", "era", "eres", "es", "esa",
    "esas", "ese", "eso", "esos", "esta", "estan", "estar", "este", "esto",
    "estos", "fue", "han", "hasta", "hay", "la", "las", "le", "les", "lo",
    "los", "mas", "me", "mi", "mis", "muy", "nada", "no", "nos", "para",
    "pero", "por", "porque", "que", "se", "ser", "si", "sin", "sobre",
    "son", "su", "sus", "tambien", "tan", "te", "tiene", "tienen", "todo",
    "todos", "tu", "un", "una", "unas", "uno", "unos", "y", "ya",
}

# Terminos genericos o valorativos que tampoco definen aspectos del producto.
# Esta lista es auditable y ajustable por dominio: si un termino excluido fuera
# relevante para otro corpus, se puede quitar y volver a generar el reporte.
GENERIC_EXCLUDE = {
    "compra", "producto", "productos", "cosa", "cosas", "dia", "dias",
    "mes", "meses", "momento", "pedido",
    "paquete", "parte", "persona", "recomendado", "recomendable", "super",
    "excelente", "exelente",
}

# Verbos funcionales generales que suelen expresar aspectos del producto.
# No se incluyen todos los verbos para evitar ruido ("comprar", "llegar",
# "tener", etc.). Esta lista blanca captura acciones tecnicas frecuentes en
# resenas de distintos dominios: aires, celulares, electrodomesticos, etc.
FUNCTIONAL_VERB_LEMMAS = {
    "abrir", "aguantar", "apagar", "arrancar", "aspirar", "bloquear",
    "calentar", "cargar", "cerrar", "climatizar", "conectar", "congelar",
    "consumir", "cortar", "cubrir", "descargar", "durar", "enfocar",
    "enfriar", "fallar", "filtrar", "funcionar", "gastar", "gotear",
    "grabar", "helar", "instalar", "lavar", "limpiar", "perder",
    "prender", "recalentar", "refrescar", "responder",
    "romper", "secar", "sonar", "tardar", "tirar", "trabar", "vibrar",
}


# ---------------------------------------------------------------------------
# Normalización y carga de configuración
# ---------------------------------------------------------------------------
def normalize(value: str) -> str:
    """Normaliza para comparar terminos y generar claves de aspecto.

    No reemplaza la normalizacion de 01_clean.py. El script 01 limpia el texto
    de las resenas y conserva acentos para NLP. Esta funcion, en cambio, quita
    acentos y signos porque necesita comparar palabras y crear claves estables
    como "camara_frontal" o "duracion_bateria".
    """
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    ascii_value = ascii_value.lower()
    return re.sub(r"[^a-z0-9]+", " ", ascii_value).strip()


def keyify(value: str) -> str:
    """Convierte un término visible en una clave válida y estable para JSON."""
    return re.sub(r"[^a-z0-9]+", "_", normalize(value)).strip("_")


def load_base_lexicon() -> dict[str, Any]:
    """Carga el vocabulario global que orienta la polaridad exploratoria."""
    with open(BASE_LEXICON_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Lectura de datos desde Supabase
# ---------------------------------------------------------------------------
def get_dataset_meta(sb: Any, dataset_key: str) -> dict[str, Any]:
    """Obtiene la categoría y el sitio asociados al dataset activo."""
    rows = (
        sb.table(DATASETS_TABLE)
        .select("dataset_key,category_id,category_label,site_id")
        .eq("dataset_key", dataset_key)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise RuntimeError(f"No existe DATASET_KEY={dataset_key!r} en {DATASETS_TABLE}.")
    return rows[0]

def fetch_reviews(
    sb: Any,
    table: str,
    dataset_key: str,
    limit: int,
    page_size: int,
    included_product_ids: set[str],
) -> list[dict[str, Any]]:
    """Lee reseñas de productos aprobados con paginación reproducible.

    ``last_id`` funciona como cursor: cada página empieza después de la última
    fila recibida. Esto mantiene el orden y evita los desplazamientos propios de
    la paginación con ``offset``.
    """
    rows_out: list[dict[str, Any]] = []
    last_id = 0
    columns = "id,review_id,product_id,content"
    while len(rows_out) < limit:
        # El filtro de productos garantiza que un producto excluido en 01b no
        # aporte términos al perfil del dominio.
        rows = (
            sb.table(table)
            .select(columns)
            .eq("dataset_key", dataset_key)
            .in_("product_id", sorted(included_product_ids))
            .gt("id", last_id)
            .order("id")
            .range(0, page_size - 1)
            .execute()
            .data
        )
        if not rows:
            break
        for row in rows:
            # Las filas vacías cuentan para avanzar el cursor, pero no forman
            # parte de la muestra lingüística.
            if row.get("content"):
                rows_out.append(row)
                if len(rows_out) >= limit:
                    break
        last_id = int(rows[-1]["id"])
        # Una página incompleta indica que PostgreSQL ya entregó el final.
        if len(rows) < page_size:
            break
    return rows_out

# ---------------------------------------------------------------------------
# Extracción lingüística
# ---------------------------------------------------------------------------
def load_spacy_model():
    """Carga spaCy y permite fallback solo si falta el paquete o el modelo.

    Un error diferente se propaga porque podría indicar una instalación dañada
    o falta de recursos, situaciones que no conviene presentar como normales.
    """
    try:
        import spacy
    except ModuleNotFoundError:
        return None
    try:
        return spacy.load("es_core_news_md")
    except OSError as exc:
        message = str(exc).lower()
        if "e050" in message or "can't find model" in message:
            return None
        raise


def split_sentences_fallback(text: str) -> list[str]:
    """Separa oraciones con puntuación básica cuando spaCy no está disponible."""
    return [s.strip() for s in re.split(r"[.!?;\n]+", text) if s.strip()]


def token_terms_fallback(sentence: str) -> set[str]:
    """Extrae unigramas y bigramas con una estrategia simple y auditable."""
    # Primero se reconocen palabras Unicode; normalize quita luego los acentos
    # para que "cámara" y "camara" se consoliden en el mismo candidato.
    tokens = [normalize(t) for t in re.findall(r"[^\W_]+", sentence, re.UNICODE)]
    tokens = [t for t in tokens if len(t) >= 3 and t not in STOPWORDS]
    terms = set(tokens)
    terms.update(
        f"{tokens[index]} {tokens[index + 1]}"
        for index in range(len(tokens) - 1)
    )
    return {term for term in terms if len(term) >= 3}


def sentence_terms_spacy(sent: Any) -> set[str]:
    """Extrae lemas individuales y frases nominales desde una oración spaCy."""
    terms = set()
    # Sustantivos y adjetivos suelen nombrar propiedades. Solo se aceptan los
    # verbos de la lista blanca porque los verbos generales agregan mucho ruido.
    for token in sent:
        lemma = normalize(token.lemma_ or token.text)
        is_nominal_candidate = token.pos_ in {"NOUN", "PROPN", "ADJ"}
        is_functional_verb = token.pos_ == "VERB" and lemma in FUNCTIONAL_VERB_LEMMAS
        if (
            (is_nominal_candidate or is_functional_verb)
            and len(lemma) >= 3
            and lemma not in STOPWORDS
            and not token.is_stop
            and not token.is_punct
        ):
            terms.add(lemma)

    # Los noun_chunks conservan expresiones informativas como "batería interna"
    # que perderían significado si solo se guardaran palabras independientes.
    for chunk in sent.noun_chunks:
        clean_tokens = []
        for token in chunk:
            lemma = normalize(token.lemma_ or token.text)
            if (
                token.pos_ in {"NOUN", "PROPN", "ADJ"}
                and len(lemma) >= 3
                and lemma not in STOPWORDS
                and not token.is_stop
                and not token.is_punct
            ):
                clean_tokens.append(lemma)
        if 1 <= len(clean_tokens) <= 3:
            terms.add(" ".join(clean_tokens))

    return terms

def sentiment_for_sentence(sentence_norm: str, positive: set[str], negative: set[str]) -> str:
    """Calcula una señal exploratoria; la polaridad ABSA final se resuelve en 05.

    Esta métrica ayuda a leer el reporte, pero no se usa como clasificación final
    porque aquí no se modelan el alcance local de negaciones ni múltiples aspectos.
    """
    pos = sum(1 for term in positive if term and term in sentence_norm)
    neg = sum(1 for term in negative if term and term in sentence_norm)
    if pos > neg:
        return "pos"
    if neg > pos:
        return "neg"
    return "neu"

def is_candidate_term(term: str, excluded: set[str]) -> bool:
    """Descarta candidatos vacíos, numéricos o formados solo por ruido."""
    if not term or term in excluded:
        return False
    tokens = term.split()
    if not tokens or all(token in excluded for token in tokens):
        return False
    if all(token.isdigit() for token in tokens):
        return False
    return True

def build_candidates(
    reviews: list[dict[str, Any]],
    positive: set[str],
    negative: set[str],
    excluded: set[str],
    nlp: Any,
) -> list[dict[str, Any]]:
    """Construye y ordena candidatos a partir de las reseñas seleccionadas.

    Para cada término conserva dos frecuencias diferentes: cantidad de oraciones
    y cantidad de reseñas únicas. También guarda hasta tres ejemplos breves para
    que el experto pueda verificar el contexto original.
    """
    # defaultdict crea el acumulador la primera vez que aparece cada término.
    # El set de reviews impide contar dos veces una misma reseña.
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "sentences": 0,
            "reviews": set(),
            "pos": 0,
            "neg": 0,
            "neu": 0,
            "examples": [],
        }
    )

    if nlp:
        # Procesar por lotes reduce considerablemente el coste fijo de spaCy.
        texts = [(row.get("content") or "")[:5000] for row in reviews]
        documents = nlp.pipe(texts, batch_size=64)
        review_documents = zip(reviews, documents)
    else:
        review_documents = ((row, None) for row in reviews)

    for row, doc in review_documents:
        text = row.get("content") or ""
        review_id = row.get("review_id")

        if doc is not None:
            sent_iter = [(sent.text.strip(), sentence_terms_spacy(sent)) for sent in doc.sents]
        else:
            sent_iter = [
                (sentence, token_terms_fallback(sentence))
                for sentence in split_sentences_fallback(text)
            ]

        for sentence, terms in sent_iter:
            if not sentence or not terms:
                continue
            terms = {term for term in terms if is_candidate_term(term, excluded)}
            if not terms:
                continue
            sentence_norm = normalize(sentence)
            sentiment = sentiment_for_sentence(sentence_norm, positive, negative)
            for term in terms:
                data = stats[term]
                data["sentences"] += 1
                data["reviews"].add(review_id)
                data[sentiment] += 1
                # Tres ejemplos dan contexto sin inflar excesivamente el reporte.
                if len(data["examples"]) < 3:
                    data["examples"].append(sentence[:220])

    # Los sets internos no se serializan en JSON; aquí se convierten en métricas.
    rows = []
    for term, data in stats.items():
        review_count = len(data["reviews"])
        sentences = data["sentences"]
        if review_count == 0:
            continue
        rows.append({
            "term": term,
            "aspect_key_sugerido": keyify(term),
            "reviews_mencion": review_count,
            "oraciones_mencion": sentences,
            "pos": data["pos"],
            "neg": data["neg"],
            "neu": data["neu"],
            # Rango [-1, 1]: negativo, equilibrado o positivo en forma exploratoria.
            "polaridad_neta": round((data["pos"] - data["neg"]) / max(1, data["pos"] + data["neg"]), 3),
            "examples": data["examples"],
        })

    # Se prioriza cobertura entre reseñas y se desempata por menciones totales.
    rows.sort(key=lambda r: (r["reviews_mencion"], r["oraciones_mencion"]), reverse=True)
    return rows

# ---------------------------------------------------------------------------
# Escritura de reportes y borrador de configuración
# ---------------------------------------------------------------------------
def _atomic_text_write(path: Path, writer: Any, *, newline: str | None = None) -> None:
    """Evita dejar un archivo final truncado si la escritura se interrumpe.

    Primero escribe un temporal en la misma carpeta. ``os.replace`` publica el
    resultado completo de una vez y el bloque ``finally`` limpia cualquier
    temporal restante cuando ocurre una excepción.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline=newline,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            writer(temporary)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def write_reports(
    domain_key: str,
    rows: list[dict[str, Any]],
    meta: dict[str, Any],
    artifact_suffix: str = "",
) -> tuple[Path, Path]:
    """Exporta la misma evidencia en JSON procesable y CSV auditable."""
    reports_dir = domain_artifact_dir(domain_key, "reportes")
    suffix = f"_{artifact_suffix}" if artifact_suffix else ""
    json_path = reports_dir / f"domain_discovery_{domain_key}{suffix}.json"
    csv_path = reports_dir / f"domain_discovery_{domain_key}{suffix}.csv"

    _atomic_text_write(
        json_path,
        lambda file: json.dump(
            {"dataset": meta, "candidates": rows},
            file,
            ensure_ascii=False,
            indent=2,
        ),
    )

    def write_csv(file: Any) -> None:
        # En CSV los ejemplos se unen en una sola celda; el JSON conserva la lista.
        fieldnames = [
            "term", "aspect_key_sugerido", "reviews_mencion", "oraciones_mencion",
            "pos", "neg", "neu", "polaridad_neta", "examples",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["examples"] = " | ".join(row["examples"])
            writer.writerow(out)

    _atomic_text_write(csv_path, write_csv, newline="")

    return json_path, csv_path

def write_draft_config(
    domain_key: str,
    meta: dict[str, Any],
    rows: list[dict[str, Any]],
    top_n: int,
    base_lexicon: dict[str, Any],
    artifact_suffix: str = "",
) -> Path:
    """Genera una propuesta editable, nunca una configuración activa.

    Solo los primeros ``top_n`` candidatos se convierten en aspectos provisionales.
    El experto debe revisar el archivo ``.draft.json`` antes de crear el perfil
    definitivo que usarán las etapas posteriores.
    """
    DOMAIN_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f".{artifact_suffix}" if artifact_suffix else ""
    draft_path = DOMAIN_DIR / f"{domain_key}{suffix}.draft.json"

    chosen = rows[:top_n]
    quality_aspects = {
        row["aspect_key_sugerido"]: {
            "label": row["term"].replace("_", " ").title(),
            "icon": "",
        }
        for row in chosen
    }
    aspect_lexicon = {
        row["aspect_key_sugerido"]: [row["term"]]
        for row in chosen
    }

    # Se conserva la estructura esperada por domain_config.py para que el borrador
    # pueda revisarse sin inventar un formato especial para esta etapa.
    draft = {
        "_draft_notes": [
            "Borrador generado automaticamente desde resenas.",
            "El experto debe agrupar, renombrar y eliminar candidatos antes de usarlo como perfil final.",
            f"Para activarlo, revisar y guardar como config/domains/{domain_key}.json.",
        ],
        "domain_key": domain_key,
        "display_name": meta.get("category_label") or domain_key,
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
            "envio": "Envio",
        },
        "catalog_aspect_map": {},
        "ui": {
            "laf1_page_title": f"Que buscas en {meta.get('category_label') or domain_key}?",
            "laf1_title": f"Que buscas en {meta.get('category_label') or domain_key}?",
            "laf1_caption": "Indica que tan importante es cada aspecto para vos.",
            "laf2_page_title": "Como queres comprarlo?",
            "laf2_title": "Como queres comprarlo?",
            "laf2_purchase_title": "Que condiciones de compra te importan?",
        },
        "laf": {
            "system_description": f"Sistema argumentativo de recomendacion - {meta.get('category_label') or domain_key}",
            "author_line": "Trabajo Final - Ana Paula Machado - UNSE",
        },
        "lexicon": {
            "aspects": aspect_lexicon,
            "positive": base_lexicon["positive"],
            "negative": base_lexicon["negative"],
            "negation": base_lexicon["negation"],
        },
    }

    _atomic_text_write(
        draft_path,
        lambda file: json.dump(draft, file, ensure_ascii=False, indent=2),
    )
    return draft_path

def positive_int(value: str) -> int:
    """Tipo de argparse para parámetros que deben ser mayores que cero."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("debe ser mayor que cero")
    return parsed


def nonnegative_int(value: str) -> int:
    """Tipo de argparse para cantidades que admiten el valor cero."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("no puede ser negativo")
    return parsed


def artifact_suffix(value: str) -> str:
    """Valida un identificador seguro para conservar reportes por dataset."""
    normalized = value.strip().lower()
    if not normalized or re.fullmatch(r"[a-z0-9_]+", normalized) is None:
        raise argparse.ArgumentTypeError(
            "debe contener solo letras minusculas, numeros y guiones bajos"
        )
    return normalized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Define y valida los parámetros públicos del script."""
    parser = argparse.ArgumentParser(
        description="Descubre términos candidatos para el perfil de un dominio."
    )
    parser.add_argument("--dataset-key", default=os.environ.get("DATASET_KEY"))
    parser.add_argument("--table", default="reviews_clean", choices=["reviews_clean", "reviews_raw"])
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=20000,
        help="Maximo de resenas a analizar (default: 20000).",
    )
    parser.add_argument("--page-size", type=positive_int, default=500)
    parser.add_argument("--min-review-mentions", type=positive_int, default=3)
    parser.add_argument("--top-terms", type=positive_int, default=120)
    parser.add_argument("--draft-aspects", type=nonnegative_int, default=20)
    parser.add_argument(
        "--artifact-suffix",
        type=artifact_suffix,
        default="",
        help="Sufijo seguro para no sobrescribir reportes de otros datasets.",
    )
    parser.add_argument(
        "--no-draft",
        action="store_true",
        help="Genera solo reportes de evidencia, sin crear un borrador de dominio.",
    )
    args = parser.parse_args(argv)
    if args.draft_aspects > args.top_terms:
        parser.error("--draft-aspects no puede superar --top-terms")
    return args


# ---------------------------------------------------------------------------
# Orquestación del flujo completo
# ---------------------------------------------------------------------------
def main() -> None:
    """Coordina configuración, lectura, análisis y generación de artefactos."""
    args = parse_args()

    # Las credenciales se validan antes de construir el cliente para producir un
    # mensaje comprensible en lugar de un error interno de la biblioteca.
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_KEY"):
        print(
            "ERROR: faltan SUPABASE_URL y/o SUPABASE_KEY en .env.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.dataset_key:
        print("ERROR: falta DATASET_KEY.", file=sys.stderr)
        sys.exit(1)

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    meta = get_dataset_meta(sb, args.dataset_key)
    category_label = meta.get("category_label")
    if not category_label:
        print("ERROR: el dataset no tiene category_label.", file=sys.stderr)
        sys.exit(1)
    domain_key = domain_key_from_category_label(category_label)
    # Esta función detiene el flujo si 01b no terminó y devuelve exclusivamente
    # los productos que la revisión humana marcó como incluidos.
    included_product_ids = require_included_product_ids(
        sb,
        args.dataset_key,
        stage_name="02_domain_discovery.py",
    )

    print(f"Dataset: {args.dataset_key}")
    print(f"Categoria: {meta.get('category_label')} -> {domain_key}")
    print(f"Productos incluidos por revision humana: {len(included_product_ids)}")
    print(f"Leyendo resenas desde {args.table}...")

    reviews = fetch_reviews(
        sb,
        args.table,
        args.dataset_key,
        args.limit,
        args.page_size,
        included_product_ids,
    )
    if not reviews:
        print("ERROR: no se encontraron resenas con contenido.", file=sys.stderr)
        sys.exit(1)

    # Las palabras valorativas se excluyen como aspectos: "excelente" describe
    # polaridad, mientras que "batería" puede describir una propiedad evaluable.
    base_lexicon = load_base_lexicon()
    positive = {normalize(term) for term in base_lexicon["positive"]}
    negative = {normalize(term) for term in base_lexicon["negative"]}
    excluded = set(STOPWORDS) | set(GENERIC_EXCLUDE) | positive | negative

    nlp = load_spacy_model()
    if nlp:
        print("Usando spaCy es_core_news_md para extraer sustantivos/frases.")
    else:
        print("AVISO: spaCy no esta disponible; usando fallback por tokens.")

    rows = build_candidates(reviews, positive, negative, excluded, nlp)
    # La frecuencia mínima elimina términos anecdóticos antes de aplicar el tope
    # de candidatos que recibirá el experto.
    rows = [row for row in rows if row["reviews_mencion"] >= args.min_review_mentions]
    # top_terms limita deliberadamente ambos reportes; el borrador toma un
    # subconjunto todavía menor mediante draft_aspects.
    rows = rows[:args.top_terms]

    json_path, csv_path = write_reports(
        domain_key, rows, meta, args.artifact_suffix
    )
    draft_path = None
    if not args.no_draft:
        draft_path = write_draft_config(
            domain_key,
            meta,
            rows,
            args.draft_aspects,
            base_lexicon,
            args.artifact_suffix,
        )

    print()
    print(f"Resenas analizadas: {len(reviews)}")
    print(f"Candidatos exportados: {len(rows)}")
    print("Polaridad del reporte: exploratoria; la polaridad final se calcula en 05_aspects.py")
    print(f"Reporte JSON: {json_path}")
    print(f"Reporte CSV:  {csv_path}")
    if draft_path is not None:
        print(f"Borrador:     {draft_path}")
    print()
    print("Siguiente paso recomendado:")
    print("  sin LLM:  streamlit run src/04_domain_review.py")
    print("  con LLM:  python src/03_llm_suggestions.py")
    print("            streamlit run src/04_domain_review.py")
    print(f"La interfaz permite guardar el perfil final como config/domains/{domain_key}.json.")


if __name__ == "__main__":
    # Solo se traducen a mensajes simples los errores esperables del control de
    # productos. Los errores inesperados conservan su traceback para diagnóstico.
    try:
        main()
    except (ProductReviewSetupError, ProductReviewPendingError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
