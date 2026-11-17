# Experimento 1 — Juicio ciego por pares (PRE-REGISTRO)

**Estado: PRE-REGISTRO. Escrito ANTES de correr nada.**
**Fecha de redacción: 2026-09-10.** Pendiente de aprobación de Ana Paula Machado.

Este documento fija las definiciones operativas, el procedimiento de muestreo, las
métricas y el criterio de fracaso **antes** de generar los pares, de imprimir las
planillas y de recibir una sola respuesta. El tribunal observó que en trabajos
anteriores las definiciones se fijaron después de correr; acá no. Cualquier cambio
posterior a la aprobación se registra al pie, con fecha y motivo, y no se edita el
cuerpo del documento.

---

## 1. Pregunta

¿El orden que el sistema produce **para un aspecto** coincide con el orden que
producen personas que leen **la misma evidencia**, sin ver el sistema, sin ver las
estrellas y sin saber qué producto están leyendo?

Es la referencia externa que le falta a `validacion_oe5/`: allí la «precisión» se
mide contra estrellas y proporciones de positivas, que salen del mismo corpus que
alimenta el sistema (circular). Acá el criterio lo pone una persona.

## 2. Qué NO mide

- No mide si la recomendación es útil, ni si el usuario compraría el producto.
- No mide el ranking global (multicriterio con 14 aspectos): mide **un aspecto**.
- No valida la capa de explicación, que es lo que Ana rechazó en
  `docs/CHEQUEO_HUMANO_LAF1.md`. Los jueces no ven ninguna explicación.
- No mide la calidad de la extracción de aspectos. Si un fragmento está mal
  clasificado, el juez lo lee igual: eso es deliberado, porque el juez juzga la
  evidencia que el sistema realmente usa.

## 3. Entradas congeladas

Nada de esto se toca. Si algo de esto cambiara, el experimento se invalida.

| Elemento | Valor | Verificado en |
|---|---|---|
| `dataset_key` | `mlm_mlm194329_20260528_142014` | `docs/ESTADO_DATASETS_CAFE.md` |
| Productos | 18 incluidos (`products_seed.analysis_status = 'included'`) | consulta 2026-09-10 |
| Estrategia de trust | D (`PRIOR_MEAN=0,50`, `PRIOR_WEIGHT=10`) | `src/06_trust.py:99-100` |
| Modelo de decisión | `post_laf_multicriteria_v1` | `webapp/.../evaluators.py` |
| Aspecto principal | `sabor` | decisión de Ana |
| Perfil de referencia | «solo sabor» (sabor = 1,0; los otros 13 = 0,0) | decisión de Ana |
| Motor | `laf-api` de Javi en `http://localhost:8088/api/graph` (Docker) | verificado arriba 2026-09-10 |

## 4. Definiciones operativas

### 4.1 Puntaje LAF del aspecto

El **puntaje LAF de sabor** de un producto es la confianza post-conflicto que
devuelve `LAFGraphRankingMapper` en la corrida por aspecto de `sabor`: programa
generado con preferencias `{sabor: 1,0; resto: 0,0}`, filtrado con
`zero_threshold_payload` (quita los hechos con preferencia 0), evaluado por
`laf-api`. Es exactamente el número que `combine_rankings` usa como
`aspect_scores['sabor']`.

**Verificado el 2026-09-10:** con perfil «solo sabor» ese número **es** el puntaje
final del producto, porque hay un solo aspecto activo y su peso normalizado vale 1.
Los 18 valores coinciden a 4 decimales con `solo_sabor` de
`validacion_laf1/salidas/battery_multicriterio_mlm194329_20260528_142014.json`.
Por lo tanto «orden del sistema en sabor» y «ranking del perfil solo sabor» son la
misma cosa, y no hay que elegir entre dos definiciones.

### 4.2 Mención

Una fila de `review_aspects` con `dataset_key` del snapshot, `aspect = 'sabor'` y
cualquier polaridad (`pos`, `neu`, `neg`).

