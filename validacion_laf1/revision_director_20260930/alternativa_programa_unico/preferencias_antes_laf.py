"""Bounded calculator-only experiments: weights before LAF and compound rules.

Synthetic examples are marked separately from historical frozen corpus input.
No database access or production/manuscript changes; no human quality evaluation.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import re
import sys

OUT = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "webapp"))
from recommender.services.laf_api import LAFProgramParser, LAFApiClient, LAFGraphRankingMapper
from recommender.services.post_laf_decision import normalized_multicriteria_ranking
from comparar_estructura_offline import SOURCE, parse_program, parse_literal, predicate

SAVE = OUT / "preferencias_antes_laf"
SAVE.mkdir(exist_ok=True)
parser = LAFProgramParser()
mapper = LAFGraphRankingMapper()
client = LAFApiClient("http://localhost:8088/api/graph", timeout_seconds=30)


def run(name, text, conclusions):
    (SAVE / f"{name}.txt").write_text(text, encoding="utf-8")
    parsed = parser.parse(text)
    graph = client.build_graph(parsed.to_request_payload())
    (SAVE / f"{name}_grafo.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    output = {"label_count": parsed.attribute_count, "facts": len(parsed.facts), "rules": len(parsed.rules),
              "rankings": {}, "nodes_by_conclusion": {}}
    for name in conclusions:
        output["rankings"][name] = [asdict(row) for row in mapper.map(graph, [], conclusion_predicate=name)]
        output["nodes_by_conclusion"][name] = [node for node in graph["nodes"]
            if str(node.get("type", "")).upper() == "FACT"
            and re.fullmatch(rf"~?{name}\([^()]+\)", str(node.get("label", "")))]
    return output


def value(case, conclusion):
    return case["rankings"][conclusion][0]["confidence"]


def synthetic():
    prefix = "% EJEMPLO SINTETICO; no representa el corpus ni valida calidad.\n"
    cases = {
        "beta_hechos": "positivo(ejemplo). {0.80; 0.40}\nnegativo(ejemplo). {0.30; 0.40}\n"
            "aspectoBueno(X) :- positivo(X). {1; 1}\n~aspectoBueno(X) :- negativo(X). {1; 1}\n",
        "beta_reglas": "positivo(ejemplo). {0.80; 1}\nnegativo(ejemplo). {0.30; 1}\n"
            "aspectoBueno(X) :- positivo(X). {1; 0.40}\n~aspectoBueno(X) :- negativo(X). {1; 0.40}\n",
        "alpha_hechos": "positivo(ejemplo). {0.32}\nnegativo(ejemplo). {0.12}\n"
            "aspectoBueno(X) :- positivo(X). {1}\n~aspectoBueno(X) :- negativo(X). {1}\n",
        "alpha_reglas": "positivo(ejemplo). {0.80}\nnegativo(ejemplo). {0.30}\n"
            "aspectoBueno(X) :- positivo(X). {0.40}\n~aspectoBueno(X) :- negativo(X). {0.40}\n",
    }
    common = "saborBueno(ejemplo). {0.80}\n~saborBueno(ejemplo). {0.20}\naromaBueno(ejemplo). {0.60}\n"
    terminal = "recomendarPorSabor(X) :- saborBueno(X). {1}\n~recomendarPorSabor(X) :- ~saborBueno(X). {1}\n"
    cases["interaccion_base"] = common + terminal
    cases["interaccion_nueva_conclusion"] = common + terminal + "sinergiaBueno(X) :- saborBueno(X), aromaBueno(X). {0.90}\n"
    cases["interaccion_ataca_terminal"] = common + terminal + "~recomendarPorSabor(X) :- aromaBueno(X). {0.50}\n"
    output = {}
    for name, text in cases.items():
        conclusions = ["aspectoBueno"] if name.startswith(("alpha_", "beta_")) else ["saborBueno", "aromaBueno", "recomendarPorSabor"]
        if name == "interaccion_nueva_conclusion":
            conclusions.append("sinergiaBueno")
        output[name] = run(f"toy_{name}", prefix + text, conclusions)
    output["arithmetic_comparison"] = {
        "D_unweighted": (0.80 - 0.30) / (1 - 0.30),
        "weight_times_D_unweighted": 0.40 * (0.80 - 0.30) / (1 - 0.30),
        "D_weighted_inputs_observed": value(output["alpha_hechos"], "aspectoBueno"),
        "compound_confidence_observed": value(output["interaccion_nueva_conclusion"], "sinergiaBueno"),
        "compound_product_prediction": 0.80 * 0.60 * 0.90,
        "compound_min_then_rule_prediction": min(0.80, 0.60) * 0.90,
        "base_terminal": value(output["interaccion_base"], "recomendarPorSabor"),
        "terminal_after_cross_aspect_attack": value(output["interaccion_ataca_terminal"], "recomendarPorSabor"),
    }
    return output


def frozen_input():
    source = parse_program(SOURCE)
    meta = json.loads((OUT / "comparacion_offline.json").read_text(encoding="utf-8"))
    aspects = sorted(meta["components"])
    products = sorted(next(iter(meta["expected_per_aspect_scores_under_accumulated_support_model"].values())))
    post_scores = meta["expected_per_aspect_scores_under_accumulated_support_model"]
    names = {p: p for p in products}
    profiles = {
        "neutral_067": {a: 0.67 for a in aspects},
        "proporcional_033": {a: 0.33 for a in aspects},
        "mixto": {a: [0, 0.33, 0.67, 1][i % 4] for i, a in enumerate(aspects)},
        "solo_sabor": {a: float(a == "sabor") for a in aspects},
        "solo_aroma": {a: float(a == "aroma") for a in aspects},
    }
    output = {"source": str(SOURCE.relative_to(ROOT)),
              "label_count": 1, "weight_applied_times_per_path": 1,
              "profiles": {}, "interpretation": "Sensitivity and non-equivalence, not recommendation quality."}
    for name, weights in profiles.items():
        profile = {"weights": weights, "variants": {}}
        current = normalized_multicriteria_ranking(post_scores, weights, names)
        profile["post_laf_reference"] = list(current)
        post = {r["entity_id"]: r["score"] for r in current}
        for variant in ("alpha_hechos", "alpha_puente_reglas"):
            program = []
            for statement in source:
                alpha = statement.alpha
                if statement.body is None:
                    asp = re.sub(r"^resena(?:Positiva|Negativa)", "", predicate(statement.head)).lower()
                    if weights[asp] == 0:
                        continue
                    if variant == "alpha_hechos":
                        alpha *= weights[asp]
                elif variant == "alpha_puente_reglas":
                    asp = predicate(statement.body).removesuffix("Bueno")
                    if asp in weights:
                        alpha *= weights[asp]
                program.append(replace(statement, alpha_text=f"{alpha:.12g}"))
            text = "% NUEVA PRUEBA ACOTADA: una etiqueta; peso continuo antes LAF.\n" + "\n".join(s.text() for s in program) + "\n"
            case = run(f"corpus_{name}_{variant}", text, ["recomendar"])
            selected = {r["entity_id"]: r["confidence"] for r in case["rankings"]["recomendar"]}
            case["comparison_to_post_laf"] = {
                "same_present_products": set(selected) == set(post),
                "same_order": [r["entity_id"] for r in case["rankings"]["recomendar"]] == [r["entity_id"] for r in current],
                "max_absolute_score_difference": max((abs(selected.get(p, 0) - post.get(p, 0)) for p in set(selected) | set(post)), default=0),
            }
            profile["variants"][variant] = case
        left = {r["entity_id"]: r["confidence"] for r in profile["variants"]["alpha_hechos"]["rankings"]["recomendar"]}
        right = {r["entity_id"]: r["confidence"] for r in profile["variants"]["alpha_puente_reglas"]["rankings"]["recomendar"]}
        profile["weight_placement_comparison"] = {
            "same_present_products": set(left) == set(right),
            "max_absolute_score_difference": max((abs(left.get(p, 0) - right.get(p, 0)) for p in set(left) | set(right)), default=0),
        }
        output["profiles"][name] = profile
    return output


def main():
    output = {"scope": "Local calculator only; distinct synthetic and frozen-input experiments.",
              "synthetic": synthetic(), "frozen_corpus": frozen_input()}
    (SAVE / "resultados.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    concise = {name: {"weight_placement_difference": p["weight_placement_comparison"]["max_absolute_score_difference"],
                      "vs_post_laf": p["variants"]["alpha_hechos"]["comparison_to_post_laf"],
                      "winner": p["variants"]["alpha_hechos"]["rankings"]["recomendar"][0]["entity_id"]}
               for name, p in output["frozen_corpus"]["profiles"].items()}
    print(json.dumps({"synthetic": output["synthetic"]["arithmetic_comparison"], "corpus": concise}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
