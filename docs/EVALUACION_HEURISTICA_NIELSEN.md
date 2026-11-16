# Evaluación heurística de la interfaz (Nielsen) — plantilla

Fecha de la evaluación: 2026-09-10 y 2026-09-11 (más cinco hallazgos reclasificados del chequeo del
2026-09-03) · Evaluadora: Ana Paula Machado (única evaluadora; también autora) ·
Configuración de la app: commit `0e5bae8` más la pasada de correcciones del 2026-09-11 (ADR-006) ·
hash de metodología `735f9b0c…` · snapshot `mlm_mlm194329_20260528_142014`.

**Método.** Inspección heurística según Nielsen (1994): una evaluadora recorre los flujos principales
de la interfaz y registra cada violación de las diez heurísticas con su severidad. No participan
usuarios (el Alcance del TFG lo excluye). Cumple la actividad «pruebas de usabilidad básica» de la
Etapa 7 de la propuesta en la única forma compatible con ese alcance.

**Escala de severidad (Nielsen).** 0 = no es un problema · 1 = cosmético · 2 = menor (baja prioridad) ·
3 = mayor (alta prioridad) · 4 = catastrófico (impide completar la tarea).

**Referencias.**

1. J. Nielsen, «Heuristic evaluation», en J. Nielsen y R. L. Mack (eds.), *Usability
   Inspection Methods*, John Wiley & Sons, Nueva York, 1994, pp. 25–62. ISBN 0-471-01877-5
   (ISBN-13 978-0-471-01877-3). El libro tiene xxiv + 413 páginas.
   **Verificado el 2026-09-11** en Open Library (editorial, lugar, año, ISBN, extensión).
   **Queda una duda:** el registro del capítulo en la ACM Digital Library indica **pp. 25–64**, no
   25–62. Las dos formas circulan en la literatura. Antes de la entrega hay que abrir un ejemplar o
   el registro de la Library of Congress y fijar una; mientras tanto se deja 25–62, que es la forma
   más citada.
2. J. Nielsen, «10 Usability Heuristics for User Interface Design», Nielsen Norman Group, 1994
   (actualizado 2024), https://www.nngroup.com/articles/ten-usability-heuristics/ (consultado ____).
3. Sobre la cantidad de evaluadores de la sección 5, donde la cifra **ya no se usa**: J. Nielsen, «The Theory Behind Heuristic Evaluations»,
   Nielsen Norman Group, https://www.nngroup.com/articles/how-to-conduct-a-heuristic-evaluation/theory-heuristic-evaluations/
   (consultado 2026-09-11). Texto literal: «Averaged over six of my projects, single evaluators found
   only 35 percent of the usability problems in the interfaces». **Atención:** la página no cita una
   publicación para esa cifra, y el artículo «How to Conduct a Heuristic Evaluation» **no la
   menciona**: sólo recomienda de tres a cinco evaluadores. Atribuir el 35 % a «Nielsen 1994» sin
   más es arriesgado en un tribunal; conviene citar esta página, o verificar la cifra en el capítulo
   de 1994 antes de atribuírsela.

**Falta cargar en Zotero.**

## 1. Flujos evaluados

| # | Flujo | Pantallas (plantillas) | Origen en la propuesta |
|---|---|---|---|
| F1 | Consultar recomendaciones | `home.html` (categoría) → `quality.html` (preferencias) → `product_ranking.html` | Etapa 7: «consulta de recomendaciones» |
| F2 | Pedir explicaciones | `product_ranking.html` (tarjeta) → `product_detail.html` («Ver por qué») → grafo por aspecto (`argument_graph.html`) | Etapa 7: «solicitud de explicaciones» |
| F3 | Explorar el corpus | fragmentos de reseñas por aspecto dentro de «Ver por qué» | Etapa 7: «exploración del corpus de reseñas» (forma acotada) |
| F4 | Elegir dónde comprar | `listing_ranking.html` → `explanation.html` (LAF2) → grafo por condición | Introducción del TFG: segundo nivel de «opciones de compra» |
| F5 | Auditar | `traceability.html`, descarga de programas, `methodology.html` | OE6/OE7: acceso a la estructura argumentativa |

Nota sobre F1: el recorrido publicado arranca en `home.html`, que hace POST a la vista `start`; esa
vista sólo redirige y **nunca renderiza `start.html`**, que quedó sin uso en la interfaz.

## 2. Las diez heurísticas

| H | Nombre | Pregunta guía para esta app |
|---|---|---|
| H1 | Visibilidad del estado del sistema | ¿El usuario sabe siempre en qué paso está, qué perfil rige y por qué un producto está donde está? |
| H2 | Correspondencia entre el sistema y el mundo real | ¿Los rótulos hablan de café y reseñas, no de LAF, α, dMP? ¿«menciones» dice lo que cuenta? |
| H3 | Control y libertad del usuario | ¿Se puede volver, cambiar preferencias, deshacer la elección de producto? |
| H4 | Consistencia y estándares | ¿La tarjeta, «Ver por qué» y el grafo dicen lo mismo con las mismas palabras y umbrales? |
| H5 | Prevención de errores | ¿Se impide consultar con todo en «No me importa» o con presupuesto imposible? |
| H6 | Reconocer antes que recordar | ¿Las preferencias elegidas se ven en el ranking sin volver atrás? |
| H7 | Flexibilidad y eficiencia | ¿Un usuario repetido puede ir rápido (atajos, perfiles guardados, HTMX sin recarga)? |
| H8 | Diseño estético y minimalista | ¿Cada pantalla muestra sólo lo que decide? |
| H9 | Reconocer, diagnosticar y recuperarse de errores | ¿Qué pasa si laf-api no responde o el snapshot no tiene datos? |
| H10 | Ayuda y documentación | ¿La página de metodología y las leyendas del grafo alcanzan para entender sin la tesis? |

