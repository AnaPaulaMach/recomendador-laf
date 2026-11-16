# -*- coding: utf-8 -*-
"""Experimento 2: figura de intervalos de puesto por producto.

Dibuja el SVG a mano siguiendo docs/figuras/ESTILO_FIGURAS.md (Arial, viewBox
760-900, tinta #22292f, linea #5e6871, un solo acento #294f6d, cuerpos >= 14).
El PNG a escala 3 lo produce el script del proyecto, docs/figuras/exportar_figura.ps1.

Uso:  python validacion_robustez/figura_intervalos.py [--perfil neutro]
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SALIDAS = HERE / "robustez_8089"
FIGURAS = HERE / "robustez_8089"

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TINTA = "#22292f"
LINEA = "#5e6871"
TENUE = "#788189"
BORDE = "#d7dbde"
ACENTO = "#294f6d"

# Nombres cortos, derivados a mano de products_raw.name (auditable y estable).
CORTOS = {
    "MLM26912881": "Blasón Espresso Robusto 1 kg",
    "MLM41148521": "Blasón Gourmet Espresso 400 g",
    "MLM19543513": "La Parroquia Puro 1 kg",
    "MLM25263480": "Blasón Gourmet Americano 1 kg",
    "MLM19544520": "Capuccino Moka MM 1,8 kg",
    "MLM16250244": "Taster's Choice Caramel 100 g",
    "MLM19566313": "Capuccino Vainilla MM 1,8 kg",
    "MLM16207894": "Nescafé Reserva Xiapan 180 g",
    "MLM20999002": "Nescafé Clásico Professional 1 kg",
    "MLM19663240": "Nescafé Clásico frasco 200 g",
    "MLM16250253": "Nescafé Decaf 170 g",
    "MLM23633481": "Nescafé Clásico ICE 170 g",
    "MLM20075768": "Nescafé Clásico bolsa 400 g",
    "MLM16207863": "Nescafé Café de Olla 170 g",
    "MLM16250252": "Nescafé Clásico sin gluten 400 g",
    "MLM27068249": "Juan Valdez Tripack 95 g",
    "MLM43007251": "Blasón Arábico 900 g",
    "MLM16207890": "Nescafé Reserva Verarica 180 g",
}


def coma(x: float) -> str:
    """Separador decimal castellano, como el resto del documento."""
    return f"{x:.3f}".replace(".", ",")


def id_producto(entity_id: str) -> str:
    return entity_id.split("_")[0].upper()


def construir_svg(puestos: dict, perfil: str, replicas: int) -> str:
    """El metodo y el significado de los simbolos van al caption del manuscrito, no a la
    imagen: por eso ya no se dibujan el parrafo del pie ni la columna de amplitud."""
    ancho = 880
    x0, x1 = 336, 844          # zona de puestos; se gano el ancho de la columna «amp.»
    y0 = 118                   # primera fila
    alto_fila = 30
    n = len(puestos)
    alto = y0 + n * alto_fila + 24

    def x(puesto: float) -> float:
        return x0 + (puesto - 1) * (x1 - x0) / (n - 1)

    s = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ancho} {alto}" '
        f'width="{ancho}" height="{alto}" font-family="Arial, Helvetica, sans-serif">',
        f'<rect width="{ancho}" height="{alto}" fill="#ffffff"/>',
        f'<text x="24" y="38" font-size="17" font-weight="bold" fill="{TINTA}">'
        f'Intervalo de puesto de cada producto en {replicas} remuestreos del corpus</text>',
        f'<text x="24" y="60" font-size="14" fill="{LINEA}">Perfil {escape(perfil)}</text>',
        f'<text x="24" y="{y0 - 30}" font-size="14" fill="{LINEA}">Puesto</text>',
    ]
    for p in range(1, n + 1):
        s.append(
            f'<text x="{x(p):.1f}" y="{y0 - 30}" font-size="14" fill="{LINEA}" '
            f'text-anchor="middle">{p}</text>'
        )
        s.append(
            f'<line x1="{x(p):.1f}" y1="{y0 - 22}" x2="{x(p):.1f}" '
            f'y2="{y0 + n * alto_fila - 14}" stroke="{BORDE}" stroke-width="1"/>'
        )

    for i, fila in enumerate(puestos):
        y = y0 + i * alto_fila
        etiqueta = CORTOS.get(fila["product_id"], fila["product_id"])
        s.append(
            f'<text x="316" y="{y + 5}" font-size="14" fill="{TINTA}" '
            f'text-anchor="end">{escape(etiqueta)}</text>'
        )
        xa, xb = x(fila["p5"]), x(fila["p95"])
        if xb - xa < 3:
            xa, xb = xa - 1.5, xb + 1.5
        s.append(
            f'<line x1="{xa:.1f}" y1="{y}" x2="{xb:.1f}" y2="{y}" '
            f'stroke="{LINEA}" stroke-width="7" stroke-linecap="round"/>'
        )
        xm = x(fila["mediana"])
        s.append(
            f'<line x1="{xm:.1f}" y1="{y - 6}" x2="{xm:.1f}" y2="{y + 6}" '
            f'stroke="#ffffff" stroke-width="1.6"/>'
        )
        xo = x(fila["puesto_original"])
        s.append(
            f'<path d="M {xo:.1f} {y - 6.5} L {xo + 6:.1f} {y} L {xo:.1f} {y + 6.5} '
            f'L {xo - 6:.1f} {y} Z" fill="{ACENTO}"/>'
        )

    s.append("</svg>")
    return "\n".join(s)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--perfil", default="neutro", choices=["neutro", "solo_sabor"])
    ap.add_argument("--resumen", default=None)
    args = ap.parse_args()

    # Los `*_pre_fila13.json` son de la configuracion anterior y quedan EXCLUIDOS: con
    # `reverse=True` ordenaban antes que el definitivo ('_' > '.') y la figura se venia
    # generando con ellos. Comprobado el 2026-09-17 contra la tabla 10.1 de RESULTADOS.md.
    ruta = Path(args.resumen) if args.resumen else next(
        iter(sorted((p for p in SALIDAS.glob("resumen_*.json")
                     if "pre_fila13" not in p.name), reverse=True)), None
    )
    if ruta is None:
        raise SystemExit("ERROR: falta el resumen. Corré bootstrap_ranking.py primero.")
    datos = json.load(open(ruta, encoding="utf-8"))
    perfil = datos["perfiles"][args.perfil]

    filas = [
        {"product_id": id_producto(entity), **valores}
        for entity, valores in perfil["puestos"].items()
    ]
    filas.sort(key=lambda f: f["puesto_original"])
    faltantes = [f["product_id"] for f in filas if f["product_id"] not in CORTOS]
    if faltantes:
        raise SystemExit(f"ERROR: faltan nombres cortos para {faltantes}")

    # Las estadisticas de rho ya no se dibujan: van al caption. Se imprimen igual para
    # que quien corra el script pueda cotejarlas con la tabla 10.1 de RESULTADOS.md.
    print("  ρ media %s  mínimo %s  p5 %s  p95 %s"
          % (coma(perfil["rho_media"]), coma(perfil["rho_min"]),
             coma(perfil["rho_p5"]), coma(perfil["rho_p95"])))
    print("  fuente: %s" % ruta.name)
    svg = construir_svg(filas, args.perfil, datos["replicas"])

    nombre = f"figura_robustez_intervalos_puesto_{args.perfil}"
    FIGURAS.mkdir(parents=True, exist_ok=True)
    destino_svg = FIGURAS / f"{nombre}.svg"
    destino_svg.write_text(svg, encoding="utf-8")
    print(f"  SVG -> {destino_svg.relative_to(ROOT)}")

    # PNG a escala 3 con el exportador del proyecto
    alto = svg.split('height="')[1].split('"')[0]
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if ps:
        resultado = subprocess.run(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(FIGURAS / "exportar_figura.ps1"),
             "-Nombre", nombre, "-Ancho", "880", "-Alto", str(int(float(alto)) + 20)],
            capture_output=True, text=True,
        )
        png = FIGURAS / f"{nombre}.png"
        if png.exists():
            print(f"  PNG -> {png.relative_to(ROOT)} (escala 3)")
            shutil.copy(png, SALIDAS / png.name)
            print(f"  copia -> {(SALIDAS / png.name).relative_to(ROOT)}")
        else:
            print(f"  AVISO: no se generó el PNG. {resultado.stdout}{resultado.stderr}")
    else:
        print("  AVISO: no hay powershell en PATH; exportá el PNG a mano con "
              f"docs/figuras/exportar_figura.ps1 {nombre} 880 {alto}")


if __name__ == "__main__":
    main()
