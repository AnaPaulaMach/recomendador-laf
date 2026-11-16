"""Compare prepared programs against the local calculator only.

No Django initialization, database access, production writes, or manuscript edits.
Raw graphs are saved so conclusions and mapper selections can be reviewed.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re
import sys
import time

OUT = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "webapp"))
from recommender.services.laf_api import LAFApiClient, LAFProgramParser, LAFGraphRankingMapper
from recommender.services.post_laf_decision import normalized_multicriteria_ranking
from comparar_estructura_offline import parse_literal

TOLERANCE = 1e-9
ENDPOINT = "http://localhost:8088/api/graph"
parser = LAFProgramParser()
mapper = LAFGraphRankingMapper()
client = LAFApiClient(ENDPOINT, timeout_seconds=30)
meta = json.loads((OUT / "comparacion_offline.json").read_text(encoding="utf-8"))
aspects = sorted(meta["components"])
products = sorted(next(iter(meta["expected_per_aspect_scores_under_accumulated_support_model"].values())))
entities = [{"argument": p, "entity_id": p, "entity_name": p} for p in products]
names = {p: p for p in products}


def calculate(filename, save_name):
    parsed = parser.parse((OUT / filename).read_text(encoding="utf-8"))
    if parsed.attribute_count != 1:
        raise AssertionError("The comparison requires one confidence label")
    start = time.perf_counter()
    graph = client.build_graph(parsed.to_request_payload())
    elapsed = time.perf_counter() - start
    graph_dir = OUT / "grafos_motor"
    graph_dir.mkdir(exist_ok=True)
    (graph_dir / f"{save_name}.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Motor {save_name}: {len(graph['nodes'])} nodos, {elapsed:.3f} s", flush=True)
    return graph, {"nodes": len(graph["nodes"]), "edges": len(graph.get("edges", [])),
                   "seconds": elapsed, "attribute_count": parsed.attribute_count}


def relevant_nodes(graph, predicate):
    labels = {str(n.get("id")): str(n.get("label")) for n in graph["nodes"]}
    output = []
    for node in graph["nodes"]:
        if str(node.get("type", "")).upper() != "FACT":
            continue
        literal = str(node.get("label", ""))
        if not re.fullmatch(rf"~?{re.escape(predicate)}\([^()]+\)", literal):
            continue
        incoming = [e for e in graph.get("edges", []) if e.get("to") == node["id"]]
        outgoing = [e for e in graph.get("edges", []) if e.get("from") == node["id"]]
        further = [e for e in outgoing if e.get("kind") == "AGGREGATION" and labels.get(str(e.get("to"))) == literal]
        output.append({**node, "incoming_edges": incoming, "outgoing_edges": outgoing,
                       "terminal_in_same_literal_aggregation": not further})
    return output


def mapped(graph, predicate):
    rows = mapper.map(graph, entities, conclusion_predicate=predicate)
    by_id = {row.entity_id: row.confidence for row in rows}
    nodes = relevant_nodes(graph, predicate)
    chosen = {str(row.metadata["laf_node_id"]) for row in rows}
    groups = {}
    for node in nodes:
        node["selected_by_current_mapper"] = node["id"] in chosen
        groups.setdefault(node["label"], []).append(node)
    return by_id, {"ranking": [asdict(row) for row in rows],
                   "all_conclusion_nodes": groups,
                   "multiple_nodes_same_literal": {k: len(v) for k, v in groups.items() if len(v) > 1},
                   "selected_nonterminal_aggregation_nodes": [n["id"] for n in nodes
                         if n["id"] in chosen and not n["terminal_in_same_literal_aggregation"]]}


def difference(left, right):
    ids = sorted(set(left) | set(right))
    result = {p: float(left.get(p, 0.0)) - float(right.get(p, 0.0)) for p in ids}
    return {"same_present_products": set(left) == set(right),
            "max_absolute_difference": max(map(abs, result.values()), default=0),
            "all_within_tolerance": max(map(abs, result.values()), default=0) <= TOLERANCE,
            "differences": result}


def numeric_nodes(graph, predicate):
    result = {}
    for node in relevant_nodes(graph, predicate):
        neg, pred, product = parse_literal(node["label"])
        key = neg + product
        numbers = tuple(float(x) for x in node.get("attributes", [])) + tuple(float(x) for x in node.get("deltaAttributes", []))
        result.setdefault(key, []).append(numbers)
    return {k: sorted(v) for k, v in result.items()}


def node_difference(left, right):
    if set(left) != set(right) or any(len(left[k]) != len(right[k]) for k in left):
        return {"same_node_multiplicities": False, "all_within_tolerance": False}
    maximum = max((abs(a - b) for key in left for lv, rv in zip(left[key], right[key])
                   for a, b in zip(lv, rv)), default=0)
    return {"same_node_multiplicities": True, "max_absolute_difference": maximum,
            "all_within_tolerance": maximum <= TOLERANCE}


def weighted(scores, weights):
    rows = normalized_multicriteria_ranking(scores, weights, names)
    return list(rows), {r["entity_id"]: r["score"] for r in rows}


def main():
    independent_scores = {}
    independent_graphs = {}
    runs = {}
    evidence = {}
    for aspect in aspects:
        graph, info = calculate(f"programas_por_aspecto/{aspect}.txt", f"aislado_{aspect}")
        independent_graphs[aspect] = graph
        independent_scores[aspect], evidence[f"aislado_{aspect}"] = mapped(graph, "recomendar")
        runs[f"aislado_{aspect}"] = info
    union, runs["union_terminales"] = calculate("programa_unico_terminales_independientes.txt", "union_terminales")
    full, runs["global"] = calculate("programa_completo_confianza_global.txt", "global")
    vector, runs["vector"] = calculate("programa_unico_vector_aspectos.txt", "vector")
    union_scores = {}
    vector_scores = {}
    per_aspect = {}
    intermediate_equivalence = {}
    for aspect in aspects:
        terminal = meta["components"][aspect]["terminal_predicate"]
        union_scores[aspect], evidence[f"union_{aspect}"] = mapped(union, terminal)
        vector_scores[aspect], evidence[f"vector_{aspect}"] = mapped(vector, f"{aspect}Bueno")
        full_aspect, evidence[f"global_aspecto_{aspect}"] = mapped(full, f"{aspect}Bueno")
        isolated_aspect, evidence[f"aislado_aspecto_{aspect}"] = mapped(independent_graphs[aspect], f"{aspect}Bueno")
        per_aspect[aspect] = {
            "selected_scores": difference(independent_scores[aspect], union_scores[aspect]),
            "all_positive_and_negative_terminal_mu_delta": node_difference(
                numeric_nodes(independent_graphs[aspect], "recomendar"), numeric_nodes(union, terminal)),
            "both_have_unique_terminal_literals": not evidence[f"aislado_{aspect}"]["multiple_nodes_same_literal"]
                  and not evidence[f"union_{aspect}"]["multiple_nodes_same_literal"],
        }
        intermediate_equivalence[aspect] = {
            "full_vs_vector": difference(full_aspect, vector_scores[aspect]),
            "full_vs_isolated": difference(full_aspect, isolated_aspect),
            "vector_mu_delta_vs_full": node_difference(numeric_nodes(vector, f"{aspect}Bueno"), numeric_nodes(full, f"{aspect}Bueno")),
        }
    global_scores, evidence["global_recomendar"] = mapped(full, "recomendar")
    profiles = {"neutral": {a: 1.0 for a in aspects},
                "mixto": {a: [0.0, 0.33, 0.67, 1.0][i % 4] for i, a in enumerate(aspects)},
                "todos_cero": {a: 0.0 for a in aspects}}
    profiles.update({f"solo_{a}": {b: float(a == b) for b in aspects} for a in aspects})
    rankings = {}
    for name, weights in profiles.items():
        original, original_scores = weighted(independent_scores, weights)
        single, single_scores = weighted(union_scores, weights)
        intermediary, intermediary_scores = weighted(vector_scores, weights)
        rankings[name] = {
            "weights": weights,
            "union_vs_independent": difference(original_scores, single_scores),
            "identical_order": [r["entity_id"] for r in original] == [r["entity_id"] for r in single],
            "vector_vs_independent": difference(original_scores, intermediary_scores),
            "vector_identical_order": [r["entity_id"] for r in original] == [r["entity_id"] for r in intermediary],
            "independent_ranking": original, "union_ranking": single, "vector_ranking": intermediary,
        }
    baseline_saved = json.loads((ROOT / meta["saved_ranking"]).read_text(encoding="utf-8"))["neutral"]
    saved_scores = {r["product"]: r["score"] for r in baseline_saved}
    current_neutral = {r["entity_id"]: r["score"] for r in rankings["neutral"]["independent_ranking"]}
    output = {
        "endpoint": ENDPOINT, "tolerance": TOLERANCE,
        "scope": "Local calculator; historical frozen input; no production, DB or manuscript writes.",
        "runs": runs, "per_aspect_equivalence": per_aspect,
        "intermediate_nodes_equivalence": intermediate_equivalence,
        "rankings_by_profile": rankings,
        "new_independent_neutral_vs_saved": difference(current_neutral, saved_scores),
        "global_scalar_vs_current_neutral": difference(global_scores, current_neutral),
        "node_and_mapper_evidence": evidence,
        "all_union_terminal_nodes_equivalent": all(
            x["selected_scores"]["all_within_tolerance"] and x["selected_scores"]["same_present_products"]
            and x["all_positive_and_negative_terminal_mu_delta"]["all_within_tolerance"] for x in per_aspect.values()),
        "all_17_profiles_identical": all(x["identical_order"] and x["union_vs_independent"]["all_within_tolerance"] for x in rankings.values()),
    }
    (OUT / "comparacion_motor_local.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_union_terminal_nodes_equivalent": output["all_union_terminal_nodes_equivalent"],
                      "all_17_profiles_identical": output["all_17_profiles_identical"],
                      "saved_neutral_max_diff": output["new_independent_neutral_vs_saved"]["max_absolute_difference"],
                      "global_scalar_neutral_max_diff": output["global_scalar_vs_current_neutral"]["max_absolute_difference"],
                      "global_multiple_literals": len(evidence["global_recomendar"]["multiple_nodes_same_literal"]),
                      "global_mapper_selected_nonterminal": len(evidence["global_recomendar"]["selected_nonterminal_aggregation_nodes"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
