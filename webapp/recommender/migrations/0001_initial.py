import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="RecommendationSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("domain_key", models.CharField(max_length=80)),
                ("dataset_key", models.CharField(max_length=160)),
                ("strategy", models.CharField(default="D", max_length=1)),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("quality", "Preferencias de calidad"),
                            ("product_ranking", "Ranking de productos"),
                            ("purchase", "Preferencias de compra"),
                            ("listing_ranking", "Ranking de publicaciones"),
                        ],
                        default="quality",
                        max_length=32,
                    ),
                ),
                ("quality_preferences", models.JSONField(default=dict)),
                ("selected_product_id", models.CharField(blank=True, max_length=240)),
                ("selected_product_name", models.CharField(blank=True, max_length=240)),
                ("purchase_preferences", models.JSONField(default=dict)),
                ("budget_min", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("budget_max", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("laf1_result", models.JSONField(default=dict)),
                ("laf2_result", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-created_at"]},
        )
    ]
