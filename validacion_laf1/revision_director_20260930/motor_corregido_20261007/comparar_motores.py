"""Compara el motor actual (8088, main de Javi) con la rama propagacion-delta-budan (8089)
sobre los 14 programas por aspecto guardados el 30/09/2026. Solo lectura sobre el proyecto."""
import json, re, glob, os, sys, urllib.request, math
from collections import defaultdict

BASE = r"validacion_laf1\revision_director_20260930\alternativa_programa_unico"
OUT = os.path.dirname(os.path.abspath(__file__))
ENGINES = {"actual_8088": "http://localhost:8088/api/graph", "delta_8089": "http://localhost:8089/api/graph"}
OPS = {"labels": [{"labelName": "confidence", "supportFunction": "X * Y",
                   "aggregationFunction": "X + Y - X * Y",
                   "conflictFunction": "max((X-Y)/max(1-Y,0.000000001),0)"}]}

def parse_program(path):
    facts, rules = [], []
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        s = line.strip()
        if not s or s.startswith("%"):
            continue
        m = re.match(r"^(~?\w+)\(X\)\s*:-\s*(.+?)\.\s*\{([\d.]+)\}$", s)
        if m:
            body = [b.strip().replace("(X)", "") for b in m.group(2).split(",")]
            rules.append({"headName": m.group(1), "bodyLiterals": body, "attributes": [m.group(3)],
                          "attributeIntervals": [None], "sourceKey": f"RULE|line:{n}"})
            continue
        m = re.match(r"^(~?\w+)\(([^)]+)\)\.\s*\{([\d.]+)\}$", s)
        if m:
            facts.append({"name": m.group(1), "argument": m.group(2), "attributes": [m.group(3)],
                          "attributeIntervals": [None], "sourceKey": f"FACT|{m.group(1)}|{m.group(2)}"})
    return {"facts": facts, "rules": rules, "explainabilityEnabled": False, "operations": OPS}

def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))

def terminal_delta(graph):
    out = {}
    for n in graph["nodes"]:
        if n["type"] != "FACT":
            continue
        m = re.match(r"^recomendar\((.+)\)$", n["label"])
        if m:
            out[m.group(1)] = float(n["deltaAttributes"][0])
    return out

def conf(x, y): return max((x - y) / max(1 - y, 1e-9), 0.0)

def manual_article(payload):
    """Recurrencia Def. 8 calculada a mano (cadena acíclica de 3 niveles)."""
    rules = {r["headName"]: (r["bodyLiterals"][0], float(r["attributes"][0])) for r in payload["rules"]}
    chain = ["recomendar"]
    while rules.get(chain[-1], (None,))[0] and rules[chain[-1]][0] not in chain:
        chain.append(rules[chain[-1]][0])
    chain = chain[::-1]
    negleaf = rules.get("~" + chain[1], (None,))[0]
    mu = {(f["name"], f["argument"]): float(f["attributes"][0]) for f in payload["facts"]}
    prods = sorted({a for (_, a) in mu})
    res = {}
    for p in prods:
        dp = mu.get((chain[0], p), 0.0); dn = mu.get((negleaf, p), 0.0) if negleaf else 0.0
        if (chain[0], p) not in mu:
            continue
        for lvl in chain[1:]:
            mp = dp * rules[lvl][1]; mn = dn * rules["~" + lvl][1] if ("~" + lvl) in rules else 0.0
            dp, dn = conf(mp, mn), conf(mn, mp)
        res[p] = dp
    return res

def spearman(a, b):
    keys = sorted(set(a) & set(b))
    if len(keys) < 2: return float("nan")
    ra = {k: i for i, k in enumerate(sorted(keys, key=lambda k: (-a[k], k)))}
    rb = {k: i for i, k in enumerate(sorted(keys, key=lambda k: (-b[k], k)))}
    n = len(keys); d2 = sum((ra[k] - rb[k]) ** 2 for k in keys)
    return 1 - 6 * d2 / (n * (n * n - 1))

results = {"aspectos": {}, "resumen": {}}
per_aspect = {e: {} for e in ENGINES}
lines = []
for path in sorted(glob.glob(os.path.join(BASE, "programas_por_aspecto", "*.txt"))):
    asp = os.path.splitext(os.path.basename(path))[0]
    payload = parse_program(path)
    outs = {e: terminal_delta(post(url, payload)) for e, url in ENGINES.items()}
    manual = manual_article(payload)
    for e in ENGINES: per_aspect[e][asp] = outs[e]
    prods = sorted(outs["actual_8088"])
    diff = [p for p in prods if abs(outs["actual_8088"][p] - outs["delta_8089"][p]) > 1e-9]
    maxd = max(abs(outs["actual_8088"][p] - outs["delta_8089"][p]) for p in prods)
    man_ok = all(abs(outs["delta_8089"][p] - manual.get(p, -1)) < 1e-9 for p in prods)
    r_old = sorted(prods, key=lambda p: (-outs["actual_8088"][p], p)); r_new = sorted(prods, key=lambda p: (-outs["delta_8089"][p], p))
    moved = sum(1 for i in range(len(prods)) if r_old[i] != r_new[i])
    rho = spearman(outs["actual_8088"], outs["delta_8089"])
    results["aspectos"][asp] = {"n": len(prods), "valores_distintos": len(diff), "max_dif": maxd, "posiciones_cambian": moved,
                               "spearman": rho, "nuevo_motor_igual_a_recurrencia_manual": man_ok,
                               "primero_actual": r_old[0], "primero_delta": r_new[0],
                               "valores": {p: {"actual": outs["actual_8088"][p], "delta": outs["delta_8089"][p], "manual": manual.get(p)} for p in prods}}
    lines.append(f"{asp:13s} n={len(prods):2d} distintos={len(diff):2d} max|dif|={maxd:.4f} posiciones={moved:2d} rho={rho:.3f} manual={'OK' if man_ok else 'DIFIERE'} 1ro: {r_old[0][:28]} -> {r_new[0][:28]}")

# ranking combinado: perfil neutro (pesos iguales en todos los aspectos) y «solo sabor»
def combined(engine, weights):
    score = defaultdict(float); den = sum(weights.values())
    prods = set().union(*(set(per_aspect[engine][a]) for a in weights))
    for p in prods:
        score[p] = sum(w * per_aspect[engine][a].get(p, 0.0) for a, w in weights.items()) / den
    return dict(score)
aspects = list(per_aspect["actual_8088"])
profiles = {"neutro (todos los aspectos, peso 1)": {a: 1.0 for a in aspects}, "solo sabor": {"sabor": 1.0}}
for name, w in profiles.items():
    old, new = combined("actual_8088", w), combined("delta_8089", w)
    r_old = sorted(old, key=lambda p: (-old[p], p)); r_new = sorted(new, key=lambda p: (-new[p], p))
    moved = sum(1 for i in range(len(r_old)) if r_old[i] != r_new[i])
    results["resumen"][name] = {"n": len(r_old), "posiciones_cambian": moved, "spearman": spearman(old, new),
                                "top3_actual": r_old[:3], "top3_delta": r_new[:3],
                                "ranking_actual": [(p, old[p]) for p in r_old], "ranking_delta": [(p, new[p]) for p in r_new]}
    lines.append(f"PERFIL {name}: n={len(r_old)} posiciones que cambian={moved} rho={spearman(old,new):.3f} top3 actual={[p[:22] for p in r_old[:3]]} top3 delta={[p[:22] for p in r_new[:3]]}")

json.dump(results, open(os.path.join(OUT, "comparacion_motores_20261007.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("\n".join(lines))
