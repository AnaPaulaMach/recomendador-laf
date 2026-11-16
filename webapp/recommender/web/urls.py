"""Rutas de la aplicacion: pantallas del recorrido, grafos y exportaciones."""
from django.urls import path

from . import exports, views

app_name = "recommender"

urlpatterns = [
    path("", views.home, name="home"),
    path("comenzar/", views.start, name="start"),
    path("metodologia/", views.methodology, name="methodology"),
    path("recorridos/<uuid:flow_id>/calidad/", views.quality, name="quality"),
    path(
        "recorridos/<uuid:flow_id>/htmx/preferencias/",
        views.preference_summary,
        name="preference-summary",
    ),
    path(
        "recorridos/<uuid:flow_id>/productos/",
        views.product_ranking,
        name="product-ranking",
    ),
    path(
        "recorridos/<uuid:flow_id>/auditoria/laf2/producto/",
        views.audit_laf2_product,
        name="audit-laf2-product",
    ),
    path(
        "recorridos/<uuid:flow_id>/productos/<path:entity_id>/seleccionar/",
        views.select_product,
        name="select-product",
    ),
    path(
        "recorridos/<uuid:flow_id>/productos/<path:entity_id>/",
        views.product_detail,
        name="product-detail",
    ),
    path("recorridos/<uuid:flow_id>/compra/", views.purchase, name="purchase"),
    path(
        "recorridos/<uuid:flow_id>/publicaciones/",
        views.listing_ranking,
        name="listing-ranking",
    ),
    path(
        "recorridos/<uuid:flow_id>/publicaciones/comparar/",
        views.compare_listings,
        name="compare-listings",
    ),
    path(
        "recorridos/<uuid:flow_id>/explicacion/",
        views.explanation,
        name="explanation",
    ),
    path(
        "recorridos/<uuid:flow_id>/grafo/fragmento/",
        views.graph_fragment,
        name="graph-fragment",
    ),
    path(
        "recorridos/<uuid:flow_id>/grafo/lista/",
        views.graph_list,
        name="graph-list",
    ),
    path(
        "recorridos/<uuid:flow_id>/grafo/aspecto.json",
        views.aspect_graph,
        name="aspect-graph",
    ),
    path(
        "recorridos/<uuid:flow_id>/grafo/condicion.json",
        views.listing_condition_graph,
        name="listing-condition-graph",
    ),
    path(
        "recorridos/<uuid:flow_id>/trazabilidad/",
        views.traceability,
        name="traceability",
    ),
    path(
        "recorridos/<uuid:flow_id>/exportar/subgrafo.json",
        exports.export_graph_json,
        name="export-graph-json",
    ),
    path(
        "recorridos/<uuid:flow_id>/exportar/programa-laf1.txt",
        exports.export_laf1_program,
        name="export-laf1-program",
    ),
    path(
        "recorridos/<uuid:flow_id>/exportar/programa-laf2.txt",
        exports.export_laf2_program,
        name="export-laf2-program",
    ),
    path(
        "recorridos/<uuid:flow_id>/exportar/argumentos.csv",
        exports.export_arguments_csv,
        name="export-arguments-csv",
    ),
]
