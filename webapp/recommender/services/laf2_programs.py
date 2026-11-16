"""Generacion web del mismo programa LAF 2 producido por el paso 10."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
from types import ModuleType

from recommender.domain.contracts import EvaluationRequest
from recommender.repositories.contracts import LAF2SourceRepository


class LAF2ProgramGenerationError(RuntimeError):
    """La entrada real no permite producir un programa LAF 2 reproducible."""


@dataclass(frozen=True)
class GeneratedLAF2Program:
    run_id: str
    text: str
    generated_at: str
    methodology_sha256: str
    product_id: str
    product_name: str
    items_count: int
    facts_count: int
    rules_count: int
    entities: tuple[dict[str, object], ...] = ()


@lru_cache(maxsize=1)
def _load_step_10(repository_root: str) -> ModuleType:
    root = Path(repository_root).resolve()
    source_dir = root / "src"
    script_path = source_dir / "10_laf2_generate.py"
    if not script_path.exists():
        raise LAF2ProgramGenerationError(f"No existe el paso 10: {script_path}")

    source_text = str(source_dir)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    spec = importlib.util.spec_from_file_location("laf2_step_10", script_path)
    if spec is None or spec.loader is None:
        raise LAF2ProgramGenerationError("No se pudo cargar el constructor del paso 10.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LAF2ProgramService:
    """Adapta las preferencias web al contrato de 09 y genera el paso 10."""

    def __init__(self, repository: LAF2SourceRepository, repository_root: Path):
        self.repository = repository
        self.repository_root = Path(repository_root).resolve()

    # Condición de compra -> bandera que produce parse_item() del paso 10.
    CONDITION_FLAGS = {
        "precio": None,  # siempre hay hecho de precio
        "descuento": "has_discount",
        "cuotas": "has_cuotas",
        "garantia": "has_long_warranty",
        "tienda_oficial": "is_official_store",
        "factura": "has_invoice",
        "envio": "has_free_shipping",
    }

    def generate(self, request: EvaluationRequest) -> GeneratedLAF2Program:
        return self.generate_many(request, (request.preferences,))[0]

    def generate_many(
        self,
        request: EvaluationRequest,
        preference_sets: list[dict[str, float]] | tuple[dict[str, float], ...],
    ) -> tuple[GeneratedLAF2Program, ...]:
        """Genera variantes cargando catálogo y publicaciones una única vez.

        La decisión multicriterio necesita el programa completo más uno por
        condición activa; sin esto Supabase se consultaba 1 + N veces.
        """
        if not request.selected_entity_id:
            raise LAF2ProgramGenerationError(
                "LAF 2 necesita un producto seleccionado de forma explicita."
            )
        try:
            source = self._load_source(request)
            return tuple(
                self._generate_from_source(
                    EvaluationRequest(
                        domain=request.domain,
                        dataset_key=request.dataset_key,
                        strategy=request.strategy,
                        preferences=dict(preferences),
                        selected_entity_id=request.selected_entity_id,
                        budget_min=request.budget_min,
                        budget_max=request.budget_max,
                    ),
                    source,
                )
                for preferences in preference_sets
            )
        except LAF2ProgramGenerationError:
            raise
        except Exception as exc:
            raise LAF2ProgramGenerationError(
                "No se pudo preparar el programa LAF 2 para este producto."
            ) from exc

    def generate_conditions(
        self,
        request: EvaluationRequest,
    ) -> tuple[GeneratedLAF2Program, dict[str, GeneratedLAF2Program]]:
        """Un respaldo completo y programas independientes por condición.

        Espejo de ``LAF1ProgramService.generate_aspects`` (ADR-002, ADR-007).
        Las publicaciones se cargan una vez. Cada programa recibe exclusivamente
        los hechos de su condición por selección explícita; no se usa la máscara
        de preferencias 1,0/0,0 ni ``zero_threshold_payload``. La anotación se
        proyecta a ``{confianza}`` antes de enviarla al motor.
        """
        if not request.selected_entity_id:
            raise LAF2ProgramGenerationError(
                "LAF 2 necesita un producto seleccionado de forma explicita."
            )
        try:
            source = self._load_source(request)
            preferences = self._complete_preferences(
                request.preferences,
                source["domain_config"],
            )
            backup = self._generate_from_source(request, source)
            conditions = {
                condition: self._generate_from_source(
                    request, source, condition=condition,
                )
                for condition, weight in sorted(preferences.items())
                if weight > 0
            }
            return backup, conditions
        except LAF2ProgramGenerationError:
            raise
        except Exception as exc:
            raise LAF2ProgramGenerationError(
                "No se pudieron generar los programas independientes de LAF 2."
            ) from exc

    def available_purchase_condition_keys(
        self,
        dataset_key: str,
        domain_key: str,
        *,
        product_id: str | None = None,
    ) -> tuple[str, ...]:
        """Condiciones que al menos una publicación comparable cumple.

        Cuando se conoce el producto, usa exactamente sus publicaciones candidatas
        de LAF2. El alcance de catálogo queda disponible para pantallas anteriores.
        """
        step_10 = _load_step_10(str(self.repository_root))
        from domain_config import load_domain_config_for_key

        rule_structure = load_domain_config_for_key(domain_key)["laf2_rule_structure"]
        if product_id:
            _product, rows = self.repository.laf2_generation_items(
                dataset_key,
                product_id,
            )
        else:
            rows = self.repository.laf2_dataset_items(dataset_key)
        available = {"precio"}
        for row in rows:
            parsed = step_10.parse_item(row, rule_structure)
            for condition, flag in self.CONDITION_FLAGS.items():
                if flag and parsed.get(flag):
                    available.add(condition)
        return tuple(sorted(available))

    def _load_source(self, request: EvaluationRequest) -> dict:
        step_10 = _load_step_10(str(self.repository_root))
        from domain_config import load_domain_config_for_key
        from methodology_freeze import load_and_validate_freeze

        domain_config = load_domain_config_for_key(request.domain)
        manifest, methodology_sha256 = load_and_validate_freeze(domain_config)
        product, raw_items = self.repository.laf2_generation_items(
            request.dataset_key,
            request.selected_entity_id,
            budget_min=request.budget_min,
            budget_max=request.budget_max,
        )
        rule_structure = domain_config["laf2_rule_structure"]
        items = []
        for row in raw_items:
            parsed_item = step_10.parse_item(row, rule_structure)
            parsed_item["seller_id"] = row.get("seller_id")
            parsed_item["warranty_label"] = self._warranty_label(row)
            items.append(parsed_item)
        return {
            "step_10": step_10,
            "domain_config": domain_config,
            "manifest": manifest,
            "methodology_sha256": methodology_sha256,
            "product": product,
            "items": items,
        }

    def _generate_from_source(
        self,
        request: EvaluationRequest,
        source: dict,
        *,
        condition: str = "",
    ) -> GeneratedLAF2Program:
        try:
            step_10 = source["step_10"]
            domain_config = source["domain_config"]
            manifest = source["manifest"]
            methodology_sha256 = source["methodology_sha256"]
            product = source["product"]
            items = source["items"]
            preferences = self._complete_preferences(
                request.preferences,
                domain_config,
            )
            program = step_10.build_laf2(
                items,
                preferences,
                product["name"],
                domain=domain_config,
                dataset_key=request.dataset_key,
                product_id=product["product_id"],
                budget_min=request.budget_min,
                budget_max=request.budget_max,
                methodology_sha256=methodology_sha256,
                frozen_at=manifest.get("frozen_at"),
            )
        except LAF2ProgramGenerationError:
            raise
        except Exception as exc:
            raise LAF2ProgramGenerationError(
                "No se pudo preparar el programa LAF 2 para este producto."
            ) from exc

        if condition:
            program = self._condition_program(
                program,
                condition,
                domain_config,
                dataset_key=request.dataset_key,
                product_id=str(product["product_id"]),
                methodology_sha256=str(methodology_sha256),
            )

        statements = [
            line.strip()
            for line in program.splitlines()
            if line.strip() and not line.lstrip().startswith("%")
        ]
        payload = json.dumps(
            {
                "domain": request.domain,
                "dataset_key": request.dataset_key,
                "product_id": request.selected_entity_id,
                "budget_min": request.budget_min,
                "budget_max": request.budget_max,
                "preferences": preferences,
                "methodology_sha256": methodology_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        if condition:
            payload += f"|confidence-only-v1:{condition}"
        return GeneratedLAF2Program(
            run_id=(
                "laf2-program-"
                + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
            ),
            text=program,
            generated_at=datetime.now().astimezone().isoformat(),
            methodology_sha256=methodology_sha256,
            product_id=str(product["product_id"]),
            product_name=str(product["name"]),
            items_count=len(items),
            facts_count=sum(":-" not in line for line in statements),
            rules_count=sum(":-" in line for line in statements),
            entities=tuple(
                {
                    "argument": step_10.safe_id(item["item_id"]),
                    "entity_id": str(item["item_id"]),
                    "entity_name": (
                        f"Publicación {item['item_id']}"
                    ),
                    "metadata": {
                        "product_id": str(product["product_id"]),
                        "seller": (
                            f"Vendedor {item.get('seller_id')}"
                            if item.get("seller_id")
                            else "Vendedor no informado"
                        ),
                        "price": float(item["price"]),
                        "installments": (
                            "12 cuotas sin interés"
                            if item.get("has_12x")
                            else "9 cuotas sin interés"
                            if item.get("has_9x")
                            else "3 cuotas sin interés"
                            if item.get("has_3x")
                            else "No informadas"
                        ),
                        "warranty": (
                            str(item.get("warranty_label") or "No informada")
                        ),
                        "shipping": (
                            "Gratis"
                            if item.get("has_free_shipping")
                            else "No informado"
                        ),
                        # Datos que la publicación declara, para mostrarlos tal
                        # cual en la explicación. No entran al programa ni al
                        # puntaje: los hechos ya los generó `parse_item`.
                        "has_free_shipping": bool(item.get("has_free_shipping")),
                        "is_official_store": bool(item.get("is_official_store")),
                        "has_discount": bool(item.get("has_discount")),
                        "discount_pct": float(item.get("discount_pct") or 0.0),
                        "warranty_months": float(item.get("warranty_months") or 0),
                    },
                }
                for item in items
            ),
        )

    @staticmethod
    def _condition_program(
        program: str,
        condition: str,
        domain_config: dict,
        *,
        dataset_key: str,
        product_id: str,
        methodology_sha256: str,
    ) -> str:
        """Selección explícita de los hechos de una condición, con una etiqueta.

        Se conservan sólo los hechos de esa condición, su regla de agregación y
        la regla de recomendación; las reglas de las otras condiciones no se
        generan en esta corrida (hoy tampoco disparaban, porque la máscara les
        dejaba el cuerpo sin hechos). La anotación de dos etiquetas se proyecta
        a una con la misma expresión regular que ``laf1_programs``: al motor
        viaja únicamente la confianza. Los pesos del usuario siguen siendo
        externos y se aplican después, en ``combine_rankings``.
        """
        rule_structure = domain_config["laf2_rule_structure"]
        conditions = rule_structure.get("conditions", {})
        predicate = (conditions.get(condition) or {}).get("fact_predicate", "")
        if not predicate:
            raise LAF2ProgramGenerationError(
                f"La condicion {condition!r} no tiene predicado en la estructura congelada."
            )
        recommendation = rule_structure.get("recommendation", {})
        head = recommendation.get("head_predicate", "recomendar")
        body = recommendation.get("body_predicate", "compraBuena")
        fact_prefix = f"{predicate}("
        aggregation_prefix = f"{body}(X) :- {predicate}(X)"
        recommendation_prefix = f"{head}(X) :- {body}(X)"

        selected = []
        for raw_line in program.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("%"):
                continue
            if (
                line.startswith(fact_prefix)
                or line.startswith(aggregation_prefix)
                or line.startswith(recommendation_prefix)
            ):
                selected.append(re.sub(r"\{([^;{}]+);[^{}]+\}", r"{\1}", line))
        return "\n".join([
            "% LAF2 independiente: una etiqueta (confianza)",
            f"% Condicion de compra: {condition}",
            f"% Dataset key: {dataset_key}",
            f"% Product ID: {product_id}",
            f"% Methodology SHA256: {methodology_sha256}",
            "% Preferencias del usuario: pesos externos, no etiquetas LAF.",
            *selected,
            "",
        ])

    @staticmethod
    def _warranty_label(row: dict) -> str:
        """Conserva la unidad original para mostrarla sin afectar el cálculo."""
        sale_terms = row.get("sale_terms") or []
        if isinstance(sale_terms, str):
            try:
                sale_terms = json.loads(sale_terms)
            except json.JSONDecodeError:
                return "No informada"
        if not isinstance(sale_terms, list):
            return "No informada"
        for term in sale_terms:
            if not isinstance(term, dict) or term.get("id") != "WARRANTY_TIME":
                continue
            value_struct = term.get("value_struct") or {}
            number = value_struct.get("number")
            unit = str(value_struct.get("unit") or "").strip().casefold()
            if number in (None, ""):
                return str(term.get("value_name") or "No informada")
            try:
                numeric = float(number)
            except (TypeError, ValueError):
                return str(term.get("value_name") or "No informada")
            rendered = str(int(numeric)) if numeric.is_integer() else f"{numeric:g}"
            if "día" in unit or "dia" in unit or "day" in unit:
                label = "día" if numeric == 1 else "días"
            elif "mes" in unit or "month" in unit:
                label = "mes" if numeric == 1 else "meses"
            elif "año" in unit or "ano" in unit or "year" in unit:
                label = "año" if numeric == 1 else "años"
            else:
                label = unit or ""
            return f"{rendered} {label}".strip()
        return "No informada"

    @staticmethod
    def _complete_preferences(
        submitted: dict[str, float],
        domain_config: dict,
    ) -> dict[str, float]:
        configured = set(domain_config.get("purchase_aspects", {}))
        unknown = set(submitted) - configured
        if unknown:
            raise LAF2ProgramGenerationError(
                "La solicitud contiene condiciones ajenas a la categoria congelada."
            )

        preferences = {aspect: 0.0 for aspect in configured}
        for aspect, raw_value in submitted.items():
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise LAF2ProgramGenerationError(
                    f"La preferencia de {aspect!r} no es numerica."
                ) from exc
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise LAF2ProgramGenerationError(
                    f"La preferencia de {aspect!r} esta fuera de [0, 1]."
                )
            preferences[aspect] = value
        return preferences
