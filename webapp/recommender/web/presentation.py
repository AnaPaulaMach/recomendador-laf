"""Capa de presentación del recorrido.

Etiquetas legibles, títulos y resúmenes de argumentos, formateo de moneda y
niveles de preferencia. Separa el texto de cara al usuario del manejo HTTP en
``views.py``: no accede a la base ni a repositorios; recibe contratos ya
evaluados y devuelve texto listo para las plantillas.
"""
from __future__ import annotations

import re

from recommender.domain.contracts import EvaluationResult
from recommender.services.comparison import join_es


MARKETPLACE_FALLBACK_URL = "https://www.mercadolibre.com.mx/mas-vendidos/MLM194336"

# Dirección de una publicación armada desde su `item_id` (U30 de la evaluación
# heurística). El relevamiento no guardó `permalink` ni `url` —verificado en
# Supabase el 2026-09-11: no están en `items_raw`, ni en `items_raw.raw_json`,
# ni en `items_clean`—, así que lo único disponible es el identificador.
#
# Supuesto verificado en el navegador el 2026-09-11 por la autora con dos ítems
# reales del catálogo histórico (MLM2107019722 y MLM2528199353): esta forma
# resuelve y Mercado Libre redirige a la página del producto con
# `?pdp_filters=item_id:<item_id>`, es decir que identifica la publicación
# exacta y no un destino genérico. Es una dirección construida, no relevada:
# si Mercado Libre cambia el esquema, deja de resolver, y ésa es la razón por la
# que el supuesto queda escrito acá y en ADR-006.
MARKETPLACE_ITEM_URL = "https://articulo.mercadolibre.com.mx/MLM-{number}"


def marketplace_item_url(item_id: str) -> str:
    """La dirección de esta publicación, armada desde su `item_id`.

    Devuelve cadena vacía si el identificador no tiene la forma `MLM` + dígitos:
    preferimos no ofrecer enlace antes que ofrecer uno que no resuelve.
    """
    match = re.fullmatch(r"MLM(\d+)", str(item_id or "").strip(), re.IGNORECASE)
    if not match:
        return ""
    return MARKETPLACE_ITEM_URL.format(number=match.group(1))

# Umbrales de presentación (chequeo humano 2026-09-03, discrepancias E2-E4).
# Una crítica se muestra como línea "−" solo si tiene al menos NEGATIVE_MIN_MENTIONS
# menciones y representa al menos NEGATIVE_MIN_SHARE de las menciones del aspecto.
# No cambian el ranking: solo qué se muestra y cómo se rotula.
NEGATIVE_MIN_MENTIONS = 2
NEGATIVE_MIN_SHARE = 0.05
# Un producto se marca "pocas menciones" si su evidencia total es menor que esta
# fracción de la mediana del ranking mostrado.
LOW_SUPPORT_RATIO = 0.5
LOW_SUPPORT_NOTE = "Pocas menciones en reseñas: el respaldo es menor"
# Resguardo del rótulo del primer puesto (experimento 2, bootstrap de 200
# réplicas: validacion_robustez/RESULTADOS.md §3, §7 y §10.1). En el perfil
# «solo sabor» los cuatro primeros puntajes son 0,6412 · 0,6403 · 0,6313 ·
# 0,6313: el 1.º y el 2.º difieren en 0,0009 y el ganador sólo se sostiene en el
# 41 % de las réplicas. Un centésimo de puntaje es el corte: por debajo,
# "Mejor opción para vos" afirma un orden que el corpus no sostiene. En el
# perfil neutro la diferencia es 0,0133 y el ganador se conserva en el 94,5 %,
# así que ahí el rótulo se mantiene. No cambia el ranking ni el puntaje.
SHARED_LABEL_MAX_GAP = 0.01
FIRST_MATCH_LABEL = "Mejor opción para vos"
SHARED_MATCH_LABEL = "Entre las mejores opciones para vos"
SHARED_LABEL_NOTE = (
    "Las {count} primeras opciones quedaron a menos de 0,01 de puntaje: "
    "el orden entre ellas no es concluyente"
)


ASPECT_LABELS = {
    "acidez": "valoración de la acidez",
    "aroma": "aroma",
    "caducidad": "frescura",
    "cuotas": "financiación",
    "dulzor": "dulzor y amargor",
    "factura": "factura",
    "garantia": "garantía",
    "intensidad": "intensidad",
    "molienda": "tipo de molienda",
    "originalidad": "originalidad",
    "preparacion": "preparación",
    "presentacion": "presentación",
    "precio": "precio",
    "rendimiento": "rendimiento",
    "sabor": "sabor",
    "tamano": "tamaño",
    "tienda_oficial": "tienda oficial",
    "tueste": "calidad del tueste",
    "variedad": "variedad",
}


POSITIVE_ARGUMENT_TITLES = {
    "acidez": "La acidez recibe buenas opiniones",
    "aroma": "Su aroma recibe buenas opiniones",
    "caducidad": "Hay opiniones favorables sobre su frescura",
    "cuotas": "Ofrece cuotas sin interés",
    "intensidad": "Su intensidad recibe buenas opiniones",
    "molienda": "La molienda recibe buenas opiniones",
    "originalidad": "Se destaca por ser una opción original",
    "preparacion": "Es fácil de preparar",
    "precio": "Tiene un precio competitivo",
    "rendimiento": "Se destaca por su rendimiento",
    "sabor": "La mayoría valora su sabor",
    "tienda_oficial": "Es una tienda oficial",
    "tueste": "La calidad del tueste recibe buenas opiniones",
    "variedad": "Ofrece una variedad diferente",
}


