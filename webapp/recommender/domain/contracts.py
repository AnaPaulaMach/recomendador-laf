"""Contratos estables entre las vistas y cualquier evaluador LAF."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

EvaluationStatus = Literal["mock", "pending", "validated"]
ProgramStatus = Literal["not_generated", "generated", "failed"]
ProgramKind = Literal["", "laf1", "laf2"]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ArgumentEvidence:
    argument_id: str
    title: str
    aspect: str
    polarity: Literal["positive", "negative", "neutral"]
    confidence: float
    preference: float
    evidence_count: int
    summary: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArgumentEvidence":
        polarity = data.get("polarity")
        if polarity not in {"positive", "negative", "neutral"}:
            polarity = "neutral"
        return cls(
            argument_id=str(data.get("argument_id") or "argumento-sin-id"),
            title=str(data.get("title") or "Argumento sin título"),
            aspect=str(data.get("aspect") or "sin_aspecto"),
            polarity=polarity,
            confidence=_number(data.get("confidence")),
            preference=_number(data.get("preference")),
            evidence_count=max(int(data.get("evidence_count") or 0), 0),
            summary=str(data.get("summary") or ""),
        )


@dataclass(frozen=True)
class RankingEntry:
    entity_id: str
    entity_name: str
    position: int
    final_score: float
    confidence: float
    preference: float
    status: str
    evidence_count: int
    arguments_for: tuple[ArgumentEvidence, ...] = field(default_factory=tuple)
    arguments_against: tuple[ArgumentEvidence, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RankingEntry":
        return cls(
            entity_id=str(data.get("entity_id") or "entidad-sin-id"),
            entity_name=str(data.get("entity_name") or "Entidad sin nombre"),
            position=max(int(data.get("position") or 0), 0),
            final_score=_number(data.get("final_score")),
            confidence=_number(data.get("confidence")),
            preference=_number(data.get("preference")),
            status=str(data.get("status") or "undetermined"),
            evidence_count=max(int(data.get("evidence_count") or 0), 0),
            arguments_for=tuple(
                ArgumentEvidence.from_dict(item)
                for item in (data.get("arguments_for") or [])
                if isinstance(item, dict)
            ),
            arguments_against=tuple(
                ArgumentEvidence.from_dict(item)
                for item in (data.get("arguments_against") or [])
                if isinstance(item, dict)
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class EvaluationRequest:
    domain: str
    dataset_key: str
    strategy: str
    preferences: dict[str, float]
    selected_entity_id: str = ""
    budget_min: float | None = None
    budget_max: float | None = None


@dataclass(frozen=True)
class EvaluationResult:
    run_id: str
    evaluation_status: EvaluationStatus
    evaluator_version: str
    operator_profile: str
    dataset_key: str
    domain: str
    strategy: str
    generated_at: str
    ranking: tuple[RankingEntry, ...]
    program_status: ProgramStatus = "not_generated"
    program_kind: ProgramKind = ""
    laf_program: str = ""
    methodology_sha256: str = ""
    products_count: int = 0
    items_count: int = 0
    facts_count: int = 0
    rules_count: int = 0
    laf_graph: dict[str, Any] = field(default_factory=dict)
    aspect_programs: dict[str, str] = field(default_factory=dict)
    aspect_graphs: dict[str, Any] = field(default_factory=dict)
    execution_payloads: dict[str, Any] = field(default_factory=dict)
    backup_laf_graph: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationResult":
        status = data.get("evaluation_status")
        if status not in {"mock", "pending", "validated"}:
            status = "pending"
        program_status = data.get("program_status")
        if program_status not in {"not_generated", "generated", "failed"}:
            program_status = "not_generated"
        program_kind = data.get("program_kind")
        if program_kind not in {"", "laf1", "laf2"}:
            program_kind = ""
        generated_at = str(data.get("generated_at") or datetime.now().astimezone().isoformat())
        return cls(
            run_id=str(data.get("run_id") or "run-sin-id"),
            evaluation_status=status,
            evaluator_version=str(data.get("evaluator_version") or "sin-versión"),
            operator_profile=str(data.get("operator_profile") or "sin-perfil"),
            dataset_key=str(data.get("dataset_key") or "sin-dataset"),
            domain=str(data.get("domain") or "sin-dominio"),
            strategy=str(data.get("strategy") or "D"),
            generated_at=generated_at,
            ranking=tuple(
                RankingEntry.from_dict(item)
                for item in (data.get("ranking") or [])
                if isinstance(item, dict)
            ),
            program_status=program_status,
            program_kind=program_kind,
            laf_program=str(data.get("laf_program") or ""),
            methodology_sha256=str(data.get("methodology_sha256") or ""),
            products_count=max(int(data.get("products_count") or 0), 0),
            items_count=max(int(data.get("items_count") or 0), 0),
            facts_count=max(int(data.get("facts_count") or 0), 0),
            rules_count=max(int(data.get("rules_count") or 0), 0),
            laf_graph=dict(data.get("laf_graph") or {}),
            aspect_programs=dict(data.get("aspect_programs") or {}),
            aspect_graphs=dict(data.get("aspect_graphs") or {}),
            execution_payloads=dict(data.get("execution_payloads") or {}),
            backup_laf_graph=dict(data.get("backup_laf_graph") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
