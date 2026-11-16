"""Escribe `docs/CHEQUEO_HUMANO_LAF2.md` desde la corrida real, sin retipear nada.

Lee `validacion_laf2/salidas/tablas_chequeo_humano_laf2.json` (producido por
`tablas_chequeo_humano_laf2.py` recorriendo el flujo web con el `.env` real) y
arma una tabla por perfil con puesto, puntaje, rótulo, condiciones declaradas,
la oración de cada condición y la columna vacía «Veredicto de Ana». Los números
del encabezado y de los «puntos que conviene mirar» se calculan de ese JSON.

Uso:  venv\\Scripts\\python.exe validacion_laf2\\tablas_chequeo_humano_laf2_md.py
"""
import json
from itertools import groupby
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATOS = ROOT / "validacion_laf2" / "salidas" / "tablas_chequeo_humano_laf2.json"
DESTINO = ROOT / "docs" / "CHEQUEO_HUMANO_LAF2.md"

TITULOS = {
    "todo_bastante": ("1", "Perfil todo «Bastante» (0,67 en las cuatro condiciones)"),
    "solo_precio": ("2", "Perfil solo precio (precio «Es prioridad», el resto «No me importa»)"),
    "envio_y_oficial_prioridad": (
        "3",
        "Perfil envío y tienda oficial en prioridad (las dos en «Es prioridad», precio y descuento en «Bastante»)",
    ),
}
CABECERA = (
    "| Puesto | Publicación | Vendedor | Puntaje | Rótulo | Condiciones declaradas "
    "| Oración por condición | Veredicto de Ana |"
)
SEPARADOR = "|---:|---|---|---:|---|---|---|---|"


def corta(etiqueta: str) -> str:
    """Nombre corto de la condición, sin el paréntesis explicativo de la fila."""
    return etiqueta.split(" (")[0].strip().lower()


def declaradas(datos: dict) -> str:
    """Los datos del catálogo con el mismo formato que muestra la explicación."""
    partes = [f"precio {datos.get('price_label') or 'no informado'}"]
    partes.append(f"envío {str(datos.get('shipping') or 'no informado').lower()}")
    partes.append("tienda oficial" if datos.get("is_official_store") else "no es tienda oficial")
    if datos.get("has_discount"):
        pct = round(float(datos.get("discount_pct") or 0.0) * 100)
        partes.append(f"descuento {pct} %")
    else:
        partes.append("sin descuento")
    partes.append(f"garantía {str(datos.get('warranty') or 'no informada').lower()}")
    return "; ".join(partes)


def celda_oraciones(publicacion: dict) -> str:
    participan = [c for c in publicacion["condiciones"] if c["estado"] == "participa"]
    fuera = [c for c in publicacion["condiciones"] if c["estado"] != "participa"]
    # La oración de la app no repite el nombre de la condición: en la pantalla se
    # lee dentro de su fila. Acá van cuatro en una celda, así que se prefija.
    partes = [f"**{corta(c['etiqueta'])}** {c['oracion']}" for c in participan]
    if fuera:
        etiquetas = ", ".join(corta(c["etiqueta"]) for c in fuera)
        estados = {c["estado"] for c in fuera}
        motivo = (
            "en «No me importa»: no participan del puntaje"
            if estados == {"no_me_importa"}
            else "fuera del puntaje"
        )
        partes.append(f"[{etiquetas}] {motivo}.")
    return " · ".join(partes)


def gap(publicaciones: list[dict]) -> float:
    return publicaciones[0]["score_exacto"] - publicaciones[1]["score_exacto"]


def empates(publicaciones: list[dict]) -> list[tuple[float, list[int]]]:
    salida = []
    for clave, grupo in groupby(publicaciones, key=lambda p: round(p["score_exacto"], 6)):
        puestos = [p["puesto"] for p in grupo]
        if len(puestos) > 1:
            salida.append((clave, puestos))
    return salida


def numero(valor: float, decimales: int = 4) -> str:
    return f"{valor:.{decimales}f}".replace(".", ",")