**Decisión declarada — se incluyen las `neu`.** El sistema las descarta antes de
LAF (`src/06_trust.py:503`), pero son evidencia que una persona leyendo reseñas
tiene delante. Mostrar sólo `pos` y `neg` sería construirle al juez un corpus que
el sistema no lee ni desecha, sino que nadie lee. Se muestran las tres y la
composición por polaridad de cada muestra queda registrada en la tabla privada.
**Consecuencia declarada:** parte de cualquier desacuerdo entre juez y sistema
puede deberse a que el juez pesó fragmentos neutros que el sistema ignora. Es una
divergencia conocida, no un error, y se informa en RESULTADOS.md.

Composición del corpus de sabor (consulta del 2026-09-10, 3.385 menciones):
2.959 `pos` (87,4 %), 349 `neu` (10,3 %), 77 `neg` (2,3 %).

### 4.3 Fragmento

El campo `sentence_excerpt` de la mención, **tal como está guardado en la tabla**,
sin reescribir, sin completar y sin recortar (salvo el enmascarado de marcas de
§4.6).

**Verificado el 2026-09-10:** los excerpts ya vienen truncados a **200 caracteres**
por `05_aspects.py` (mínimo 6, mediana 38, máximo 200). El tope de 300 caracteres
del diseño original nunca se activa y no se implementa.

**Decisión declarada — no se recupera la oración completa de `reviews_clean`.** El
experimento pregunta si el orden refleja la evidencia *que el sistema usa*, y el
sistema usa este texto truncado. El costo es conocido: el caso X1 de
`docs/CHEQUEO_HUMANO_LAF1.md` es un excerpt cortado que invierte el sentido. Ese
costo se declara como limitación, no se corrige.

**Deduplicación:** dentro de un mismo producto, si dos menciones tienen exactamente
el mismo texto (misma cadena tras normalizar espacios y pasar a minúsculas) se
conserva una sola antes de muestrear. Motivo: una reseña que menciona sabor y aroma
en la misma oración genera dos filas con el mismo excerpt, y mostrar el mismo texto
dos veces al juez es ruido de presentación, no evidencia adicional. Se registra
cuántas se cayeron por producto.

**Verificado:** tras deduplicar, el producto con menos fragmentos distintos de
sabor tiene **38** (Arábico 900g). Los 18 siguen muy por encima de 15.

### 4.4 Producto elegible

Producto del snapshot con **≥ 15 menciones de sabor**.

**Verificado el 2026-09-10: los 18 productos son elegibles.** El mínimo es 41
menciones. El umbral no excluye a nadie y por lo tanto **no introduce ninguna
selección**; se deja escrito igual porque es parte del diseño pre-registrado y
porque sí filtraría si se repitiera con `aroma` (allí sólo 13 de 18 llegan a 15).

| Producto (posición en `products_seed`) | Menciones sabor | pos / neu / neg | Fragmentos únicos |
|---|---:|---|---:|
| Capuccino Moka Members Mark 1.8 kg (7) | 477 | 417 / 49 / 11 | 399 |
| Capuccino Vainilla Francesa MM 1.8 kg (17) | 397 | 360 / 32 / 5 | 339 |
| Blasón Espresso Robusto 1 kg (4) | 395 | 340 / 50 / 5 | 343 |
| Nescafé Taster's Choice Caramel 100 g (8) | 392 | 347 / 35 / 10 | 345 |
| La Parroquia Puro 1 kg (20) | 388 | 336 / 40 / 12 | 359 |
| Nescafé Reserva Xiapan 180 g (1) | 210 | 189 / 15 / 6 | 190 |
| Gourmet Tostado y Molido Americano Blasón 1 kg (6) | 209 | 190 / 19 / 0 | 188 |
| Nescafé Café de Olla 170 g (10) | 144 | 130 / 8 / 6 | 130 |
| Gourmet Molido Espresso 400 g Blasón (12) | 123 | 113 / 10 / 0 | 112 |
| Tripack Juan Valdez 95 g (19) | 116 | 98 / 14 / 4 | 107 |
| Nescafé Clásico ICE 170 g (9) | 91 | 71 / 13 / 7 | 82 |
| Nescafé Clásico Frasco 200 g (15) | 89 | 77 / 12 / 0 | 82 |
| Nescafé Clásico Bolsa 400 g (2) | 72 | 45 / 20 / 7 | 69 |
| Nescafé Reserva Verarica 180 g (16) | 68 | 63 / 4 / 1 | 63 |
| Nescafé Clásico Professional 1 kg (18) | 65 | 53 / 11 / 1 | 63 |
| Nescafé Clásico sin gluten 400 g (5) | 64 | 52 / 10 / 2 | 60 |
| Nescafé Decaf 170 g (11) | 44 | 41 / 3 / 0 | 42 |
| Arábico Gourmet Americano 900 g Blasón (13) | 41 | 37 / 4 / 0 | 38 |