### 2.1 De dónde salen las preguntas

Nielsen (1994) **no aporta un cuestionario**: las diez heurísticas son principios de una línea cada
uno. Toda pregunta concreta que se le hizo a la pantalla es, por lo tanto, una **operacionalización**
de esos principios para esta app, y no una cita. Para que el instrumento sea auditable, cada pregunta
del recorrido se derivó de una de estas tres fuentes, o de su combinación:

- **(A) La columna «pregunta guía para esta app»** de la sección 2, que ya existía en esta plantilla
  antes de la evaluación. Es la traducción de cada heurística al dominio del recomendador.
- **(B) La lectura del código y las plantillas.** La mayoría de las preguntas no son abiertas: son
  «confirmá en pantalla esto que aparece en el archivo tal». Eso las hace verificables y evita
  inventar hallazgos.
- **(C) Los documentos del propio proyecto**: `CHEQUEO_HUMANO_LAF1.md` (E1–E5, X1), los ADR 003, 004
  y 005 —en particular sus secciones «Lo que queda afuera», que declaran deudas conocidas—, y
  `webapp/AGENTS.md`, que fija reglas de interfaz que se pueden verificar como cualquier heurística.

| Pregunta del recorrido (resumida) | H | De dónde salió |
|---|---|---|
| ¿Se nota que empezó un recorrido de cuatro pasos? | H1 | A + B: `flow_steps.html` se incluye desde el paso 1 y no en `home.html` |
| ¿La tarjeta dice por qué ese producto está ahí? | H1 | A + C: E2/U02, que es exactamente ese reclamo |
| Texto literal del rótulo del 1.º y del 2.º | H1 | C: ADR-004 y los puntajes del bootstrap de `validacion_robustez/RESULTADOS.md` |
| ¿«N menciones en reseñas» se entiende? | H2 | C: E1/U01 |
| ¿Aparecen líneas de aspectos con peso 0? | H4 | C: E4/U04 y la función `is_active_argument` |
| ¿Se ve en el ranking qué preferencias elegiste? | H6 | A + B: `top_preferences` se calcula en la vista y ninguna plantilla lo usa |
| ¿Cambia algo al mover los radios del paso 1? | H7/H9 | B: `quality.html` apunta a `#preference-summary`, que no existe en esa pantalla |
| ¿Se puede enviar todo en «No me importa»? | H5 | A (la pregunta guía de H5 lo nombra) + B: el formulario no lo valida |
| ¿La leyenda del grafo dice `dMP` y `CA`? | H2 | A: la pregunta guía de H2 nombra `dMP` como ejemplo de lo que no debería aparecer |
| ¿Se entiende «Resultado LAF»? | H2 | A + C: `AGENTS.md`, que manda la explicación académica a segundo plano |
| ¿El detalle llama «opiniones» al mismo número? | H4 | C: U01 llevado a otra pantalla |
| ¿Ves algún paréntesis con números? | H4 | C: ADR-004, «Lo que queda afuera» (la ecuación instanciada ya no está en el árbol) |
| ¿Cuántos fragmentos en contra aparecen? | H2 | B: `graph.js` dice «una en contra» y el repositorio usa `per_polarity = 2` |
| ¿Algún fragmento queda cortado a mitad de oración? | H4 | C: X1 del chequeo humano |
| ¿Qué pasa si el grafo no carga? | H9 | A + B: el texto «¿motor LAF disponible?» está en `graph.js` |
| Copiame las condiciones del paso 3 | H2/H4 | C: ADR-003 y `SUFICIENCIA_DATOS.md` §3 y §6 (cuotas y factura no operativas) |
| Presupuesto mínimo mayor que el máximo | H5/H9 | A (la pregunta guía de H5 nombra el «presupuesto imposible») + B: `PurchasePreferencesForm.clean` |
| ¿Qué mensaje aparece sin publicaciones? | H9 | A + B: los dos estados vacíos de `listing_ranking.html` |
| «Puesto» contra «Opción» en el medallón | H4 | B: comparación de las dos plantillas de detalle |
| ¿«Cómo funciona» sigue ofreciendo el grafo completo? | H10 | C: U07 / ADR-005 contra el texto de `methodology.html` |
| ¿Qué trae cada botón de descarga? | H4 | C: U07 (el mismo artefacto retirado) + medición de los dos endpoints |
| ¿Se entiende el hash y el identificador de corrida? | H2 | A: la pregunta guía de H2 llevada a la capa de auditoría |

Las preguntas de caso límite (laf-api apagado, snapshot sin datos, presupuesto imposible) salen
directamente de la pregunta guía de H9, que las nombra.

**Advertencia de método.** Muchas preguntas se formularon diciéndole antes a la evaluadora qué
esperaba encontrar el asistente («esperado: los cuatro primeros comparten rótulo»). Eso hace las
respuestas más rápidas y verificables, pero **condiciona el juicio**: la evaluadora confirma o
corrige una hipótesis en vez de mirar sin expectativa. Es la misma desviación declarada en la
sección 0 de `CHEQUEO_HUMANO_LAF1.md`, y hay que leer los juicios de esta tabla con esa advertencia
puesta. Los hallazgos que **no** dependen de ese sesgo son los que se verificaron en código o
midiendo (U11, U12, U22, U30, U32, U40): esos no requieren tomar la palabra de nadie.

