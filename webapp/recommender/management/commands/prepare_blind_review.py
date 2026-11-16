"""Orden de consola: arma los casos del juicio humano ciego."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from recommender.models import RecommendationSession
from recommender.repositories.domain_repository import DomainConfigRepository
from recommender.repositories.supabase_repository import SupabaseRepository
from recommender.services.blind_review import build_blind_profiles, write_blind_review_packet


class Command(BaseCommand):
    help = "Prepara casos humanos ciegos con reseñas reales, sin ejecutar ni revelar LAF."

    def add_arguments(self, parser):
        parser.add_argument("--flow", required=True, help="UUID de un recorrido existente.")
        parser.add_argument("--cases", type=int, default=10, help="Cantidad de perfiles mixtos nuevos.")
        parser.add_argument(
            "--candidates-per-case",
            type=int,
            default=4,
            help="Cantidad de productos visibles en cada caso compacto.",
        )
        parser.add_argument(
            "--samples-per-polarity",
            type=int,
            default=3,
            help="Reseñas por producto, aspecto y polaridad en cada ficha; 0 muestra todas.",
        )
        parser.add_argument("--output-dir", help="Carpeta de salida opcional.")

    def handle(self, *args, **options):
        try:
            flow_id = uuid.UUID(options["flow"])
        except ValueError as exc:
            raise CommandError("--flow debe ser un UUID válido.") from exc
        try:
            flow = RecommendationSession.objects.get(id=flow_id)
        except RecommendationSession.DoesNotExist as exc:
            raise CommandError("No existe el recorrido indicado.") from exc
        if options["cases"] <= 0:
            raise CommandError("--cases debe ser positivo.")
        if options["samples_per_polarity"] < 0:
            raise CommandError("--samples-per-polarity no puede ser negativo.")
        if options["candidates_per_case"] <= 1:
            raise CommandError("--candidates-per-case debe ser al menos 2.")

        domain = DomainConfigRepository(settings.DOMAIN_CONFIG_DIR).get(flow.domain_key)
        aspect_labels = {aspect.key: aspect.label for aspect in domain.quality_aspects}
        profiles = build_blind_profiles(aspect_labels, case_count=options["cases"])
        repository = SupabaseRepository(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        self.stdout.write("Cargando candidatos curados...")
        try:
            products, _ = repository.laf1_generation_data(flow.dataset_key, flow.strategy)
            rows = repository.blind_review_evidence(
                flow.dataset_key,
                products,
                aspect_labels,
            )
        except Exception as exc:
            raise CommandError(f"No se pudieron cargar las reseñas trazables: {exc}") from exc

        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(options["output_dir"]) if options["output_dir"] else (
            settings.BASE_DIR / "reports" / "blind_review" / f"{timestamp}_{flow.id}"
        )
        metadata = {
            "flow_id": str(flow.id),
            "domain": flow.domain_key,
            "dataset_key": flow.dataset_key,
            "strategy": flow.strategy,
            "generated_at": datetime.now().astimezone().isoformat(),
            "blind_protocol": "mixed_profiles_without_laf_outputs_v1",
        }
        paths = write_blind_review_packet(
            output_dir,
            metadata=metadata,
            products=products,
            aspect_labels=aspect_labels,
            profiles=profiles,
            review_rows=rows,
            samples_per_polarity=options["samples_per_polarity"],
            candidates_per_case=options["candidates_per_case"],
        )
        self.stdout.write(self.style.SUCCESS(f"Casos ciegos: {len(profiles)}"))
        self.stdout.write(self.style.SUCCESS(f"Productos por caso: {paths['candidate_count']}"))
        self.stdout.write(self.style.SUCCESS(f"Extracciones únicas: {paths['review_count']}"))
        self.stdout.write(self.style.SUCCESS(f"Instrucciones: {paths['instructions']}"))
        self.stdout.write(self.style.SUCCESS(f"Primer caso: {paths['case_files'][0]}"))
        self.stdout.write(self.style.SUCCESS(f"Reseñas completas: {paths['reading_csv']}"))
        self.stdout.write(self.style.SUCCESS(f"Respuestas: {paths['responses']}"))
