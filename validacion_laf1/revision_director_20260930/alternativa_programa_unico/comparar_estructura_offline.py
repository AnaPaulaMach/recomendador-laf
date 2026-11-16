"""Prepare one-run alternatives from saved LAF text, without DB or HTTP access.

This script uses only the Python standard library. It does not execute LAF.
The algebraic calculations below use accumulated support values and are checked
against an existing saved ranking, rather than labelled as new engine results.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / "validacion_laf1/salidas/recongelado_20260910/despues/programa_laf1_D.txt"
SAVED_RANKING = ROOT / "validacion_laf1/salidas/recongelado_20260910/despues/battery_multicriterio_mlm194329_20260528_142014.json"
LINE = re.compile(r"^(.+?)\.\s*\{([^{}]+)\}$")
LITERAL = re.compile(r"^(~?)([A-Za-z_][A-Za-z_0-9]*)\(([^()]+)\)$")


@dataclass(frozen=True)
class Statement:
    head: str
    body: str | None
    alpha_text: str
    source_line: int

    @property
    def alpha(self):
        return float(self.alpha_text)

    def text(self):
        formula = self.head if self.body is None else f"{self.head} :- {self.body}"
        return f"{formula}. {{{self.alpha_text}}}"


def parse_literal(value):
    match = LITERAL.fullmatch(value)
    if not match:
        raise ValueError(f"Unsupported literal: {value}")
    return match.groups()


def predicate(value):
    return parse_literal(value)[1]


def parse_program(path):
    statements = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("%"):
            continue
        match = LINE.fullmatch(line)
        if not match:
            raise ValueError(f"Unsupported source statement at {number}: {line}")
        formula, attributes = match.groups()
        parts = formula.split(" :- ")
        if len(parts) not in (1, 2):
            raise ValueError(f"Unsupported rule at {number}")
        head = parts[0]
        body = parts[1] if len(parts) == 2 else None
        parse_literal(head)
        if body:
            parse_literal(body)
        statements.append(Statement(head, body, attributes.split(";")[0].strip(), number))
    return statements


def cap(aspect):
    return aspect[0].upper() + aspect[1:]


def isolate(statements, aspect):
    fact_predicates = {f"resenaPositiva{cap(aspect)}", f"resenaNegativa{cap(aspect)}"}
    facts = [s for s in statements if s.body is None and predicate(s.head) in fact_predicates]
    known = set(fact_predicates)
    rules = []
    while True:
        added = [s for s in statements if s.body and predicate(s.body) in known and s not in rules]
        if not added:
            break
        rules.extend(added)
        known.update(predicate(s.head) for s in added)
    return facts + rules


def rename_literal(value, aliases):
    neg, pred, argument = parse_literal(value)
    return f"{neg}{aliases.get(pred, pred)}({argument})"


def namespace(program, aspect):
    # Evidence and aspect literals are already distinct between aspects. Shared
    # dimensions and recomendar must be distinct too, including their negations.
    own = f"{aspect}Bueno"
    aliases = {}
    for s in program:
        if s.body:
            pred = predicate(s.head)
            if pred == "recomendar":
                aliases[pred] = f"recomendarPor{cap(aspect)}"
            elif pred != own:
                aliases[pred] = pred.removesuffix("Bueno") + f"Por{cap(aspect)}Bueno"
    return [replace(s, head=rename_literal(s.head, aliases),
                    body=rename_literal(s.body, aliases) if s.body else None)
            for s in program], aliases


def write_program(name, statements, description):
    lines = [f"% {description}", "% Preparado offline; ejecución/verificación documentada en comparacion_motor_local.json.",
             f"% Fuente: {SOURCE.relative_to(ROOT).as_posix()}",
             "% Una etiqueta de confianza; preferencias como pesos externos."]
    lines.extend(s.text() for s in statements)
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def weaken(positive, negative):
    return max((positive - negative) / max(1 - negative, 1e-9), 0.0)


def chain_values(program, product):
    # Single-aspect programs here have unary support rules and one path for each
    # sign. No aggregation across different criteria occurs in this calculation.
    values = {s.head: s.alpha for s in program if s.body is None and parse_literal(s.head)[2] == product}
    remaining = [s for s in program if s.body]
    for _ in range(len(remaining) + 1):
        changed = False
        for s in remaining:
            head = s.head.replace("(X)", f"({product})")
            body = s.body.replace("(X)", f"({product})")
            if body in values and head not in values:
                values[head] = values[body] * s.alpha
                changed = True
        if not changed:
            break
    result = {}
    for literal in list(values):
        neg, pred, argument = parse_literal(literal)
        if neg:
            continue
        mu_pos = values[literal]
        mu_neg = values.get(f"~{pred}({argument})", 0.0)
        result[pred] = {"accumulated_positive": mu_pos, "accumulated_negative": mu_neg,
                        "weakened_positive": weaken(mu_pos, mu_neg)}
    return result


def main():
    source = parse_program(SOURCE)
    facts = [s for s in source if s.body is None]
    rules = [s for s in source if s.body]
    aspects = sorted({predicate(s.head).removeprefix("resenaPositiva").removeprefix("resenaNegativa").lower() for s in facts})
    products = sorted({parse_literal(s.head)[2] for s in facts})
    isolates = {a: isolate(source, a) for a in aspects}
    combined = []
    components = {}
    scores = {}
    intermediate_scores = {}
    for aspect, program in isolates.items():
        renamed, aliases = namespace(program, aspect)
        reverse = {new: old for old, new in aliases.items()}
        restored = [replace(s, head=rename_literal(s.head, reverse),
                            body=rename_literal(s.body, reverse) if s.body else None) for s in renamed]
        if restored != program:
            raise AssertionError(f"Renaming changed the component {aspect}")
        combined.extend(renamed)
        components[aspect] = {
            "facts": sum(s.body is None for s in program),
            "rules": sum(s.body is not None for s in program),
            "terminal_predicate": f"recomendarPor{cap(aspect)}",
            "aliases": aliases,
            "reversible_exact_statement_identity": True,
            "source_lines": [s.source_line for s in program],
        }
        write_program(f"programas_por_aspecto/{aspect}.txt", program,
                      f"Referencia independiente por aspecto: {aspect}")
        scores[aspect] = {}
        intermediate_scores[aspect] = {}
        for product in products:
            values = chain_values(program, product)
            scores[aspect][product] = values.get("recomendar", {}).get("weakened_positive", 0.0)
            intermediate_scores[aspect][product] = values.get(f"{aspect}Bueno", {}).get("weakened_positive", 0.0)
    write_program("programa_unico_terminales_independientes.txt", combined,
                  "Una corrida propuesta: componentes con terminales independientes")
    write_program("programa_completo_confianza_global.txt", source,
                  "Una corrida propuesta: dimensiones y recomendar compartidos")
    vector = facts + [s for s in rules if predicate(s.head) in {f"{a}Bueno" for a in aspects}]
    write_program("programa_unico_vector_aspectos.txt", vector,
                  "Una corrida propuesta: vector de aspectos, sin niveles superiores")
    # Structural disjointness: equality of product constants creates no rule or
    # conflict edge, which is determined by predicate and sign, not constant alone.
    predicate_sets = {a: {predicate(s.head) for s in namespace(p, a)[0]} for a, p in isolates.items()}
    overlaps = {f"{a}/{b}": sorted(predicate_sets[a] & predicate_sets[b])
                for i, a in enumerate(aspects) for b in aspects[i + 1:]
                if predicate_sets[a] & predicate_sets[b]}
    if overlaps:
        raise AssertionError(f"Unexpected shared predicates: {overlaps}")
    expected = {p: sum(scores[a][p] for a in aspects) / len(aspects) for p in products}
    intermediate = {p: sum(intermediate_scores[a][p] for a in aspects) / len(aspects) for p in products}
    saved = json.loads(SAVED_RANKING.read_text(encoding="utf-8-sig"))["neutral"]
    differences = {row["product"]: expected[row["product"]] - row["score"] for row in saved}
    calculated_order = sorted(products, key=lambda p: (-expected[p], p.casefold()))
    saved_order = [row["product"] for row in saved]
    vector_order = sorted(products, key=lambda p: (-intermediate[p], p.casefold()))
    blason = next(p for p in products if p.startswith("mlm26912881_"))
    values = chain_values(isolates["sabor"], blason)
    delta_aspect = values["saborBueno"]["weakened_positive"]
    terminal = values["recomendar"]["weakened_positive"]
    naive = delta_aspect * 0.90 * 0.90
    comparison = {
        "execution_mode": "offline_standard_library_no_db_no_http_no_laf_engine",
        "source_program": str(SOURCE.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "saved_ranking": str(SAVED_RANKING.relative_to(ROOT)),
        "source_facts": len(facts), "source_rules": len(rules),
        "products": len(products), "aspects": len(aspects),
        "single_namespaced_facts": sum(s.body is None for s in combined),
        "single_namespaced_rules": sum(s.body is not None for s in combined),
        "components": components, "cross_component_shared_predicates": overlaps,
        "algebraic_model_vs_saved_neutral_ranking": {
            "same_order": calculated_order == saved_order,
            "max_absolute_score_difference": max(map(abs, differences.values())),
            "differences": differences,
            "meaning": "Consistency with saved ranking, not a new engine equivalence test.",
        },
        "intermediate_vector_vs_current_scores": {
            "same_order": vector_order == calculated_order,
            "max_absolute_score_difference": max(abs(intermediate[p] - expected[p]) for p in products),
            "top3_intermediate": vector_order[:3], "top3_current": calculated_order[:3],
        },
        "real_blason_sabor_chain_under_model": {
            "product": blason, "levels": values,
            "naive_delta_aspect_times_positive_rule_factors": naive,
            "terminal_weakened_value": terminal,
            "difference": naive - terminal,
        },
        "expected_per_aspect_scores_under_accumulated_support_model": scores,
        "expected_neutral_scores_under_model": expected,
        "pending_engine_validation": [
            "One-label parser and API acceptance of independent terminal predicates.",
            "Per-product, per-aspect delta and mu equality between union and separate runs.",
            "Identical weighted rankings under neutral, individual and mixed preference profiles.",
            "Missing evidence, negative-only evidence, conflict ties and boundary values.",
            "Compare extraction from full aspect nodes with vector-only source on all products.",
        ],
    }
    (OUT / "comparacion_offline.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"products": len(products), "aspects": len(aspects),
                      "source_facts": len(facts), "source_rules": len(rules),
                      "union_rules": sum(s.body is not None for s in combined),
                      "same_saved_neutral_order": calculated_order == saved_order,
                      "max_diff_saved_neutral": max(map(abs, differences.values())),
                      "blason_naive": naive, "blason_terminal": terminal}, ensure_ascii=False))


if __name__ == "__main__":
    main()
