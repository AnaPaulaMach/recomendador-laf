# Experimento 1 — Por qué difieren la jueza y el sistema (ANÁLISIS POSTERIOR)

> ⚠️ **Este análisis NO está pre-registrado.** Se escribió **después** de ver las
> respuestas. No modifica ninguna cifra de `RESULTADOS.md` ni el criterio de
> fracaso, que se cumplió y se informa como se había fijado. Sirve para
> **explicar** un desacuerdo, no para relativizarlo. Todo lo que sigue sale de
> `analisis_post_hoc.py` y de `salidas/analisis_post_hoc_20260910.csv`.

**Fecha:** 2026-09-10 · Snapshot `mlm_mlm194329_20260528_142014` · aspecto `sabor`

---

## 1. El resultado que hay que explicar

El acuerdo jueza–sistema fue **7 de 14 pares con veredicto (50 %)**, y **1 de 4
(25 %) en la franja de diferencia grande**, que es donde el pre-registro fijaba
el criterio. El criterio de fracaso se cumplió.

Lo primero que había que descartar es que la jueza estuviera respondiendo al
azar. No lo estaba.

## 2. Los dos criterios

Se contrastaron dos hipótesis sobre qué está usando cada parte para decidir.

| Hipótesis | Se cumple en |
|---|---|
| **El sistema** elige el lado con **más menciones de sabor en el corpus** | **17 de 20 pares (85 %)** |
| **La jueza** elige el lado con **menos críticas entre los 15 fragmentos mostrados** | **11 de 12 pares (92 %)** |
| Acuerdo entre ambos (referencia) | 7 de 14 (50 %) |

Las dos partes son **muy consistentes consigo mismas y consistentemente
distintas entre sí**. Esto no es ruido: son dos criterios coherentes que
compiten.

Los comentarios de la jueza lo dicen sin ambigüedad, y fueron escritos sin ver
nada del sistema:

> «Esta muy peleado pero B tiene una negativa y A no» (P02, P04, P17)
> «Estuvo peleado pero la critica al sabor de B es mas fuerte» (P03)
> «Ambos 1 critica pero la de A es mas fuerte» (P08)
> «Si bien A tiene mas criticas B tiene una de sabor que A no» (P11)

Y cuando no hay críticas de ningún lado, no elige: de los **7 pares sin ninguna
crítica mostrada**, respondió «no puedo decidir» en **5**. De los **13 pares con
alguna crítica**, sólo en **1**. La ausencia de crítica es lo que la deja sin
criterio, lo cual confirma que la crítica *es* su criterio.

## 3. Por qué el diseño garantizó que difirieran

Acá está el problema, y es del experimento tanto como del sistema.

El sistema ordena por **cuánta evidencia hay**. Ya estaba medido antes de esto:
`docs/CHEQUEO_HUMANO_LAF1.md` §4b reporta ρ = 0,88 entre el puntaje de sabor y el
número de menciones positivas, contra ρ = 0,43 con la proporción de positivas y
ρ = 0,45 con las estrellas. Este experimento lo vuelve a confirmar por otra vía:
el 85 % de las veces gana el lado con más menciones.

Pero el material **le muestra a la jueza exactamente 15 fragmentos por lado,
siempre**. Un producto con 477 menciones de sabor y otro con 41 se presentan
idénticos en tamaño. **El volumen —la señal principal del sistema— es invisible
por construcción del experimento.** La jueza no podía usarla aunque hubiera
querido; lo único que podía leer era la proporción de crítica dentro de la
muestra, que es justamente lo que el sistema casi no usa.

En los 20 pares, el lado con más menciones tenía entre **1,1 y 10,8 veces** las
menciones del otro (P18: 477 contra 44; P13: 397 contra 41; P16: 392 contra 44).
Nada de esa diferencia llegó a la planilla.

El pre-registro declaraba esta limitación en §12 —«15 fragmentos por lado son una
muestra de hasta 477 menciones: el juez ve una ventana, el sistema ve todo»—,
pero **subestimó su consecuencia**: no es que el juez vea menos, es que no ve la
variable que decide el ranking.

## 4. La observación de la jueza: trust invisible