## 3. Hallazgos

Un hallazgo por fila. Los cinco primeros son las discrepancias del chequeo humano del 2026-09-03
(`docs/CHEQUEO_HUMANO_LAF1.md`), reclasificadas como hallazgos de usabilidad: el método ya operó antes
de nombrarse.

| ID | Flujo | Pantalla | Heurística | Hallazgo | Sev. | Estado | Fecha |
|---|---|---|---|---|---:|---|---|
| U01 (=E1) | F1 | tarjeta del ranking | H2 | «N opiniones» contaba menciones por hecho, no reseñas (Blasón: 670 vs 1.062 reseñas) | 3 | corregido: rótulo «menciones en reseñas» | 2026-09-03 |
| U02 (=E2) | F2 | «Ver por qué» | H1 | Arábico 17.º con «Sin objeciones» en sus 8 aspectos y 0 en contra; los 6 aspectes ausentes figuraban como «resultado LAF 0,000»: sin razón legible del puesto | 3 | corregido: «sin información en las reseñas», nota «Pocas menciones» y «Información sobre N características» | 2026-09-03 |
| U03 (=E3) | F1/F2 | tarjeta y «Ver por qué» | H4 | Una crítica de 1 de 47 menciones se mostraba al mismo nivel visual que el elogio mayoritario y cambiaba el estado a «Discutido» | 3 | corregido: umbral 2 menciones y 5 % del aspecto; marginales sólo en detalle, marcadas | 2026-09-03 |
| U04 (=E4) | F1 | tarjeta | H4 | Se mostraban críticas de aspectos que el usuario puso en «No me importa» | 3 | corregido: aspectos con peso 0 no generan líneas | 2026-09-03 |
| U05 (=E5) | F2 | «Ver por qué» | H1 | Estado «No se sostiene» sin texto que lo explique | 2 | corregido con la oración por aspecto (2026-09-10) | 2026-09-03 |
| U06 | F1 | tarjeta | H1 | «Mejor opción para vos» con diferencia de 0,0009 con el 2.º (invisible con dos decimales) | 3 | corregido: resguardo del rótulo, umbral 0,01 (ADR-004) | 2026-09-10 |
| U07 | F5 | trazabilidad | H4 | «Grafo completo por producto» mostraba el programa combinado, que no interviene en el ranking | 3 | corregido: se retiraron la sección, la vista `product_graph`, su ruta y la plantilla (ADR-005) | 2026-09-10 |
| U08 | F1 | tarjeta | H1 | `support_note` («Pocas menciones en reseñas») se calcula y no se renderiza | 2 | corregido (2026-09-11, ADR-006): la nota se renderiza bajo el título de la tarjeta (`.ranking-support-note`) | 2026-09-10 |
| U09 | F2 | «Ver por qué» | H2 | Oración de cierre «Les diste el mismo peso a todas» en perfiles de un solo aspecto. Texto literal en pantalla con solo sabor: «Quedó 1º de 18. La única característica que elegiste es sabor, con 0,64. Les diste el mismo peso a todas, así que el orden lo decidieron esos resultados»: dos oraciones seguidas que se contradicen | 2 | corregido (2026-09-11, ADR-006): con una sola característica elegida la oración de cierre dice «El orden lo decidió ese único resultado»; la frase sobre el peso igual sólo aparece con dos o más | 2026-09-10 |
| U10 | F1 | ranking sin ranking (sin preferencias o con laf-api caído) | H8 | La pantalla sigue ofreciendo «Información técnica de esta recomendación» aunque no hay recomendación. Se da en los dos estados vacíos: con todo en «No me importa» y con el evaluador sin responder | 1 | corregido (2026-09-11, ADR-006): el bloque técnico ya no aparece en el recorrido sin ranking; en modo auditoría se conserva y su título dice «de esta corrida», no «de esta recomendación» | 2026-09-10 |
| U11 | F1 | paso 1, preferencias | H9 | Cada cambio de radio produce un error de consola (`htmx:targetError, #preference-summary`): el destino del resumen en vivo no existe en esa pantalla. Sin efecto visible y sin tráfico de red (htmx aborta el pedido) | 1 | corregido (2026-09-11, ADR-006): se quitaron los cuatro atributos `hx-*` del `<form>` de `quality.html`; sin errores de consola | 2026-09-10 |
| U12 | F1 | tarjeta del ranking | H4 | El aspecto `tamano` se muestra como «Tamano» (clave técnica, sin ñ) mientras el paso 1 lo llama «Tamaño / cantidad»: dos escrituras del mismo aspecto y una incorrecta. Es el único de los 14 aspectos ausente de `ASPECT_LABELS` | 2 | corregido (2026-09-11, ADR-006): `"tamano": "tamaño"` en `ASPECT_LABELS`, con una prueba que exige una etiqueta legible para cada aspecto | 2026-09-10 |
| U13 | F1 | paso 1 → ranking | H5 | Se puede enviar el paso 1 con los 14 aspectos en «No me importa»: el botón está habilitado y el problema se informa después, en el ranking | 1 | aceptado: decisión de diseño de la autora (el recorrido le enseña al usuario que algo le tiene que importar); la prevención sería apagar el botón hasta que haya un aspecto con peso | 2026-09-10 |
| A01 | F1 | tarjeta del ranking | H1 | Acierto: el puesto se explica desde el dato visible («me doy cuenta porque tiene menos menciones y características»); es el arreglo de U02 funcionando en uso | 0 | verificado en pantalla | 2026-09-10 |
| A02 | F1 | ranking (neutro y solo sabor) | H1 | Acierto: el resguardo del rótulo se comporta como lo define ADR-004 en pantalla: con el neutro el 1.º conserva «Mejor opción para vos» (diferencia 0,0133) y con solo sabor los cuatro a menos de 0,01 comparten «Entre las mejores opciones para vos» | 0 | verificado en pantalla | 2026-09-10 |
| A03 | F1 | tarjeta del ranking | H2 | Acierto: «N menciones en reseñas» se lee como distinto de «N reseñas»; el rótulo de U01 alcanza | 0 | verificado en pantalla | 2026-09-10 |
| A04 | F1 | tarjeta y «Ver por qué» | H4 | Acierto: los números de la tarjeta coinciden con los del detalle para el mismo producto, y los aspectos con peso 0 no generan líneas (U03 y U04 verificados en pantalla, no sólo en test) | 0 | verificado en pantalla | 2026-09-10 |
| A05 | F1 | ranking → paso 1 | H3 | Acierto: «Cambiar preferencias» vuelve con los radios como quedaron; con «Buscar otro producto» alcanza para deshacer | 0 | verificado en pantalla | 2026-09-10 |
| A06 | F1 | ranking sin preferencias | H9 | Acierto: el estado vacío nombra la causa («cuando todo queda en No me importa, no hay con qué comparar») y da la salida en un clic | 0 | verificado en pantalla | 2026-09-10 |
| A07 | F1 | paso 1, «Cómo usamos lo que elegiste» | H10 | Acierto: alcanza para entender qué hace la app con los radios sin ir a «Cómo funciona» | 0 | verificado en pantalla | 2026-09-10 |
| U14 | F2 | grafo por característica | H2 | La leyenda y el grafo usan `dMP` y `CA`, notación del formalismo, en la pantalla del usuario final | 1 | pendiente: la leyenda al pie explica qué hace cada uno, así que el usuario no queda trabado; queda como deuda de vocabulario | 2026-09-11 |
| U15 | F2/F4 | detalle de producto y de publicación | H2 | «Resultado LAF» aparece tres veces (nota del listado, encabezado de la columna y valor de cada fila) sin definirse en la pantalla | 2 | pendiente: separar por capa — el rótulo visible nombra el respaldo de las reseñas y la sigla LAF queda en el bloque técnico plegado, la descarga de programas y trazabilidad, que es donde miran director y tribunal (`AGENTS.md`: la explicación académica es contenido secundario) | 2026-09-11 |
| U16 | F2 | tarjeta ↔ detalle | H4 | El mismo número se llama «menciones en reseñas» en la tarjeta y «Opiniones sobre sus características» en el detalle y en el paso 1 del recorrido: regresión parcial de U01 sobre el mismo valor | 2 | corregido (2026-09-11, ADR-006): «menciones en reseñas» en el detalle y en el paso 1 del recorrido explicativo, el mismo rótulo que la tarjeta | 2026-09-11 |
| U17 | F2/F4 | desglose de la suma | H1 | Las características sin menciones aportan «0,000» en la suma sin decir ahí que el 0 es por falta de menciones; el listado de arriba sí lo dice | 1 | pendiente: marcar esas filas en el desglose. Es la misma brecha que ADR-003 declara para publicaciones | 2026-09-11 |
| U18 | F2/F4 | nota al pie de la suma | H4 | La nota habla de «los números de adentro del paréntesis», pero la ecuación instanciada se quitó de la pantalla (ADR-004): el texto remite a un elemento que ya no existe | 2 | corregido (2026-09-11, ADR-006): se restituyó la ecuación instanciada en las dos pantallas y, en una segunda pasada, la nota pasó a decir «los números de adentro de los corchetes», que es lo que la ecuación usa; decía «paréntesis» y la cuenta escrita lleva corchetes | 2026-09-11 |
| U19 | F2 | barra lateral del detalle | H1 | «Elegir este producto» no nombra a dónde lleva: se entiende que hay que seguir, no que el paso siguiente son las condiciones de compra | 1 | corregido (2026-09-11, ADR-006): la bajada del botón nombra el paso siguiente («las condiciones de compra: precio, descuento, tienda oficial y envío») | 2026-09-11 |
| U20 | F2/F4 | barra lateral del detalle y paso 3 | H2 | El texto ofrece comparar «precios, cuotas, garantía y envío», pero cuotas es una condición que ninguna publicación del catálogo informa y que el paso 3 no muestra: la app promete una comparación que después no aparece. El paso 3 repite la promesa en «Cómo comparamos las opciones de compra», que nombra descuento, cuotas, garantía o envío gratuito cuando las condiciones reales de este catálogo son precio, descuento, tienda oficial y envío | 2 | corregido (2026-09-11, ADR-006): la app nombra sólo las condiciones operativas (precio, descuento, tienda oficial, envío). Garantía queda afuera de los textos: `SUFICIENCIA_DATOS.md` §5 la da por «casi muerta» (3–5 %), no por viva; sigue mostrándose como dato de la publicación donde el catálogo lo informa | 2026-09-11 |
| U21 | F1/F2 | ranking con laf-api caído | H9 | «Falta ejecutar el motor algebraico para obtener un ranking validado» se lee como un paso del método que todavía no corrió, no como un servicio que no responde: el usuario no puede saber que algo se cayó, no hay acción de reintento ni indicación de que sea temporal, y «motor algebraico» es jerga. Reconoce que no hay ranking, pero no puede diagnosticar ni recuperarse | 2 | corregido (2026-09-11, ADR-006): las dos pantallas dicen que el servicio de evaluación no respondió, sin «motor algebraico» ni «el programa 10» ni «LAF Studio», y ofrecen «Volver a intentar» al paso que reenvía las preferencias (es el paso que dispara la evaluación: recargar el ranking no la vuelve a correr) | 2026-09-11 |
| A08 | F2 | grafo por característica | H10 | Acierto: el grafo se entiende con su leyenda y los ejemplos, sin recurrir a la tesis, incluso con `dMP` y `CA` a la vista | 0 | verificado en pantalla | 2026-09-11 |
| A09 | F2 | listado de características | H5 | Acierto: una característica sin menciones no es clicleable, así que el panel nunca intenta cargar un grafo que no existe. Prevención real, lo contrario de U13 | 0 | verificado en pantalla | 2026-09-11 |
| A10 | F2 | oración por característica | H1 | Acierto: la oración agrega lo que la fila no dice («la conclusión no fue debilitada»); el cambio 2 de ADR-004 aporta información nueva y no sólo repite el conteo | 0 | verificado en pantalla | 2026-09-11 |
| A11 | F2 | detalle → ranking | H3 | Acierto: «Volver al ranking» no pierde el ranking ni el perfil | 0 | verificado en pantalla | 2026-09-11 |
| U22 | F3 | fragmentos de reseñas | H2 | La pantalla describe mal su propia regla: dice «hasta dos a favor y **una** en contra, si la hay», pero el repositorio usa `per_polarity = 2` para las dos polaridades y en pantalla aparecen dos y dos | 2 | corregido (2026-09-11, ADR-006): `renderExamples` dice «hasta dos de cada polaridad»; verificado contra `per_polarity = 2` del repositorio | 2026-09-11 |
| U23 | F3 | fragmentos de reseñas | H2 | «peso de la reseña 0,87» se entiende como a qué se refiere pero no cómo se calcula, y la pantalla no da forma de averiguarlo | 1 | pendiente: una línea o un enlace que diga de dónde sale el peso del testimonio (α) | 2026-09-11 |
| U24 | F3 | fragmentos de reseñas | H4 | «Cómo se mide la calidad de esta detección» no se ve como un enlace: es la única puerta a la calidad de la extracción y pasa desapercibida | 2 | corregido (2026-09-11, ADR-006): el enlace tiene color de acción, subrayado y peso propio dentro de la línea atenuada | 2026-09-11 |
| U25 | F3/F5 | trazabilidad, calidad de extracción | H10 | «Muestra anterior, independiente», «3.ª muestra, 30 reseñas» y «82,1 % de polaridad» se muestran sin explicar qué es una muestra ni por qué hay varias; el resto de la sección sí se entiende | 2 | corregido (2026-09-11, ADR-006): la bajada explica qué es una muestra y por qué hay varias (cada corrección obliga a medir de nuevo con reseñas no vistas); las cifras se rotulan «última muestra: la medición que vale» y «muestra anterior: da casi lo mismo» | 2026-09-11 |
| U26 | F3 | panel de característica | H8 | El panel acumula grafo, leyenda, oración, fragmentos y desglose de la suma: demasiado en una sola vista, aunque abrirlo sea voluntario | 1 | pendiente, decisión abierta: mover el desglose de la suma a trazabilidad. La evaluadora lo considera importante y no quiere perderlo | 2026-09-11 |
| U27 | F3 | panel de característica, grafo caído | H9 | «No se pudo cargar el grafo de este punto (¿motor LAF disponible?)»: le hace al usuario una pregunta técnica que no puede contestar, nombra un componente interno y no ofrece ninguna acción | 2 | corregido (2026-09-11, ADR-006): «No pudimos mostrar la explicación de este punto ahora» y un botón «Volver a intentar» que vuelve a pedir el grafo; sin pregunta técnica y sin nombrar componentes internos | 2026-09-11 |
| U28 | F3 | fragmentos de reseñas | H9 | Si la consulta de ejemplos falla, el bloque entero desaparece sin avisar: la característica queda sin fragmentos y nada distingue «no hay» de «no se pudo leer» | 1 | pendiente: distinguir los dos casos. Verificado en código (`_aspect_mention_examples` devuelve vacío ante cualquier error); no observado en pantalla | 2026-09-11 |
| A12 | F3 | fragmentos de reseñas | H2 | Acierto: se entiende que son ejemplos y no la lista completa, aun cuando la fila de arriba anuncia muchas más menciones | 0 | verificado en pantalla | 2026-09-11 |
| A13 | F3 | panel de característica | H1 | Acierto: al abrir otra característica el título del panel cambia y siempre se sabe cuál se está viendo | 0 | verificado en pantalla | 2026-09-11 |
| U29 | F4 | fila de publicación, paso 4 | H2 | Cada publicación se identifica como «Vendedor 272093102»: un id numérico crudo. Es el único rótulo que distingue una fila de otra en las 26, y por eso la lista se vuelve difícil de recorrer | 3 | corregido (2026-09-11, ADR-006): la fila se rotula «Publicación N · $precio» y el `item_id` queda como dato secundario. **No hay nombre de vendedor que mostrar**: verificado en Supabase el 2026-09-11, `items_raw` tiene `seller_id` y `seller_address` (ciudad/estado), y las 22 claves de `raw_json` no traen apodo ni nombre | 2026-09-11 |
| U30 | F4 | fila de publicación y detalle | H1 | Las 26 publicaciones enlazan al **mismo** destino genérico (`mercadolibre.com.mx/mas-vendidos/MLM194336`, la lista de más vendidos de la categoría) porque ninguna trae `permalink` en su metadata: el botón que cierra la tarea lleva a todos al mismo lado y no a la publicación elegida | 4 | corregido (2026-09-11, ADR-006), salida (b): el enlace se arma desde `item_id` en la capa de presentación (`marketplace_item_url`). **Supuesto verificado por la autora en el navegador el 2026-09-11** con MLM2107019722 y MLM2528199353: `articulo.mercadolibre.com.mx/MLM-<número>` resuelve y redirige a la publicación exacta (`?pdp_filters=item_id:<item_id>`). Es una dirección construida, no relevada: el supuesto queda escrito en el código y en ADR-006 | 2026-09-11 |
| U31 | F4 | fila de publicación, paso 4 | H1 | La fila muestra precio, garantía y envío, pero no descuento ni tienda oficial, que son las condiciones que deciden el orden: la 1.ª sale $426,55 y está por encima de una de $380, y la razón (tienda oficial + envío gratis) sólo aparece dentro de «Ver por qué» | 2 | pendiente: mostrar en la fila las condiciones que participan del puntaje | 2026-09-11 |
| U32 | F4 | paso 3, presupuesto | H9 | Con mínimo mayor que máximo el mensaje correcto sí se muestra y los valores se conservan, pero aparece a unos 350 px por encima de los campos, separado por el título del panel, y ninguno de los dos campos queda marcado: el error no se ve donde está el error | 2 | corregido (2026-09-11, ADR-006): el mensaje se renderiza dentro del panel del presupuesto, junto a los campos, y los dos quedan marcados (`.input-error` y `aria-invalid`) | 2026-09-11 |
| U33 | F4 | paso 4, sin publicaciones | H9 | Un presupuesto que no deja ninguna publicación y un perfil con todas las condiciones en «No me importa» producen el **mismo** mensaje: «No pudimos preparar las publicaciones. Revisá el presupuesto, los datos del catálogo y la configuración del generador». No nombra la causa real, no ofrece la salida obvia (ampliar el presupuesto) y le pide al usuario revisar el catálogo y el generador, que no puede tocar. Contrasta con el paso 2, que para el caso equivalente tiene un estado vacío que sí nombra la causa y da la salida (A06) | 3 | corregido (2026-09-11, ADR-006): dos estados vacíos con causa y acción propias, con el modelo del paso 2 (A06); el presupuesto que no deja nada nombra el rango y ofrece ampliarlo | 2026-09-11 |
| U34 | F4 | medallón del detalle | H4 | El mismo componente dice «Puesto» en publicaciones y «Opción» en productos | 1 | corregido (2026-09-11, ADR-006): «Opción» en las dos pantallas | 2026-09-11 |
| U35 | F4 | comparar lado a lado | H8 | La tabla agrega la fila «Lo mejor y lo que conviene mirar», con líneas «+» y «−»: el mismo componente que se retiró de la tarjeta de producto en la revisión de U03. La evaluadora lo sacaría | 1 | corregido (2026-09-11, ADR-006): se quitó la fila de `partials/listing_comparison.html` | 2026-09-11 |
| U36 | F4 | comparar lado a lado | H2 | La tabla tiene filas fijas «Factura» y «Cuotas», condiciones que ninguna publicación del catálogo informa: «Factura — No» afirma un hecho negativo donde lo cierto es «no informado» | 2 | corregido (2026-09-11, ADR-006): se quitaron las filas fijas Factura y Cuotas, y la ausencia de dato se muestra como «no informado», nunca como «No» | 2026-09-11 |
| A14 | F4 | explicación de publicación | H2 | Acierto: las condiciones sin dato dicen «sin información en la publicación» y no son clicleables; las que sí tienen dato abren su grafo. Verificado en la publicación 6.ª, con descuento y envío sin informar (ADR-003 cumplido en pantalla) | 0 | verificado en pantalla | 2026-09-11 |
| A15 | F4 | paso 3, panel lateral | H1 | Acierto: «Lo más importante para vos» se actualiza solo al mover los radios, sin recargar la página | 0 | verificado en pantalla | 2026-09-11 |
| A16 | F4 | grafo por condición | H10 | Acierto: se entiende mejor que el de producto porque el panel no carga además los fragmentos de reseñas | 0 | verificado en pantalla | 2026-09-11 |
| A17 | F4 | enlace a Mercado Libre | H3 | Acierto: abre pestaña nueva y el recorrido no se pierde | 0 | verificado en pantalla | 2026-09-11 |
| A18 | F4 | explicación de publicación | H1 | Acierto: la oración de cierre nombra el resultado más alto y el más bajo con sus valores y explica el puesto («El resultado LAF más alto es el de envío y tienda oficial (0,727) y el más bajo el de descuento (0,474)») | 0 | verificado en pantalla | 2026-09-11 |
| U37 | F5 | «Cómo funciona» | H10 | La página de ayuda describe dos cosas que ya no están: ofrece «el grafo completo de un producto» (retirado por U07 / ADR-005 justamente por no intervenir en el ranking) y dice que el puntaje «está escrito con sus valores reales en la pantalla del producto» (la ecuación instanciada se quitó en ADR-004; hoy hay tabla de la suma, no ecuación) | 2 | corregido (2026-09-11, ADR-006): se quitó la promesa del grafo completo (ahora nombra los programas por característica) y el paso 5 describe la tabla y la ecuación instanciada, ya restituida | 2026-09-11 |
| U38 | F5 | trazabilidad, operadores | H10 | Las tres fórmulas (`X × Y`, `X + Y − X × Y`, `(X − Y) ÷ (1 − Y)`) se muestran sin decir qué son X e Y | 1 | corregido (2026-09-11, ADR-006): una línea dice qué son X e Y en cada operador y que el resultado es otra confianza entre 0 y 1 | 2026-09-11 |
| U39 | F5 | trazabilidad, datos de la corrida | H2 | «Configuración congelada» (un hash largo) e «Identificador de corrida» se muestran sin decir para qué sirven: ni la autora puede explicar el hash leyéndolo en pantalla | 2 | corregido (2026-09-11, ADR-006): una línea por campo dice para qué sirve (nombrar la corrida y pedirla de nuevo; comparar dos corridas) | 2026-09-11 |
| U40 | F5 | trazabilidad, descargas | H4 | El botón principal, «Descargar respaldo completo», entrega el **programa combinado**, que no produce el ranking (el mismo artefacto que U07 retiró de la interfaz), y su encabezado se presenta como «PROGRAMA LAF 1 - RANKING DE PRODUCTOS». Los 14 programas por aspecto, que sí producen el orden, están en un enlace secundario. Medido el 2026-09-11: 33.265 bytes el combinado contra 34.205 los usados, tan parecidos que no se distinguen por tamaño, y la evaluadora los dio por idénticos | 3 | corregido (2026-09-11, ADR-006): la descarga principal son los programas que produjeron el ranking; el combinado baja a enlace secundario rotulado «Programa combinado (no interviene en el ranking; sólo referencia)» y su archivo abre con un encabezado que lo dice (agregado al servir la descarga: el generador está en `src/`, congelado) | 2026-09-11 |
| A19 | F5 | trazabilidad | H4 | Acierto: la pantalla declara el modelo real —confianza de LAF por característica combinada por los pesos del usuario— y coincide con lo que dice el detalle del producto. Es el efecto de la corrección de U07 | 0 | verificado en pantalla | 2026-09-11 |
| A20 | F5 | trazabilidad, preferencias registradas | H1 | Acierto: los valores y las barras coinciden con lo elegido en los pasos 1 y 3 | 0 | verificado en pantalla | 2026-09-11 |
| A21 | F5 | descarga de programas usados | H10 | Acierto: el archivo de los 14 programas abre diciendo que cada bloque se ejecutó por separado y que no debe enviarse completo al motor como si fuera uno solo: el artefacto se explica a sí mismo | 0 | verificado en la descarga | 2026-09-11 |