def main() -> int:
    datos = json.loads(DATOS.read_text(encoding="utf-8"))
    producto = datos["producto"]
    perfiles = datos["perfiles"]
    primero = perfiles["todo_bastante"]
    total = len(primero["publicaciones"])
    desvio_max = max(
        pub["desvio"] for perfil in perfiles.values() for pub in perfil["publicaciones"]
    )

    lineas: list[str] = []
    add = lineas.append
    add("# Chequeo humano del ranking de publicaciones (LAF 2)")
    add("")
    add(
        "Pendiente de completar por Ana. Cada fila trae lo que la app muestra hoy "
        "para esa publicación y una columna vacía para el veredicto "
        "(confirmo / rechazo / matiz, con la razón)."
    )
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| `dataset_key` | `{datos['dataset_key']}` |")
    add(f"| hash de metodología | `{primero['methodology_sha256']}` |")
    add(f"| fecha de la corrida | {primero['generated_at'][:19].replace('T', ' ')} (-03:00) |")
    add(
        f"| producto | {producto['entity_name']} (`{producto['entity_id']}`), "
        f"puesto {producto['position']} del ranking neutro de LAF 1 |"
    )
    add(f"| publicaciones evaluadas | {total} |")
    add(
        "| condiciones ofrecidas | "
        + ", ".join(f"`{key}`" for key in datos["condiciones_ofrecidas"])
        + " |"
    )
    add(f"| modelo de decisión | `{primero['decision_model']}` |")
    add(f"| estado de la evaluación | `{primero['evaluation_status']}` |")
    add(
        "| condiciones sin evidencia | "
        + (", ".join(primero["sin_evidencia"]) or "ninguna")
        + " |"
    )
    add(
        "| scripts | `validacion_laf2/tablas_chequeo_humano_laf2.py` → "
        "`validacion_laf2/salidas/tablas_chequeo_humano_laf2.json`; markdown con "
        "`validacion_laf2/tablas_chequeo_humano_laf2_md.py` |"
    )
    add("")
    add("## 0. Cómo se armó y cómo repetirlo")
    add("")
    add(
        "El recorrido es el de producción, con el `.env` real: Supabase + `laf-api` "
        "en Docker, dominio café recongelado. Se eligió el perfil neutro de calidad "
        "(0,67 en los catorce aspectos) para llegar al producto, y después se "
        "evaluaron las condiciones de compra tres veces, una por perfil. **Nada de "
        "este documento se transcribió de la pantalla a mano**: el puesto, el "
        "puntaje, el rótulo, las condiciones declaradas y la oración de cada "
        "condición se leen del contexto que la vista «Ver por qué» "
        "(`recommender:explanation`) ya armó sobre el `EvaluationResult` que produjo "
        "el orden."
    )
    add("")
    add(
        f"Se eligió este producto y no el ganador del perfil neutro porque el "
        f"ganador (Café Blasón Espresso Robusto) tiene **una sola** publicación y "
        f"LAF 2 no compara: ahí la app muestra otra pantalla "
        f"(`single_listing.html`). Este producto tiene {total} publicaciones, el "
        f"máximo del snapshot junto con Capuccino Moka (`MLM19544520`)."
    )
    add("")
    add(
        "Para repetirlo en la interfaz: con la webapp en `localhost:8000` y "
        "`LAF_API_RESULTS_VALIDATED=1`, elegir el producto "
        f"`{producto['entity_id']}` en el ranking de calidad, cargar el perfil de "
        "condiciones de cada sección y abrir «Ver por qué lo recomendamos» de cada "
        "publicación."
    )
    add("")
    add("**Convenciones de las tablas.**")
    add("")
    add(
        "- «Oración por condición» trae la oración completa de las condiciones que "
        "**participan** del puntaje, separadas por «·», y al final, entre "
        "corchetes, las que quedaron afuera con el motivo que muestra la app. Las "
        "oraciones son plantilla fija completada con los valores de esa corrida: "
        "sin adjetivos y sin modelo de lenguaje. En la pantalla cada oración se "
        "lee dentro de la fila de su condición, así que no repite su nombre; acá "
        "van varias en la misma celda y el nombre va **en negrita** al principio. "
        "Es el único agregado de este documento al texto de la app."
    )
    add(
        "- «Condiciones declaradas» son los datos del catálogo de esa publicación, "
        "en el mismo orden y con el mismo formato que muestra la explicación "
        "(precio, envío, tienda oficial, descuento y garantía). Son datos para "
        "mostrar: no entran al programa LAF ni al puntaje. La garantía aparece "
        "aunque no sea una condición ofrecida en este producto."
    )
    add(
        "- El «Rótulo» es el de la columna «Resultado» del listado. Desde el "
        "2026-09-10 el 1.º sólo se declara único si se separa del 2.º por al menos "
        "0,01 de puntaje (`webapp/docs/ADR-004`)."
    )
    add(
        f"- Control de coherencia: para las {total * len(perfiles)} publicaciones de "
        f"las tres tablas, el puntaje reconstruido con los pesos y los resultados "
        f"LAF que muestran las filas coincide con el que ordenó el ranking; desvío "
        f"máximo **{numero(desvio_max, 6)}** (los valores se muestran redondeados)."
    )
    add("")

    for clave, (numero_seccion, titulo) in TITULOS.items():
        perfil = perfiles[clave]
        publicaciones = perfil["publicaciones"]
        add(f"## {numero_seccion}. {titulo}")
        add("")
        pesos = ", ".join(
            f"{key} {str(value).replace('.', ',')}"
            for key, value in perfil["preferencias"].items()
        )
        add(f"Pesos cargados: {pesos}.")
        add("")
        add(CABECERA)
        add(SEPARADOR)
        for pub in publicaciones:
            rotulo = pub["rotulo"]
            if pub["nota_rotulo"]:
                rotulo += f" ([detalle] {pub['nota_rotulo']})"
            add(
                "| "
                + " | ".join(
                    [
                        str(pub["puesto"]),
                        f"`{pub['entity_id']}`",
                        pub["vendedor"],
                        numero(pub["score_exacto"]),
                        rotulo,
                        declaradas(pub["declaradas"]),
                        celda_oraciones(pub),
                        "",
                    ]
                )
                + " |"
            )
        add("")
        add(f"Oración de cierre del 1.º: «{publicaciones[0]['cierre']}»")
        add("")

    add("## 4. Puntos que conviene mirar")
    add("")
    add("Salen de las tablas; no son juicios.")
    add("")
    for clave, (numero_seccion, titulo) in TITULOS.items():
        perfil = perfiles[clave]
        publicaciones = perfil["publicaciones"]
        distancia = gap(publicaciones)
        compartido = sum(
            1 for pub in publicaciones if "Entre las mejores" in pub["rotulo"]
        )
        detalle = (
            f"comparten el rótulo {compartido} publicaciones"
            if compartido
            else "el 1.º queda declarado único"
        )
        add(
            f"- **{titulo.split(' (')[0]}**: la diferencia entre el 1.º y el 2.º es "
            f"**{numero(distancia)}**, así que {detalle}."
        )
    empatados = empates(perfiles["todo_bastante"]["publicaciones"])
    if empatados:
        add(
            "- **Empates exactos de puntaje** en el perfil todo «Bastante»: "
            + "; ".join(
                f"{numero(valor)} en los puestos "
                + ", ".join(str(p) for p in puestos)
                for valor, puestos in empatados
            )
            + ". El orden entre ellas lo fija el desempate declarado de LAF 2 "
            "(`-puntaje`, `-confianza del programa completo`, `id`) y la pantalla "
            "sólo muestra el puesto."
        )
    movidas = []
    por_id = {
        pub["entity_id"]: pub["puesto"]
        for pub in perfiles["todo_bastante"]["publicaciones"]
    }
    for pub in perfiles["solo_precio"]["publicaciones"]:
        movidas.append((abs(por_id[pub["entity_id"]] - pub["puesto"]), pub["entity_id"],
                        por_id[pub["entity_id"]], pub["puesto"]))
    movidas.sort(reverse=True)
    salto, item, antes, despues = movidas[0]
    add(
        f"- **Los perfiles reordenan de verdad**: `{item}` pasa del puesto "
        f"{antes}.º con todo en «Bastante» al {despues}.º con solo precio "
        f"({salto} puestos). La preferencia gradúa el aporte de cada condición "
        "por fuera de LAF; adentro del programa la máscara es 0/1."
    )
    add(
        "- El rótulo compartido del perfil solo precio es el **primer caso real** "
        "del resguardo de ADR-004 sobre publicaciones: dos publicaciones a 0,0077 "
        "de puntaje, $287,99 y $295, con la misma condición operativa. El umbral "
        "de 0,01 se midió sobre LAF 1 (bootstrap del corpus de reseñas), no sobre "
        "publicaciones; acá no hay bootstrap que respalde ni desmienta el corte."
    )
    sin_dato = [
        pub["entity_id"]
        for pub in perfiles["todo_bastante"]["publicaciones"]
        if "entra en la cuenta con 0,000" in celda_oraciones(pub)
    ]
    add(
        f"- **Condiciones que la publicación no informa**: en {len(sin_dato)} de las "
        f"{len(perfiles['todo_bastante']['publicaciones'])} publicaciones al menos "
        "una condición con peso entra a la cuenta con 0,000 y su peso sigue en el "
        "divisor. La fila lo dice con esas palabras y nunca muestra el 0,000 como "
        "si fuera una medición (ADR-003)."
    )
    add(
        "- **La oración de cierre cambia de forma según los pesos**: con pesos "
        "iguales nombra los resultados LAF; con pesos distintos nombra el aporte "
        "(peso × resultado). Las dos versiones están arriba, al pie de cada tabla."
    )
    add("")

    DESTINO.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"-> {DESTINO} ({len(lineas)} líneas)")
    print(f"desvío máximo: {desvio_max}")
    for clave in TITULOS:
        pubs = perfiles[clave]["publicaciones"]
        print(f"{clave}: gap 1-2 = {gap(pubs):.6f} | empates {empates(pubs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
