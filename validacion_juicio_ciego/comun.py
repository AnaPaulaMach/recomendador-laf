# -*- coding: utf-8 -*-
"""Piezas compartidas por los scripts del experimento 1 (juicio ciego por pares).

Solo LECTURA de Supabase. No modifica src/, config/, webapp/ ni LAF/.
Las funciones de trust y la construccion del programa LAF se IMPORTAN de src/;
aca no se reescribe ninguna formula.
"""
from __future__ import annotations

import collections
import importlib.util
import os
import sys
import unicodedata
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# src/ y webapp/ quedan importables para todos los scripts de la carpeta.
for _ruta in (ROOT / "src", ROOT / "webapp"):
    if str(_ruta) not in sys.path:
        sys.path.insert(0, str(_ruta))

DATASET_KEY = "mlm_mlm194329_20260528_142014"
ESTRATEGIA = "D"
ASPECTO = "sabor"
LAF_API = "http://localhost:8088/api/graph"

# Semillas declaradas en el pre-registro (README.md, §5).
SEMILLA = 20260910
SEMILLA_PARES = SEMILLA
SEMILLA_FRAGMENTOS = SEMILLA + 1
SEMILLA_ROTACION = SEMILLA + 2

# Los 14 aspectos del dominio cafe, en el orden que usa battery_multicriterio.py.
ASPECTOS = [
    "sabor", "aroma", "intensidad", "dulzor", "tueste", "acidez", "presentacion",
    "rendimiento", "variedad", "preparacion", "molienda", "originalidad",
    "tamano", "caducidad",
]

MIN_MENCIONES = 15          # umbral de producto elegible (README §4.4)
FRAGMENTOS_POR_LADO = 15    # README §5.2
CUOTAS = {"grande": 7, "mediana": 7, "chica": 6}   # README §5.1
TOPE_APARICIONES = 4
MAX_INTENTOS = 1000


# --------------------------------------------------------------------------
# Carga de modulos de src/ sin renombrar archivos que empiezan con digito
# --------------------------------------------------------------------------

def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def cargar_modulos():
    """Devuelve (trust06, gen08, laf) con los componentes reales del proyecto."""
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "webapp"))
    trust06 = _load_module("trust06", ROOT / "src" / "06_trust.py")
    gen08 = _load_module("gen08", ROOT / "src" / "08_laf1_generate.py")
    gen08.initialize_runtime(DATASET_KEY)
    from recommender.services.laf_api import (  # noqa: E402
        LAFProgramParser, LAFApiClient, LAFGraphRankingMapper,
    )
    from recommender.services.post_laf_decision import (  # noqa: E402
        zero_threshold_payload,
    )
    laf = {
        "parser": LAFProgramParser(),
        "client": LAFApiClient(LAF_API),
        "mapper": LAFGraphRankingMapper(),
        "zero_threshold_payload": zero_threshold_payload,
    }
    return trust06, gen08, laf


def conectar():
    from dotenv import load_dotenv
    from supabase import create_client
    load_dotenv(ROOT / ".env")
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


# --------------------------------------------------------------------------
# Lectura paginada (solo lectura)
# --------------------------------------------------------------------------

def leer_todo(sb, tabla: str, columnas: str, **filtros) -> list[dict]:
    filas: list[dict] = []
    ultimo = 0
    while True:
        q = sb.table(tabla).select(columnas)
        for campo, valor in filtros.items():
            q = q.eq(campo, valor)
        pagina = q.gt("id", ultimo).order("id").limit(1000).execute().data
        if not pagina:
            return filas
        filas.extend(pagina)
        ultimo = pagina[-1]["id"]


def cargar_corpus(sb):
    """Trust por resena, menciones y productos incluidos. Una sola lectura."""
    trust = leer_todo(
        sb, "review_trust", "id,review_id,product_id,trust_score",
        dataset_key=DATASET_KEY,
    )
    menciones = leer_todo(
        sb, "review_aspects",
        "id,review_id,product_id,aspect,polarity,extraction_confidence,sentence_excerpt",
        dataset_key=DATASET_KEY,
    )
    from product_scope import require_included_product_ids
    incluidos = require_included_product_ids(sb, DATASET_KEY, stage_name="validacion_juicio_ciego")
    nombres = {
        r["product_id"]: (r.get("name") or r.get("family_name") or r["product_id"])
        for r in sb.table("products_raw")
        .select("product_id,name,family_name")
        .eq("dataset_key", DATASET_KEY)
        .in_("product_id", sorted(incluidos))
        .execute()
        .data
    }
    return trust, menciones, incluidos, nombres


# --------------------------------------------------------------------------
# Reconstruccion de los hechos D y puntaje LAF por aspecto
# --------------------------------------------------------------------------

def construir_hechos(trust06, trust_rows, mention_rows):
    """Reconstruye los hechos de la estrategia D con las funciones de 06_trust.py.

    Verificado el 2026-09-10: reproduce product_aspect_trust exactamente
    (259 hechos, mismas claves, mismos valores).
    """
    trust_map = {(r["review_id"], r["product_id"]): float(r["trust_score"]) for r in trust_rows}
    evidencia: dict = {}
    menciones = collections.Counter()
    trust06.add_aspect_evidence(mention_rows, trust_map, evidencia, menciones)
    agrupado = trust06.group_review_evidence(evidencia)
    return trust06.build_product_aspect_rows(agrupado, menciones, {}, ESTRATEGIA, DATASET_KEY)


def puntaje_por_aspecto(gen08, laf, productos, hechos, aspecto):
    """Confianza post-conflicto de cada producto en la corrida de UN aspecto.

    Es exactamente `aspect_scores[aspecto]` de `combine_rankings`, y con perfil
    de un solo aspecto coincide con el puntaje final del ranking (README §4.1).
    """
    prefs = {a: 0.0 for a in ASPECTOS}
    prefs[aspecto] = 1.0
    programa = gen08.build_laf1(productos, hechos, prefs, ESTRATEGIA, dataset_key=DATASET_KEY)
    payload = laf["zero_threshold_payload"](laf["parser"].parse(programa).to_request_payload())
    ranking = laf["mapper"].map(laf["client"].build_graph(payload), [])
    return {entrada.entity_id: float(entrada.confidence) for entrada in ranking}


def id_producto(entity_id: str) -> str:
    """Recupera el product_id (MLM...) del atomo LAF del producto."""
    return entity_id.split("_")[0].upper()


# --------------------------------------------------------------------------
# Texto
# --------------------------------------------------------------------------

def sin_acentos(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )


def normalizar_fragmento(texto: str) -> str:
    """Clave de deduplicacion: espacios colapsados y minusculas (README §4.3)."""
    return " ".join((texto or "").split()).lower()


# --------------------------------------------------------------------------
# Encabezado obligatorio de cada script
# --------------------------------------------------------------------------

def encabezado(script: str, semilla, n_resenas: int, n_menciones: int, extra: str = "") -> None:
    print("=" * 74)
    print(f"{script}  |  experimento 1 — juicio ciego por pares")
    print("=" * 74)
    print(f"  dataset_key   : {DATASET_KEY}")
    print(f"  fecha         : {date.today().isoformat()}")
    print(f"  semilla       : {semilla}")
    print(f"  estrategia    : {ESTRATEGIA}   aspecto: {ASPECTO}")
    print(f"  resenas       : {n_resenas} con trust individual")
    print(f"  menciones     : {n_menciones} (todas las de {ASPECTO}, incluye neu)")
    if extra:
        print(f"  {extra}")
    print("-" * 74)


def hoy() -> str:
    return date.today().isoformat().replace("-", "")