### 4.5 Franjas de distancia

Sobre los 153 pares posibles (18 sobre 2) se calcula |Δ| = diferencia absoluta de
puntaje LAF de sabor. Los 153 valores se ordenan y se cortan en terciles:

- **chica**: |Δ| ≤ percentil 33,3
- **mediana**: percentil 33,3 < |Δ| ≤ percentil 66,7
- **grande**: |Δ| > percentil 66,7

**Medido el 2026-09-10** (los cortes se recalculan en el script y se guardan; estos
son los valores esperados): corte 1 = **0,051**, corte 2 = **0,115**, |Δ| máximo =
**0,273**.

**Exclusión declarada: los pares con |Δ| = 0 no entran al conjunto elegible.** El
sistema no ordena esos dos productos, así que no hay predicción que verificar y el
par no puede ni acertar ni fallar. Hay **exactamente uno** en el snapshot: Nescafé
Decaf y Arábico 900 g, ambos en 0,5233. El script informa cuántos excluyó.

### 4.6 Anonimización

Los fragmentos se muestran sin nombre de producto, sin marca, sin estrellas, sin
fecha, sin likes y sin identificador de reseña.

La lista de términos a enmascarar se deriva de los nombres de los 18 productos
(`products_raw.name`) y se guarda en `materiales/marcas_a_enmascarar.csv` con tres
columnas: `termino`, `frecuencia_en_menciones_sabor`, `enmascarar` (sí/no).
**Ana revisa y aprueba ese CSV antes de que se impriman las planillas.**
`products_raw.attributes` está **vacío** (`[]`) en este snapshot, así que no existe
un campo de marca del que leerla: la lista es derivada y revisada, no un dato.

Reglas de aplicación:
- comparación insensible a mayúsculas y a acentos, sobre límites de palabra;
- el término se reemplaza por el literal `[marca]`;
- se enmascaran marcas (Blasón, Nescafé, Nestlé, Members Mark, Juan Valdez,
  La Parroquia) **y** nombres de línea que identifican el producto (Taster's
  Choice, Xiapan, Verarica, Reserva, Clásico, ICE, Decaf, Tripack…), según lo que
  quede aprobado en el CSV;
- **no** se enmascaran formatos ni tamaños («frasco», «bolsa», «400 g», «1 kg») ni
  tipos de café («capuccino», «molido», «soluble», «vainilla»). Enmascararlos
  vaciaría la evidencia de sabor.

**Limitación declarada por adelantado:** con formatos y tipos a la vista, un juez
que conozca bien el mercado mexicano puede reconocer algún producto. No se puede
evitar sin destruir la evidencia. Se pregunta en la planilla si reconoció algún
producto, y las respuestas afirmativas se informan.

### 4.7 Par y rotación A/B

Un par es un conjunto de dos productos elegibles. Cuál de los dos se rotula **A** y
cuál **B** se decide al azar por par, con semilla declarada. La asignación queda
registrada en la tabla privada y **no** se le muestra a los jueces.

### 4.8 Verdicto del juez

Una de tres categorías: **A**, **B**, **No puedo decidir**. Más un campo opcional
de comentario libre y una casilla «reconocí alguno de los dos productos».

### 4.9 Veredicto mayoritario y pares excluidos

