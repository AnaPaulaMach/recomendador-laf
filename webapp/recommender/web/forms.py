"""Formularios del recorrido: validan y normalizan lo que entra del navegador.

Los cuatro niveles de importancia (`PREFERENCE_LEVELS`) se declaran aca; ver
tambien ``web/presentation.preference_level`` y ``services/comparison``, que
traducen el mismo valor a texto.
"""
from __future__ import annotations

from django import forms

from recommender.repositories.domain_repository import DomainConfig


PREFERENCE_LEVELS = (
    ("0", "No me importa"),
    ("0.33", "Poco"),
    ("0.67", "Bastante"),
    ("1", "Es prioridad"),
)


def _closest_preference_level(value) -> str:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        numeric_value = 0.67
    level = min((0.0, 0.33, 0.67, 1.0), key=lambda item: abs(item - numeric_value))
    # RadioSelect compara el valor inicial con las claves textuales de choices.
    # Los extremos guardados por JSON son 0.0/1.0, pero sus claves son "0"/"1".
    return {0.0: "0", 0.33: "0.33", 0.67: "0.67", 1.0: "1"}[level]


class DomainSelectionForm(forms.Form):
    domain = forms.ChoiceField(label="Dominio")
    dataset_key = forms.ChoiceField(label="Dataset")
    strategy = forms.ChoiceField(
        label="Estrategia de balanceo",
        choices=[
            ("A", "A · Normalización logarítmica"),
            ("B", "B · Umbral mínimo"),
            ("C", "C · Catálogo como base"),
            ("D", "D · Contracción hacia una media a priori"),
            ("E", "E · Sin ajuste + metadatos"),
        ],
        initial="D",
    )

    def __init__(self, *args, domains=(), datasets=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["domain"].choices = [(item.key, item.display_name) for item in domains]
        self.fields["dataset_key"].choices = [
            (item["key"], item["label"]) for item in datasets
        ]


class DynamicPreferencesForm(forms.Form):
    def __init__(self, *args, aspects=(), initial_value=0.67, **kwargs):
        super().__init__(*args, **kwargs)
        for aspect in aspects:
            current_initial = self.initial.get(aspect.key, initial_value)
            self.initial[aspect.key] = _closest_preference_level(current_initial)
            self.fields[aspect.key] = forms.FloatField(
                label=aspect.label,
                min_value=0,
                max_value=1,
                initial=self.initial[aspect.key],
                widget=forms.RadioSelect(
                    choices=PREFERENCE_LEVELS,
                    attrs={"data-preference-levels": ""}
                ),
            )

    def preferences(self) -> dict[str, float]:
        return {
            key: float(value)
            for key, value in self.cleaned_data.items()
            if isinstance(value, (float, int))
        }


class QualityPreferencesForm(DynamicPreferencesForm):
    def __init__(self, *args, domain: DomainConfig, aspects=None, **kwargs):
        selected_aspects = domain.quality_aspects if aspects is None else tuple(aspects)
        super().__init__(*args, aspects=selected_aspects, initial_value=0.67, **kwargs)


class PurchasePreferencesForm(DynamicPreferencesForm):
    budget_min = forms.DecimalField(
        label="Presupuesto mínimo",
        min_value=0,
        required=False,
        localize=True,
        widget=forms.TextInput(attrs={"inputmode": "decimal"}),
    )
    budget_max = forms.DecimalField(
        label="Presupuesto máximo",
        min_value=0,
        required=False,
        localize=True,
        widget=forms.TextInput(attrs={"inputmode": "decimal"}),
    )

    def __init__(self, *args, domain: DomainConfig, aspects=None, **kwargs):
        selected_aspects = domain.purchase_aspects if aspects is None else tuple(aspects)
        super().__init__(*args, aspects=selected_aspects, initial_value=0.67, **kwargs)
        self.order_fields(["budget_min", "budget_max", *[a.key for a in selected_aspects]])

    def clean(self):
        cleaned = super().clean()
        minimum = cleaned.get("budget_min")
        maximum = cleaned.get("budget_max")
        if minimum is not None and maximum is not None and minimum > maximum:
            # U32: el error se veía a unos 350 px de los campos y ninguno de los
            # dos quedaba marcado. Acá se marcan los dos; la plantilla muestra el
            # mensaje dentro del panel del presupuesto, junto a ellos.
            for field_name in ("budget_min", "budget_max"):
                widget = self.fields[field_name].widget
                css_classes = f"{widget.attrs.get('class', '')} input-error".strip()
                widget.attrs["class"] = css_classes
                widget.attrs["aria-invalid"] = "true"
            raise forms.ValidationError(
                "El presupuesto mínimo no puede superar al presupuesto máximo."
            )
        return cleaned

    def preferences(self) -> dict[str, float]:
        ignored = {"budget_min", "budget_max"}
        return {
            key: float(value)
            for key, value in self.cleaned_data.items()
            if key not in ignored and isinstance(value, (float, int))
        }


class LAF2AuditProductForm(forms.Form):
    product_id = forms.ChoiceField(label="Producto controlado")

    def __init__(self, *args, products=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.products = {
            str(product["product_id"]): product for product in products
        }
        self.fields["product_id"].choices = [
            (
                product_id,
                (
                    f"#{product.get('position', 0):02d} - {product.get('name', product_id)} "
                    f"({product.get('items_count', 0)} publicaciones)"
                ),
            )
            for product_id, product in self.products.items()
        ]

    def selected_product(self) -> dict:
        return self.products[self.cleaned_data["product_id"]]