Instrucciones para completar: recorrer F1 a F5 en orden, una heurística por vez, con el perfil neutro y
después con «solo sabor» y «todo en No me importa». Anotar también lo que funciona bien cuando una
heurística se cumple de forma notable (columna Sev. = 0), para que la tabla no sea sólo negativa.
Las filas `Ann` son esos aciertos; se numeran aparte de los hallazgos `Unn` pero cuentan en el resumen.

Decisiones tomadas durante el recorrido y registradas acá para no repetir la discusión:

- **Rótulo compartido (ADR-004): se mantiene.** El orden pone primero al mejor siempre; lo único que
  cambia bajo 0,01 de diferencia es que la app dice «Entre las mejores opciones para vos» en vez de
  afirmar un único mejor. En «solo sabor» el ganador se sostiene en el 41 % de las réplicas del
  bootstrap, así que la afirmación exclusiva no es sostenible (A02).
- **No se anota como hallazgo** la ausencia de barra de pasos en `home.html` (la evaluadora no la
  esperaba y no la echó de menos), ni la falta de un resumen de preferencias en el ranking (decisión
  explícita: no hace falta recordarlas). De esta última queda pendiente de limpieza que la vista
  `product_ranking` calcule `top_preferences` y ninguna plantilla lo use: es código muerto, no un
  problema de usabilidad.
