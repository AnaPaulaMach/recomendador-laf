"""Descargas reproducibles y exportaciones del recorrido de recomendación."""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile

from django.conf import settings
from django.http import Http404, HttpResponse
from django.views.decorators.http import require_GET

from .flow_state import explanation_result, get_flow, result_for_flow
from .graph_support import graph_filters, graph_service


def _combined_program_text(result, *, stage: str, component_label: str) -> str:
    """El programa combinado, encabezado por lo que realmente es.

    El generador escribe su propia cabecera («PROGRAMA LAF 1 - RANKING DE
    PRODUCTOS», `src/08_laf1_generate.py`), que promete más de lo que el archivo
    entrega: desde el paso a una etiqueta por corrida el orden lo producen las
    corridas independientes y se combinan después con la suma ponderada
    (ADR-002, ADR-005). No se toca el generador, que está congelado: se antepone
    un encabezado de descarga que dice qué es este archivo y cuál es el que
    produjo el ranking (U40 de la evaluación heurística).
    """
    usados = len(result.aspect_programs or {})
    encabezado = [
        f"% PROGRAMA {stage.upper()} COMBINADO — NO INTERVIENE EN EL RANKING",
        "%",
        "% Este archivo reúne toda la evidencia en una corrida única. Esa corrida",
        f"% NO es la que ordenó el ranking: el orden lo producen {usados} programas",
        f"% independientes, uno por {component_label or 'aspecto'}, que se combinan",
        "% después con la suma ponderada de tus pesos (ADR-002, ADR-005).",
        "%",
        "% Se ofrece como referencia del camino anterior. Para auditar el orden,",
        f"% descargá los {usados} programas utilizados (opción «?used=1»).",
        f"% Corrida: {result.run_id}",
        f"% Catálogo: {result.dataset_key}",
        "",
    ]
    return "\n".join(encabezado) + result.laf_program


def _independent_programs_text(result, *, stage: str, component_label: str) -> str:
    ordered = sorted(result.aspect_programs.items())
    sections = [
        f"PROGRAMAS {stage.upper()} UTILIZADOS PARA EL RANKING",
        "Estos son los programas que produjeron el orden: cada uno se ejecutó por separado",
        "y sus resultados se combinaron después con la suma ponderada de tus pesos.",
        f"Corrida: {result.run_id}",
        f"Catálogo: {result.dataset_key}",
        f"Programas independientes: {len(ordered)}",
        "",
        "Cada bloque se ejecutó por separado. Este archivo los reúne para lectura y revisión;",
        "no debe enviarse completo al motor como si fuera un único programa.",
    ]
    for position, (component, program) in enumerate(ordered, start=1):
        separator = "=" * 72
        sections.extend(
            (
                "",
                separator,
                (
                    f"PROGRAMA {position}/{len(ordered)} — {component_label.upper()}: {component.upper()}"
                    if component_label
                    else f"PROGRAMA {position}/{len(ordered)} — {component.upper()}"
                ),
                (
                    "Ejecución independiente · una etiqueta: confianza"
                    if stage.upper() == "LAF1"
                    else "Ejecución independiente que aportó al puntaje final"
                ),
                separator,
                program.rstrip(),
            )
        )
        payload = result.execution_payloads.get(component)
        if payload:
            sections.extend(
                (
                    "",
                    "PAYLOAD JSON EXACTO ENVIADO A /api/graph",
                    json.dumps(payload, ensure_ascii=False, indent=2),
                )
            )
    return "\n".join(sections) + "\n"


