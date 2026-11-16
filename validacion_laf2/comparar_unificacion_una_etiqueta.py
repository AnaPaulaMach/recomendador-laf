"""Compara antes/ contra despues/ del cambio de LAF2 a una etiqueta.

Exige identidad: mismo orden de publicaciones y |delta puntaje| <= 1e-6.
Los campos de presentacion que el cambio si toca a proposito
(evaluator_version, label_count, score_projection) se informan aparte.

Uso: venv\Scripts\python.exe validacion_laf2\comparar_unificacion_una_etiqueta.py
"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent / "salidas" / "unificacion_una_etiqueta"
TOL = 1e-6


def main() -> int:
    antes = json.loads((BASE / "antes" / "ranking_laf2.json").read_text(encoding="utf-8"))
    despues = json.loads((BASE / "despues" / "ranking_laf2.json").read_text(encoding="utf-8"))
    problemas: list[str] = []
    comparadas = 0
    presentacion: set[str] = set()
    for product_id, perfiles in antes["productos"].items():
        for perfil, bloque in perfiles.items():
            if not isinstance(bloque, dict) or "ranking" not in bloque:
                continue
            otro = despues["productos"][product_id][perfil]
            a, b = bloque["ranking"], otro["ranking"]
            if bloque["condiciones_sin_evidencia"] != otro["condiciones_sin_evidencia"]:
                problemas.append(
                    f"{product_id}/{perfil}: condiciones sin evidencia "
                    f"{bloque['condiciones_sin_evidencia']} -> {otro['condiciones_sin_evidencia']}"
                )
            if bloque["condiciones_con_programa"] != otro["condiciones_con_programa"]:
                problemas.append(
                    f"{product_id}/{perfil}: condiciones con programa "
                    f"{bloque['condiciones_con_programa']} -> {otro['condiciones_con_programa']}"
                )
            if len(a) != len(b):
                problemas.append(f"{product_id}/{perfil}: {len(a)} publicaciones -> {len(b)}")
                continue
            for fila_a, fila_b in zip(a, b, strict=True):
                comparadas += 1
                if fila_a["entity_id"] != fila_b["entity_id"]:
                    problemas.append(
                        f"{product_id}/{perfil} puesto {fila_a['posicion']}: "
                        f"{fila_a['entity_id']} -> {fila_b['entity_id']}"
                    )
                    continue
                delta = abs(fila_a["final_score"] - fila_b["final_score"])
                if delta > TOL:
                    problemas.append(
                        f"{product_id}/{perfil} puesto {fila_a['posicion']} "
                        f"{fila_a['entity_id']}: {fila_a['final_score']:.6f} -> "
                        f"{fila_b['final_score']:.6f} (delta {delta:.2e})"
                    )
                if fila_a["status"] != fila_b["status"]:
                    problemas.append(
                        f"{product_id}/{perfil} {fila_a['entity_id']}: "
                        f"estado {fila_a['status']} -> {fila_b['status']}"
                    )
                ca = {c["aspect"]: c["laf_score"] for c in fila_a["contribuciones"]}
                cb = {c["aspect"]: c["laf_score"] for c in fila_b["contribuciones"]}
                if set(ca) != set(cb):
                    problemas.append(
                        f"{product_id}/{perfil} {fila_a['entity_id']}: "
                        f"condiciones activas {sorted(ca)} -> {sorted(cb)}"
                    )
                else:
                    for aspecto in ca:
                        if abs(ca[aspecto] - cb[aspecto]) > TOL:
                            problemas.append(
                                f"{product_id}/{perfil} {fila_a['entity_id']} [{aspecto}]: "
                                f"confianza LAF {ca[aspecto]:.6f} -> {cb[aspecto]:.6f}"
                            )
                for campo in ("label_count", "score_projection"):
                    if fila_a[campo] != fila_b[campo]:
                        presentacion.add(f"{campo}: {fila_a[campo]} -> {fila_b[campo]}")
            if bloque["evaluator_version"] != otro["evaluator_version"]:
                presentacion.add(
                    f"evaluator_version: {bloque['evaluator_version']} -> "
                    f"{otro['evaluator_version']}"
                )
    print(f"filas comparadas: {comparadas}")
    if presentacion:
        print("cambios de presentacion esperados:")
        for linea in sorted(presentacion):
            print("  ", linea)
    if problemas:
        print(f"NO IDENTICO: {len(problemas)} diferencias")
        for linea in problemas[:40]:
            print("  ", linea)
        return 1
    print("IDENTICO: mismo orden y |delta puntaje| <= 1e-6 en todas las filas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
