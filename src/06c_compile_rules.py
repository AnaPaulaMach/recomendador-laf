"""
06c_compile_rules.py - Compila las decisiones del experto a alpha.

Este script CIERRA el bucle del rol experto (OE3):

    04/curaduria  ->  experto define aspectos/lexicon
    06a           ->  genera programas de prueba desde las estructuras de reglas
    06b           ->  el experto (asistido por LLM) revisa reglas y DECIDE
                      (aceptar / editar / rechazar) -> registro auditado
    06c (ESTE)    ->  COMPILA las decisiones aprobadas a alpha (confianza
                      estructural). En LAF 1 y LAF 2 beta queda neutral en las
                      reglas porque la preferencia proviene solo del usuario.
    06a           ->  se regenera el programa de prueba con las fuerzas nuevas.

Asi el experto NUNCA edita a mano el programa logico ni los numeros del
JSON: trabaja en 06b en terminos de reglas y el sistema los traduce a las
etiquetas formales que consume el razonador.

Que fuerzas se pueden compilar (las argumentativas):
  - aspecto  -> dimension        : aspects[i].confidence
  - aspecto(neg) -> dimension    : aspects[i].negative_confidence
  - dimension -> recomendar      : dimensions[d].recommend.confidence
  - dimension(neg) -> ~recomendar: dimensions[d].not_recommend.confidence
  - condicion compra -> compraBuena: LAF 2 .rule_confidence (solo alpha)
  - compraBuena -> recomendar: LAF 2 recommendation.confidence (solo alpha)

El nivel evidencia -> aspecto (resenaPositivaX -> aspectoBueno) NO se compila:
su confianza es una constante de fiabilidad del pipeline (0.85 en 08), no una
decision argumentativa del experto. Si una decision apunta a ese nivel, se
reporta como "no compilable" (no se escribe nada en silencio).

OPCIONAL (--allow-new): permite CREAR reglas nuevas cuando el experto aprueba
una sugerencia del LLM que agrupa un aspecto EXISTENTE en una dimension nueva
o ya existente. No inventa aspectos (eso es curaduria, paso 04) ni crea
dimensiones vacias. Por defecto esta APAGADO: sin el flag, 06c solo ajusta
fuerzas de reglas que ya existen.

Uso:
    # Compilar el registro auditado que deja 06b:
    python src/06c_compile_rules.py --domain cafe --review config/laf_rule_review_decisions.json --dry-run
    python src/06c_compile_rules.py --domain cafe --yes                # escribe

    # Permitir ademas crear reglas nuevas aprobadas por el experto:
    python src/06c_compile_rules.py --domain cafe --allow-new --dry-run

    # Ajustes directos (sin pasar por 09), utiles para probar o afinar a mano:
    python src/06c_compile_rules.py --domain cafe --dry-run \
        --set "recomendar(X) :- sensorialBueno(X) = 0.95; 1.0"
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"
DOMAINS_DIR = CONFIG_DIR / "domains"
DEFAULT_REVIEW = CONFIG_DIR / "laf_rule_review_decisions.json"
LAF2_RULES_PATH = CONFIG_DIR / "laf2_rule_structure.json"

# Decisiones del experto (de 06b) que SI se compilan al programa.
APPLY_DECISIONS = {"aceptar", "editar"}

# Fuerzas por defecto para una regla recien creada (el experto las afina despues).
DEFAULT_NEW_CONF = 0.80
DEFAULT_NEW_PREF = 1.00


# --------------------------------------------------------------------------- #
# Utilidades de atomos (mismas convenciones que 08 / 09)
# --------------------------------------------------------------------------- #
def atom_part(value: Any) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9_]", "_", ascii_value)).strip("_").lower()


def parse_term(term: str) -> tuple[bool, str]:
    """Devuelve (es_negado, functor_normalizado). '~sensorialBueno(X)' -> (True,'sensorialbueno')."""
    term = str(term or "").strip()
    neg = term.startswith("~")
    if neg:
        term = term[1:].strip()
    functor = term.split("(", 1)[0].strip()
    return neg, atom_part(functor)


def strip_annotation(rule: str) -> tuple[str, float | None, float | None]:
    """Separa 'head :- body. {a; b}' en (regla_sin_anotacion, a, b)."""
    rule = str(rule or "").strip()
    match = re.search(r"\{\s*([^;{}]+);\s*([^{}]+)\}\s*$", rule)
    conf = pref = None
    if match:
        conf = as_float(match.group(1))
        pref = as_float(match.group(2))
        rule = rule[: match.start()].strip()
    rule = rule.rstrip(".").strip()
    return rule, conf, pref


def split_rule(stmt: str) -> tuple[str, str]:
    if ":-" not in stmt:
        return stmt.strip(), ""
    head, body = stmt.split(":-", 1)
    return head.strip(), body.strip()


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# --------------------------------------------------------------------------- #
# Config del dominio
# --------------------------------------------------------------------------- #
def domain_config_path(domain_key: str) -> Path:
    return DOMAINS_DIR / f"{domain_key}.json"


def load_config(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_config(path: Path, config: dict[str, Any]) -> Path:
    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return backup


def aspect_atom_map(config: dict[str, Any]) -> dict[str, str]:
    """atom del aspecto -> clave real del aspecto (de quality_aspects/lexicon)."""
    keys = list((config.get("quality_aspects") or {}).keys())
    if not keys:
        keys = list(((config.get("lexicon") or {}).get("aspects") or {}).keys())
    return {atom_part(k): k for k in keys}


# --------------------------------------------------------------------------- #
# Slots editables de laf1_rule_structure
# --------------------------------------------------------------------------- #
class Slot:
    """Un lugar de LAF 1 donde se fija alpha y beta permanece neutral.

    - subkey None: `container` ES el dict destino (caso aspecto).
    - subkey no None: el destino es container[subkey], que se crea solo al
      escribir (para no ensuciar el config con recommend/not_recommend vacios).
    """

    def __init__(self, container: dict, subkey: str | None, conf_key: str, pref_key: str, label: str, level: str):
        self.container = container
        self.subkey = subkey
        self.conf_key = conf_key
        self.pref_key = pref_key
        self.label = label
        self.level = level

    def _target(self, create: bool = False) -> dict | None:
        if self.subkey is None:
            return self.container
        if self.subkey not in self.container:
            if not create:
                return None
            self.container[self.subkey] = {}
        return self.container[self.subkey]

    def current(self) -> tuple[Any, Any]:
        target = self._target(create=False)
        if target is None:
            return None, None
        return target.get(self.conf_key), target.get(self.pref_key)

    def apply(self, conf: float | None, pref: float | None) -> tuple[Any, Any, Any, Any]:
        old_c, old_p = self.current()
        target = self._target(create=True)
        if conf is not None:
            target[self.conf_key] = round(clamp01(conf), 2)
        target[self.pref_key] = 1.0
        return old_c, old_p, target.get(self.conf_key), target.get(self.pref_key)


class ConfidenceOnlySlot:
    """Slot LAF 2: compila alpha; beta siempre proviene del usuario en 09."""

    def __init__(self, target: dict, conf_key: str, label: str, level: str):
        self.target = target
        self.conf_key = conf_key
        self.label = label
        self.level = level

    def current(self) -> tuple[Any, None]:
        return self.target.get(self.conf_key), None

    def apply(self, conf: float | None, pref: float | None) -> tuple[Any, None, Any, None]:
        old_c, _ = self.current()
        if conf is not None:
            self.target[self.conf_key] = round(clamp01(conf), 2)
        return old_c, None, self.target.get(self.conf_key), None


def register_aspect_slots(index: dict, dim_key: str, dim_functor: str, rule: dict, aspect: str) -> None:
    asp_functor = f"{atom_part(aspect)}bueno"
    index[(False, dim_functor, False, asp_functor)] = Slot(
        rule, None, "confidence", "preference", f"{aspect} -> {dim_key}", "aspecto->dimension")
    index[(True, dim_functor, True, asp_functor)] = Slot(
        rule, None, "negative_confidence", "negative_preference",
        f"~{aspect} -> ~{dim_key}", "aspecto(neg)->dimension")


def register_dimension_slots(index: dict, dim_key: str, dim: dict) -> None:
    dim_functor = f"{atom_part(dim_key)}bueno"
    index[(False, "recomendar", False, dim_functor)] = Slot(
        dim, "recommend", "confidence", "preference", f"{dim_key} -> recomendar", "dimension->recomendar")
    index[(True, "recomendar", True, dim_functor)] = Slot(
        dim, "not_recommend", "confidence", "preference", f"~{dim_key} -> ~recomendar", "dimension->~recomendar")
    for item in dim.get("aspects", []):
        rule = {"aspect": item} if isinstance(item, str) else item
        aspect = rule.get("aspect")
        if aspect:
            register_aspect_slots(index, dim_key, dim_functor, rule, aspect)


def build_slot_index(structure: dict) -> dict[tuple[bool, str, bool, str], Any]:
    index: dict[tuple[bool, str, bool, str], Any] = {}
    for dim_key, dim in (structure.get("dimensions") or {}).items():
        register_dimension_slots(index, dim_key, dim)
    return index


def register_laf2_slots(index: dict, structure: dict) -> None:
    """Registra las reglas compartidas de compra editables por el experto."""
    recommendation = structure.get("recommendation") or {}
    body = atom_part(recommendation.get("body_predicate", "compraBuena"))
    head = atom_part(recommendation.get("head_predicate", "recomendar"))
    index[(False, head, False, body)] = ConfidenceOnlySlot(
        recommendation,
        "confidence",
        f"{body} -> {head}",
        "LAF2 compra->recomendar",
    )
    for key, condition in (structure.get("conditions") or {}).items():
        predicate = atom_part(condition.get("fact_predicate", ""))
        if predicate:
            index[(False, body, False, predicate)] = ConfidenceOnlySlot(
                condition,
                "rule_confidence",
                f"{key} -> {body}",
                "LAF2 condicion->compra",
            )


# --------------------------------------------------------------------------- #
# Fuente de decisiones
# --------------------------------------------------------------------------- #
def adjustments_from_review(review_path: Path) -> list[dict[str, Any]]:
    """Lee el registro auditado de 06b y devuelve ajustes."""
    if not review_path.exists():
        return []
    data = load_config(review_path)
    rows = data.get("decisions", data if isinstance(data, list) else [])
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        decision = str(row.get("decision_experta") or "").strip().lower()
        if decision not in APPLY_DECISIONS:
            continue
        rule = str(row.get("regla_propuesta") or "").strip() or str(row.get("regla_actual") or "").strip()
        if not rule:
            continue
        out.append({
            "rule": rule,
            "conf": as_float(row.get("confianza_propuesta")),
            "pref": as_float(row.get("preferencia_propuesta")),
            "motivo": str(row.get("motivo") or "").strip() or None,
            "origen": f"06b[{decision}] {row.get('rule_id') or f'fila {i}'}",
        })
    return out


def adjustments_from_set(set_args: list[str]) -> list[dict[str, Any]]:
    """Ajustes directos: 'head :- body = conf; pref' o 'head :- body. {conf; pref}'."""
    out: list[dict[str, Any]] = []
    for raw in set_args or []:
        text = raw.strip()
        conf = pref = None
        if "=" in text and "{" not in text:
            rule_part, _, weights = text.rpartition("=")
            nums = re.split(r"[;,]", weights.strip())
            conf = as_float(nums[0]) if len(nums) >= 1 else None
            pref = as_float(nums[1]) if len(nums) >= 2 else None
            text = rule_part.strip()
        out.append({"rule": text, "conf": conf, "pref": pref, "motivo": None, "origen": "--set"})
    return out


# --------------------------------------------------------------------------- #
# Resolucion y creacion
# --------------------------------------------------------------------------- #
def resolve_adjustment(adj: dict[str, Any], index: dict) -> dict[str, Any]:
    """Resuelve un ajuste contra el indice de slots. No muta todavia."""
    clean, ann_conf, ann_pref = strip_annotation(adj["rule"])
    head, body = split_rule(clean)
    base = {"regla": clean, "origen": adj["origen"], "motivo": adj.get("motivo")}
    if not body:
        return {"status": "no_regla", "detalle": "no es una regla (head :- body)", **base}

    h_neg, h_atom = parse_term(head)
    b_neg, b_atom = parse_term(body)
    conf = adj["conf"] if adj["conf"] is not None else ann_conf
    pref = adj["pref"] if adj["pref"] is not None else ann_pref
    parsed = {"h_neg": h_neg, "h_atom": h_atom, "b_neg": b_neg, "b_atom": b_atom,
              "conf": conf, "pref": pref, **base}

    slot = index.get((h_neg, h_atom, b_neg, b_atom))
    if slot is None:
        if b_atom.startswith("resenapositiva") or b_atom.startswith("resenanegativa"):
            return {"status": "no_compilable",
                    "detalle": "nivel evidencia->aspecto: confianza constante del pipeline (0.85), no editable por regla",
                    **parsed}
        return {"status": "sin_slot",
                "detalle": f"no hay regla '{h_atom}' <- '{b_atom}' en laf1_rule_structure", **parsed}
    if conf is None and pref is not None:
        return {"status": "no_compilable",
                "detalle": "beta estructural es neutral (1.0); la preferencia se define con los sliders del usuario",
                "slot": slot, **parsed}
    if conf is None:
        return {"status": "sin_valores", "detalle": "la decision no trae confianza ni preferencia",
                "slot": slot, **parsed}
    return {"status": "ok", "slot": slot, **parsed}


def try_create_slot(structure: dict, index: dict, aspect_atoms: dict[str, str], res: dict) -> tuple[Slot | None, str]:
    """Crea una regla aspecto->dimension (pos o neg). Solo con --allow-new.

    Reglas: el aspecto debe existir (curaduria); no se crean dimensiones vacias;
    la clave de dimension no puede colisionar con un aspecto (rompe 08).
    """
    h_atom, b_atom = res["h_atom"], res["b_atom"]
    if h_atom == "recomendar":
        return None, "no creo dimensiones vacias: primero asignale un aspecto (dimBueno :- aspectoBueno)"
    if not h_atom.endswith("bueno") or not b_atom.endswith("bueno"):
        return None, "no reconozco la forma de la regla para crearla"

    dim_base = h_atom[: -len("bueno")]
    asp_base = b_atom[: -len("bueno")]
    if not dim_base or not asp_base:
        return None, "nombres de dimension/aspecto vacios"

    aspect_key = aspect_atoms.get(asp_base)
    if aspect_key is None:
        return None, f"'{asp_base}' no es un aspecto conocido; agregalo primero en la curaduria (04)"
    if dim_base in aspect_atoms:
        return None, f"la dimension '{dim_base}' colisiona con un aspecto; elegi otro nombre"

    dimensions = structure.setdefault("dimensions", {})
    dim_key = next((k for k in dimensions if atom_part(k) == dim_base), None)
    created_dim = False
    if dim_key is None:
        dim_key = dim_base
        dimensions[dim_key] = {
            "label": dim_base.replace("_", " ").capitalize(),
            "aspects": [],
            "recommend": {"confidence": DEFAULT_NEW_CONF, "preference": DEFAULT_NEW_PREF},
        }
        register_dimension_slots(index, dim_key, dimensions[dim_key])
        created_dim = True

    dim = dimensions[dim_key]
    dim_functor = f"{atom_part(dim_key)}bueno"
    existing = next((r for r in dim.get("aspects", [])
                     if (r.get("aspect") if isinstance(r, dict) else r) == aspect_key), None)
    if existing is None or isinstance(existing, str):
        rule = {"aspect": aspect_key}
        if res.get("motivo"):
            rule["_note"] = res["motivo"]
        aspects = dim.setdefault("aspects", [])
        if isinstance(existing, str):
            aspects[aspects.index(existing)] = rule
        else:
            aspects.append(rule)
        register_aspect_slots(index, dim_key, dim_functor, rule, aspect_key)

    key = (res["h_neg"], dim_functor, res["b_neg"], f"{atom_part(aspect_key)}bueno")
    action = "dimension+aspecto NUEVOS" if created_dim else f"aspecto agregado a '{dim_key}'"
    return index.get(key), action


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compila alpha experta; beta estructural queda neutral y la preferencia viene del usuario.")
    parser.add_argument("--domain", default="cafe", help="clave del dominio (config/domains/<domain>.json)")
    parser.add_argument("--review", default=str(DEFAULT_REVIEW), help="registro auditado de 06b")
    parser.add_argument("--set", dest="sets", action="append", default=[],
                        help="ajuste directo 'head :- body = conf; pref' (repetible)")
    parser.add_argument("--no-review", action="store_true", help="ignorar el registro de 06b (solo --set)")
    parser.add_argument("--allow-new", action="store_true",
                        help="OPCIONAL: permitir crear reglas nuevas (aspecto existente -> dimension)")
    parser.add_argument("--dry-run", action="store_true", help="previsualizar sin escribir")
    parser.add_argument("--yes", action="store_true", help="escribir sin confirmar")
    args = parser.parse_args()

    cfg_path = domain_config_path(args.domain)
    if not cfg_path.exists():
        print(f"ERROR: no existe {cfg_path}", file=sys.stderr)
        return 1
    config = load_config(cfg_path)
    structure = config.get("laf1_rule_structure") or {}
    if not LAF2_RULES_PATH.exists():
        print(f"ERROR: no existe {LAF2_RULES_PATH}", file=sys.stderr)
        return 1
    laf2_structure = load_config(LAF2_RULES_PATH)
    original_config = copy.deepcopy(config)
    original_laf2 = copy.deepcopy(laf2_structure)

    adjustments: list[dict[str, Any]] = []
    if not args.no_review:
        adjustments += adjustments_from_review(Path(args.review))
    adjustments += adjustments_from_set(args.sets)

    if not adjustments:
        print("No hay decisiones para compilar.")
        print(f"  - registro 06b: {args.review} (vacio o sin filas aceptar/editar)")
        print(f"  - --set: {len(args.sets)} ajuste(s)")
        return 0

    index = build_slot_index(structure) if structure.get("mode") == "hierarchical" else {}
    register_laf2_slots(index, laf2_structure)
    aspect_atoms = aspect_atom_map(config)

    print(f"Dominio: {args.domain}  ({cfg_path.name})   allow-new={args.allow_new}")
    print(f"Decisiones a evaluar: {len(adjustments)}")
    print("=" * 72)

    changed = 0
    created = 0
    skipped: list[dict[str, Any]] = []
    for adj in adjustments:
        res = resolve_adjustment(adj, index)

        if res["status"] == "sin_slot" and args.allow_new:
            can_create_laf1 = (
                res.get("h_atom") != "recomendar"
                and str(res.get("h_atom", "")).endswith("bueno")
                and str(res.get("b_atom", "")).endswith("bueno")
            )
            if not can_create_laf1:
                res["detalle"] = "--allow-new solo crea reglas aspectoBueno -> dimensionBueno de LAF 1"
                skipped.append(res)
                continue
            if structure.get("mode") != "hierarchical":
                structure = {
                    "mode": "hierarchical",
                    "beta_semantics": "user_only_structural_neutral",
                    "unassigned_aspect_policy": "direct",
                    "direct_recommendation_confidence": 0.75,
                    "dimensions": {},
                }
                config["laf1_rule_structure"] = structure
            slot, msg = try_create_slot(structure, index, aspect_atoms, res)
            if slot is None:
                res["detalle"] = f"no se pudo crear: {msg}"
                skipped.append(res)
                continue
            if res["conf"] is None:
                res["conf"] = DEFAULT_NEW_CONF
            res["pref"] = DEFAULT_NEW_PREF
            res["slot"] = slot
            res["status"] = "ok"
            res["_created"] = msg
            created += 1

        if res["status"] != "ok":
            skipped.append(res)
            continue

        old_c, old_p, new_c, new_p = res["slot"].apply(res["conf"], res["pref"])
        was_changed = (old_c, old_p) != (new_c, new_p)
        changed += 1 if was_changed else 0
        flag = "+" if res.get("_created") else ("*" if was_changed else " ")
        tag = f"CREADA ({res['_created']})" if res.get("_created") else res["slot"].level
        print(f" [{flag}] {tag:34s} {res['slot'].label}")
        print(f"       {res['origen']}" + (f"   motivo: {res['motivo']}" if res.get("motivo") else ""))
        print(f"       conf {old_c} -> {new_c}   pref {old_p} -> {new_p}")

    if skipped:
        print("-" * 72)
        print(f"No compiladas: {len(skipped)}")
        for s in skipped:
            print(f"   [{s['status']}] {s.get('regla', s.get('rule', ''))}")
            print(f"       {s['detalle']}  ({s['origen']})")

    print("=" * 72)
    print(f"Reglas modificadas: {changed}   nuevas: {created}")

    if changed == 0 and created == 0:
        print("Nada que escribir.")
        return 0

    if args.dry_run:
        print("DRY-RUN: no se escribio el config. Quita --dry-run para aplicar.")
        return 0

    if not args.yes:
        print("Agrega --yes para escribir los cambios en el config (o --dry-run para solo ver).")
        return 0

    stamp = datetime.now().isoformat(timespec="seconds") + f" ({changed} modificadas, {created} nuevas)"
    if config != original_config:
        structure.setdefault("_compiled_at", []).append(stamp)
        backup = save_config(cfg_path, config)
        print(f"Escrito LAF 1: {cfg_path}")
        print(f"Backup: {backup}")
    if laf2_structure != original_laf2:
        laf2_structure.setdefault("_compiled_at", []).append(stamp)
        backup = save_config(LAF2_RULES_PATH, laf2_structure)
        print(f"Escrito LAF 2 compartido: {LAF2_RULES_PATH}")
        print(f"Backup: {backup}")
    print("PROXIMO PASO: regenera los programas de auditoria con 06a y revisa otra vez.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