Con tres jueces:
- si dos o tres coinciden en **A** o en **B**, ese es el veredicto mayoritario;
- el par se **excluye** si (a) los tres jueces responden categorías distintas, o
  (b) dos o tres responden «No puedo decidir».

Un par con dos **A** y un «No puedo decidir» tiene mayoría **A** y se incluye.
Los pares excluidos se cuentan e informan aparte, con su franja de distancia.

## 5. Muestreo y semillas

Semilla maestra declarada: **`SEMILLA = 20260910`**. Tres generadores
independientes y deterministas de la biblioteca estándar:

| Uso | Generador |
|---|---|
| Selección de pares | `random.Random(20260910)` |
| Muestreo de fragmentos | `random.Random(20260911)` |
| Rotación A/B | `random.Random(20260912)` |

### 5.1 Selección de los 20 pares

Objetivo: **7 grandes, 7 medianas, 6 chicas**, sin que ningún producto aparezca en
más de **4** pares.

Algoritmo (determinista dado la semilla):
1. Construir los 153 pares, calcular |Δ|, descartar los de |Δ| = 0, clasificarlos
   en las tres franjas de §4.5.
2. Para cada franja en el orden `grande`, `mediana`, `chica`: barajar los pares de
   la franja con el generador de pares y recorrerlos, aceptando un par sólo si
   ninguno de sus dos productos alcanzó ya el tope de 4 apariciones, hasta llegar
   a la cuota de la franja.
3. Si alguna franja no llega a su cuota, se reintenta desde el paso 2 con la
   siguiente permutación del mismo generador, hasta 1.000 intentos.
4. Si a los 1.000 intentos no se llega, el script **falla con error** y no produce
   materiales. No hay relajación silenciosa del tope ni de las cuotas.

### 5.2 Muestreo de fragmentos

Para **cada producto en cada par** se toman **15 fragmentos** por muestreo
aleatorio simple **sin reemplazo** sobre el conjunto deduplicado de fragmentos de
sabor de ese producto, sin estratificar por polaridad. Si el producto tuviera menos
de 15, se usan todos (no ocurre: el mínimo es 38).

**Decisión declarada — la muestra se sortea de nuevo en cada par.** Es lo que dice
el diseño de Ana («evidencia por producto **y par**»). Consecuencia: un producto que
aparece en 4 pares se juzga sobre 4 muestras distintas de su propia evidencia, lo
que mide el producto y no una muestra afortunada, pero permite que un mismo juez dé
veredictos aparentemente inconsistentes entre pares. Esa inconsistencia es
información, no error, y se informa: se cuenta cuántos ciclos de preferencia
(A>B, B>C, C>A) aparecen por juez.

El orden en que se listan los 15 fragmentos de un lado también se baraja con el
generador de fragmentos, para que la posición no arrastre la polaridad.

## 6. Instrumento

Por cada juez se generan dos archivos en `materiales/`:

- `planilla_juez_<N>.csv` — una fila por par: `par_id`, `veredicto` (a completar),
  `reconoci_producto` (a completar), `comentario` (a completar). Es el archivo que
  el juez devuelve; se puede abrir en Google Sheets.
- `evidencia_juez_<N>.html` — documento autocontenido de sólo lectura, con la
  consigna arriba y los 20 pares en orden, cada uno con sus 15 + 15 fragmentos en
  dos columnas rotuladas A y B.

Los tres jueces reciben **los mismos 20 pares con la misma evidencia y la misma
asignación A/B**: si cambiara entre jueces, el acuerdo entre jueces no sería
medible. Lo único que puede diferir entre jueces es el **orden de presentación de
los 20 pares**, barajado por juez con el generador de pares, para que el cansancio
no golpee siempre a los mismos pares. El `par_id` es el mismo en las tres planillas.

`materiales/INSTRUCCIONES.md` (y su versión imprimible) contiene la consigna: cómo
responder, que no hay respuesta correcta, que no busquen el producto en internet,
que respondan sólo con lo que leen, y el tiempo estimado (45–60 minutos).

