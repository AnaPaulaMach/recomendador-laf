from django.conf import settings
from django import forms
from django.test import SimpleTestCase

from recommender.repositories.domain_repository import DomainConfigRepository
from recommender.web.forms import PurchasePreferencesForm, QualityPreferencesForm


class FormTests(SimpleTestCase):
    def setUp(self):
        self.domain = DomainConfigRepository(settings.DOMAIN_CONFIG_DIR).get("cafe")

    def test_quality_fields_come_from_domain_configuration(self):
        form = QualityPreferencesForm(domain=self.domain)
        self.assertEqual(set(form.fields), {item.key for item in self.domain.quality_aspects})
        self.assertIn("molienda", form.fields)
        self.assertIsInstance(form.fields["molienda"].widget, forms.RadioSelect)
        self.assertEqual(
            [label for _, label in form.fields["molienda"].widget.choices],
            ["No me importa", "Poco", "Bastante", "Es prioridad"],
        )

    def test_quality_form_can_be_limited_to_dataset_aspects(self):
        selected = tuple(
            aspect
            for aspect in self.domain.quality_aspects
            if aspect.key in {"sabor", "tueste"}
        )
        form = QualityPreferencesForm(domain=self.domain, aspects=selected)

        self.assertEqual(tuple(form.fields), ("sabor", "tueste"))
        self.assertEqual(form.fields["tueste"].label, "Calidad del tueste")

    def test_purchase_form_can_be_limited_to_catalog_conditions(self):
        selected = tuple(
            aspect
            for aspect in self.domain.purchase_aspects
            if aspect.key in {"precio", "envio"}
        )
        form = PurchasePreferencesForm(domain=self.domain, aspects=selected)

        self.assertEqual(tuple(form.fields), ("budget_min", "budget_max", "precio", "envio"))
        self.assertNotIn("cuotas", form.fields)

    def test_coffee_domain_declares_all_dataset_category_labels(self):
        self.assertEqual(
            set(self.domain.dataset_category_labels),
            {
                "Cafe",
                "Cafe instantaneo",
                "Cafe instantaneo c",
                "Cafe en granos y molido",
            },
        )

    def test_purchase_rejects_inverted_budget(self):
        data = {
            "budget_min": "500",
            "budget_max": "300",
            **{aspect.key: "0.67" for aspect in self.domain.purchase_aspects},
        }
        form = PurchasePreferencesForm(data=data, domain=self.domain)
        self.assertFalse(form.is_valid())
        self.assertIn("mínimo", form.non_field_errors()[0])

    def test_purchase_accepts_localized_decimal_budget(self):
        data = {
            "budget_min": "121,22",
            "budget_max": "410",
            **{aspect.key: "0.67" for aspect in self.domain.purchase_aspects},
        }
        form = PurchasePreferencesForm(data=data, domain=self.domain)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(str(form.cleaned_data["budget_min"]), "121.22")