- **No se cuenta como acierto de H2** que la evaluadora entienda el bloque «Información técnica de
  esta recomendación»: es la autora del sistema, y ese es justamente el sesgo declarado en la
  sección 5.
- **No se anota «Comparar con los demás»** como violación de H8: repite en parte el ranking, pero
  muestra el valor de cada producto, que el ranking no da. Juicio de la evaluadora en pantalla.
- **X1 no se observó en esta pasada.** Se buscaron fragmentos cortados a mitad de oración cuya
  etiqueta contradijera lo que se lee (el caso «…da un aroma y sabor bue[no]» del chequeo del
  2026-09-03) y no apareció ninguno. Sigue siendo un problema de extracción conocido; no se
  convierte en hallazgo de usabilidad porque no se vio en pantalla.
- **No se anota la píldora «Estado» de trazabilidad** (Validada / Simulada / Pendiente): en el
  recorrido publicado dice siempre «Validada», y la evaluadora la considera poco relevante para el
  usuario final, pero sí distingue una demostración de una corrida validada, que es el propósito
  declarado de la pantalla.
- **No se anota la falta de un botón de regreso en trazabilidad**: se llega a esa pantalla desde
  LAF 1 o desde LAF 2, así que no hay un único lugar al que volver; el navegador alcanza y el
  recorrido no se pierde. Decisión razonada de la evaluadora.
