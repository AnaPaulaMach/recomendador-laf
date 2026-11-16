"""Estado persistido del recorrido.

``RecommendationSession`` guarda preferencias y resultados serializados. Los
campos de ``EvaluationResult`` son contrato: no se renombran (ver
``docs/ARCHITECTURE.md``).
"""
import uuid
from django.db import models


class RecommendationSession(models.Model):
    """Estado durable y auditable del recorrido LAF 1 → LAF 2."""

    class Stage(models.TextChoices):
        QUALITY = "quality", "Preferencias de calidad"
        PRODUCT_RANKING = "product_ranking", "Ranking de productos"
        PURCHASE = "purchase", "Preferencias de compra"
        LISTING_RANKING = "listing_ranking", "Ranking de publicaciones"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    domain_key = models.CharField(max_length=80)
    dataset_key = models.CharField(max_length=160)
    strategy = models.CharField(max_length=1, default="D")
    stage = models.CharField(max_length=32, choices=Stage.choices, default=Stage.QUALITY)
    quality_preferences = models.JSONField(default=dict)
    selected_product_id = models.CharField(max_length=240, blank=True)
    selected_product_name = models.CharField(max_length=240, blank=True)
    purchase_preferences = models.JSONField(default=dict)
    budget_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    budget_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    laf1_result = models.JSONField(default=dict)
    laf2_result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.domain_key}:{self.dataset_key}:{self.id}"
