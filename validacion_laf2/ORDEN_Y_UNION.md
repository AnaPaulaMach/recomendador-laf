# Pregunta 2 — ¿LAF1 y después LAF2, LAF2 primero, o un solo programa?

Análisis con los datos de `SUFICIENCIA_DATOS.md` (2026-09-03). No es una decisión: son los tres
diseños con pros, contras y ejemplos del catálogo para que Ana elija y lo fundamente.

## Punto de partida (verificado)

- **Producto y publicación son objetos distintos.** Un producto de catálogo (ej. Nescafé Taster's
  Choice Caramel, MLM16250244) tiene N publicaciones (7 en el histórico), cada una de un vendedor,
  con su precio y sus condiciones. Las reseñas (LAF1) son del **producto**; las condiciones de
  compra (LAF2) son de la **publicación**.
- **LAF1 hoy** (`post_laf_multicriteria_v1`): una corrida LAF por aspecto, puntaje = confianza
  post-conflicto, preferencia del usuario = peso en la suma. Cerrado y validado.
- **LAF2 hoy** (`10_laf2_generate.py`, `LAF2ProgramService`): un programa por producto elegido,
  reglas solo positivas, preferencia como segunda etiqueta de hechos y reglas.
- **Lo medido en LAF1 que importa acá** (`validacion_laf1/EXPERIMENTOS_LEGACY_SEGUNDO_LAF.md`):
  - EXP 2: combinar 14 aspectos con `⊕ = X+Y−XY` en un segundo LAF **satura** (neutral: todos los
    productos entre 0,967 y 0,999; rango útil 0,03); el orden coincide con la suma (ρ 0,98) pero
    pierde la escala.
  - EXP 5: dentro de la Def. 8 toda agregación admisible tiene `⊤` absorbente, así que **cualquier**
    álgebra satura con muchos argumentos; no hay arreglo cambiando operadores.
- **Datos del catálogo que pesan en la decisión**: condiciones que realmente discriminan =
  precio, envío gratis (66–84 % de las publicaciones), tienda oficial (17–22 %), descuento
  (8–12 %). Cuotas y factura no existen; garantía ≥ 6 meses es 3–5 %. En 11 de 53 productos hay
  una sola publicación.

## Diseño (a) — el actual: LAF1 elige producto, después LAF2 elige publicación

**Cómo funciona.** El usuario pone pesos de calidad (sabor, aroma…) → ranking de productos.
Elige uno → pone pesos de compra (precio, envío…) → ranking de sus publicaciones.

**Pros**
- Respeta que son objetos distintos: cada LAF razona sobre hechos de su propio objeto. El
  programa de LAF2 tiene una variable `X` = publicación; el de LAF1, `X` = producto.
- Dos preguntas al usuario en dos momentos: "¿qué café?" y "¿a quién se lo compro?". Es lo que
  hace la gente en Mercado Libre (primero el producto de catálogo, después la lista de ofertas).
- LAF2 es un programa chico (7 publicaciones → 7 `recomendar`), fácil de explicar y de mostrar
  como grafo; no arrastra los 14 aspectos de LAF1.
- No toca LAF1, que ya está validado.

**Contras**
- El usuario puede elegir un producto excelente en reseñas cuya única publicación es cara o sin
  envío, y recién enterarse en LAF2. Ej.: Nescafé Clásico bolsa (histórico, puesto 2 del catálogo):
  1 publicación, sin descuento, sin oficial, sin envío. LAF2 no puede ofrecer alternativa.
- En 11/53 productos LAF2 devuelve un ranking de un elemento (hay que mostrarlo como "una sola
  oferta", no como ranking).
- Las condiciones de compra no influyen en absoluto en la elección del producto. Si al usuario le
  importa mucho el envío gratis, no lo puede decir hasta después de elegir.

**Qué habría que validar (pregunta 3).** Saturación de la preferencia agregada con 2+ condiciones;
sensibilidad a los sliders vivos (precio, envío, oficial, descuento); comportamiento con
sliders muertos (cuotas, factura); productos de 1 publicación.

## Diseño (b) — LAF2 primero: filtrar "compra mala" y después rankear productos

**Cómo funcionaría.** Antes de LAF1, descartar publicaciones que no cumplen las condiciones que
el usuario exige (ej. "solo con envío gratis"); un producto sin publicaciones sobrevivientes sale
del ranking; después LAF1 sobre los productos que quedan.

**Pros**
- Evita recomendar un producto que después no se puede comprar como el usuario quiere.
- Conceptualmente simple: un filtro duro antes del razonamiento.

**Contras (con datos)**
- **LAF2 hoy no define "compra mala".** Sus reglas son todas positivas (`compraBuena :- cond`); no
  hay `~compraBuena` ni umbral. Para filtrar habría que inventar una regla negativa o un umbral
  sobre el puntaje, y `10` genera hechos solo cuando la condición se cumple, así que "no tiene
  envío" no es un hecho: la ausencia no puede disparar una regla. Sería otro programa, no LAF2.
- **Filtrar por condiciones recorta el catálogo de productos**, y lo recorta según datos del
  vendedor, no de la calidad del café. Medido: si se exige "alguna publicación con envío gratis",
  quedan 16/18 (histórico), 13/16 (instantáneo) y 13/19 (grano/molido) productos; si se exige
  garantía ≥ 6 meses quedan 4/18, 3/16 y 3/19. En grano/molido, 6 de los 7 productos
  artesanales de un solo vendedor desaparecerían con un filtro de envío + oficial.
- **Mezcla dos preguntas.** Un producto queda fuera porque su vendedor no ofrece envío gratis
  hoy; mañana otro vendedor lo publica y vuelve. Las reseñas son estables; las condiciones de
  compra cambian por snapshot (las publicaciones por producto varían: 9 → 11 en Xiapan, 26 → 38
  en Members Mark Moka entre histórico e instantáneo).
- Si en vez de filtro duro se hace "primero rankear publicaciones de todos los productos y quedarse
  con la mejor de cada uno", el precio normalizado deja de tener sentido (se normaliza dentro
  del producto, entre publicaciones del mismo café), y se termina en el diseño (c).

