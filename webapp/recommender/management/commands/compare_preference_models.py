"""Orden de consola: compara el modelo de preferencia vigente con alternativas."""
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
from recommender.services.preference_alternatives import (
    MODEL_LABELS,
    PreferenceAlternativesRunner,
    build_weight_sweep_profiles,
    summarize_alternatives,
    summarize_weight_sweep,
    write_alternative_reports,
    write_weight_sweep_reports,
)
from recommender.services.recommendation_quality import (
    build_quality_profiles,
    load_expectations,
)
from recommender.services.use_cases import get_evaluator


class Command(BaseCommand):
    help = (
        "Compara experimentalmente tres formas de integrar las preferencias con LAF 1."
    )

    def add_arguments(self, parser):
        parser.add_argument("--flow", required=True, help="UUID de un recorrido existente.")
        parser.add_argument(
            "--expectations",
            required=True,
            help="JSON con los casos humanos aprobados.",
        )
        parser.add_argument(
            "--output-dir",
            help="Carpeta de salida. Por defecto reports/preference_models/<fecha>_<flow>.",
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

        expectation_path = Path(options["expectations"])
        try:
            expectations = load_expectations(expectation_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise CommandError(f"No se pudieron leer las expectativas: {exc}") from exc
        approved_cases = sum(
            str(row.get("review_status") or "") == "approved"
            and bool(row.get("expected_winner_ids"))
            for row in expectations.values()
        )
        if not approved_cases:
            raise CommandError("El archivo no contiene casos aprobados con ganador esperado.")

        domain = DomainConfigRepository(settings.DOMAIN_CONFIG_DIR).get(flow.domain_key)
        aspect_labels = {aspect.key: aspect.label for aspect in domain.quality_aspects}
        dimensions = self._dimensions(flow.domain_key)
        profiles = build_quality_profiles(
            aspect_labels,
            dimensions,
            flow.quality_preferences,
        )
        evaluator = get_evaluator()
        required = ("laf1_programs", "parser", "api_client", "ranking_mapper")
        missing = [name for name in required if not hasattr(evaluator, name)]
        if missing:
            raise CommandError(
                "El evaluador activo no permite el experimento HTTP: " + ", ".join(missing)
            )
        self._cache_laf1_source(evaluator, flow.dataset_key, flow.strategy)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Comparación de preferencias · {len(profiles)} perfiles · 4 modelos"
            )
        )
        runner = PreferenceAlternativesRunner(evaluator)
        cases = runner.run(
            EvaluationRequest(
                domain=flow.domain_key,
                dataset_key=flow.dataset_key,
                strategy=flow.strategy,
                preferences={},
            ),
            profiles,
            expectations=expectations,
            progress=self.stdout.write,
        )
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(options["output_dir"]) if options["output_dir"] else (
            settings.BASE_DIR / "reports" / "preference_models" / f"{timestamp}_{flow.id}"
        )
        metadata = {
            "flow_id": str(flow.id),
            "domain": flow.domain_key,
            "dataset_key": flow.dataset_key,
            "strategy": flow.strategy,
            "generated_at": datetime.now().astimezone().isoformat(),
            "expectations_source": str(expectation_path),
            "approved_cases": approved_cases,
            "profiles": len(profiles),
            "aspects": list(aspect_labels),
            "development_set": True,
            "blind_independent_validation": False,
        }
        paths = write_alternative_reports(output_dir, metadata=metadata, cases=cases)
        summary = summarize_alternatives(cases)

        sweep_profiles = build_weight_sweep_profiles(aspect_labels)
        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Sensibilidad intermedia · {len(sweep_profiles)} perfiles"
            )
        )
        sweep_cases = runner.run(
            EvaluationRequest(
                domain=flow.domain_key,
                dataset_key=flow.dataset_key,
                strategy=flow.strategy,
                preferences={},
            ),
            sweep_profiles,
            expectations={},
            progress=self.stdout.write,
        )
        sweep_paths = write_weight_sweep_reports(
            output_dir,
            metadata={
                **metadata,
                "weight_levels": [0.33, 0.67, 1.0],
                "background_weight": 0.67,
                "weight_sweep_profiles": len(sweep_profiles),
            },
            cases=sweep_cases,
        )
        sweep_summary = summarize_weight_sweep(sweep_cases)

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Resultados"))
        for model in MODEL_LABELS:
            row = summary[model]
            sensitivity = sweep_summary[model]
            self.stdout.write(
                f"{row['label']}: exacto {self._percent(row['exact_accuracy'])}, "
                f"top 3 {self._percent(row['top3_accuracy'])}, "
                f"dominancia {self._percent(row['dominant_winner_share'])}, "
                f"cambio 0.33 a 1 en {sensitivity['winner_changed_aspects']}/"
                f"{sensitivity['aspects']} aspectos"
            )
        self.stdout.write(self.style.SUCCESS(f"Informe: {paths['markdown']}"))
        self.stdout.write(self.style.SUCCESS(f"Casos: {paths['csv']}"))
        self.stdout.write(self.style.SUCCESS(f"Datos: {paths['json']}"))
        self.stdout.write(
            self.style.SUCCESS(f"Sensibilidad: {sweep_paths['markdown']}")
        )

    def _dimensions(self, domain_key: str) -> dict[str, dict[str, object]]:
        path = Path(settings.DOMAIN_CONFIG_DIR) / f"{domain_key}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError("No se pudo leer la estructura de dimensiones.") from exc
        raw = data.get("laf1_rule_structure", {}).get("dimensions", {})
        return {
            str(key): {
                "label": str(value.get("label") or key),
                "aspects": [
                    str(item.get("aspect"))
                    for item in value.get("aspects", [])
                    if isinstance(item, dict) and item.get("aspect")
                ],
            }
            for key, value in raw.items()
            if isinstance(value, dict)
        }

    def _cache_laf1_source(self, evaluator, dataset_key: str, strategy: str) -> None:
        repository = evaluator.laf1_programs.repository
        loader = repository.laf1_generation_data
        self.stdout.write("Cargando catálogo y evidencia una sola vez...")
        try:
            cached = loader(dataset_key, strategy)
        except Exception as exc:
            raise CommandError("No se pudieron cargar los datos del experimento.") from exc

        def cached_loader(requested_dataset: str, requested_strategy: str):
            if (requested_dataset, requested_strategy) == (dataset_key, strategy):
                return cached
            return loader(requested_dataset, requested_strategy)

        repository.laf1_generation_data = cached_loader
        products, evidence = cached
        self.stdout.write(
            f"Datos cacheados: {len(products):,} productos y {len(evidence):,} filas."
        )

    @staticmethod
    def _percent(value: object) -> str:
        return "No medido" if value is None else f"{float(value):.1%}"