## 7. Jueces

Tres personas externas que toman café. **No participan la autora ni el director.**
Ana los consigue; este experimento sólo prepara el material. Se registra, sin
identificarlos, si toman café a diario y si compran café por internet.

## 8. Métricas

Todas se calculan con `analizar_respuestas.py`, **escrito y congelado antes de
recibir ninguna respuesta**.

1. **Acuerdo sistema–jueces** = (pares con mayoría cuyo veredicto coincide con el
   lado de mayor puntaje LAF de sabor) / (pares con mayoría). Se informa con
   intervalo de confianza del 95 % de Wilson.
2. **Acuerdo por franja**: la misma proporción, calculada dentro de grande,
   mediana y chica.
3. **Acuerdo entre jueces**: Fleiss κ sobre las tres categorías (3 jueces, 20
   ítems, sin ponderar) y porcentaje de pares con las tres respuestas iguales.
4. **Pares excluidos**: cantidad, motivo y franja.
5. **Descriptivos**: distribución de respuestas por juez, tasa de «No puedo
   decidir» por franja, ciclos de preferencia por juez, pares donde el juez
   declaró haber reconocido un producto.

Hipótesis direccional pre-registrada: **el acuerdo debería ser mayor en la franja
grande que en la chica.** Si fuera igual o menor, el orden del sistema no está
capturando una diferencia que las personas perciban, y se informa así.

## 9. Criterio de fracaso (pre-registrado)

> **Si el acuerdo sistema–jueces en los pares de distancia grande es menor al 70 %,
> se declara que el ranking por aspecto no refleja la lectura humana de la
> evidencia, y se escribe así en la tesis.**

No se ajustará ningún umbral, fórmula, regla ni operador del sistema en función de
este resultado. La metodología está congelada; este experimento la describe, no la
calibra.

**Potencia — declarada por adelantado.** Con 7 pares en la franja grande, el 70 %
equivale a 5 de 7. El intervalo de Wilson del 95 % para 5/7 va aproximadamente de
36 % a 92 %. **Este experimento no puede distinguir un sistema del 70 % de uno del
90 %.** Sólo puede detectar un fracaso grosero (3 de 7 o menos). Eso es lo que se
va a afirmar y nada más. La alternativa —cientos de pares— exige jueces que no hay.

## 10. Entregables

| Archivo | Cuándo |
|---|---|
| `README.md` (este documento) | antes de correr |
| `generar_pares.py` | tras la aprobación |
| `generar_planillas.py` | tras la aprobación |
| `analizar_respuestas.py` | antes de recibir respuestas |
| `salidas/tabla_pares_con_puntajes_<fecha>.csv` | **privado**, no se entrega a los jueces |
| `materiales/marcas_a_enmascarar.csv` | Ana lo aprueba antes de imprimir |
| `materiales/INSTRUCCIONES.md` | con las planillas |
| `materiales/planilla_juez_{1,2,3}.csv` | con las planillas |
| `materiales/evidencia_juez_{1,2,3}.html` | con las planillas |
| `respuestas/` | lo carga Ana |
| `RESULTADOS.md` | cuando estén las tres planillas |

Cada script imprime al arrancar: `dataset_key`, fecha, semilla, cantidad de reseñas
y cantidad de menciones usadas.

## 11. Repetición con `aroma`

Si hay tiempo, se repite con `aroma`, **con este mismo pre-registro y las mismas
semillas**, y con una diferencia que ya está medida: en `aroma` sólo **13 de los 18**
productos alcanzan 15 menciones (Capuccino Moka tiene 8 y Clásico ICE 3), de modo
que el conjunto elegible baja a 78 pares posibles. Se informará por separado y no
se mezclará con sabor.

## 12. Limitaciones (a repetir en RESULTADOS.md)

- Tres jueces. Fleiss κ sobre 3 jueces y 20 ítems tiene un error estándar grande.
- Un solo aspecto (`sabor`), no el ranking multicriterio que ve el usuario.
- Los pares los eligió el sistema, a partir de su propio puntaje: el diseño
  garantiza cobertura de distancias, no representatividad del catálogo.
