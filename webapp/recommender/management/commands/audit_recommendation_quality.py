"""Orden de consola: mide la calidad del ranking contra expectativas declaradas."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from recommender.domain.contracts import EvaluationRequest
from recommender.models import RecommendationSession
from recommender.repositories.domain_repository import DomainConfigRepository
from recommender.services.recommendation_quality import (
    RecommendationQualityRunner,
    build_quality_profiles,
    load_expectations,
    summarize_quality,
    write_quality_reports,
)
from recommender.services.use_cases import get_evaluator


class Command(BaseCommand):
    help = (
        "Compara LAF con una línea base de evidencia y con expectativas humanas revisadas."
    )

    def add_arguments(self, parser):
        parser.add_argument("--flow", required=True, help="UUID de un recorrido existente.")
        parser.add_argument(
            "--expectations",
            help="JSON de casos revisados, generado previamente como casos_para_revision.json.",
        )
        parser.add_argument(
            "--output-dir",
            help="Carpeta de salida. Por defecto reports/recommendation_quality/<fecha>_<flow>.",
        )

    def handle(self, *args, **options):
        try:
            flow_id = uuid.UUID(options["flow"])
        except ValueError as exc:
            raise CommandError("--flow debe ser un UUID válido.") from exc
        try:
            flow = RecommendationSession.objects.get(id=flow_id)
        except RecommendationSession.DoesNotExist as exc:
            raise CommandError("No existe el recorrido indicado.") from exc

        domain = DomainConfigRepository(settings.DOMAIN_CONFIG_DIR).get(flow.domain_key)
        aspect_labels = {aspect.key: aspect.label for aspect in domain.quality_aspects}
        dimensions = self._dimensions(flow.domain_key)
        profiles = build_quality_profiles(
            aspect_labels,
            dimensions,
            flow.quality_preferences,
        )
        try:
            expectations = load_expectations(
                Path(options["expectations"]) if options["expectations"] else None
            )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise CommandError(f"No se pudieron leer las expectativas: {exc}") from exc

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Calidad LAF 1 · {len(profiles)} casos interpretables"
            )
        )
        evaluator = get_evaluator()
        self._cache_laf1_source(evaluator, flow.dataset_key, flow.strategy)
        runner = RecommendationQualityRunner(evaluator)

        def progress(index, profile, case):
            result = (
                f"{case.laf_winner_name} · base: {case.baseline_winner_name}"
                if case.status == "ok"
                else f"ERROR: {case.error}"
            )
            self.stdout.write(f"[{index:>2}/{len(profiles)}] {profile.name}: {result}")

        cases = runner.run(
            EvaluationRequest(
                domain=flow.domain_key,
                dataset_key=flow.dataset_key,
                strategy=flow.strategy,
                preferences={},
            ),
            profiles,
            expectations=expectations,
            progress=progress,
        )
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(options["output_dir"]) if options["output_dir"] else (
            settings.BASE_DIR
            / "reports"
            / "recommendation_quality"
            / f"{timestamp}_{flow.id}"
        )
        metadata = {
            "flow_id": str(flow.id),
            "domain": flow.domain_key,
            "dataset_key": flow.dataset_key,
            "strategy": flow.strategy,
            "aspects": list(aspect_labels),
            "dimensions": dimensions,
            "generated_at": datetime.now().astimezone().isoformat(),
            "expectations_source": str(options["expectations"] or ""),
        }
        paths = write_quality_reports(output_dir, metadata=metadata, cases=cases)
        summary = summarize_quality(cases)

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Resumen"))
        self.stdout.write(
            "Coincidencia LAF/línea base: "
            + self._percent(summary["baseline_winner_agreement"])
        )
        self.stdout.write(
            "Casos aprobados por una persona: "
            f"{summary['reviewed_cases']}/{summary['successful_cases']}"
        )
        self.stdout.write(
            "Exactitud humana: " + self._percent(summary["human_winner_accuracy"])
        )
        self.stdout.write(
            f"Producto dominante: {summary['dominant_winner_name']} "
            f"({float(summary['dominant_winner_share']):.1%})"
        )
        self.stdout.write(self.style.SUCCESS(f"Resumen: {paths['markdown']}"))
        self.stdout.write(self.style.SUCCESS(f"Casos: {paths['csv']}"))
        self.stdout.write(self.style.SUCCESS(f"Revisión humana: {paths['review']}"))
        self.stdout.write(
            self.style.SUCCESS(f"Revisión asistida: {paths['assisted_markdown']}")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Propuestas editables: {paths['assisted_json']}")
        )
        self.stdout.write(self.style.SUCCESS(f"Datos completos: {paths['json']}"))

    def _dimensions(self, domain_key: str) -> dict[str, dict[str, object]]:
        path = Path(settings.DOMAIN_CONFIG_DIR) / f"{domain_key}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError("No se pudo leer la estructura de dimensiones.") from exc
        raw_dimensions = (
            data.get("laf1_rule_structure", {}).get("dimensions", {})
            if isinstance(data, dict) else {}
        )
        dimensions = {}
        for key, value in raw_dimensions.items():
            if not isinstance(value, dict):
                continue
            dimensions[str(key)] = {
                "label": str(value.get("label") or key),
                "aspects": [
                    str(item.get("aspect"))
                    for item in value.get("aspects", [])
                    if isinstance(item, dict) and item.get("aspect")
                ],
            }
        return dimensions

    def _cache_laf1_source(self, evaluator, dataset_key: str, strategy: str) -> None:
        service = getattr(evaluator, "laf1_programs", None)
        repository = getattr(service, "repository", None)
        loader = getattr(repository, "laf1_generation_data", None)
        if loader is None:
            return
        self.stdout.write("Cargando productos y evidencias una sola vez...")
        try:
            cached = loader(dataset_key, strategy)
        except Exception as exc:
            raise CommandError(
                "No se pudieron cargar los datos necesarios para la auditoría."
            ) from exc

        def cached_loader(requested_dataset: str, requested_strategy: str):
            if requested_dataset == dataset_key and requested_strategy == strategy:
                return cached
            return loader(requested_dataset, requested_strategy)

        repository.laf1_generation_data = cached_loader
        products, evidence = cached
        self.stdout.write(
            f"Datos cacheados: {len(products):,} productos y {len(evidence):,} filas de evidencia."
        )

    @staticmethod
    def _percent(value: object) -> str:
        return "No medida" if value is None else f"{float(value):.1%}"