- **Los medidores de «Confianza» y «Preferencia» y el mapa de puntos no se dibujan nunca**:
  pertenecen al camino viejo del `min(confianza, preferencia)` y producción usa
  `post_laf_multicriteria_v1`. Verificado en pantalla (no aparece ninguno de los dos). Es código
  muerto, no un problema de usabilidad; importa para F5 y para la tesis, no para esta tabla.

## 4. Resumen

La columna «Sev. 0» cuenta los aciertos (filas `Ann`): sin ella la tabla resumen volvería a ser sólo
negativa, que es lo que las instrucciones de la sección 3 quieren evitar. El total incluye los
aciertos; la columna «Corregidos» cuenta sólo hallazgos.

| Heurística | Sev. 4 | Sev. 3 | Sev. 2 | Sev. 1 | Sev. 0 | Total | Corregidos |
|---|---:|---:|---:|---:|---:|---:|---:|
| H1 | 1 | 2 | 3 | 2 | 7 | 15 | 6 |
| H2 | | 2 | 6 | 2 | 3 | 13 | 7 |
| H3 | | | | | 3 | 3 | |
| H4 | | 4 | 4 | 1 | 2 | 11 | 9 |
| H5 | | | | 1 | 1 | 2 | |
| H6 | | | | | | | |
| H7 | | | | | | | |
| H8 | | | | 3 | | 3 | 2 |
| H9 | | 1 | 3 | 2 | 1 | 7 | 5 |
| H10 | | | 2 | 1 | 4 | 7 | 3 |
| **Total** | **1** | **9** | **18** | **12** | **21** | **61** | **32** |