NEGATIVE_ARGUMENT_TITLES = {
    "acidez": "La acidez recibe opiniones desfavorables",
    "caducidad": "Hay pocas opiniones sobre frescura",
    "dulzor": "Puede resultar amargo para algunas personas",
    "factura": "No informa si entrega factura",
    "garantia": "No informa la garantía",
    "presentacion": "La presentación recibe opiniones dispares",
    "precio": "No es la opción más barata",
    "sabor": "Hay algunas críticas al sabor",
    "tienda_oficial": "No es una tienda oficial",
    "tueste": "El tueste recibe algunas críticas",
}


POSITIVE_ARGUMENT_SUMMARIES = {
    "acidez": "Las opiniones favorables destacan el equilibrio de la acidez.",
    "aroma": "Varias opiniones destacan que mantiene un aroma agradable.",
    "intensidad": "Las opiniones favorables destacan su intensidad.",
    "preparacion": "Varias personas mencionan que se prepara con facilidad.",
    "rendimiento": "Las opiniones señalan que ofrece un buen rendimiento.",
    "sabor": "Es uno de los puntos más mencionados en las opiniones.",
    "tueste": "Varias opiniones valoran favorablemente la calidad del tueste.",
    "variedad": "Su variedad es uno de los rasgos que más la diferencia.",
}


NEGATIVE_ARGUMENT_SUMMARIES = {
    "acidez": "Algunas opiniones consideran que la acidez no está equilibrada.",
    "caducidad": "Hay muy poca información para evaluar la frescura con seguridad.",
    "dulzor": "Algunas personas describen un sabor más amargo de lo esperado.",
    "presentacion": "Algunas opiniones señalan problemas con la presentación.",
    "sabor": "Son pocas frente al total, pero conviene tenerlas en cuenta.",
    "tueste": "Algunas opiniones consideran inadecuado el nivel de tueste.",
}


def preference_level(value: float) -> tuple[str, str]:
    """Traduce un peso en [0, 1] al nivel legible y su clave estable.

    Lo usan las vistas y el resumen en vivo. **No es el único lugar donde vive
    la escala de importancia**: `web/forms.py` define los cuatro valores que la
    persona puede elegir (`PREFERENCE_LEVELS`) y `services/comparison.py`
    resuelve la misma etiqueta por cercanía (`_level_label`, `_level_key`).
    Sobre esos cuatro valores las tres coinciden; si se cambia la escala hay que
    tocar los tres lugares.
    """
    if value >= 0.84:
        return "Es prioridad", "priority"
    if value >= 0.5:
        return "Bastante", "high"
    if value > 0:
        return "Poco", "low"
    return "No me importa", "none"


def format_currency(value: float) -> str:
    decimals = 0 if float(value).is_integer() else 2
    rendered = f"{value:,.{decimals}f}"
    return "$" + rendered.replace(",", "_").replace(".", ",").replace("_", ".")


def format_decimal_input(value: float) -> str:
    return format_currency(value).removeprefix("$")


def match_label(position: int, gap: float) -> str:
    """Rótulo del puesto, con el resguardo de la cabeza del ranking.

    ``gap`` es la distancia de puntaje que decide si el orden de la cabeza es
    concluyente: para el 1.º, puntaje(1.º) − puntaje(2.º); para los demás,
    puntaje(1.º) − puntaje propio. Los dos casos los calcula ``head_gaps``.
    Por debajo de ``SHARED_LABEL_MAX_GAP`` el rótulo es compartido y no declara
    un único mejor. No cambia el puntaje ni el puesto: sólo el rótulo.
    """
    if gap < SHARED_LABEL_MAX_GAP:
        return SHARED_MATCH_LABEL
    if position == 1:
        return FIRST_MATCH_LABEL
    if position == 2:
        return "Buena coincidencia"
    return "Coincidencia media"


def head_gaps(ranking) -> tuple[dict[str, float], int]:
    """Distancia al puntaje más alto por entidad y tamaño de la cabeza empatada.

    Devuelve ``(gap por entity_id, cuántas opciones comparten la cabeza)``. La
    cabeza empatada son las primeras opciones que quedan a menos de
    ``SHARED_LABEL_MAX_GAP`` del puntaje más alto; es 0 cuando el 1.º se separa
    del 2.º por al menos el umbral. Las entidades que no cumplen lo pedido
    (``not_recommended``) no participan: llevan su propio rótulo.
    """
    entries = sorted(
        (entry for entry in ranking if entry.status != "not_recommended"),
        key=lambda entry: entry.position,
    )
    if not entries:
        return {}, 0
    top = float(entries[0].final_score or 0.0)
    second = float(entries[1].final_score or 0.0) if len(entries) > 1 else None
    gaps = {
        entry.entity_id: (
            (top - second if second is not None else float("inf"))
            if index == 0
            else top - float(entry.final_score or 0.0)
        )
        for index, entry in enumerate(entries)
    }
    shared = 0
    for entry in entries:
        if gaps[entry.entity_id] >= SHARED_LABEL_MAX_GAP:
            break
        shared += 1
    return gaps, shared


def shared_label_note(count: int) -> str:
    """Oración fija del detalle cuando la cabeza del ranking está empatada."""
    return SHARED_LABEL_NOTE.format(count=count) if count > 1 else ""


def _number_es(value: float, decimals: int = 2) -> str:
    """Número con coma decimal, como el resto de la explicación."""
    return f"{float(value):.{decimals}f}".replace(".", ",")


