"""Generación web del mismo programa LAF 1 producido por el paso 08."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import importlib.util
import json
import math
import re
from functools import lru_cache
from pathlib import Path
import sys
from types import ModuleType
from collections import defaultdict

from recommender.domain.contracts import EvaluationRequest
from recommender.repositories.contracts import LAF1SourceRepository


class LAF1ProgramGenerationError(RuntimeError):
    """La entrada real no permite producir un programa LAF 1 reproducible."""


@dataclass(frozen=True)
class GeneratedLAF1Program:
    run_id: str
    text: str
    generated_at: str
    methodology_sha256: str
    products_count: int
    facts_count: int
    rules_count: int
    entities: tuple[dict[str, object], ...] = ()


@lru_cache(maxsize=1)
def _load_step_08(repository_root: str) -> ModuleType:
    """Carga 08 como módulo para reutilizar su constructor, sin subprocesos."""
    root = Path(repository_root).resolve()
    source_dir = root / "src"
    script_path = source_dir / "08_laf1_generate.py"
    if not script_path.exists():
        raise LAF1ProgramGenerationError(f"No existe el paso 08: {script_path}")

    source_text = str(source_dir)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    spec = importlib.util.spec_from_file_location("laf1_step_08", script_path)
    if spec is None or spec.loader is None:
        raise LAF1ProgramGenerationError("No se pudo cargar el constructor del paso 08.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LAF1ProgramService:
    """Adapta los botones web al contrato de 07 y ejecuta la generación de 08."""

    def __init__(self, repository: LAF1SourceRepository, repository_root: Path):
        self.repository = repository
        self.repository_root = Path(repository_root).resolve()

    def generate(self, request: EvaluationRequest) -> GeneratedLAF1Program:
        try:
            source = self._load_source(request)
            return self._generate_from_source(request, source)
        except LAF1ProgramGenerationError:
            raise
        except Exception as exc:
            raise LAF1ProgramGenerationError(
                "No se pudo preparar el programa LAF 1 para este catálogo."
            ) from exc

    def generate_many(
        self,
        request: EvaluationRequest,
        preference_sets: list[dict[str, float]] | tuple[dict[str, float], ...],
    ) -> tuple[GeneratedLAF1Program, ...]:
        """Genera variantes cargando catálogo y evidencia una única vez."""
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
        except LAF1ProgramGenerationError:
            raise
        except Exception as exc:
            raise LAF1ProgramGenerationError(
                "No se pudieron preparar las variantes LAF 1 para este catálogo."
            ) from exc

    def generate_aspects(
        self, request: EvaluationRequest,
    ) -> tuple[GeneratedLAF1Program, dict[str, GeneratedLAF1Program]]:
        """Un respaldo completo y programas independientes de confianza.

        La evidencia se carga una vez. Cada programa recibe exclusivamente las
        filas de su aspecto; no usa preferencias cero como filtro. El constructor
        congelado conserva las confianzas y las cadenas de reglas pertinentes.
        """
        try:
            source = self._load_source(request)
            preferences = self._complete_preferences(request.preferences, source["domain_config"])
            backup = self._generate_from_source(request, source)
            aspects = {
                aspect: self._generate_from_source(request, source, aspect=aspect)
                for aspect, weight in sorted(preferences.items()) if weight > 0
            }
            return backup, aspects
        except LAF1ProgramGenerationError:
            raise
        except Exception as exc:
            raise LAF1ProgramGenerationError(
                "No se pudieron generar los programas independientes de LAF 1."
            ) from exc

    def _load_source(self, request: EvaluationRequest) -> dict[str, object]:
        step_08 = _load_step_08(str(self.repository_root))
        domain_config = step_08.load_domain_config_for_key(request.domain)
        manifest, methodology_sha256 = step_08.load_and_validate_freeze(domain_config)
        products, evidence = self.repository.laf1_generation_data(
            request.dataset_key,
            request.strategy,
        )
        return {
            "step_08": step_08,
            "domain_config": domain_config,
            "manifest": manifest,
            "methodology_sha256": methodology_sha256,
            "products": products,
            "evidence": evidence,
        }

    def _generate_from_source(
        self,
        request: EvaluationRequest,
        source: dict[str, object],
        *,
        aspect: str = "",
    ) -> GeneratedLAF1Program:
        step_08 = source["step_08"]
        domain_config = source["domain_config"]
        manifest = source["manifest"]
        methodology_sha256 = str(source["methodology_sha256"])
        products = source["products"]
        evidence = source["evidence"]
        if aspect:
            evidence = [row for row in evidence if row["aspect"] == aspect]
        preferences = self._complete_preferences(
            request.preferences,
            domain_config,
        )
        program = step_08.build_laf1(
            products,
            evidence,
            preferences,
            request.strategy,
            domain=domain_config,
            dataset_key=request.dataset_key,
            methodology_sha256=methodology_sha256,
            frozen_at=manifest.get("frozen_at"),
        )

        if aspect:
            # Reutilizar el constructor validado preserva reglas, asimetrías y
            # redondeo de alpha. Sólo se proyecta su anotación a confianza;
            # nunca se envía una etiqueta de preferencia al motor en esta ruta.
            lines = []
            for line in program.splitlines():
                stripped = line.strip()
                if stripped.startswith("% n="):
                    lines.append(stripped)
                elif stripped and not stripped.startswith("%"):
                    lines.append(re.sub(r"\{([^;{}]+);[^{}]+\}", r"{\1}", stripped))
            program = "\n".join([
                "% LAF1 independiente: una etiqueta (confianza)",
                f"% Aspecto: {aspect}",
                f"% Dataset key: {request.dataset_key}",
                f"% Methodology SHA256: {methodology_sha256}",
                "% Preferencias del usuario: pesos externos, no etiquetas LAF.",
                *lines,
                "",
            ])

        statements = [
            line.strip()
            for line in program.splitlines()
            if line.strip() and not line.lstrip().startswith("%")
        ]
        preference_payload = json.dumps(
            preferences,
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = "|".join(
            (
                request.domain,
                request.dataset_key,
                request.strategy,
                methodology_sha256,
                preference_payload,
            )
        )
        if aspect:
            fingerprint += f"|confidence-only-v1:{aspect}"
        evidence_counts: dict[str, dict[str, dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: {"positive": 0, "negative": 0})
        )
        for row in evidence:
            if row.get("from_catalog"):
                continue
            product_id = str(row.get("product_id") or "")
            aspect = str(row.get("aspect") or "")
            polarity = "negative" if row.get("polarity") == "neg" else "positive"
            if product_id and aspect:
                evidence_counts[product_id][aspect][polarity] += max(
                    int(row.get("n_reviews") or 0),
                    0,
                )
        return GeneratedLAF1Program(
            run_id=(
                "laf1-program-"
                + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
            ),
            text=program,
            generated_at=datetime.now().astimezone().isoformat(),
            methodology_sha256=methodology_sha256,
            products_count=len(products),
            facts_count=sum(":-" not in line for line in statements),
            rules_count=sum(":-" in line for line in statements),
            entities=tuple(
                {
                    "argument": step_08.product_atom(
                        product_id,
                        product.get("name") or product_id,
                    ),
                    "entity_id": str(product_id),
                    "entity_name": str(product.get("name") or product_id),
                    "evidence_counts": dict(evidence_counts.get(str(product_id), {})),
                    "metadata": {
                        "product_id": str(product_id),
                        "source_position": product.get("position"),
                        "price_min": product.get("price_min"),
                        "price_max": product.get("price_max"),
                        "items_count": product.get("n_items", 0),
                    },
                }
                for product_id, product in sorted(
                    products.items(),
                    key=lambda item: item[1]["position"],
                )
            ),
        )

    @staticmethod
    def _complete_preferences(
        submitted: dict[str, float],
        domain_config: dict,
    ) -> dict[str, float]:
        configured = set(domain_config.get("quality_aspects", {}))
        unknown = set(submitted) - configured
        if unknown:
            raise LAF1ProgramGenerationError(
                "La solicitud contiene aspectos ajenos a la categoría congelada."
            )

        preferences = {aspect: 0.0 for aspect in configured}
        for aspect, raw_value in submitted.items():
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise LAF1ProgramGenerationError(
                    f"La preferencia de {aspect!r} no es numérica."
                ) from exc
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise LAF1ProgramGenerationError(
                    f"La preferencia de {aspect!r} está fuera de [0, 1]."
                )
            preferences[aspect] = value
        return preferences