61 filas: **40 hallazgos** (severidad 1 a 4) y **21 aciertos** (severidad 0). De los hallazgos, **10
son de severidad mayor o catastrófica** (nueve de 3 y uno de 4) y **32 están corregidos**: siete
antes de que la evaluación se formalizara (U01–U07, seis de ellos durante el desarrollo) y
veinticinco el 2026-09-11, en las dos pasadas de correcciones que registra ADR-006. **Los 10
hallazgos de severidad mayor o catastrófica están los 10 corregidos**. Por severidad: 1 de 1 en la
catastrófica, 9 de 9 en las mayores, 16 de 18 en las menores y 6 de 12 en las cosméticas.

Los 8 pendientes son U13, U14, U15, U17, U23, U26, U28 y U31. Dos son de severidad 2 y quedan por la
decisión abierta que el propio hallazgo anota —U15 (dónde vive la sigla «LAF») y U31 (qué condiciones
muestra la fila)—; los otros seis son cosméticos. U13 además está *aceptado* como decisión de
diseño, no sólo postergado.

**Dos heurísticas quedaron sin filas y la razón no es que la interfaz sobresalga en ellas.**
En H6 (reconocer antes que recordar) el único candidato —que el ranking no muestre las preferencias
elegidas— se descartó porque la evaluadora decidió que no hacía falta recordarlas; queda registrado
como decisión en la sección 3. En H7 (flexibilidad y eficiencia) directamente **no se evaluó el
escenario que esa heurística mide**: no se probó el uso repetido, no hay perfiles guardados que
probar y no se midieron atajos. Es un hueco del recorrido, no un resultado.