def aspect_claim_narrative(claim, laf_score: float | None = None) -> str:
    """La oración que se lee al abrir una característica en el detalle.

    Única fuente del texto (antes vivía en el atributo ``data-aspect-narr`` de
    ``partials/argument_graph.html``). Plantilla fija completada con lo que ya
    calculó el evaluador para esa corrida: las menciones del aspecto, la
    confianza de los hechos que entran (``fact_favor`` / ``fact_against``), μ y
    δ del reclamo y el resultado LAF que entra a la suma. No recalcula nada y no
    califica el producto.

    Tres casos, según lo que haya en la corrida:

    - **con crítica** (menciones en contra y hecho negativo): el conflicto con
      sus valores, μ → δ y el resultado LAF;
    - **sin críticas**: la evidencia favorable, que la conclusión no fue
      debilitada y el resultado LAF;
    - **crítica sin hecho negativo agregado**: sólo el conteo, porque no hay
      valores que mostrar.
    """
    favor = int(getattr(claim, "mentions_favor", 0) or 0)
    against = int(getattr(claim, "mentions_against", 0) or 0)
    fact_favor = float(getattr(claim, "fact_favor", 0.0) or 0.0)
    fact_against = float(getattr(claim, "fact_against", 0.0) or 0.0)
    noun = "mención" if favor == 1 else "menciones"
    contra = f" y {against} en contra" if against else " y ninguna en contra"
    conteo = f"{favor} {noun} del aspecto a favor{contra} en las reseñas de este café."
    reglas = (
        f" y las reglas que llevan de este punto a la recomendación la dejan en "
        f"{_number_es(laf_score)}"
        if laf_score is not None
        else ""
    )
    if against and fact_against:
        cierre = (
            f"; las reglas que llevan de este punto a la recomendación la dejan en "
            f"{_number_es(laf_score)}"
            if laf_score is not None
            else ""
        )
        return (
            f"{conteo} La evidencia favorable pesa {_number_es(fact_favor)} y la "
            f"crítica {_number_es(fact_against)}. Al enfrentarlas, la conclusión "
            f"favorable pasa de {_number_es(getattr(claim, 'mu', 0.0))} a "
            f"{_number_es(getattr(claim, 'delta', 0.0))}{cierre}."
        )
    if not against and fact_favor:
        return (
            f"{conteo} La evidencia favorable pesa {_number_es(fact_favor)}; sin "
            f"críticas, la conclusión no fue debilitada{reglas}."
        )
    return conteo


def opinion_label(count: int, aspect: str) -> str:
    noun = "mención" if count == 1 else "menciones"
    return f"{count} {noun} sobre {aspect}"


def plain_argument(argument, *, positive: bool) -> dict[str, str]:
    aspect_key = str(argument.aspect or "").casefold()
    aspect = ASPECT_LABELS.get(aspect_key, aspect_key.replace("_", " ") or "este punto")
    titles = POSITIVE_ARGUMENT_TITLES if positive else NEGATIVE_ARGUMENT_TITLES
    title = titles.get(
        aspect_key,
        f"Menciones favorables sobre {aspect}"
        if positive
        else f"Menciones desfavorables sobre {aspect}",
    )
    if positive:
        summary = POSITIVE_ARGUMENT_SUMMARIES.get(
            aspect_key,
            "Encontramos menciones favorables sobre este punto."
            if argument.evidence_count != 1
            else "Encontramos una mención favorable sobre este punto.",
        )
    else:
        summary = NEGATIVE_ARGUMENT_SUMMARIES.get(
            aspect_key,
            "La información disponible sobre este punto todavía es limitada."
            if argument.evidence_count <= 1
            else "Aparece en algunas menciones y conviene tenerlo en cuenta.",
        )
    return {
        "title": title,
        "summary": summary,
        "evidence_label": opinion_label(argument.evidence_count, aspect),
    }


def is_active_argument(argument) -> bool:
    """Un argumento cuenta para la presentación solo si su aspecto tiene peso > 0.

    Con "No me importa" la preferencia propagada es 0 y el argumento no participa
    del puntaje; mostrarlo como razón principal contradice al perfil (E4).
    """
    try:
        return float(argument.preference) > 0
    except (TypeError, ValueError):
        return True


def positive_mentions_by_aspect(entry) -> dict[str, int]:
    counts: dict[str, int] = {}
    for argument in entry.arguments_for:
        key = str(argument.aspect or "").casefold()
        counts[key] = counts.get(key, 0) + int(argument.evidence_count or 0)
    return counts


def negative_mentions_by_aspect(entry) -> dict[str, int]:
    counts: dict[str, int] = {}
    for argument in entry.arguments_against:
        key = str(argument.aspect or "").casefold()
        counts[key] = counts.get(key, 0) + int(argument.evidence_count or 0)
    return counts


def mentions_by_aspect(entry) -> dict[str, dict[str, int]]:
    """Menciones a favor y totales por aspecto, sin filtrar.

    Cuenta todos los argumentos del producto: el conteo es un dato de las
    reseñas, no una selección de presentación. Qué aspectos se muestran lo
    decide el perfil (``aspect_mention_lines``). Por eso la suma de los totales
    coincide con ``entry.evidence_count``.
    """
    favorable = positive_mentions_by_aspect(entry)
    against = negative_mentions_by_aspect(entry)
    return {
        key: {
            "favorable": favorable.get(key, 0),
            "against": against.get(key, 0),
            "total": favorable.get(key, 0) + against.get(key, 0),
        }
        for key in (*favorable, *against)
    }