Al terminar, Ana señaló por su cuenta que en el material **no ve la longitud de
la reseña, ni si tiene imágenes, ni los likes**. Es exacto, y es una segunda
capa del mismo problema.

El peso de cada mención en el sistema es `trust × extraction_confidence`, y el
trust se compone de (`src/06_trust.py:334`): base 0,30 + relevancia hasta 0,30 +
0,15 si tiene imagen o video + hasta 0,20 por likes − 0,15 si el texto tiene
menos de 20 caracteres. **Ninguno de esos cinco componentes es visible en el
fragmento.**

Y no es un detalle despreciable. Medido sobre las 12.050 reseñas con trust del
snapshot:

| | valor |
|---|---:|
| mínimo | 0,160 |
| percentil 5 | 0,160 |
| mediana | 0,350 |
| percentil 95 | 0,600 |
| máximo | 0,950 |
| media (desvío) | 0,347 (0,148) |

**Una reseña del percentil 95 pesa 3,75 veces más que una del percentil 5**, y
esa diferencia se decide por likes, imágenes y largo, no por lo que dice. Dos
fragmentos que la jueza lee como equivalentes pueden entrar al cálculo con pesos
muy distintos.

## 5. Qué se puede concluir, entonces

**Lo que el criterio pre-registrado obliga a decir, y se dice:** el orden por
aspecto del sistema **no coincide con una lectura humana ciega de la evidencia**
en los pares donde el sistema declara una diferencia grande. 1 de 4. Eso va a la
tesis tal cual, sin atenuantes.

**Lo que el análisis posterior agrega, declarado como posterior:** el desacuerdo
no es aleatorio ni un fallo de la jueza. Son dos criterios distintos, cada uno
internamente coherente:

- el sistema responde a **cuánta gente habló bien de un aspecto**;
- la persona responde a **si alguien habló mal**.

Y hay una consecuencia que trasciende este experimento: **una persona que lee las
reseñas de dos productos no puede reconstruir el orden del sistema**, porque ese
orden depende de cuántas reseñas existen y de cuánto pesa cada una —volumen,
likes, imágenes, longitud—, y nada de eso está en el texto que la persona lee.
Eso convierte al ranking en algo que la evidencia mostrada no puede justificar
por sí sola, y conecta directamente con lo que Ana ya había rechazado en el
chequeo de septiembre: las explicaciones «no sé de dónde salen».

**Lo que este experimento NO prueba:** que el sistema esté equivocado. Ordenar
por volumen de evidencia es una decisión defendible —más respaldo es más
confianza, que es exactamente lo que α mide— y Ana misma la había avalado en
septiembre («para mí más reseñas es mejor, pero es relativo»). Lo que queda
probado es que **esa decisión no es legible desde la evidencia**, y que un lector
humano aplica otro criterio.

## 6. Qué haría falta para separar las dos cosas

Este experimento no puede distinguir «el sistema ordena mal» de «el experimento
escondió la señal del sistema». Para separarlo haría falta un diseño distinto,
que **no se hizo y no se propone hacer ahora sin decidirlo con el director**:
mostrar la misma evidencia **más** el número total de opiniones de cada lado, y
ver si el acuerdo sube. Si subiera, la conclusión sería «el criterio del sistema
es legible pero el material lo ocultaba»; si no subiera, sería «el criterio del
sistema no es el de un lector humano ni siquiera informándolo».

Cualquiera de esas dos corridas sería un experimento nuevo, con su propio
pre-registro escrito antes.

## 7. Limitaciones de este análisis

- **Es post hoc.** Las dos hipótesis se formularon después de leer los
  comentarios de la jueza. Que ajusten al 85 % y al 92 % es sugerente, no
  confirmatorio: nadie las puso a prueba antes de mirar.
- **n = 1 jueza**, que además es la autora del sistema (en ciego, pero autora).
- **12 pares** para la hipótesis de la jueza, **20** para la del sistema.
- «Menos críticas mostradas» se calculó con la polaridad que asigna el propio
  extractor, que acierta ~83 %. La jueza leyó el texto, no la etiqueta, así que
  las dos cuentas no son idénticas.
- La medición del trust describe el corpus completo, no específicamente las
  menciones mostradas.