## 5. Limitaciones (van a §7.8 y §6.7)

- Una sola evaluadora, que además es la autora: Nielsen recomienda entre tres y cinco evaluadores
  porque uno solo detecta una fracción de los problemas (Nielsen 1994); los problemas de primer uso
  quedan subestimados.
- Sin usuarios: no se mide tiempo de tarea, tasa de error ni satisfacción.
- Cinco de los hallazgos provienen de un chequeo previo no ciego (2026-09-03).
- Las preguntas no son de Nielsen sino una operacionalización propia, documentada en la sección
  2.1, y buena parte se formularon anticipando el resultado esperado: la evaluadora confirmaba o
  corregía una hipótesis. Los hallazgos verificados en código o por medición no dependen de eso.
- Dos heurísticas quedaron sin hallazgos por motivos distintos, y ninguno es que la interfaz
  sobresalga en ellas: en H6 el único candidato se descartó por decisión de diseño de la autora, y
  **H7 no se evaluó** —no se probó el uso repetido ni se midieron atajos o perfiles guardados—.
- La evaluadora es además la autora del sistema: su comprensión de la capa técnica (siglas, hashes,
  identificadores de corrida) no es transferible a un usuario final, por lo que esos elementos no se
  contaron como aciertos.

## 6. Texto para §7.8 (borrador, completar con los números del resumen)

> La evaluación de la interacción se realizó mediante inspección heurística (Nielsen, 1994), sin
> participación de usuarios, conforme al alcance del trabajo. La autora recorrió cinco flujos de
> interacción con las diez heurísticas de Nielsen y registró 40 hallazgos y 21 aciertos; 10 de los
> hallazgos son de severidad mayor o catastrófica y 32 fueron corregidos antes del cierre del
> prototipo —entre ellos los 10 de severidad mayor o catastrófica—, mientras 8 de severidad menor
> quedan declarados como deuda (Tabla 7.X). Cinco de ellos
> provienen del chequeo humano del ranking (Sección 6.5.3), lo que muestra que el método operó
> durante el desarrollo antes de formalizarse. La limitación principal es la de un único evaluador,
> que además es la autora del sistema.