def aspect_display_label(aspect_key: str) -> str:
    aspect = ASPECT_LABELS.get(
        aspect_key, aspect_key.replace("_", " ") or "este punto"
    )
    return aspect[:1].upper() + aspect[1:]


def mention_line_text(aspect_key: str, favorable: int, total: int) -> str:
    """Una línea de la tarjeta: cuántas de las menciones del aspecto son a favor."""
    label = aspect_display_label(aspect_key)
    if total <= 0:
        return f"{label}: sin menciones en las reseñas"
    noun = "mención favorable" if total == 1 else "menciones favorables"
    return f"{label}: {favorable} de {total} {noun}"


def profile_weights(entry, preferences: dict[str, float] | None) -> dict[str, float]:
    """Pesos del perfil por aspecto: los de la sesión o los que guardó la decisión."""
    source: dict[str, object]
    if preferences:
        source = dict(preferences)
    else:
        source = {
            str(item.get("aspect") or ""): item.get("weight")
            for item in (entry.metadata.get("aspect_contributions") or [])
            if isinstance(item, dict)
        }
    weights: dict[str, float] = {}
    for key, value in source.items():
        try:
            weight = float(value)
        except (TypeError, ValueError):
            continue
        if weight > 0:
            weights[str(key).casefold()] = weight
    return weights