- 15 fragmentos por lado son una muestra de hasta 477 menciones. El juez ve una
  ventana; el sistema ve todo.
- Los excerpts están truncados a 200 caracteres en origen, con casos conocidos de
  sentido invertido (X1).
- La evidencia mostrada incluye menciones `neu` que el sistema descarta.
- Anonimización imperfecta: formatos y tipos de café siguen a la vista.
- 20 pares no alcanzan para estimar el acuerdo con precisión; alcanzan para
  detectar un fracaso grosero.

---

## Enmiendas posteriores a la aprobación

Cada enmienda va acá con fecha y motivo; el cuerpo del documento no se edita.

**2026-09-10 — corrección de un dato anticipado en §4.5, no de una regla.** El
cuerpo dice que hay «exactamente uno» par con |Δ| = 0. Al ejecutar
`generar_pares.py` resultaron **dos**: Nescafé Decaf = Arábico 900 g (ambos
0,5233) y Capuccino Moka = Blasón Espresso Robusto (ambos 0,6313). La **regla**
pre-registrada —excluir del conjunto elegible los pares que el sistema no
ordena— no cambia y se aplicó igual; lo que estaba mal era mi conteo previo.
Pares elegibles: 151 de 153.

**2026-09-10 — LIMITACIÓN señalada por la jueza al terminar, antes de ver
resultados.** Ana observó que en el material **no se ve la longitud de la reseña,
ni si tiene imágenes, ni los likes**. Es correcto y se suma a §12 como limitación
declarada: el peso de cada mención en el sistema es `trust × extraction_confidence`
y el trust se compone de relevancia, likes, media y longitud
(`src/06_trust.py:334`), **ninguno de los cuales es visible en el fragmento**.
Medido sobre las 12.050 reseñas del snapshot: trust mediano 0,350, percentil 5
0,160, percentil 95 0,600 — **una reseña del p95 pesa 3,75 veces una del p5**, y
esa diferencia la deciden likes, imágenes y largo, no lo que dice el texto. La
observación se registra acá porque la hizo **antes** de conocer ninguna cifra.

**2026-09-10 — normalización de una respuesta en texto libre.** La jueza escribió
`Empatados` en P13. El script no lo reconocía y lo trataba como ilegible. Se
agregó `empat*` a los sinónimos de la tercera categoría. **No cambia ninguna
cifra**: con un solo juez, «ilegible» y «no puedo decidir» excluyen el par por
igual; sólo cambia el motivo de exclusión que se informa. Verificado corriendo el
análisis antes y después: mismos 14 pares con veredicto, mismo 7/14, mismo 1/4 en
la franja grande.

**2026-09-10 — análisis posterior, declarado como tal.** El desacuerdo resultó
sistemático y se contrastaron dos hipótesis para explicarlo. Ese contraste se
formuló **después** de leer las respuestas, no está pre-registrado, y vive
separado en `RESULTADOS_POST_HOC.md` con esa advertencia al frente. **No modifica
ninguna métrica ni el criterio de fracaso de §9**, que se cumplió y se informa
como estaba fijado.

**2026-09-10 — CAMBIO DE INSTRUMENTO: no hay panel de tres jueces externos.**
Pedido por Ana. Motivo declarado: la propuesta del TFG establece que la
evaluación se hace «sin participación de usuarios reales» y no es viable
convocar personas externas. Queda anotada, para que el cambio sea auditable,
la observación del asistente: tres personas leyendo fragmentos anonimizados no
serían «usuarios» en el sentido de la propuesta —no abren la aplicación, no ven
un ranking ni una explicación— sino **anotadores**, la misma categoría que el
«etiquetado manual o semiautomático» que la propuesta lista como instrumento en
su Etapa 2. Ana consideró la observación y decidió igual; se procede como pidió.

En consecuencia, **§7 (Jueces) queda reemplazado** por dos instrumentos:

1. **Instrumento humano: Ana Paula Machado, en ciego, n = 1.** Recibe el mismo
   material que se había preparado para los jueces externos, sin ver el nombre
   del producto, la marca, las estrellas, el puntaje LAF ni la predicción del
   sistema. Los 20 pares y su evidencia se congelaron el 2026-09-10, **antes**
   de que los mirara.
   **Condición de validez:** Ana no debe abrir
   `salidas/tabla_pares_con_puntajes_sabor_20260910.csv` ni
   `salidas/fragmentos_usados_sabor_20260910.csv` hasta haber entregado su
   planilla. Si los abriera antes, el experimento queda invalidado y no hay
   corrección posible; se declararía así.
2. **Instrumento automático: lector LLM.** Pre-registrado por separado en
   `README_LLM.md`, con sus propios controles y su propio criterio de descarte.
   **No es un juez humano y no se informa como tal.**

**Qué mejora respecto del chequeo de `docs/CHEQUEO_HUMANO_LAF1.md`:** aquel fue
con la pantalla a la vista, con el orden del sistema conocido y con la lectura
del asistente presentada antes del juicio; así está anotado allí. Éste es ciego
en los dos sentidos que importan: Ana no sabe qué producto lee ni qué lado
prefiere el sistema, de modo que no puede inclinarse a favor del sistema aunque
quisiera.

**Qué se pierde, y se declara:** desaparece el acuerdo entre jueces. Con n = 1
**no se calcula Fleiss κ** ni porcentaje de pares unánimes (la unanimidad de una
persona consigo misma es 100 % por definición y no significa nada). El
experimento deja de ofrecer un **criterio externo** en sentido fuerte: ofrece
una lectura ciega de la autora más un lector automático declarado. Así debe
escribirse en la tesis, sin eufemismos.

**§4.9 (veredicto mayoritario) se generaliza** sin cambiar la regla para tres
jueces: hay mayoría cuando una de las dos alternativas supera la mitad de los
votos válidos. Con n = 3 equivale exactamente a lo escrito en el cuerpo (dos o
más votos, y quedan excluidos «los tres distintos» y «dos o más no puedo
decidir»). Con n = 1 el veredicto del único juez es la mayoría, salvo que
responda «no puedo decidir», en cuyo caso el par se excluye.

**Lo que NO cambia:** los pares, la evidencia, las semillas, el enmascarado, las
franjas de distancia, las métricas de acuerdo sistema–juez, el intervalo de
Wilson y **el criterio de fracaso del §9** (acuerdo < 70 % en la franja grande).
El material ya generado no se vuelve a sortear.

**2026-09-10 — material entregable generado.** Con la lista de enmascarado
aprobada por Ana (20 términos), se produjeron `materiales/INSTRUCCIONES.md`,
`evidencia_juez_{1,2,3}.html` y `planilla_juez_{1,2,3}.csv`. Ana usa la planilla
1. Verificación: 600 fragmentos mostrados, **cero apariciones** de un término
enmascarado en el texto mostrado. Identificabilidad residual medida: 12
fragmentos de 600 (2 %) contienen una palabra que apunta a una línea de producto
(«olla» 4, «vainilla» 3, «moka» 3, «descafeinado» 1, «capuccino» 1), y algún
fragmento menciona Veracruz, que para un lector mexicano señalaría a La
Parroquia o a Reserva Verarica. No se enmascaran porque son evidencia de sabor;
la casilla «reconocí alguno» registra el efecto. Se agregó a la consigna un
párrafo de participación voluntaria y anónima, que no afecta ninguna medición.

**2026-09-10 — resultado de la selección (informativo).** Cuotas y tope se
cumplieron en el **primer** intento del generador sembrado. Cortes de tercil
efectivos: chica ≤ 0,0529 < mediana ≤ 0,1149 < grande, con |Δ| máximo 0,2727.
De los 18 productos elegibles, **16 aparecen** en algún par; quedan fuera Blasón
Espresso Robusto 1 kg y Nescafé Clásico Frasco 200 g. El diseño no exige que
todos aparezcan (exige el tope de 4, no un piso de 1); se deja registrado.