**Variante razonable dentro de (a).** Sin cambiar el orden, se puede mostrar en el ranking de LAF1
una **señal informativa** por producto ("N ofertas, la más barata $X, envío gratis disponible: sí/no")
calculada con los mismos hechos de `10`, sin que entre al puntaje. Eso ataca el contra principal de
(a) sin recortar el catálogo ni tocar LAF1. Es un cambio de interfaz, no de razonador.

## Diseño (c) — un solo programa o un solo puntaje (condiciones de compra como aspectos de LAF1)

**Cómo funcionaría.** Agregar `envioGratis`, `tiendaOficial`, `precioBueno`… como aspectos más de
LAF1, ya sea en el programa combinado o como criterios extra en `combine_rankings`.

**Contras (son de fondo)**
- **Objeto equivocado.** Los aspectos de LAF1 son del producto; el envío gratis es de una
  publicación. Para hacerlo aspecto de producto hay que agregar: ¿"tiene envío gratis" si alguna
  publicación lo tiene (Members Mark Moka: 21 de 26), si todas, si la más barata? Cualquier
  elección esconde información que LAF2 sí muestra: en el ejemplo de Taster's Choice Caramel, la
  publicación con garantía de 12 meses es justamente la que no tiene envío; a nivel producto ese
  compromiso desaparece.
- **Precio no normalizable entre productos.** `precioBueno` se calcula dentro del rango del
  producto (más barato 0,95, más caro 0,30). Entre productos compararía un Nescafé de 100 g con
  un Members Mark de 1,8 kg. Habría que inventar un precio por kilo o por porción que hoy no está
  en el pipeline.
- **Saturación medida.** EXP 2 y EXP 5 muestran que agregar más argumentos al mismo conflicto con
  operadores de Budán empuja todo a 1 y aplana. Sumar 4–7 condiciones a los 14 aspectos en el
  programa combinado empeora exactamente eso. En el multicriterio (suma ponderada) no saturaría,
  pero entonces las condiciones no pasarían por LAF: serían pesos externos, y se pierde la
  justificación argumentativa de LAF2 (que es lo que se quiere mostrar en el grafo).
- **Un solo puntaje mezcla escalas distintas**: confianza post-conflicto de reseñas (0–1, con
  incertidumbre bayesiana) y hechos deterministas de catálogo (0,95 fijo). El 0,95 de "tiene
  envío" pesaría más que el 0,55 de "buen sabor con 20 reseñas", sin que eso signifique nada.

**Pros**
- Un solo ranking, una sola pantalla. Menos pasos para el usuario.
- Formalmente "una KB, una consulta".

## Resumen comparativo

| criterio | (a) actual | (b) LAF2 primero | (c) unir |
|---|---|---|---|
| respeta producto ≠ publicación | sí | parcialmente | no |
| toca LAF1 validado | no | sí (recorta candidatos) | sí (cambia el programa o la suma) |
| riesgo de saturación/aplanamiento (EXP 2/5) | solo dentro de LAF2, a medir | igual que (a) | alto |
| necesita definir "compra mala" o precio entre productos | no | sí | sí |
| recorta catálogo por datos del vendedor | no | sí (hasta 15/19 fuera con garantía) | no |
| el usuario se entera tarde de malas condiciones | sí (mitigable con señal informativa) | no | no |
| explicable como grafo LAF chico | sí | depende | no (grafo enorme) |

## Mi recomendación (Ana decide)

Mantener **(a)** y validar LAF2 tal como está (pregunta 3), agregando dos cosas que **no** cambian
el razonador: (1) en el ranking de LAF1, una señal informativa por producto con lo que las
publicaciones ofrecen (sin entrar al puntaje); (2) en LAF2, tratar los productos de 1
publicación como "única oferta" y ocultar o marcar como "sin datos en este catálogo" los sliders
de cuotas y factura. Razones: es el único diseño coherente con "producto ≠ publicación", no
reabre LAF1, y evita el aplanamiento medido en EXP 2/5. Los contras de (a) son de interfaz y se
resuelven en la interfaz; los de (b) y (c) son de modelado.

Si el director prefiere (b), la forma menos dañina es un filtro **opcional y explícito** del
usuario ("mostrar solo productos con envío gratis") aplicado a la lista de candidatos antes de
LAF1, documentado como filtro y no como argumentación. (c) no lo recomiendo con los datos
actuales.

## Qué NO verifiqué

- Si Mercado Libre México expone cuotas en algún campo distinto de `tags` (solo miré `items_raw`).
- El comportamiento numérico de LAF2 (saturación, orden vs. preferencias): es la pregunta 3.