@require_GET
def export_laf1_program(request, flow_id):
    """Descarga el programa LAF 1 de esta corrida.

    Con ``?used=1`` entrega los programas por aspecto que realmente produjeron
    el orden; sin el parametro, el programa combinado de respaldo.
    """
    flow = get_flow(flow_id)
    if not flow.laf1_result:
        raise Http404("Esta sesión todavía no generó un programa LAF 1.")
    result = result_for_flow(flow, flow.laf1_result)
    if result.program_status != "generated" or not result.laf_program:
        raise Http404("Esta sesión todavía no generó un programa LAF 1.")
    if request.GET.get("used") == "1" and result.aspect_programs:
        response = HttpResponse(
            _independent_programs_text(result, stage="LAF1", component_label=""),
            content_type="text/plain; charset=utf-8",
        )
        response["Content-Disposition"] = 'attachment; filename="programas-laf1-utilizados.txt"'
        return response
    if request.GET.get("bundle") == "1" and result.aspect_programs:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("respaldo-completo-dos-etiquetas.txt", result.laf_program)
            for aspect, program in result.aspect_programs.items():
                safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", aspect)
                archive.writestr(f"aspectos/{safe_name}.txt", program)
            archive.writestr(
                "resultado.json",
                json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            )
        response = HttpResponse(buffer.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="programas-laf1.zip"'
        return response
    aspect = str(request.GET.get("aspect") or "")
    if aspect:
        if aspect not in result.aspect_programs:
            raise Http404("Este aspecto no tiene un programa guardado.")
        response = HttpResponse(
            result.aspect_programs[aspect],
            content_type="text/plain; charset=utf-8",
        )
        response["Content-Disposition"] = 'attachment; filename="programa-laf1-aspecto.txt"'
        return response
    if result.aspect_programs:
        response = HttpResponse(
            _combined_program_text(result, stage="LAF1", component_label="aspecto"),
            content_type="text/plain; charset=utf-8",
        )
        response["Content-Disposition"] = (
            'attachment; filename="programa-laf1-combinado-solo-referencia.txt"'
        )
        return response
    response = HttpResponse(result.laf_program, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="programa-laf1.txt"'
    return response


@require_GET
def export_laf2_program(request, flow_id):
    """Descarga el programa LAF 2 de esta corrida y su carga de ejecucion."""
    flow = get_flow(flow_id)
    if not flow.laf2_result:
        raise Http404("Esta sesión todavía no generó un programa LAF 2.")
    result = result_for_flow(flow, flow.laf2_result)
    if result.program_status != "generated" or not result.laf_program:
        raise Http404("Esta sesión todavía no generó un programa LAF 2.")
    if request.GET.get("used") == "1" and result.aspect_programs:
        response = HttpResponse(
            _independent_programs_text(result, stage="LAF2", component_label="condición"),
            content_type="text/plain; charset=utf-8",
        )
        response["Content-Disposition"] = 'attachment; filename="programas-laf2-utilizados.txt"'
        return response
    if result.aspect_programs:
        response = HttpResponse(
            _combined_program_text(result, stage="LAF2", component_label="condición de compra"),
            content_type="text/plain; charset=utf-8",
        )
        response["Content-Disposition"] = (
            'attachment; filename="programa-laf2-combinado-solo-referencia.txt"'
        )
        return response
    response = HttpResponse(result.laf_program, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="respaldo-laf2-completo.txt"'
    return response


@require_GET
def export_graph_json(request, flow_id):
    """Descarga el subgrafo visible en JSON (``?full=1`` entrega el grafo entero).

    No esta enlazada desde la interfaz: se conserva a proposito para la
    trazabilidad (ADR-005).
    """
    flow = get_flow(flow_id)
    entity_id = str(request.GET.get("entity_id") or "")
    result = explanation_result(flow, entity_id)
    service = graph_service(flow.domain_key, result, entity_id)
    full_graph = request.GET.get("full") == "1"
    payload = service.data if full_graph else service.fragment(
        root_id=request.GET.get("root_id"),
        depth=request.GET.get("depth", 3),
        limit=request.GET.get("limit", settings.GRAPH_VISIBLE_NODE_LIMIT),
        filters=graph_filters(request),
    ).to_dict()
    response = HttpResponse(
        json.dumps(payload, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8",
    )
    filename = "grafo-laf-completo.json" if full_graph else "subgrafo-visible.json"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_GET
def export_arguments_csv(request, flow_id):
    """Descarga los argumentos del ultimo resultado (LAF 2 si existe, si no LAF 1).

    Tampoco esta enlazada desde la interfaz.
    """
    flow = get_flow(flow_id)
    result = result_for_flow(flow, flow.laf2_result or flow.laf1_result)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response.write("\ufeff")
    response["Content-Disposition"] = 'attachment; filename="argumentos.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "entidad", "posición", "polaridad", "aspecto", "argumento",
            "confianza", "preferencia", "evidencias",
        ]
    )
    for entry in result.ranking:
        for polarity, arguments in (
            ("favorable", entry.arguments_for),
            ("contrario", entry.arguments_against),
        ):
            for argument in arguments:
                writer.writerow(
                    [
                        entry.entity_name, entry.position, polarity, argument.aspect,
                        argument.title, argument.confidence, argument.preference,
                        argument.evidence_count,
                    ]
                )
    return response
