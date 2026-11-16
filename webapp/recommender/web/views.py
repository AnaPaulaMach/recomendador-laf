"""Vistas del recorrido de recomendacion.

Capa de borde: resuelve el recorrido guardado, pide la evaluacion a
``services/`` y arma el contexto de las plantillas. No calcula puntajes ni
ordena: el ranking lo produce ``services/post_laf_decision.py`` y los textos,
``web/presentation.py``.
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_POST

from recommender.domain.contracts import EvaluationRequest, EvaluationResult, RankingEntry
from recommender.graph.service import ArgumentGraphService
from recommender.models import RecommendationSession
from recommender.repositories import (
    DomainConfigRepository,
    FixtureRepository,
    SupabaseRepository,
)
from recommender.services.use_cases import RecommendationWorkflow, get_evaluator
from recommender.services.laf_api import LAFGraphPresentationMapper
from recommender.services.post_laf_decision import zero_threshold_payload
from recommender.web.presentation import ASPECT_LABELS

from recommender.services.laf2_programs import LAF2ProgramService
from recommender.services import comparison as comparison_service

from .forms import (
    DomainSelectionForm,
    LAF2AuditProductForm,
    PurchasePreferencesForm,
    QualityPreferencesForm,
)
from .flow_state import (
    explanation_result as _explanation_result,
    get_flow as _flow,
    result_for_flow as _result_for_flow,
)
from .graph_support import graph_filters as _graph_filters
from .graph_support import graph_service as _graph_service

from .presentation import (
    MARKETPLACE_FALLBACK_URL,
    argument_priority as _argument_priority,
    aspect_claim_narrative as _aspect_claim_narrative,
    attach_primary_copy as _attach_primary_copy,
    format_currency as _format_currency,
    format_decimal_input as _format_decimal_input,
    listing_condition_names as _listing_condition_names,
    listing_condition_rows as _listing_condition_rows,
    listing_score_equation as _listing_score_equation,
    listing_score_story as _listing_score_story,
    listing_tie_note as _listing_tie_note,
    marketplace_item_url as _marketplace_item_url,
    plain_argument as _plain_argument,
    preference_level,
)

_DIMENSION_LABELS_ES = {
    "sensorial": "Perfil sensorial",
    "producto": "El producto",
    "valor": "Relación precio/valor",
    "elaboracion": "Elaboración",
    "conservacion": "Conservación",
}

# Claves cuyo nombre visible es femenino, para concordar «bien valorado/a».
_FEMININE_LABELS_ES = frozenset({
    "valor", "elaboracion", "conservacion", "acidez", "caducidad", "intensidad",
    "molienda", "originalidad", "preparacion", "presentacion", "variedad",
})

# Nombres cortos para los nodos del grafo (ASPECT_LABELS trae versiones largas).
_ASPECT_SHORT_ES = {
    "acidez": "Acidez", "aroma": "Aroma", "caducidad": "Frescura",
    "dulzor": "Dulzor", "intensidad": "Intensidad", "molienda": "Molienda",
    "originalidad": "Originalidad", "preparacion": "Preparación",
    "presentacion": "Presentación", "rendimiento": "Rendimiento",
    "sabor": "Sabor", "tamano": "Tamaño", "tueste": "Tueste",
    "variedad": "Variedad",
}


def _pred_label(literal: str) -> str:
    """Traduce un literal LAF (p. ej. ~sensorialBueno(X)) a lenguaje común."""
    text = str(literal or "").strip()
    negated = text.startswith("~")
    text = text.lstrip("~")
    head = text.split("(", 1)[0]
    label = head
    m = re.match(r"resena(Positiva|Negativa)([A-Za-z]+)", head)
    if m:
        aspect = m.group(2).casefold()
        short = _ASPECT_SHORT_ES.get(aspect, aspect)
        label = f"menciones a favor de {short.lower()}" if m.group(1) == "Positiva" else f"críticas sobre {short.lower()}"
        return label
    if head == "recomendar":
        return "no recomendar" if negated else "recomendar el café"
    m = re.match(r"([a-zA-Z_]+)Bueno", head)
    if m:
        key = m.group(1).casefold()
        base = _DIMENSION_LABELS_ES.get(key) or _ASPECT_SHORT_ES.get(key) or key
        if negated:
            return f"{base.lower()} en duda"
        valued = "bien valorada" if key in _FEMININE_LABELS_ES else "bien valorado"
        return f"{base.lower()} {valued}"
    return text


CATALOG_MARKETS = {
    "mx": {"name": "México", "site_id": "MLM"},
    "co": {"name": "Colombia", "site_id": "MCO"},
    "ar": {"name": "Argentina", "site_id": "MLA"},
}

logger = logging.getLogger(__name__)


def _domains() -> DomainConfigRepository:
    return DomainConfigRepository(settings.DOMAIN_CONFIG_DIR)


def _fixtures() -> FixtureRepository:
    return FixtureRepository(settings.FIXTURE_DIR)


DATABASE_UNAVAILABLE_MESSAGE = "No se pudo conectar con la base de datos"


def _datasets(
    domain_key: str,
    market: str = "mx",
    errors: list[str] | None = None,
) -> tuple[dict[str, str], ...]:
    """Catálogos de Supabase; el fixture de demostración sólo con ALLOW_DEMO_FIXTURE.

    Si la base no está configurada o falla y el respaldo no está habilitado,
    devuelve vacío y agrega DATABASE_UNAVAILABLE_MESSAGE a ``errors``.
    """
    source = SupabaseRepository(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    database_failed = not source.is_configured
    if source.is_configured:
        try:
            domain = _domains().get(domain_key)
            datasets = source.datasets(
                domain_key,
                category_labels=domain.dataset_category_labels,
                site_id=CATALOG_MARKETS.get(market, {}).get("site_id", ""),
            )
            if datasets:
                return datasets
        except Exception:
            logger.exception("No se pudieron consultar los catálogos en Supabase.")
            database_failed = True
    if settings.ALLOW_DEMO_FIXTURE:
        # Respaldo explícito: valores ilustrativos rotulados «demostración».
        return _fixtures().datasets(domain_key) if market == "mx" else ()
    if database_failed and errors is not None and DATABASE_UNAVAILABLE_MESSAGE not in errors:
        errors.append(DATABASE_UNAVAILABLE_MESSAGE)
    return ()


def _quality_aspects(flow: RecommendationSession, domain):
    """Limita los sliders a evidencia comparable del snapshot elegido."""
    source = SupabaseRepository(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    if not source.is_configured:
        return domain.quality_aspects

    fixture_keys = _fixtures().fixture_dataset_keys(domain.key)
    if flow.dataset_key in fixture_keys:
        return domain.quality_aspects

    cache_key = ":".join(
        (
            "quality-aspects",
            domain.key,
            flow.dataset_key,
            flow.strategy,
        )
    )
    cached_keys = cache.get(cache_key)
    if cached_keys is not None:
        available_keys = set(cached_keys)
        return tuple(
            aspect
            for aspect in domain.quality_aspects
            if aspect.key in available_keys
        )

    try:
        available_keys = set(
            source.available_quality_aspect_keys(
                flow.dataset_key,
                flow.strategy,
            )
        )
    except Exception:
        logger.exception(
            "No se pudo consultar la disponibilidad de aspectos para el catálogo."
        )
        # Una caída externa no debe romper una sesión ya iniciada. El formulario
        # completo conserva el comportamiento anterior hasta recuperar conexión.
        return domain.quality_aspects

    cache.set(
        cache_key,
        tuple(sorted(available_keys)),
        timeout=settings.QUALITY_ASPECT_CACHE_SECONDS,
    )

    return tuple(
        aspect for aspect in domain.quality_aspects if aspect.key in available_keys
    )


def _purchase_aspects(
    flow: RecommendationSession,
    domain,
    selected_product: RankingEntry | None = None,
):
    """Limita las condiciones a las publicaciones del producto seleccionado.

    Una condición que ninguna de esas publicaciones cumple no cambia el ranking;
    mostrarla haría creer que el sistema puede compararla.
    """
    source = SupabaseRepository(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    if not source.is_configured:
        return domain.purchase_aspects
    if flow.dataset_key in _fixtures().fixture_dataset_keys(domain.key):
        return domain.purchase_aspects

    product_id = (
        _catalog_product_id(selected_product)
        if selected_product is not None
        else str(flow.selected_product_id or "")
    )
    cache_key = ":".join(
        ("purchase-aspects", domain.key, flow.dataset_key, product_id)
    )
    cached_keys = cache.get(cache_key)
    if cached_keys is None:
        try:
            cached_keys = LAF2ProgramService(
                source,
                settings.REPOSITORY_ROOT,
            ).available_purchase_condition_keys(
                flow.dataset_key,
                domain.key,
                product_id=product_id,
            )
        except Exception:
            logger.exception(
                "No se pudo consultar la disponibilidad de condiciones de compra."
            )
            return domain.purchase_aspects
        cache.set(
            cache_key,
            tuple(sorted(cached_keys)),
            timeout=settings.QUALITY_ASPECT_CACHE_SECONDS,
        )
    available_keys = set(cached_keys)
    return tuple(
        aspect for aspect in domain.purchase_aspects if aspect.key in available_keys
    )


def _available_domains():
    """Publica sólo categorías con una demostración completa disponible."""
    fixtures = _fixtures()
    return tuple(
        domain
        for domain in _domains().list_domains()
        if fixtures.load(domain.key).get("products")
    )


def _local_datetime(value: str):
    parsed = parse_datetime(str(value or ""))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return timezone.localtime(parsed)


def _preference_items(values: dict, aspects) -> list[dict]:
    labels = {aspect.key: aspect.label for aspect in aspects}
    items = []
    for key, raw_value in (values or {}).items():
        try:
            value = max(0.0, min(float(raw_value), 1.0))
        except (TypeError, ValueError):
            value = 0.0
        level, level_key = preference_level(value)
        items.append(
            {
                "key": key,
                "label": labels.get(key, key.replace("_", " ").capitalize()),
                "value": value,
                "value_display": f"{value:.2f}".replace(".", ","),
                "percent": round(value * 100),
                "level": level,
                "level_key": level_key,
            }
        )
    return sorted(items, key=lambda item: (-item["value"], item["label"]))


def _resume_flow(flow: RecommendationSession):
    """Lleva al último paso disponible sin exponer una página de error técnica."""
    if not flow.laf1_result:
        return redirect("recommender:quality", flow_id=flow.id)
    if not flow.selected_product_id:
        return redirect("recommender:product-ranking", flow_id=flow.id)
    if not flow.laf2_result:
        return redirect("recommender:purchase", flow_id=flow.id)
    return redirect("recommender:listing-ranking", flow_id=flow.id)


def _catalog_product_id(entry: RankingEntry) -> str:
    """Recupera el identificador MLM aun cuando el fixture use un slug legible."""
    candidates = (entry.metadata.get("product_id"), entry.entity_id)
    for candidate in candidates:
        match = re.match(r"^([a-z]{3,4}\d+)", str(candidate or ""), flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ""


def _attach_product_images(
    flow: RecommendationSession,
    result: EvaluationResult,
) -> EvaluationResult:
    """Enriquece el contrato de presentación sin modificar el resultado guardado."""
    pending = {
        _catalog_product_id(entry)
        for entry in result.ranking
        if not entry.metadata.get("image_url")
    }
    pending.discard("")
    if not pending:
        return result

    source = SupabaseRepository(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    if not source.is_configured:
        return result
    try:
        images = source.product_images(flow.dataset_key, pending)
    except Exception:
        # La recomendación debe seguir disponible si falla la fuente visual.
        return result

    for entry in result.ranking:
        image_url = images.get(_catalog_product_id(entry), "")
        if image_url:
            entry.metadata["image_url"] = image_url
    return result


def _budget_range(flow: RecommendationSession, product: RankingEntry) -> dict | None:
    product_id = _catalog_product_id(product)
    source = SupabaseRepository(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    if source.is_configured and product_id:
        try:
            observed = source.listing_price_range(flow.dataset_key, product_id)
        except Exception:
            observed = None
        if observed:
            minimum, maximum, count = observed
            return {
                "minimum": minimum,
                "maximum": maximum,
                "minimum_label": _format_currency(minimum),
                "maximum_label": _format_currency(maximum),
                "count": count,
            }

    # El fixture conserva un rango legible para que el recorrido local no quede vacío.
    values = [
        float(value.replace(",", "."))
        for value in re.findall(r"\d+(?:[.,]\d+)?", str(product.metadata.get("price_range") or ""))
    ]
    if not values:
        return None
    return {
        "minimum": min(values),
        "maximum": max(values),
        "minimum_label": _format_currency(min(values)),
        "maximum_label": _format_currency(max(values)),
        "count": None,
    }


def _single_purchase_option(
    flow: RecommendationSession,
    product: RankingEntry,
    budget_range: dict | None,
) -> RankingEntry | None:
    """Presenta una única publicación sin inventar una comparación LAF 2."""
    if not budget_range or budget_range.get("count") != 1:
        return None
    source = SupabaseRepository(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    if not source.is_configured:
        return None
    try:
        _product, rows = source.laf2_generation_items(
            flow.dataset_key,
            _catalog_product_id(product),
        )
    except Exception:
        logger.exception("No se pudo cargar la única publicación disponible.")
        return None
    if len(rows) != 1:
        return None

    row = rows[0]
    tags = row.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except json.JSONDecodeError:
            tags = []
    tags = set(tags) if isinstance(tags, list) else set()
    installments = (
        "12 cuotas sin interés"
        if {"12x_campaign", "1p_12x_campaign"} & tags
        else "9 cuotas sin interés"
        if "9x_campaign" in tags
        else "3 cuotas sin interés"
        if "3x_campaign" in tags
        else "No informadas"
    )
    try:
        price_label = _format_currency(float(row.get("price")))
    except (TypeError, ValueError):
        price_label = "No informado"

    entry = RankingEntry.from_dict(
        {
            "entity_id": str(row.get("item_id") or "publicacion-unica"),
            "entity_name": flow.selected_product_name,
            "position": 1,
            "metadata": {
                "product_id": flow.selected_product_id,
                "seller": (
                    f"Vendedor {row.get('seller_id')}"
                    if row.get("seller_id")
                    else "Vendedor no informado"
                ),
                "price_label": price_label,
                "installments": installments,
                "warranty": LAF2ProgramService._warranty_label(row),
                "shipping": "Gratis" if row.get("shipping_free_shipping") else "No informado",
            },
        }
    )
    # Publicación única: no pasa por `attach_primary_copy`, así que el rótulo
    # (U29) y la dirección armada desde el `item_id` (U30) se ponen acá.
    entry.metadata["listing_title"] = " · ".join(
        part for part in ("Publicación", price_label) if part and part != "No informado"
    )
    entry.metadata["item_id_display"] = str(entry.entity_id or "")
    marketplace_url = _marketplace_item_url(entry.entity_id)
    entry.metadata["purchase_url"] = marketplace_url or MARKETPLACE_FALLBACK_URL
    entry.metadata["purchase_url_is_fallback"] = not bool(marketplace_url)
    return entry


def _attach_marketplace_links(result: EvaluationResult) -> EvaluationResult:
    """Sólo publica enlaces HTTPS que realmente apunten a Mercado Libre."""
    for entry in result.ranking:
        candidate = str(
            entry.metadata.get("permalink")
            or entry.metadata.get("marketplace_url")
            or ""
        ).strip()
        parsed = urlparse(candidate)
        hostname = (parsed.hostname or "").casefold()
        if parsed.scheme == "https" and (
            hostname == "mercadolibre.com"
            or hostname.endswith(".mercadolibre.com")
            or hostname == "mercadolibre.com.mx"
            or hostname.endswith(".mercadolibre.com.mx")
        ):
            entry.metadata["marketplace_url"] = candidate
        else:
            entry.metadata.pop("marketplace_url", None)
    return result


def _entry(result: EvaluationResult, entity_id: str) -> RankingEntry:
    for item in result.ranking:
        if item.entity_id == entity_id:
            return item
    raise Http404("La entidad solicitada no pertenece a esta corrida.")


def _summary_graph_service(
    result: EvaluationResult,
    entity_id: str,
) -> ArgumentGraphService:
    """Vista explicada de un único producto; no reemplaza el grafo técnico LAF."""
    selected = _entry(result, entity_id) if entity_id else result.ranking[0]
    is_multicriteria = str(
        selected.metadata.get("decision_model") or ""
    ).startswith("post_laf_multicriteria")
    root_id = f"summary:conclusion:{selected.entity_id}"
    aggregation_id = f"summary:aggregation:{selected.entity_id}"
    nodes = [
        {
            "id": root_id,
            "label": "Recomendación final",
            "literal": str(selected.metadata.get("laf_argument") or selected.entity_id),
            "node_type": "conclusion",
            "polarity": "positive",
            "confidence": selected.confidence,
            "preference": selected.preference,
            "accumulated_value": selected.final_score,
            "weakened_value": selected.final_score,
            "acceptability_status": "accepted" if selected.final_score > 0 else "rejected",
            "evidence_count": selected.evidence_count,
            "metadata": {
                "product": selected.entity_name,
                "display_name": f"Recomendar {selected.entity_name}",
                "graph_label": "Recomendación final",
                "is_root": True,
                "view_kind": "summary",
            },
        },
        {
            "id": aggregation_id,
            "label": "LAF + preferencias" if is_multicriteria else "LAF",
            "literal": (
                "decision_multicriterio_post_laf"
                if is_multicriteria
                else "resumen_de_agregacion_laf"
            ),
            "node_type": "operator",
            "polarity": "neutral",
            "confidence": 0,
            "preference": 0,
            "accumulated_value": 0,
            "weakened_value": 0,
            "acceptability_status": "accepted",
            "evidence_count": 0,
            "metadata": {
                "operator": "SUMMARY",
                "display_name": (
                    "La decisión pondera resultados LAF por aspecto"
                    if is_multicriteria
                    else "LAF combina los argumentos"
                ),
                "plain_summary": (
                    "LAF evalúa la evidencia de cada aspecto y luego se aplican los pesos elegidos para producir el ranking."
                    if is_multicriteria
                    else "En este paso LAF combina el apoyo, los conflictos y las preferencias antes de producir la recomendación."
                ),
                "view_kind": "summary",
            },
        },
    ]
    edges = [
        {
            "id": "summary:edge:result",
            "source": aggregation_id,
            "target": root_id,
            "edge_type": "support",
            "label": "Resultado",
            "rule_id": "resumen-explicado",
        }
    ]
    displayed_arguments = [
        *((argument, True) for argument in sorted(selected.arguments_for, key=_argument_priority)[:3]),
        *((argument, False) for argument in sorted(selected.arguments_against, key=_argument_priority)[:3]),
    ]
    for index, (argument, positive) in enumerate(displayed_arguments, start=1):
        display = _plain_argument(argument, positive=positive)
        node_id = f"summary:argument:{index}:{argument.argument_id}"
        score = min(float(argument.confidence), float(argument.preference))
        nodes.append(
            {
                "id": node_id,
                "label": display["title"],
                "literal": argument.title,
                "node_type": "aspect",
                "polarity": "positive" if positive else "negative",
                "confidence": argument.confidence,
                "preference": argument.preference,
                "accumulated_value": score,
                "weakened_value": score,
                "acceptability_status": "accepted" if score > 0 else "rejected",
                "evidence_count": argument.evidence_count,
                "metadata": {
                    "product": selected.entity_name,
                    "aspect": argument.aspect,
                    "display_name": display["title"],
                    "graph_label": display["title"],
                    "plain_summary": display["summary"],
                    "view_kind": "summary",
                },
            }
        )
        edges.append(
            {
                "id": f"summary:edge:{index}",
                "source": node_id,
                "target": aggregation_id,
                "edge_type": "support" if positive else "conflict",
                "label": "A favor" if positive else "En contra",
                "rule_id": "resumen-explicado",
            }
        )
    graph = {
        "graph_id": f"summary:{result.run_id}:{selected.entity_id}",
        "root_id": root_id,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "nodes": nodes,
        "edges": edges,
        "available_filters": {},
    }
    return ArgumentGraphService(graph, settings.GRAPH_VISIBLE_NODE_LIMIT)


def home(request):
    """Portada: elige categoria y catalogo, y abre un recorrido nuevo."""
    requested_market = request.GET.get("market")
    if requested_market in CATALOG_MARKETS:
        request.session["catalog_market"] = requested_market

    catalog_market = request.session.get("catalog_market", "mx")
    if catalog_market not in CATALOG_MARKETS:
        catalog_market = "mx"
        request.session["catalog_market"] = catalog_market

    domains = _available_domains()
    category_options = []
    catalog_errors: list[str] = []
    for domain in domains:
        datasets = _datasets(domain.key, catalog_market, errors=catalog_errors)
        for position, dataset in enumerate(datasets):
            category_label = str(dataset.get("category_label") or "").strip()
            captured_at = str(dataset.get("captured_at") or "").strip()
            display_name = {
                "cafe": "Café",
                "cafe instantaneo": "Café instantáneo",
                "cafe en granos y molido": "Café en grano o molido",
            }.get(category_label.casefold(), category_label or domain.display_name)
            detail = (
                f"{CATALOG_MARKETS[catalog_market]['name']} · relevado el {captured_at}"
                if captured_at
                else str(dataset.get("label") or "Catálogo disponible")
            )
            category_options.append(
                {
                    "domain": domain,
                    "dataset": dataset,
                    "display_name": display_name,
                    "detail": detail,
                    "option_id": f"{domain.key}-{position}",
                }
            )
    catalog_market_available = bool(category_options)
    return render(
        request,
        "recommender/home.html",
        {
            "domains": domains,
            "category_options": category_options,
            "catalog_market": catalog_market,
            "catalog_market_name": CATALOG_MARKETS[catalog_market]["name"],
            "catalog_market_available": catalog_market_available,
            "catalog_error": "" if catalog_market_available else (catalog_errors[0] if catalog_errors else ""),
        },
    )


def start(request):
    """Crea el recorrido con la categoria elegida y lleva al paso 1."""
    if request.method != "POST":
        return redirect("recommender:home")

    domains = _available_domains()
    selected_domain = (
        request.POST.get("domain")
        or (domains[0].key if domains else "cafe")
    )
    catalog_market = request.session.get("catalog_market", "mx")
    if catalog_market not in CATALOG_MARKETS:
        catalog_market = "mx"
    datasets = _datasets(selected_domain, catalog_market)
    form = DomainSelectionForm(
        request.POST or None,
        domains=domains,
        datasets=datasets,
        initial={"domain": selected_domain, "strategy": "D"},
    )
    if request.method == "POST" and form.is_valid():
        flow = RecommendationSession.objects.create(
            domain_key=form.cleaned_data["domain"],
            dataset_key=form.cleaned_data["dataset_key"],
            strategy=form.cleaned_data["strategy"],
        )
        request.session["recommendation_flow_id"] = str(flow.id)
        return redirect("recommender:quality", flow_id=flow.id)
    return redirect("recommender:home")


def quality(request, flow_id):
    """Paso 1: que le importa a la persona de la calidad del producto."""
    flow = _flow(flow_id)
    domain = _domains().get(flow.domain_key)
    quality_aspects = _quality_aspects(flow, domain)
    form = QualityPreferencesForm(
        request.POST or None,
        domain=domain,
        aspects=quality_aspects,
        initial=flow.quality_preferences or None,
    )
    if request.method == "POST" and quality_aspects and form.is_valid():
        RecommendationWorkflow().evaluate_quality(flow, form.preferences())
        return redirect("recommender:product-ranking", flow_id=flow.id)
    return render(
        request,
        "recommender/quality.html",
        {
            "flow": flow,
            "domain": domain,
            "form": form,
            "quality_aspects": quality_aspects,
        },
    )


@require_POST
def preference_summary(request, flow_id):
    """Fragmento HTMX: resumen en vivo de las preferencias marcadas."""
    flow = _flow(flow_id)
    domain = _domains().get(flow.domain_key)
    stage = request.POST.get("stage", "quality")
    aspects = (
        _purchase_aspects(flow, domain)
        if stage == "purchase"
        else _quality_aspects(flow, domain)
    )
    values = []
    for aspect in aspects:
        try:
            value = float(request.POST.get(aspect.key, 0))
        except (TypeError, ValueError):
            value = 0
        normalized_value = max(0, min(value, 1))
        level, _ = preference_level(normalized_value)
        values.append(
            {"label": aspect.label, "value": normalized_value, "level": level}
        )
    values.sort(key=lambda item: item["value"], reverse=True)
    return render(
        request,
        "recommender/partials/preference_summary.html",
        {"preferences": values[:4]},
    )


@require_GET
def product_ranking(request, flow_id):
    """Paso 2: el orden de productos que produjo LAF 1."""
    flow = _flow(flow_id)
    if not flow.laf1_result:
        return _resume_flow(flow)
    domain = _domains().get(flow.domain_key)
    result = _attach_primary_copy(
        _attach_product_images(flow, _result_for_flow(flow, flow.laf1_result)),
        preferences=flow.quality_preferences,
    )
    return render(
        request,
        "recommender/product_ranking.html",
        {
            "flow": flow,
            "result": result,
            "domain": domain,
            "no_preferences_selected": not any(
                value > 0 for value in flow.quality_preferences.values()
            ),
            "laf2_audit_enabled": (
                settings.DEBUG
                and result.evaluation_status == "pending"
                and result.program_status == "generated"
                and not result.ranking
            ),
        },
    )


def audit_laf2_product(request, flow_id):
    """Puente local de 08 a 09; nunca forma parte del recorrido publicado."""
    if not settings.DEBUG:
        raise Http404("El modo de auditoria LAF 2 solo esta disponible localmente.")
    flow = _flow(flow_id)
    if not flow.laf1_result:
        return _resume_flow(flow)
    result = _result_for_flow(flow, flow.laf1_result)
    if result.program_status != "generated" or result.ranking:
        raise Http404("Esta corrida no necesita un producto controlado.")

    source = SupabaseRepository(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    products = ()
    load_error = ""
    try:
        products = source.laf2_audit_products(flow.dataset_key)
    except Exception:
        logger.exception("No se pudieron cargar productos para la auditoria LAF 2.")
        load_error = (
            "No pudimos cargar los productos revisados de este catalogo. "
            "Comproba la conexion y el estado de la revision 01b."
        )

    form = LAF2AuditProductForm(request.POST or None, products=products)
    if request.method == "POST" and form.is_valid():
        product = form.selected_product()
        RecommendationWorkflow().select_product(
            flow,
            str(product["product_id"]),
            str(product["name"]),
        )
        return redirect("recommender:purchase", flow_id=flow.id)
    return render(
        request,
        "recommender/audit_laf2_product.html",
        {
            "flow": flow,
            "form": form,
            "products": products,
            "load_error": load_error,
        },
    )


@require_GET
def product_detail(request, flow_id, entity_id):
    """Detalle de un producto: su explicacion, su ledger y su grafo por aspecto."""
    flow = _flow(flow_id)
    if not flow.laf1_result:
        return _resume_flow(flow)
    result = _attach_primary_copy(
        _attach_product_images(flow, _result_for_flow(flow, flow.laf1_result))
    )
    product = _entry(result, entity_id)
    fragment = _summary_graph_service(result, entity_id).fragment(
        depth=2,
        limit=250,
    )
    domain = _domains().get(flow.domain_key)
    aspect_labels = {aspect.key: aspect.label for aspect in domain.quality_aspects}
    # Grafo de presentación (mismo que baja el JSON) para ubicar al producto
    # frente a los demás por aspecto, sin recalcular LAF.
    comparison_graph = _graph_service(flow.domain_key, result, entity_id).data
    standings = comparison_service.build_aspect_standings(
        comparison_graph,
        product.entity_name if product else "",
        aspect_labels,
        flow.quality_preferences,
    )
    ranking = comparison_service.build_ranking(result.ranking, entity_id)
    breakdown = comparison_service.build_score_breakdown(
        product,
        comparison_graph,
        aspect_labels,
    )
    claims = comparison_service.build_claim_ledger(
        comparison_graph,
        product.entity_name if product else "",
        aspect_labels,
        flow.quality_preferences,
        criticism_info=(product.metadata.get("aspect_criticism") if product else None),
    )
    verdict = comparison_service.build_verdict(product, claims)
    # La tabla por característica y la fórmula del puntaje muestran lo mismo:
    # el resultado LAF de cada aspecto, en el mismo orden.
    laf_scores = {
        str(row.key): row
        for row in (breakdown.contributions if breakdown else ())
    }
    def _claim_row(claim) -> dict:
        contribution = laf_scores.get(claim.key)
        laf_score = contribution.laf_score if contribution is not None else None
        return {
            "claim": claim,
            "label": claim.label,
            "laf_score": laf_score,
            "weight": contribution.weight if contribution is not None else 0.0,
            "mentions": claim.mentions_favor + claim.mentions_against,
            # Una sola fuente para la oración del aspecto (presentation.py), la
            # misma con y sin críticas.
            "narrative": _aspect_claim_narrative(claim, laf_score),
        }

    claim_rows = [_claim_row(claim) for claim in claims]
    claim_rows.sort(key=lambda row: (row["laf_score"] is None, -(row["laf_score"] or 0.0), row["label"]))
    score_groups = comparison_service.build_score_groups(breakdown)
    score_equation = comparison_service.build_score_equation(breakdown)
    score_story = comparison_service.build_score_story(
        getattr(product, "position", 0) if product else 0,
        len(ranking),
        claim_rows,
    )
    position_note = comparison_service.build_position_note(ranking, claims)
    score_map = comparison_service.build_score_map(ranking)
    collapsed = comparison_service.build_collapsed_graph(
        comparison_graph,
        product.entity_name if product else "",
        aspect_labels,
    )
    return render(
        request,
        "recommender/product_detail.html",
        {
            "flow": flow,
            "result": result,
            "product": product,
            "fragment": fragment,
            "graph_url": reverse("recommender:graph-fragment", args=[flow.id]),
            "entity_id": entity_id,
            "is_laf1": True,
            "standings": standings,
            "ranking": ranking,
            "breakdown": breakdown,
            "claims": claims,
            "claim_rows": claim_rows,
            "score_groups": score_groups,
            "score_equation": score_equation,
            "score_story": score_story,
            "verdict": verdict,
            "position_note": position_note,
            "score_map": score_map,
            "collapsed": collapsed,
            "product_count": len(ranking),
            "ranking_top_score": max((row.final_score for row in ranking), default=0),
            "process_steps": {
                "mentions": getattr(product, "evidence_count", 0) if product else 0,
                "aspects_ok": sum(1 for c in claims if c.plain_status == "bien_valorado"),
                "aspects_crit": sum(1 for c in claims if c.plain_status == "con_criticas"),
                "position": getattr(product, "position", 0) if product else 0,
                "total": len(ranking),
            },
            "graph_total_nodes": len((comparison_graph or {}).get("nodes") or []),
        },
    )


def _aspect_mention_examples(dataset_key: str, entity_id: str, aspect: str) -> list[dict]:
    """Menciones de ejemplo del aspecto; vacío si no hay Supabase o falla."""
    source = SupabaseRepository(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    if not source.is_configured:
        return []
    try:
        return source.aspect_mention_examples(dataset_key, entity_id, aspect)
    except Exception:  # noqa: BLE001 - la explicación no depende de esto
        logger.exception("No se pudieron leer menciones de ejemplo de %s.", aspect)
        return []


@require_GET
def aspect_graph(request, flow_id):
    """Expone la corrida guardada que aportó el score de este aspecto.

    Las sesiones históricas, sin programas separados guardados, conservan el
    camino anterior de visualización; sus resultados no se reescriben.
    """
    flow = _flow(flow_id)
    entity_id = str(request.GET.get("entity_id") or "")
    aspect = str(request.GET.get("aspect") or "").strip()
    empty = {"nodes": [], "edges": [], "root_id": "", "total_nodes": 0, "total_edges": 0}
    if not flow.laf1_result or not aspect:
        return JsonResponse(empty)
    result = _result_for_flow(flow, flow.laf1_result)
    product = _entry(result, entity_id)
    if product is None:
        return JsonResponse(empty)
    if result.aspect_programs:
        raw_graph = result.aspect_graphs.get(aspect)
        if not raw_graph:
            return JsonResponse(empty)
        entity_names = {
            str(item.metadata.get("laf_argument") or item.entity_id): item.entity_name
            for item in result.ranking
        }
        root = str((product.metadata.get("aspect_node_ids") or {}).get(aspect) or "")
        mapped = LAFGraphPresentationMapper().map(
            raw_graph, root_id=root, entity_names=entity_names,
        )
        subgraph = _subgraph_for_product(mapped, product.entity_name.strip().casefold(), ancestors_only=True)
        _friendly_relabel(subgraph, aspect)
        subgraph["aspect"] = aspect
        subgraph["source"] = "stored_evaluation"
        subgraph["examples"] = _aspect_mention_examples(
            result.dataset_key, product.entity_id, aspect
        )
        return JsonResponse(subgraph)
    evaluator = get_evaluator()
    if not hasattr(evaluator, "api_client") or not hasattr(evaluator, "laf1_programs"):
        return JsonResponse(empty)
    try:
        aspect_request = EvaluationRequest(
            domain=flow.domain_key,
            dataset_key=result.dataset_key,
            strategy=result.strategy,
            preferences={aspect: 1.0},
        )
        generated = evaluator.laf1_programs.generate(aspect_request)
        isolated = _isolated_aspect_program(generated.text, aspect, entity_id)
        if not isolated.strip():
            return JsonResponse(empty)
        payload = zero_threshold_payload(
            evaluator.parser.parse(isolated).to_request_payload()
        )
        raw_graph = evaluator.api_client.build_graph(payload)
    except Exception:  # noqa: BLE001 - fallback amable si la API/DB falla
        logger.exception("No se pudo construir el grafo del aspecto %s.", aspect)
        return JsonResponse(empty)
    entity_names = {
        str(item.metadata.get("laf_argument") or item.entity_id): item.entity_name
        for item in result.ranking
    }
    mapped = LAFGraphPresentationMapper().map(raw_graph, entity_names=entity_names)
    name = (product.entity_name or "").strip().casefold()
    subgraph = _subgraph_for_product(mapped, name)
    _friendly_relabel(subgraph, aspect)
    subgraph["examples"] = _aspect_mention_examples(
        result.dataset_key, product.entity_id, aspect
    )
    return JsonResponse(subgraph)


def _friendly_relabel(graph: dict, default_aspect: str = "") -> None:
    """Pone etiquetas en lenguaje común (graph_label) sin cambiar la estructura
    ni los valores. El literal técnico sigue disponible en el nodo."""
    for node in graph.get("nodes") or []:
        meta = node.setdefault("metadata", {})
        meta["hide_preference"] = True  # El resultado por aspecto se explica por confianza.
        ntype = node.get("node_type")
        literal = str(node.get("literal") or "")
        if ntype == "operator":
            continue  # dMP / CA se dejan como en el motor
        if ntype == "rule":
            head, _, body = literal.partition(":-")
            meta["graph_label"] = (
                f"Si {_pred_label(body)}\n→ {_pred_label(head)}" if body.strip() else "Regla"
            )
            continue
        # El resto se etiqueta por el LITERAL (no por polaridad/tipo, que pueden
        # venir mal: resenaNegativa es un hecho "positivo", y a veces recomendar
        # aparece tipado como hecho).
        core = literal.split("(", 1)[0].strip()
        negated = core.startswith("~")
        core = core.lstrip("~")
        m = re.match(r"resena(Positiva|Negativa)([A-Za-z]+)", core)
        if m:
            asp = m.group(2).casefold()
            short = _ASPECT_SHORT_ES.get(asp, asp.capitalize())
            meta["graph_label"] = f"A favor: {short}" if m.group(1) == "Positiva" else f"Críticas: {short}"
            continue
        if core == "recomendar":
            meta["graph_label"] = (
                "Aporte en contra de este punto" if negated else "Resultado de este punto"
            )
            continue
        m = re.match(r"([a-zA-Z_]+)Bueno", core)
        if m:
            key = m.group(1).casefold()
            if key in _DIMENSION_LABELS_ES:
                dim = _DIMENSION_LABELS_ES[key]
                meta["graph_label"] = f"{dim}: en duda" if negated else dim
            else:
                short = _ASPECT_SHORT_ES.get(key, key.capitalize())
                feminine = key in _FEMININE_LABELS_ES
                if negated:
                    meta["graph_label"] = f"{short}: {'cuestionada' if feminine else 'cuestionado'}"
                else:
                    meta["graph_label"] = f"{short}: {'bien valorada' if feminine else 'bien valorado'}"


def _isolated_aspect_program(program_text: str, aspect_key: str, product_id: str) -> str:
    """Arma un programa AISLADO de un solo aspecto para un producto: sus hechos
    (resenaPositiva/Negativa<Aspecto>) + la cadena de reglas
    <aspecto>Bueno → <dimensión>Bueno → recomendar. Así el grafo resultante es
    la derivación limpia de ese aspecto, no la combinación de los 14.

    Sólo se usa en el camino de **sesiones históricas**: los resultados nuevos
    guardan un programa y un grafo por aspecto (ADR-002) y no pasan por acá.
    """
    aspect_cap = aspect_key[:1].upper() + aspect_key[1:]
    pid = (product_id or "").lower()
    lines = [ln.strip() for ln in program_text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("%")]
    facts: list[str] = []
    fact_re = re.compile(rf"^resena(?:Positiva|Negativa){re.escape(aspect_cap)}\(", re.IGNORECASE)
    for ln in lines:
        if fact_re.match(ln) and pid and pid in ln.lower():
            facts.append(ln)
    if not facts:
        return ""
    # Dimensión que agrega este aspecto: regla "<dim>Bueno(X) :- <aspecto>Bueno(X)."
    dim = None
    body_ref = f"{aspect_key}Bueno(X)"
    for ln in lines:
        if ":-" not in ln:
            continue
        head, _, body = ln.partition(":-")
        if body_ref in body and "recomendar" not in head:
            m = re.match(r"~?([a-zA-Z_]+)Bueno\(X\)", head.strip())
            if m and m.group(1) != aspect_key:
                dim = m.group(1)
                break
    rules: list[str] = []
    for ln in lines:
        if ":-" not in ln:
            continue
        if re.match(rf"~?{re.escape(aspect_key)}Bueno\(X\) :-", ln):
            rules.append(ln)
        elif dim and re.match(rf"~?{re.escape(dim)}Bueno\(X\) :- ~?{re.escape(aspect_key)}Bueno\(X\)", ln):
            rules.append(ln)
        elif dim and re.match(rf"~?recomendar\(X\) :- ~?{re.escape(dim)}Bueno\(X\)", ln):
            rules.append(ln)
    if not rules:
        return ""
    return "\n".join(facts + rules) + "\n"


def _subgraph_for_product(mapped: dict, product_name: str, *, ancestors_only: bool = False) -> dict:
    """Recorta el grafo mapeado al producto: sus hechos/aspectos + reglas y
    operadores que queden conectados; descarta ramas de otros productos."""
    nodes = mapped.get("nodes") or []
    edges = mapped.get("edges") or []

    def node_product(node):
        return str((node.get("metadata") or {}).get("product") or "").strip().casefold()

    keep = set()
    for node in nodes:
        ntype = node.get("node_type")
        if (not ancestors_only and ntype in ("rule", "operator")) or node_product(node) == product_name:
            keep.add(str(node.get("id")))
    if ancestors_only:
        # Las reglas compartidas no deben arrastrar operadores de otros productos.
        structural = {str(n.get("id")) for n in nodes if n.get("node_type") in ("rule", "operator")}
        while True:
            incoming = {str(e.get("source")) for e in edges
                        if str(e.get("target")) in keep and str(e.get("source")) in structural}
            if incoming <= keep:
                break
            keep.update(incoming)
    kept_edges = [
        edge for edge in edges
        if str(edge.get("source")) in keep and str(edge.get("target")) in keep
    ]
    # Podar reglas/operadores que quedaron sin conexión (eran de otros productos).
    connected = set()
    for edge in kept_edges:
        connected.add(str(edge.get("source")))
        connected.add(str(edge.get("target")))
    final_nodes = [
        node for node in nodes
        if str(node.get("id")) in keep
        and (
            node.get("node_type") not in ("rule", "operator")
            or str(node.get("id")) in connected
        )
    ]
    final_ids = {str(node.get("id")) for node in final_nodes}
    final_edges = [
        edge for edge in kept_edges
        if str(edge.get("source")) in final_ids and str(edge.get("target")) in final_ids
    ]
    root_id = next(
        (n["id"] for n in final_nodes if n.get("node_type") == "conclusion"),
        final_nodes[0]["id"] if final_nodes else "",
    )
    return {
        "graph_id": mapped.get("graph_id", "laf-aspecto"),
        "root_id": root_id,
        "total_nodes": len(final_nodes),
        "total_edges": len(final_edges),
        "nodes": final_nodes,
        "edges": final_edges,
    }


@require_POST
def select_product(request, flow_id, entity_id):
    """Fija el producto elegido y pasa a la etapa de compra."""
    flow = _flow(flow_id)
    if not flow.laf1_result:
        return _resume_flow(flow)
    result = _result_for_flow(flow, flow.laf1_result)
    product = _entry(result, entity_id)
    RecommendationWorkflow().select_product(flow, product.entity_id, product.entity_name)
    return redirect("recommender:purchase", flow_id=flow.id)


def purchase(request, flow_id):
    """Paso 3: condiciones de compra y presupuesto."""
    flow = _flow(flow_id)
    if not flow.laf1_result:
        return _resume_flow(flow)
    if not flow.selected_product_id:
        return redirect("recommender:product-ranking", flow_id=flow.id)
    domain = _domains().get(flow.domain_key)
    product_result = _attach_product_images(
        flow,
        _result_for_flow(flow, flow.laf1_result),
    )
    if product_result.ranking:
        selected_product = _entry(product_result, flow.selected_product_id)
    elif settings.DEBUG and product_result.program_status == "generated":
        selected_product = RankingEntry.from_dict(
            {
                "entity_id": flow.selected_product_id,
                "entity_name": flow.selected_product_name,
                "position": 0,
                "metadata": {"product_id": flow.selected_product_id},
            }
        )
    else:
        return redirect("recommender:product-ranking", flow_id=flow.id)
    budget_range = _budget_range(flow, selected_product)
    single_option = _single_purchase_option(flow, selected_product, budget_range)
    if single_option is not None:
        return render(
            request,
            "recommender/single_listing.html",
            {
                "flow": flow,
                "selected_product": selected_product,
                "item": single_option,
            },
        )
    initial = dict(flow.purchase_preferences or {})
    initial.update({"budget_min": flow.budget_min, "budget_max": flow.budget_max})
    purchase_aspects = _purchase_aspects(flow, domain, selected_product)
    unavailable_conditions = [
        aspect.label
        for aspect in domain.purchase_aspects
        if aspect not in purchase_aspects
    ]
    form = PurchasePreferencesForm(
        request.POST or None,
        domain=domain,
        aspects=purchase_aspects,
        initial=initial,
    )
    if budget_range:
        form.fields["budget_min"].widget.attrs["placeholder"] = _format_decimal_input(
            budget_range["minimum"]
        )
        form.fields["budget_max"].widget.attrs["placeholder"] = _format_decimal_input(
            budget_range["maximum"]
        )
    if request.method == "POST" and form.is_valid():
        RecommendationWorkflow().evaluate_purchase(
            flow,
            form.preferences(),
            float(form.cleaned_data["budget_min"]) if form.cleaned_data["budget_min"] is not None else None,
            float(form.cleaned_data["budget_max"]) if form.cleaned_data["budget_max"] is not None else None,
        )
        return redirect("recommender:listing-ranking", flow_id=flow.id)
    return render(
        request,
        "recommender/purchase.html",
        {
            "flow": flow,
            "domain": domain,
            "form": form,
            "selected_product": selected_product,
            "budget_range": budget_range,
            "audit_mode": not bool(product_result.ranking),
            "unavailable_conditions": unavailable_conditions,
        },
    )


@require_GET
def listing_ranking(request, flow_id):
    """Paso 4: el orden de publicaciones que produjo LAF 2."""
    flow = _flow(flow_id)
    if not flow.laf2_result:
        return _resume_flow(flow)
    result = _attach_primary_copy(
        _attach_marketplace_links(
            _attach_product_images(flow, _result_for_flow(flow, flow.laf2_result))
        ),
        include_purchase_links=True,
    )
    # Los dos estados vacíos del paso 4 tienen causas distintas y hasta ahora
    # compartían un mismo mensaje que no nombraba ninguna (U33). Se distinguen
    # acá, en el contexto, con el modelo del paso 2 (A06): causa y salida.
    sin_condiciones = not any(
        float(peso or 0) > 0 for peso in (flow.purchase_preferences or {}).values()
    )
    presupuesto_activo = flow.budget_min is not None or flow.budget_max is not None
    return render(
        request,
        "recommender/listing_ranking.html",
        {
            "flow": flow,
            "result": result,
            "has_marketplace_links": any(
                item.metadata.get("marketplace_url") for item in result.ranking
            ),
            "show_installments": _show_installments(result.ranking),
            "no_purchase_preferences": sin_condiciones,
            "budget_left_nothing": bool(presupuesto_activo and not result.ranking),
            "budget_min_label": (
                _format_currency(float(flow.budget_min))
                if flow.budget_min is not None
                else ""
            ),
            "budget_max_label": (
                _format_currency(float(flow.budget_max))
                if flow.budget_max is not None
                else ""
            ),
        },
    )


def _show_installments(entries) -> bool:
    """La columna de cuotas solo aparece si alguna publicación las informa."""
    return any(
        str(item.metadata.get("installments") or "No informadas") != "No informadas"
        for item in entries
    )


@require_GET
def compare_listings(request, flow_id):
    """Comparacion lado a lado de las publicaciones marcadas."""
    flow = _flow(flow_id)
    if not flow.laf2_result:
        return _resume_flow(flow)
    result = _attach_primary_copy(
        _attach_marketplace_links(
            _attach_product_images(flow, _result_for_flow(flow, flow.laf2_result))
        ),
        include_purchase_links=True,
    )
    selected = request.GET.getlist("listing")
    if not selected:
        selected = [item.entity_id for item in result.ranking[:3]]
    listings = [item for item in result.ranking if item.entity_id in selected][:3]
    template = (
        "recommender/partials/listing_comparison.html"
        if request.headers.get("HX-Request") == "true"
        else "recommender/compare.html"
    )
    return render(
        request,
        template,
        {
            "flow": flow,
            "result": result,
            "listings": listings,
            "selected": selected,
            "has_marketplace_links": any(
                item.metadata.get("marketplace_url") for item in listings
            ),
            "show_installments": _show_installments(result.ranking),
        },
    )


@require_GET
def explanation(request, flow_id):
    """Por que una publicacion quedo en ese puesto (ADR-003)."""
    flow = _flow(flow_id)
    if not (flow.laf2_result or flow.laf1_result):
        return _resume_flow(flow)
    entity_id = str(request.GET.get("entity_id") or "")
    laf1_result = (
        _result_for_flow(flow, flow.laf1_result)
        if flow.laf1_result
        else None
    )
    if laf1_result and entity_id and any(
        item.entity_id == entity_id for item in laf1_result.ranking
    ):
        detail_url = reverse(
            "recommender:product-detail",
            args=[flow.id, entity_id],
        )
        return redirect(f"{detail_url}#explicacion")
    result = _attach_primary_copy(
        _attach_marketplace_links(
            _attach_product_images(flow, _explanation_result(flow, entity_id))
        ),
        include_purchase_links=True,
    )
    if not entity_id and result.ranking:
        entity_id = result.ranking[0].entity_id
    selected = next(
        (item for item in result.ranking if item.entity_id == entity_id),
        None,
    )
    if selected is None:
        raise Http404("La publicación solicitada no pertenece a esta corrida.")


    domain = _domains().get(flow.domain_key)
    aspect_labels = {aspect.key: aspect.label for aspect in domain.purchase_aspects}
    breakdown = comparison_service.build_score_breakdown(
        selected,
        None,
        aspect_labels,
    )
    ranking = comparison_service.build_ranking(result.ranking, entity_id)
    # La tabla por condición, la fórmula y el grafo de cada fila salen del mismo
    # EvaluationResult que produjo el orden; acá no se recalcula ningún puntaje.
    reason_rows = _listing_condition_rows(
        selected,
        breakdown,
        flow.purchase_preferences,
        aspect_labels,
    )
    scored_rows = [row for row in reason_rows if row["state"] == "participa"]
    total = len(ranking)
    score_groups = comparison_service.build_score_groups(breakdown)
    score_story = _listing_score_story(selected.position, total, reason_rows)
    score_equation = _listing_score_equation(breakdown)
    # La explicación de publicaciones no abre con una oración sobre el puesto:
    # el puesto ya está en el paso 3 y en la tabla, y la frase no agregaba un
    # dato nuevo (decisión de la autora, 2026-09-10). En productos se mantiene
    # `comparison.build_position_note`, que sí nombra las objeciones en pie.
    return render(
        request,
        "recommender/explanation.html",
        {
            "flow": flow,
            "result": result,
            "entity_id": entity_id,
            "selected": selected,
            "product": selected,
            "ranking": ranking,
            "breakdown": breakdown,
            "reason_rows": reason_rows,
            "score_groups": score_groups,
            "score_equation": score_equation,
            "score_story": score_story,
            "tie_note": _listing_tie_note(selected, result.ranking),
            "condition_graph_url": reverse(
                "recommender:listing-condition-graph",
                args=[flow.id],
            ),
            "ranking_top_score": max(
                (row.final_score for row in ranking),
                default=0,
            ),
            "process_steps": {
                "conditions": len(scored_rows),
                "condition_names": _listing_condition_names(reason_rows),
                "fulfilled": sum(1 for row in scored_rows if row["fulfilled"]),
                "listings": total,
                "position": selected.position,
                "total": total,
            },
        },
    )



# Literales de LAF 2 en lenguaje común. El paso 10 genera un hecho por
# condición declarada, una regla `compraBuena(X) :- <condición>(X)` por
# condición y la regla `recomendar(X) :- compraBuena(X)`; no hay reglas
# negativas ni conflicto (`validacion_laf2/SUFICIENCIA_DATOS.md`, §1).
_LAF2_FACT_LABELS = {
    "precioBueno": "Precio bajo dentro del rango",
    "tieneDescuento": "Tiene descuento",
    "tieneCuotas": "Tiene cuotas sin interés",
    "tieneGarantiaLarga": "Garantía de 6 meses o más",
    "esTiendaOficial": "Es tienda oficial",
    "tieneFactura": "Entrega factura",
    "tieneEnvioGratis": "Tiene envío gratis",
    "compraBuena": "Es una buena compra",
}


def _laf2_pred_label(literal: str) -> str:
    """Traduce un literal de LAF 2 (p. ej. `compraBuena(X)`) a lenguaje común."""
    head = str(literal or "").strip().lstrip("~").split("(", 1)[0].strip()
    if head == "recomendar":
        return "recomendar esta publicación"
    return _LAF2_FACT_LABELS.get(head, head).casefold()


def _friendly_relabel_laf2(graph: dict, condition: str = "") -> None:
    """Etiquetas legibles para el grafo de una condición de compra.

    Cambia sólo `graph_label`: la estructura, los literales y los valores del
    motor quedan intactos.
    """
    for node in graph.get("nodes") or []:
        meta = node.setdefault("metadata", {})
        # El resultado por condición se explica por la confianza; la preferencia
        # dentro de la corrida es constante (`{condición: 1.0, resto: 0.0}`).
        meta["hide_preference"] = True
        node_type = node.get("node_type")
        literal = str(node.get("literal") or "")
        if node_type == "operator":
            continue  # dMP / CA se dejan como en el motor
        if node_type == "rule":
            head, _, body = literal.partition(":-")
            meta["graph_label"] = (
                f"Si {_laf2_pred_label(body)}\n→ {_laf2_pred_label(head)}"
                if body.strip()
                else "Regla"
            )
            continue
        core = literal.split("(", 1)[0].strip().lstrip("~")
        if core == "recomendar":
            meta["graph_label"] = "Resultado de esta condición"
            continue
        meta["graph_label"] = _LAF2_FACT_LABELS.get(core, core)


@require_GET
def listing_condition_graph(request, flow_id):
    """Devuelve la corrida guardada que aportó el resultado de una condición.

    Es el mismo grafo que el motor produjo para la corrida
    `{condición: 1.0, resto: 0.0}` cuyo `recomendar` dio el número que se
    muestra en la fila: no se recalcula ni se dibuja nada propio. Espejo de
    `aspect_graph`, que hace lo mismo con los aspectos de calidad de LAF 1.
    """
    flow = _flow(flow_id)
    entity_id = str(request.GET.get("entity_id") or "")
    condition = str(request.GET.get("aspect") or "").strip()
    empty = {"nodes": [], "edges": [], "root_id": "", "total_nodes": 0, "total_edges": 0}
    if not flow.laf2_result or not condition:
        return JsonResponse(empty)
    result = _result_for_flow(flow, flow.laf2_result)
    listing = next(
        (item for item in result.ranking if item.entity_id == entity_id),
        None,
    )
    if listing is None:
        return JsonResponse(empty)
    raw_graph = (result.aspect_graphs or {}).get(condition)
    if not raw_graph:
        return JsonResponse(empty)
    entity_names = {
        str(item.metadata.get("laf_argument") or item.entity_id): item.entity_name
        for item in result.ranking
    }
    root = str(
        (listing.metadata.get("condition_node_ids") or {}).get(condition) or ""
    )
    mapped = LAFGraphPresentationMapper().map(
        raw_graph, root_id=root, entity_names=entity_names,
    )
    subgraph = _subgraph_for_product(
        mapped,
        (listing.entity_name or "").strip().casefold(),
        ancestors_only=True,
    )
    _friendly_relabel_laf2(subgraph, condition)
    subgraph["aspect"] = condition
    subgraph["source"] = "stored_evaluation"
    return JsonResponse(subgraph)


@require_GET
def graph_fragment(request, flow_id):
    """Fragmento del grafo de argumentos, en HTML, para la vista tecnica."""
    flow = _flow(flow_id)
    entity_id = str(request.GET.get("entity_id") or "")
    result = _explanation_result(flow, entity_id)
    mode = str(request.GET.get("mode") or "technical")
    service = (
        _summary_graph_service(result, entity_id)
        if mode == "summary" and entity_id
        else _graph_service(flow.domain_key, result, entity_id)
    )
    fragment = service.fragment(
        root_id=request.GET.get("root_id"),
        depth=request.GET.get("depth", 2 if mode == "summary" else 3),
        limit=request.GET.get("limit", settings.GRAPH_VISIBLE_NODE_LIMIT),
        filters=_graph_filters(request),
    )
    return JsonResponse(fragment.to_dict(), json_dumps_params={"ensure_ascii": False})


@require_GET
def graph_list(request, flow_id):
    """El mismo fragmento como lista, alternativa accesible al grafo."""
    flow = _flow(flow_id)
    entity_id = str(request.GET.get("entity_id") or "")
    result = _explanation_result(flow, entity_id)
    mode = str(request.GET.get("mode") or "summary")
    service = (
        _summary_graph_service(result, entity_id)
        if mode == "summary" and entity_id
        else _graph_service(flow.domain_key, result, entity_id)
    )
    fragment = service.fragment(
        root_id=request.GET.get("root_id"),
        depth=request.GET.get("depth", 2 if mode == "summary" else 3),
        limit=request.GET.get("limit", settings.GRAPH_VISIBLE_NODE_LIMIT),
        filters=_graph_filters(request),
    )
    return render(
        request,
        "recommender/partials/graph_list.html",
        {"fragment": fragment},
    )


@require_GET
def traceability(request, flow_id):
    """Datos y trazabilidad: de donde salio cada cosa que se mostro."""
    flow = _flow(flow_id)
    if not (flow.laf2_result or flow.laf1_result):
        return _resume_flow(flow)
    result = _result_for_flow(flow, flow.laf2_result or flow.laf1_result)
    domain = _domains().get(flow.domain_key)
    is_laf2_program = result.program_kind == "laf2"
    return render(
        request,
        "recommender/traceability.html",
        {
            "flow": flow,
            "result": result,
            "domain": domain,
            "generated_at_local": _local_datetime(result.generated_at),
            "is_laf2_program": is_laf2_program,
            "budget_min_label": (
                _format_currency(float(flow.budget_min))
                if is_laf2_program and flow.budget_min is not None
                else ""
            ),
            "budget_max_label": (
                _format_currency(float(flow.budget_max))
                if is_laf2_program and flow.budget_max is not None
                else ""
            ),
            # Cifras de docs/EVALUACION_EXTRACCION.md (cierre 2026-09-01), medidas
            # sobre el corpus de café. Sólo se publican para ese dominio.
            "extraction_quality": flow.domain_key == "cafe",
            "quality_preferences": _preference_items(
                flow.quality_preferences,
                domain.quality_aspects,
            ),
            "purchase_preferences": _preference_items(
                flow.purchase_preferences,
                domain.purchase_aspects,
            ),
        },
    )


@require_GET
def methodology(request):
    """Pagina de metodologia; no depende de ningun recorrido."""
    return render(request, "recommender/methodology.html")
