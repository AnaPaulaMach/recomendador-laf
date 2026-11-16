"""Orden de consola: auditoria de perfiles de preferencia sobre datos reales."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from recommender.domain.contracts import EvaluationRequest
from recommender.models import RecommendationSession
from recommender.repositories.domain_repository import DomainConfigRepository
from recommender.services.preference_audit import (
    BINARY_LEVELS,
    UI_LEVELS,
    PreferenceAuditRunner,
    iter_profiles,
    projected_case_count,
    summarize,
    write_reports,
)
from recommender.services.use_cases import get_evaluator


class Command(BaseCommand):
    help = "Mide de forma reproducible cuánto cambia LAF ante perfiles de preferencias."

    def add_arguments(self, parser):
        parser.add_argument("--flow", required=True, help="UUID de un recorrido existente.")
        parser.add_argument(
            "--mode",
            choices=("quick", "standard", "pairwise", "exhaustive"),
            default="standard",
            help="Cobertura de perfiles. standard incluye extremos y estabilidad ±0,01.",
        )
        parser.add_argument(
            "--levels",
            choices=("ui", "binary"),
            default="ui",
            help="Niveles del modo exhaustive: los 4 de la interfaz o sólo 0/1.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Sólo calcula cuántos casos habría.")
        parser.add_argument(
            "--confirm-exhaustive",
            action="store_true",
            help="Confirma una ejecución cartesiana exhaustiva.",
        )
        parser.add_argument(
            "--max-cases",
            type=int,
            default=50_000,
            help="Límite de seguridad para una corrida (predeterminado: 50000).",
        )
        parser.add_argument(
            "--output-dir",
            help="Carpeta de salida. Por defecto reports/preference_audits/<fecha>_<flow>.",
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
        configured = tuple(aspect.key for aspect in domain.quality_aspects)
        aspects = tuple(key for key in configured if key in flow.quality_preferences) or configured
        levels = UI_LEVELS if options["levels"] == "ui" else BINARY_LEVELS
        projected = projected_case_count(aspects, options["mode"], levels)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Auditoría LAF 1 · {len(aspects)} aspectos · {projected:,} casos proyectados"
            )
        )
        self.stdout.write("Aspectos: " + ", ".join(aspects))
        if options["mode"] == "exhaustive":
            self.stdout.write(
                "El espacio exhaustivo es cartesiano: "
                f"{len(levels)}^{len(aspects)} = {projected:,} perfiles."
            )
            if not options["confirm_exhaustive"] and not options["dry_run"]:
                raise CommandError(
                    "El modo exhaustive requiere --confirm-exhaustive. "
                    "Probá primero --dry-run o --mode standard."
                )
        if projected > options["max_cases"] and not options["dry_run"]:
            raise CommandError(
                f"La corrida proyecta {projected:,} casos y supera --max-cases="
                f"{options['max_cases']:,}. Elevá el límite de forma explícita si realmente querés ejecutarla."
            )
        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("No se ejecutaron evaluaciones (--dry-run)."))
            return

        profiles = iter_profiles(
            aspects,
            flow.quality_preferences,
            mode=options["mode"],
            levels=levels,
        )
        evaluator = get_evaluator()
        self._cache_laf1_source(evaluator, flow.dataset_key, flow.strategy)
        runner = PreferenceAuditRunner(evaluator)

        def progress(index, profile, case):
            result = (
                f"{case.winner_name} ({case.winner_score:.4f})"
                if case.status == "ok"
                else f"ERROR: {case.error}"
            )
            self.stdout.write(f"[{index:>{len(str(projected))}}/{projected}] {profile.name}: {result}")

        cases = runner.run(
            EvaluationRequest(
                domain=flow.domain_key,
                dataset_key=flow.dataset_key,
                strategy=flow.strategy,
                preferences={},
            ),
            profiles,
            progress=progress,
        )
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(options["output_dir"]) if options["output_dir"] else (
            settings.BASE_DIR / "reports" / "preference_audits" / f"{timestamp}_{flow.id}"
        )
        paths = write_reports(
            output_dir,
            metadata={
                "flow_id": str(flow.id),
                "domain": flow.domain_key,
                "dataset_key": flow.dataset_key,
                "strategy": flow.strategy,
                "mode": options["mode"],
                "levels": levels,
                "aspects": aspects,
                "projected_cases": projected,
                "generated_at": datetime.now().astimezone().isoformat(),
            },
            cases=cases,
        )
        summary = summarize(cases)
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Resumen"))
        self.stdout.write(str(summary["verdict"]))
        self.stdout.write(f"Ganadores distintos: {summary['distinct_winners']}")
        self.stdout.write(f"Cambio de ganador: {float(summary['winner_change_rate']):.1%}")
        self.stdout.write(f"Movimiento medio: {float(summary['average_rank_movement']):.2f} posiciones")
        self.stdout.write(self.style.SUCCESS(f"Resumen: {paths['markdown']}"))
        self.stdout.write(self.style.SUCCESS(f"Casos: {paths['csv']}"))
        self.stdout.write(self.style.SUCCESS(f"Datos completos: {paths['json']}"))

    def _cache_laf1_source(self, evaluator, dataset_key: str, strategy: str) -> None:
        """Evita descargar el mismo catálogo y evidencias una vez por perfil."""
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