def aspect_mention_lines(
    entry,
    preferences: dict[str, float] | None = None,
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    """Hasta ``limit`` aspectos del perfil, por peso descendente.

    Con empate de pesos —o con un perfil plano— desempata el total de menciones
    del producto y luego el nombre del aspecto, para que la tarjeta sea estable.
    Un aspecto con peso 0 no se muestra: no participa del puntaje (E4).
    """
    mentions = mentions_by_aspect(entry)
    weights = profile_weights(entry, preferences)
    candidates = list(weights) if weights else [key for key in mentions if key]
    candidates.sort(
        key=lambda key: (
            -weights.get(key, 0.0),
            -int(mentions.get(key, {}).get("total", 0)),
            key,
        )
    )
    lines = []
    for key in candidates[:limit]:
        counts = mentions.get(key, {})
        favorable = int(counts.get("favorable", 0))
        total = int(counts.get("total", 0))
        lines.append(
            {
                "aspect": key,
                "label": aspect_display_label(key),
                "favorable": favorable,
                "total": total,
                "text": mention_line_text(key, favorable, total),
            }
        )
    return lines


def is_marginal_negative(argument, positive_count: int) -> bool:
    """Crítica sostenida en muy pocas menciones frente a los elogios del mismo aspecto (E3)."""
    negative = int(argument.evidence_count or 0)
    total = negative + max(int(positive_count or 0), 0)
    if negative < NEGATIVE_MIN_MENTIONS:
        return True
    return total > 0 and (negative / total) < NEGATIVE_MIN_SHARE


def negative_argument_display(argument, positive_count: int) -> dict[str, object]:
    display = plain_argument(argument, positive=False)
    negative = int(argument.evidence_count or 0)
    total = negative + max(int(positive_count or 0), 0)
    aspect_key = str(argument.aspect or "").casefold()
    aspect = ASPECT_LABELS.get(aspect_key, aspect_key.replace("_", " ") or "este punto")
    display["evidence_label"] = (
        f"{negative} de {total} menciones sobre {aspect}" if total else display["evidence_label"]
    )
    display["mentions"] = negative
    display["total_mentions"] = total
    display["share_percent"] = round(negative / total * 100) if total else 0
    display["marginal"] = is_marginal_negative(argument, positive_count)
    return display


def argument_priority(argument) -> tuple[float, int, str]:
    """Ordena por la incidencia que realmente entra al operador LAF."""
    try:
        influence = min(float(argument.confidence), float(argument.preference))
    except (TypeError, ValueError):
        influence = 0.0
    return (-influence, -int(argument.evidence_count or 0), str(argument.aspect or ""))


def attach_primary_copy(
    result: EvaluationResult,
    *,
    include_purchase_links: bool = False,
    preferences: dict[str, float] | None = None,
) -> EvaluationResult:
    """Agrega textos de presentación sin modificar el resultado técnico guardado."""
    evidence_counts = sorted(int(entry.evidence_count or 0) for entry in result.ranking)
    median_evidence = 0.0
    if evidence_counts:
        middle = len(evidence_counts) // 2
        median_evidence = (
            float(evidence_counts[middle])
            if len(evidence_counts) % 2
            else (evidence_counts[middle - 1] + evidence_counts[middle]) / 2
        )
    # Resguardo del rótulo: el 1.º sólo se declara único si se separa del 2.º
    # por al menos un centésimo de puntaje (validacion_robustez/RESULTADOS.md).
    gaps, shared_head = head_gaps(result.ranking)
    for entry in result.ranking:
        entry.metadata["match_label"] = (
            "No cumple lo que pediste"
            if entry.status == "not_recommended"
            else match_label(entry.position, gaps.get(entry.entity_id, float("inf")))
        )
        if entry.metadata["match_label"] == SHARED_MATCH_LABEL:
            entry.metadata["shared_label_note"] = shared_label_note(shared_head)
        # E4: solo argumentos de aspectos con peso > 0 en el perfil del usuario.
        arguments_for = sorted(
            (argument for argument in entry.arguments_for if is_active_argument(argument)),
            key=argument_priority,
        )
        arguments_against = sorted(
            (argument for argument in entry.arguments_against if is_active_argument(argument)),
            key=argument_priority,
        )
        positive_counts = positive_mentions_by_aspect(entry)
        negatives_display = [
            negative_argument_display(
                argument, positive_counts.get(str(argument.aspect or "").casefold(), 0)
            )
            for argument in arguments_against
        ]
        entry.metadata["arguments_for_display"] = [
            plain_argument(argument, positive=True)
            for argument in arguments_for
        ]
        # E3: la tarjeta no muestra críticas marginales; la explicación las lista marcadas.
        entry.metadata["arguments_against_display"] = [
            display for display in negatives_display if not display["marginal"]
        ]
        entry.metadata["arguments_against_marginal_count"] = sum(
            1 for display in negatives_display if display["marginal"]
        )
        # E3 (09/09): la tarjeta no afirma nada sobre el aspecto; informa cuántas
        # de sus menciones son a favor. El conteo es de todos los argumentos; el
        # perfil sólo decide qué aspectos entran.
        entry.metadata["aspect_mentions"] = mentions_by_aspect(entry)
        entry.metadata["aspect_mention_lines"] = aspect_mention_lines(
            entry, preferences
        )
        # Menciones por aspecto (a favor/en contra) y si hay crítica RELEVANTE
        # según el umbral E3 ya aprobado. Alimenta los estados en lenguaje común
        # de la pantalla "Ver por qué" (build_claim_ledger), para que coincidan
        # con la tarjeta y una crítica de una sola mención no diga "no se sostiene".
        aspect_criticism: dict[str, dict[str, object]] = {}
        for argument in arguments_against:
            key = str(argument.aspect or "").casefold()
            if not key:
                continue
            favor = positive_counts.get(key, 0)
            info = aspect_criticism.setdefault(
                key, {"favor": favor, "against": 0, "relevant": False}
            )
            info["against"] = int(info["against"]) + int(argument.evidence_count or 0)
            if not is_marginal_negative(argument, favor):
                info["relevant"] = True
        for key, count in positive_counts.items():
            aspect_criticism.setdefault(key, {"favor": count, "against": 0, "relevant": False})
        entry.metadata["aspect_criticism"] = aspect_criticism
        entry.metadata["explanation_contributions_for"] = [
            {
                **plain_argument(argument, positive=True),
                "influence": min(float(argument.confidence), float(argument.preference)),
                "influence_percent": round(
                    min(float(argument.confidence), float(argument.preference)) * 100
                ),
            }
            for argument in arguments_for
        ]
        entry.metadata["explanation_contributions_against"] = [
            {
                **display,
                "influence": min(float(argument.confidence), float(argument.preference)),
                "influence_percent": round(
                    min(float(argument.confidence), float(argument.preference)) * 100
                ),
            }
            for argument, display in zip(arguments_against, negatives_display)
        ]
        # E2: cobertura real de aspectos con evidencia y aviso de respaldo bajo.
        aspects_with_evidence = {
            str(argument.aspect or "").casefold()
            for argument in (*entry.arguments_for, *entry.arguments_against)
            if str(argument.aspect or "")
        }
        entry.metadata["aspects_with_evidence"] = sorted(aspects_with_evidence)
        if median_evidence and int(entry.evidence_count or 0) < LOW_SUPPORT_RATIO * median_evidence:
            entry.metadata["support_note"] = LOW_SUPPORT_NOTE
        coverage_match = re.search(r"\d+", str(entry.metadata.get("coverage") or ""))
        count = int(coverage_match.group()) if coverage_match else len(aspects_with_evidence)
        if count:
            entry.metadata["coverage_display"] = f"Información sobre {count} características"
            entry.metadata["limitation_display"] = (
                f"Encontramos información sobre {count} características."
            )
        else:
            entry.metadata["limitation_display"] = (
                "Todavía hay características con pocas menciones."
            )
        if entry.metadata.get("price") not in (None, ""):
            try:
                entry.metadata["price_label"] = format_currency(
                    float(str(entry.metadata["price"]).replace(",", "."))
                )
            except (TypeError, ValueError):
                entry.metadata["price_label"] = f"${entry.metadata['price']}"
        if include_purchase_links:
            # Rótulo de la fila (U29 de la evaluación heurística). El
            # relevamiento no guardó apodo ni nombre del vendedor —verificado en
            # Supabase el 2026-09-11: `items_raw` tiene `seller_id` y
            # `seller_address`, y `raw_json` (22 claves) tampoco trae nombre—,
            # así que un id numérico crudo era el único rótulo que distinguía
            # una fila de otra. Se nombra por puesto y precio, que son los datos
            # con los que el usuario compara; el identificador queda como dato
            # secundario (`item_id_display`).
            entry.metadata["listing_title"] = " · ".join(
                part
                for part in (
                    f"Publicación {entry.position}" if entry.position else "Publicación",
                    str(entry.metadata.get("price_label") or ""),
                )
                if part
            )
            entry.metadata["item_id_display"] = str(entry.entity_id or "")
            # Orden de preferencia: el permalink relevado (hoy no existe en el
            # catálogo de café), la dirección armada desde el `item_id`, y sólo
            # como último recurso el destino genérico de la categoría.
            marketplace_url = entry.metadata.get("marketplace_url") or marketplace_item_url(
                entry.metadata.get("item_id") or entry.entity_id
            )
            entry.metadata["purchase_url"] = marketplace_url or MARKETPLACE_FALLBACK_URL
            entry.metadata["purchase_url_is_fallback"] = not bool(marketplace_url)
    return result


# --- Explicación del ranking de publicaciones (LAF 2) ------------------------
#
# Todo lo que sigue es texto de plantilla completado con valores que ya vienen
# calculados en el ``EvaluationResult`` que produjo el orden: los pesos y el
# resultado LAF de cada condición salen de ``metadata["aspect_contributions"]``,
# y el dato mostrado sale del ``metadata`` de la publicación, que el paso 10
# copió de la fila del catálogo. Acá no se recalcula ningún puntaje.

# Condición de compra -> bandera declarada por la publicación. Las claves son
# las mismas que ``LAF2ProgramService.CONDITION_FLAGS`` (un test lo verifica);
# ``precio`` no tiene bandera porque siempre hay hecho de precio.
LISTING_CONDITION_FLAGS = {
    "precio": None,
    "descuento": "has_discount",
    "cuotas": "has_cuotas",
    "garantia": "has_long_warranty",
    "tienda_oficial": "is_official_store",
    "factura": "has_invoice",
    "envio": "has_free_shipping",
}

# Nombres anteriores de las mismas banderas en los ejemplos de demostración.
_LISTING_LEGACY_FLAGS = {
    "tienda_oficial": "official_store",
    "factura": "invoice",
}

# Texto del dato para las condiciones que se responden por sí o por no. El
# primer elemento es lo que se muestra cuando la publicación lo declara.
_LISTING_CONDITION_TEXTS = {
    "descuento": ("Sí", "No informado"),
    "cuotas": ("Sí", "No informadas"),
    "garantia": ("Sí", "No informada"),
    "tienda_oficial": ("Sí", "No informado"),
    "factura": ("Sí", "No informada"),
    "envio": ("Gratis", "No informado"),
}

# Nombres cortos para nombrar las condiciones dentro de una oración; las
# etiquetas de la categoría son descripciones largas, pensadas para el
# formulario.
LISTING_CONDITION_SHORT = {
    "precio": "precio",
    "descuento": "descuento",
    "cuotas": "financiación",
    "garantia": "garantía",
    "tienda_oficial": "tienda oficial",
    "factura": "factura",
    "envio": "envío",
}

LISTING_CONDITION_MISSING = "sin información en la publicación"
LISTING_CONDITION_NO_EVIDENCE = "ninguna publicación de este producto la informa"
LISTING_CONDITION_DISABLED = "no participa"


def format_laf_score(value: float) -> str:
    """Resultado LAF con tres decimales y coma, igual que en las plantillas."""
    return _number_es(value, 3)


def _listing_condition_declared(key: str, metadata: dict, fulfilled: bool) -> bool:
    """¿La publicación declara esta condición?

    Prefiere la bandera guardada por el paso 10. Las corridas anteriores a que
    esas banderas se guardaran no la tienen: ahí se usa el resultado LAF de la
    condición, que es mayor que cero exactamente cuando el hecho existe (las
    reglas de LAF 2 son sólo positivas).
    """
    metadata = metadata or {}
    flag = LISTING_CONDITION_FLAGS.get(key)
    if flag and flag in metadata:
        return bool(metadata.get(flag))
    legacy = _LISTING_LEGACY_FLAGS.get(key)
    if legacy and legacy in metadata:
        return bool(metadata.get(legacy))
    return bool(fulfilled)


def listing_condition_value(key: str, metadata: dict, fulfilled: bool) -> str:
    """Dato que la publicación declara para esta condición, sin adjetivos."""
    metadata = metadata or {}
    declared = _listing_condition_declared(key, metadata, fulfilled)
    if key == "precio":
        return str(metadata.get("price_label") or "Precio no informado")
    if key == "garantia":
        return str(metadata.get("warranty") or "No informada")
    if key == "cuotas":
        return str(metadata.get("installments") or "No informadas")
    if key == "envio" and "has_free_shipping" not in metadata:
        # Ejemplos de demostración: la etiqueta de envío es el único dato.
        return str(metadata.get("shipping") or "No informado")
    if key == "descuento":
        if not declared:
            return _LISTING_CONDITION_TEXTS["descuento"][1]
        try:
            share = round(float(metadata.get("discount_pct") or 0.0) * 100)
        except (TypeError, ValueError):
            share = 0
        return f"Sí, {share} %" if share else "Sí"
    positive, negative = _LISTING_CONDITION_TEXTS.get(key, ("Sí", "No informado"))
    return positive if declared else negative


def _with_narrative(row: dict) -> dict:
    return {**row, "narrative": listing_condition_narrative(row)}


def _listing_disabled_rows(
    rows: list[dict],
    preferences: dict,
    label_for,
    metadata: dict | None = None,
    skip: tuple = (),
) -> list[dict]:
    """Las condiciones que la persona puso en «No me importa».

    Se listan para que se vea qué se ofreció y no participó, con peso 0: no
    entran ni al numerador ni al denominador del puntaje.
    """
    present = {row["key"] for row in rows} | set(skip)
    disabled = []
    for key, weight in (preferences or {}).items():
        if key in present or float(weight or 0.0) > 0:
            continue
        disabled.append(
            {
                "key": key,
                "label": label_for(key),
                "state": "no_me_importa",
                "weight": 0.0,
                "importance": preference_level(0.0)[0],
                "value": listing_condition_value(key, metadata, False),
                "fulfilled": False,
                "laf_score": None,
                "laf_display": LISTING_CONDITION_DISABLED,
                "node_id": "",
            }
        )
    return disabled


def listing_condition_rows(
    entry,
    breakdown,
    preferences: dict | None = None,
    labels: dict | None = None,
) -> tuple[dict, ...]:
    """Una fila por condición ofrecida, en el orden en que se leen.

    Primero las que participaron del puntaje (como las ordenó el desglose),
    después las que ninguna publicación del producto informa y al final las que
    la persona puso en «No me importa». Se distinguen por ``state``; sólo las
    primeras entran en la fórmula.
    """
    if entry is None:
        return ()
    metadata = entry.metadata or {}
    labels = labels or {}
    preferences = preferences or {}
    without_evidence = tuple(metadata.get("conditions_without_evidence") or ())

    def label_for(key: str) -> str:
        return labels.get(key, key.replace("_", " ").capitalize())

    contributions = getattr(breakdown, "contributions", ()) or ()
    if not contributions:
        # Ejemplo de demostración: no hay corridas por condición, así que no hay
        # resultado LAF por fila. Se muestran las condiciones elegidas y lo que
        # la publicación declara, sin fórmula.
        supported = {
            str(getattr(argument, "aspect", "") or "").casefold()
            for argument in (getattr(entry, "arguments_for", ()) or ())
        }
        rows = [
            {
                "key": key,
                "label": label_for(key),
                "state": "participa",
                "weight": float(weight or 0.0),
                "importance": preference_level(float(weight or 0.0))[0],
                "value": listing_condition_value(
                    key, metadata, key.casefold() in supported
                ),
                "fulfilled": key.casefold() in supported,
                "laf_score": None,
                "laf_display": "",
                "node_id": "",
            }
            for key, weight in preferences.items()
            if float(weight or 0.0) > 0
        ]
        return tuple(
            _with_narrative(row)
            for row in rows
            + _listing_disabled_rows(rows, preferences, label_for, metadata)
        )

    rows: list[dict] = []
    for item in contributions:
        fulfilled = float(item.laf_score) > 0
        rows.append(
            {
                "key": item.key,
                "label": item.label or label_for(item.key),
                "state": "participa",
                "weight": float(item.weight),
                "importance": preference_level(float(item.weight))[0],
                "value": listing_condition_value(item.key, metadata, fulfilled),
                "fulfilled": fulfilled,
                "laf_score": float(item.laf_score),
                "laf_display": (
                    format_laf_score(item.laf_score)
                    if fulfilled
                    else LISTING_CONDITION_MISSING
                ),
                "node_id": (metadata.get("condition_node_ids") or {}).get(item.key, ""),
            }
        )
    scored = {row["key"] for row in rows}
    for key in without_evidence:
        if key in scored or key not in preferences:
            continue
        weight = float(preferences.get(key) or 0.0)
        rows.append(
            {
                "key": key,
                "label": label_for(key),
                "state": "sin_evidencia",
                "weight": weight,
                "importance": preference_level(weight)[0],
                "value": listing_condition_value(key, metadata, False),
                "fulfilled": False,
                "laf_score": None,
                "laf_display": LISTING_CONDITION_NO_EVIDENCE,
                "node_id": "",
            }
        )
    rows.extend(
        _listing_disabled_rows(
            rows, preferences, label_for, metadata, skip=without_evidence
        )
    )
    return tuple(_with_narrative(row) for row in rows)


def listing_condition_narrative(row: dict) -> str:
    """Una oración de plantilla fija por fila, con los valores de esa fila.

    Es lo que se lee al abrir la condición, junto al grafo de su corrida. No
    califica la publicación: dice qué peso le dio la persona, qué declara la
    publicación y qué hizo LAF con eso.
    """
    importance = str(row.get("importance") or "").casefold()
    weight = _number_es(row.get("weight") or 0.0)
    value = str(row.get("value") or "")
    state = row.get("state")
    if state == "no_me_importa":
        return "La pusiste en «No me importa»: no participa del puntaje."
    if state == "sin_evidencia":
        return (
            f"Le diste importancia «{importance}» ({weight}), pero ninguna "
            "publicación de este producto la informa: la condición no participa "
            "del puntaje y su peso sale del divisor."
        )
    if row.get("laf_score") is None:
        return (
            f"Le diste importancia «{importance}» ({weight}). "
            f"La publicación declara: {value}."
        )
    if not row.get("fulfilled"):
        return (
            f"Le diste importancia «{importance}» ({weight}). La publicación no "
            "informa esta condición, así que no hay hecho que la sostenga: "
            f"entra en la cuenta con 0,000 y su peso {weight} sigue en el divisor."
        )
    laf = format_laf_score(row["laf_score"])
    term = _number_es(float(row["weight"]) * float(row["laf_score"]), 3)
    return (
        f"Le diste importancia «{importance}» ({weight}). La publicación "
        f"declara: {value}. LAF resolvió esta condición en {laf}; multiplicado "
        f"por {weight} aporta {term} a la suma del puntaje."
    )


def listing_condition_names(rows) -> str:
    """Nombra las condiciones que participaron, en el orden en que se muestran."""
    names = [
        LISTING_CONDITION_SHORT.get(
            row["key"], str(row["label"] or row["key"]).casefold()
        )
        for row in (rows or ())
        if row.get("state") == "participa"
    ]
    return ", ".join(names)


def _nombres_es(items) -> str:
    """Enumera en castellano: «a», «a y b», «a, b y c».

    Reexporta ``comparison.join_es`` para que la enumeración de productos y la
    de publicaciones no puedan separarse.
    """
    return join_es(list(items))


def listing_score_story(position: int, total: int, rows) -> str:
    """Cierra la explicación con los valores que decidieron el puesto.

    Cita los **resultados LAF**, que son los números que el panel muestra en
    cada fila, y no los aportes (peso × resultado), que el panel sólo agrega
    por nivel de importancia. Nombrar un aporte dejaba en la frase un número
    que no figuraba en ninguna fila —«el más bajo el de envío (0,487)» junto a
    una fila que mostraba 0,727— y se leía como una contradicción
    (corregido el 2026-09-10). Cuando hay empate se nombran todas las
    condiciones empatadas: ``max``/``min`` desempataban por orden de llegada y
    la frase señalaba una sola de dos condiciones idénticas.

    No se usa ``comparison.build_score_story`` porque está escrita para las
    características de un producto: habla de menciones y, cuando los valores
    empatan, dice «la única característica que elegiste», que acá sería falso
    (en LAF 2 los empates entre condiciones son frecuentes: con reglas sólo
    positivas, dos condiciones cumplidas dan la misma confianza).
    """
    scored = [
        row
        for row in (rows or ())
        if row.get("state") == "participa" and row.get("laf_score") is not None
    ]
    if not scored or not position:
        return ""

    def name(row: dict) -> str:
        return LISTING_CONDITION_SHORT.get(
            row["key"], str(row.get("label") or row["key"]).casefold()
        )

    partes = [f"Quedó {position}º de {total}."]
    if len(scored) == 1:
        partes.append(
            f"La única condición que elegiste es {name(scored[0])}, "
            f"con {format_laf_score(scored[0]['laf_score'])}."
        )
        return " ".join(partes)

    lafs = {row["key"]: round(float(row["laf_score"]), 3) for row in scored}
    distintos = sorted(set(lafs.values()))

    def nombres_con(valor: float) -> str:
        return _nombres_es(
            [name(row) for row in scored if lafs[row["key"]] == valor]
        )

    if len(distintos) == 1:
        # Promedio ponderado de valores iguales: el puntaje es ese mismo valor,
        # cualquiera sea el peso. Decirlo evita que los pesos parezcan decidir
        # un orden que en este caso no tocaron.
        partes.append(
            f"Las {len(scored)} condiciones que elegiste dieron el mismo "
            f"resultado LAF ({_number_es(distintos[0], 3)}), así que el "
            "puntaje es ese mismo valor: cuando todas coinciden, los pesos no "
            "cambian el promedio."
        )
        return " ".join(partes)

    partes.append(
        f"El resultado LAF más alto es el de {nombres_con(distintos[-1])} "
        f"({_number_es(distintos[-1], 3)}) y el más bajo el de "
        f"{nombres_con(distintos[0])} ({_number_es(distintos[0], 3)})."
    )
    pesos = {round(float(row["weight"]), 2) for row in scored}
    if len(pesos) == 1:
        partes.append(
            "Les diste el mismo peso a todas, así que el orden lo decidieron "
            "esos resultados."
        )
    else:
        aportes = {
            row["key"]: round(float(row["weight"]) * float(row["laf_score"]), 3)
            for row in scored
        }
        mayor = max(aportes.values())
        empatados = [row for row in scored if aportes[row["key"]] == mayor]
        if len(empatados) == 1:
            fila = empatados[0]
            detalle = (
                f"{_number_es(float(fila['weight']))} × "
                f"{format_laf_score(fila['laf_score'])} = {_number_es(mayor, 3)}"
            )
        else:
            detalle = f"{_number_es(mayor, 3)} cada una"
        partes.append(
            "Como no les diste el mismo peso, a la suma entra peso × "
            f"resultado: el aporte más alto es el de "
            f"{_nombres_es([name(row) for row in empatados])} ({detalle})."
        )
    return " ".join(partes)


def listing_score_equation(breakdown) -> str:
    """La fórmula instanciada con los valores que dieron el puntaje mostrado."""
    if not breakdown or not getattr(breakdown, "contributions", ()):
        return ""

    def number(value: float, decimals: int = 2) -> str:
        return f"{float(value):.{decimals}f}".replace(".", ",")

    terms = " + ".join(
        f"{number(row.weight)} × {number(row.laf_score, 3)}"
        for row in breakdown.contributions
    )
    weights = " + ".join(number(row.weight) for row in breakdown.contributions)
    return (
        f"Puntaje = [{terms}] ÷ [{weights}] = "
        f"{number(breakdown.weighted_total)} ÷ {number(breakdown.weights_total)} = "
        f"{number(breakdown.final_score)}"
    )


def listing_tie_note(entry, ranking) -> str:
    """Declara el desempate cuando esta publicación empata con otra.

    El orden lo resolvió el evaluador con ``(-puntaje, -confianza del programa
    completo, identificador)``; acá sólo se nombra ese criterio con los valores
    que ya están en el resultado.
    """
    if entry is None:
        return ""
    score = round(float(getattr(entry, "final_score", 0.0)), 6)
    tied = [
        item
        for item in (ranking or ())
        if round(float(item.final_score), 6) == score
    ]
    others = len(tied) - 1
    if others < 1:
        return ""
    confidence = f"{float(getattr(entry, 'confidence', 0.0)):.2f}".replace(".", ",")
    cuantas = (
        "con otra publicación"
        if others == 1
        else f"con otras {others} publicaciones"
    )
    return (
        f"Empata en puntaje {cuantas}. A igual puntaje ordenamos por la "
        "confianza del programa completo, que ya incorpora el precio (esta "
        f"publicación: {confidence}); si también empata, por el identificador "
        "de la publicación."
    )
