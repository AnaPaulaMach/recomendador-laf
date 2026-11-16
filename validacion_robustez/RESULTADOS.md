# Experimento 2 — Robustez del orden (bootstrap) · RESULTADOS

**Fecha de la corrida:** 2026-09-10
**Snapshot:** `mlm_mlm194329_20260528_142014` (18 productos) · estrategia **D** · modelo `post_laf_multicriteria_v1`
**Semilla:** 20260910 (la réplica *i* usa 20260910 + *i*) · **200 réplicas**
**Corpus:** 12.050 reseñas con trust individual · 6.862 menciones · **4.668 reseñas con al menos una mención** (universo de remuestreo; mínimo 49 y máximo 588 por producto)
**Costo real:** 0,36 s por réplica · **82 s** en total

> Las definiciones, las métricas y el criterio de fracaso están fijados en
> `README.md` **antes** de correr. Este archivo sólo los aplica. No se tocó
> `src/`, `config/`, `webapp/` ni `LAF/`, y no se escribió nada en Supabase.

---

## 1. Controles previos (§6 del pre-registro)

| Control | Resultado |
|---|---|
| Reconstruir los hechos D fuera de Supabase e igualarlos a `product_aspect_trust` | **259 = 259 hechos**, mismas claves, mismos `agg_confidence`, `n_reviews`, `n_mentions` y `coverage_ratio` (tolerancia 1e-9). Cero diferencias. |
| Réplica 0 (sin remuestreo) contra la batería validada, perfil neutro | **orden idéntico 18/18** |
| Réplica 0 (sin remuestreo) contra la batería validada, perfil solo sabor | **orden idéntico 18/18** |
| Tamaño del remuestreo igual al universo, por producto y por réplica | verificado en las 200 réplicas (el script aborta si no) |

El control de la réplica 0 corre **dentro** de la corrida definitiva: si fallara,
el script se detiene antes de generar réplica alguna.

## 2. Resultado principal

| Perfil | ρ media | ρ mínimo | ρ p5 | ρ p95 | Top 3 conservado | Ganador conservado |
|---|---:|---:|---:|---:|---:|---:|
| neutro (0,67 en los 14) | **0,938** | 0,868 | 0,889 | 0,975 | 54,5 % | 89,5 % |
| solo sabor | **0,956** | 0,867 | 0,907 | 0,990 | 49,5 % | **41,0 %** |

**Criterio de fracaso pre-registrado** (ρ media < 0,80 en el perfil neutro):
**no se cumple**. El orden global no depende de qué reseñas concretas cayeron en
el corpus: en el peor de los 200 remuestreos la correlación con el ranking
original sigue siendo 0,87.

**Criterios secundarios** (informados, no decisorios):

- *Top 3 conservado en menos de la mitad de las réplicas*: **se cumple en «solo
  sabor»** (49,5 %) y queda al borde en neutro (54,5 %).
- *Algún producto con intervalo de puesto p5–p95 mayor a 8 posiciones*: **no se
  cumple**, pero el máximo observado es exactamente 8 en los dos perfiles.

## 3. El hallazgo que importa: el orden global es estable, la cabeza no

La estabilidad no está repartida por igual a lo largo del ranking.

**Perfil neutro** — quién quedó primero en cada una de las 200 réplicas:

| Producto | Veces #1 |
|---|---:|
| Blasón Espresso Robusto 1 kg | 179 (89,5 %) |
| Blasón Gourmet Espresso 400 g | 10 (5,0 %) |
| La Parroquia Puro 1 kg | 10 (5,0 %) |
| Taster's Choice Caramel 100 g | 1 (0,5 %) |

**Perfil solo sabor** — quién quedó primero:

| Producto | Veces #1 |
|---|---:|
| Capuccino Vainilla MM 1,8 kg | 82 (41,0 %) |
| Capuccino Moka MM 1,8 kg | 53 (26,5 %) |
| Blasón Gourmet Americano 1 kg | 50 (25,0 %) |
| Blasón Espresso Robusto 1 kg | 13 (6,5 %) |
| Taster's Choice Caramel 100 g | 2 (1,0 %) |

En el perfil «solo sabor», **el producto que la interfaz rotula «Mejor opción
para vos» sólo se sostiene en 41 de cada 100 remuestreos.** Tres productos
distintos se reparten el primer puesto en el 92,5 % de las réplicas.

La causa es directa y verificable en la propia salida de la batería: en «solo
sabor» los cuatro primeros puntajes son 0,6412 · 0,6403 · 0,6313 · 0,6313. La
diferencia entre el primero y el segundo es **0,0009**. El sistema los está
declarando distintos con una diferencia que el propio corpus no sostiene.

En el perfil neutro el problema es mucho menor (ganador estable en el 89,5 %) y
el primer puesto nunca sale del conjunto {Blasón Espresso, Gourmet Espresso,
La Parroquia, Taster's Choice}: el top 3 original más Taster's Choice, que en el
corpus original está 6.º y llega a la punta una sola vez en 200 réplicas.

## 4. Intervalo de puesto por producto

![Intervalos de puesto, perfil neutro](../docs/figuras/figura_robustez_intervalos_puesto_neutro.png)

Fuente de la figura: `docs/figuras/figura_robustez_intervalos_puesto_neutro.svg`
(y su equivalente `_solo_sabor`), dibujadas según `docs/figuras/ESTILO_FIGURAS.md`
y exportadas a PNG en escala 3 con `docs/figuras/exportar_figura.ps1`.

**Perfil neutro:**

| # | Producto | p5 | mediana | p95 | Amplitud |
|---:|---|---:|---:|---:|---:|
| 1 | Blasón Espresso Robusto 1 kg | 1 | 1 | 2 | 1 |
| 2 | Blasón Gourmet Espresso 400 g | 2 | 2 | 5 | 3 |
| 3 | La Parroquia Puro 1 kg | 2 | 3 | 6 | 4 |
| 4 | Blasón Gourmet Americano 1 kg | 3 | 4 | 7 | 4 |
| 5 | Capuccino Moka MM 1,8 kg | 4 | 5,5 | 7 | 3 |
| 6 | Taster's Choice Caramel 100 g | 3 | 5 | 8 | 5 |
| 7 | Capuccino Vainilla MM 1,8 kg | 5 | 7 | 8 | 3 |
| 8 | Nescafé Reserva Xiapan 180 g | 5 | 8 | 11 | 6 |
| 9 | Nescafé Clásico Professional 1 kg | 8 | 9 | 12 | 4 |
| 10 | Nescafé Clásico frasco 200 g | 8 | 10 | 11 | 3 |
| 11 | Nescafé Decaf 170 g | 10 | 13 | 17 | 7 |
| 12 | Nescafé Clásico ICE 170 g | 11 | 13 | 17 | 6 |
| 13 | Nescafé Clásico bolsa 400 g | 11 | 13 | 17 | 6 |
| 14 | Nescafé Café de Olla 170 g | 9 | 13 | 17 | **8** |
| 15 | Nescafé Clásico sin gluten 400 g | 9 | 13 | 17 | **8** |
| 16 | Juan Valdez Tripack 95 g | 13 | 16 | 18 | 5 |
| 17 | Blasón Arábico 900 g | 14 | 17 | 18 | 4 |
| 18 | Nescafé Reserva Verarica 180 g | 15 | 17 | 18 | 3 |

Lectura: los extremos del ranking son firmes —el primero casi no se mueve y los
tres últimos tampoco—, y la **zona media, entre los puestos 11 y 15, es
intercambiable**: cinco productos comparten prácticamente el mismo intervalo
(9–17). Decir «este está 12.º y este otro 14.º» no está respaldado por la
evidencia; decir «estos cinco están en la mitad de abajo» sí.

## 5. Aspectos de baja cobertura: `tueste` y `acidez`

Sólo una minoría de productos tiene evidencia en estos dos aspectos, y en
algunos esa evidencia es tan escasa que el hecho **desaparece** al remuestrear.

**`tueste`** — 7 de 18 productos generan hecho positivo en alguna réplica:

| Producto | α⁺ original | Media | p5 | p95 | Réplicas sin hecho |
|---|---:|---:|---:|---:|---:|
| Blasón Espresso Robusto 1 kg | 0,634 | 0,632 | 0,577 | 0,676 | 0 |
| Blasón Gourmet Americano 1 kg | 0,596 | 0,594 | 0,545 | 0,641 | 1 |
| La Parroquia Puro 1 kg | 0,587 | 0,584 | 0,541 | 0,627 | 0 |
| Blasón Gourmet Espresso 400 g | 0,556 | 0,555 | 0,520 | 0,594 | 3 |
| Blasón Arábico 900 g | 0,551 | 0,551 | 0,521 | 0,597 | 14 |
| Taster's Choice Caramel 100 g | 0,536 | 0,537 | 0,508 | 0,569 | 3 |
| Nescafé Clásico Professional 1 kg | 0,519 | 0,532 | 0,519 | 0,569 | **71** |

**`acidez`** — 6 de 18 productos:

| Producto | α⁺ original | Media | p5 | p95 | Réplicas sin hecho |
|---|---:|---:|---:|---:|---:|
| La Parroquia Puro 1 kg | 0,626 | 0,624 | 0,578 | 0,675 | 0 |
| Blasón Espresso Robusto 1 kg | 0,564 | 0,562 | 0,524 | 0,605 | 2 |
| Blasón Gourmet Espresso 400 g | 0,547 | 0,549 | 0,510 | 0,592 | 12 |
| Nescafé Reserva Xiapan 180 g | 0,530 | 0,532 | 0,511 | 0,563 | **30** |
| Taster's Choice Caramel 100 g | 0,525 | 0,528 | 0,512 | 0,557 | 24 |
| Blasón Gourmet Americano 1 kg | 0,520 | 0,522 | 0,510 | 0,547 | **28** |

Dos cosas:

1. **La media de las réplicas coincide con el valor original** en todos los casos
   (diferencias en la tercera decimal). No hay sesgo: el bootstrap no corre el
   valor, sólo lo dispersa.
2. **El α⁺ de estos aspectos se mueve poco en magnitud** (amplitud p5–p95 entre
   0,036 y 0,099), pero **el hecho entero puede no existir**. En Nescafé Clásico
   Professional el tueste desaparece en 71 de 200 réplicas; en Reserva Xiapan la
   acidez desaparece en 30. Y como un aspecto sin hecho aporta **0** a la suma
   ponderada (hallazgo R1 de `docs/CHEQUEO_HUMANO_LAF1.md`), la desaparición
   pesa mucho más que el corrimiento del valor. Ahí está buena parte del
   movimiento de la zona media del ranking.

## 6. Observación sobre los hechos negativos (relacionada con R3)

Este descriptivo no estaba entre las métricas decisorias; se informa porque
toca un hallazgo abierto del chequeo humano.

**54 pares (producto, aspecto) tienen un hecho negativo que aparece en algunas
réplicas y no en otras.** La mediana es de 131 réplicas de 200: un hecho negativo
típico de este grupo **se evapora en aproximadamente un tercio de los
remuestreos**. Los 54 estaban presentes en el corpus original; ninguno aparece
que no estuviera antes, cosa esperable —el bootstrap no puede inventar una
crítica donde no había ninguna.

Esto le pone un número a R3. La discontinuidad entre 0 y 1 mención negativa que
`docs/CHEQUEO_HUMANO_LAF1.md` describe cualitativamente no es un caso raro: es
un salto que el corpus cruza sin esfuerzo en un tercio de los remuestreos, y
cada vez que lo cruza el producto cambia de «Sin objeciones» a «Discutido» y
pierde posiciones. **No se cambió nada**: R3 sigue siendo una decisión
metodológica pendiente con el director (ver `validacion_laf1/EXP8_NEGATIVO_SIN_PRIOR.md`,
no adoptado).

## 7. Qué se puede afirmar y qué no

**Se puede afirmar:**

- El orden global del ranking **no depende de qué reseñas particulares** integran
  el corpus: ρ media 0,94 en el perfil neutro y 0,96 en «solo sabor», con un
  mínimo de 0,87 en 200 remuestreos.
- Los **extremos del ranking son firmes**: el primero del perfil neutro se
  sostiene en el 89,5 % de las réplicas y los tres últimos casi no se mueven.
- La **media de α⁺ no se corre** al remuestrear: el valor congelado no es un
  artefacto de la muestra.

**No se puede afirmar:**

- Que las **diferencias finas entre puestos vecinos** signifiquen algo. En la
  zona media del perfil neutro cinco productos comparten intervalo.
- Que el **ganador del perfil «solo sabor»** sea el mejor en sabor: se sostiene
  en el 41 % de las réplicas y hay tres candidatos separados por menos de 0,01.
- Nada sobre **calidad**. Un ranking puede ser estable y estar establemente
  equivocado. Eso lo mide el experimento 1, no este.

## 8. Archivos

| Archivo | Qué contiene |
|---|---|
| `README.md` | pre-registro |
| `bootstrap_ranking.py` | remuestreo, recálculo, ranking y métricas |
| `figura_intervalos.py` | SVG de la figura + exportación a PNG escala 3 |
| `salidas/rankings_neutro_20260910.csv` | 200 × 18 filas: réplica, semilla, puesto, producto, puntaje |
| `salidas/rankings_solo_sabor_20260910.csv` | ídem |
| `salidas/alpha_baja_cobertura_20260910.csv` | α⁺ de `tueste` y `acidez` por producto y réplica |
| `salidas/resumen_20260910.json` | todas las métricas |
| `docs/figuras/figura_robustez_intervalos_puesto_{neutro,solo_sabor}.svg` / `.png` | figura |

Para reproducir: `python validacion_robustez/bootstrap_ranking.py --replicas 200`
seguido de `python validacion_robustez/figura_intervalos.py --perfil neutro`.

## 9. Limitaciones

- **El bootstrap remuestrea el corpus observado.** Si el corpus tiene un sesgo
  sistemático —reseñas de 5 estrellas sobrerrepresentadas, productos más
  vendidos con más reseñas—, cada réplica lo reproduce. Mide variabilidad de
  muestreo, **no sesgo**.
- **Sólo participan las reseñas con al menos una mención** (4.668 de 12.050 con
  trust). Las que no produjeron ninguna mención no entran ni se cuestionan.
- **El error de extracción no está en estos intervalos.** La polaridad acierta
  ~83 % (`docs/ESTADO_DATASETS_CAFE.md`) y cada fragmento mal clasificado sigue
  mal clasificado en las 200 réplicas. La incertidumbre real del sistema es
  mayor que la que muestran estas barras.
- **Los parámetros congelados no se remuestrean**: `PRIOR_WEIGHT`, los pesos del
  trust y las confianzas de las reglas se mantienen fijos.
- **Un solo snapshot y dos perfiles.**
- **Estabilidad no es corrección.** Este experimento no dice si el orden es bueno.

---

## 10. Corrida sobre la configuración definitiva (fila 13)

**Fecha:** 2026-09-10 (misma fecha que la corrida previa; las salidas previas quedaron con sufijo `_pre_fila13`). **Qué cambió entre las dos corridas:** sólo la configuración congelada de Café: se agregaron las reglas `~recomendar(X) :- ~valorBueno(X). {0.80; 1.00}` y `~recomendar(X) :- ~elaboracionBueno(X). {0.75; 1.00}` (fila 13, confianza simétrica; ver `validacion_laf1/EXP11_FILA13_IMPACTO.md` y `validacion_laf1/salidas/recongelado_20260910/RESUMEN.md`). Misma semilla (20260910), mismas 200 réplicas, mismo corpus (12050 reseñas con trust, 6862 menciones, 4.668 reseñas con al menos una mención), 0.217 s por réplica.

**Controles (§6):** los hechos reconstruidos siguen siendo 259 = 259; la réplica 0 sin remuestreo reproduce la batería **nueva** (`battery_multicriterio_mlm194329_20260528_142014.json`, regenerada tras el recongelado) en **neutro 18/18 y solo sabor 18/18**. Nota de procedimiento: una primera corrida se lanzó mientras `validacion_oe5/metrics.py` estaba regenerando esa batería y el script avisó «no se encontró la salida de la batería; control parcial»; se descartó (`bootstrap_run_sin_control_descartado.log`) y se volvió a correr con el control completo. Ambas corridas dieron números idénticos, como corresponde a la semilla fija.

### 10.1 Resultado principal, previa vs. definitiva

| Perfil | Corrida | ρ media | ρ mínimo | ρ p5 | ρ p95 | Top 3 conservado | Ganador conservado |
|---|---|---:|---:|---:|---:|---:|---:|
| neutro (0,67 en los 14) | previa (pre fila 13) | 0.938 | 0.868 | 0.888 | 0.975 | 54.5 % | 89.5 % |
| neutro (0,67 en los 14) | **definitiva (fila 13)** | 0.929 | 0.823 | 0.872 | 0.971 | 48.5 % | 94.5 % |
| solo sabor | previa (pre fila 13) | 0.956 | 0.867 | 0.907 | 0.990 | 49.5 % | 41.0 % |
| solo sabor | **definitiva (fila 13)** | 0.956 | 0.867 | 0.907 | 0.990 | 49.5 % | 41.0 % |

**Criterio de fracaso pre-registrado** (ρ media < 0,80 en neutro): **no se cumple** tampoco con la configuración definitiva (ρ media 0.929, mínimo 0.823 en 200 remuestreos).

**Lectura de la comparación:**

- **Solo sabor no cambia en nada** (mismos cuatro decimales en todas las métricas). Es lo esperado: las reglas nuevas sólo tocan las corridas por aspecto de rendimiento, tamaño, preparación y molienda, y el perfil «solo sabor» sólo usa la de sabor.
- **Neutro pierde algo de estabilidad global** (ρ media 0.938 → 0.929; mínimo 0.868 → 0.823; top 3 conservado 54.5 % → 48.5 %) **y gana estabilidad en la cabeza** (ganador conservado 89.5 % → 94.5 %). Tiene sentido: ahora hay 12 hechos negativos más que participan del resultado y que, como todos los negativos, se evaporan en parte de los remuestreos (§6), así que hay más fuentes de variación en la zona media; a la vez, La Parroquia, que en la corrida previa le quitaba el primer puesto a Blasón en 10 réplicas, ya no lo alcanza porque sus críticas de molienda, rendimiento y tamaño ahora pesan.
- El criterio secundario del top 3 (conservado en menos de la mitad de las réplicas) **ahora se cumple también en neutro** (48.5 %), no sólo en solo sabor. El máximo ancho de intervalo p5–p95 sigue siendo exactamente 8 puestos en los dos perfiles.

### 10.2 Quién quedó primero (neutro), previa vs. definitiva

| Producto | Veces #1 previa | Veces #1 definitiva |
|---|---:|---:|
| MLM26912881 cafe blason espresso robusto | 179 (89.5 %) | 189 (94.5 %) |
| MLM41148521 cafe gourmet molido espresso | 10 (5.0 %) | 10 (5.0 %) |
| MLM16250244 nescafe taster s choice | 1 (0.5 %) | 1 (0.5 %) |
| MLM19543513 cafe molido la parroquia | 10 (5.0 %) | 0 (0.0 %) |

En «solo sabor» la distribución de ganadores es idéntica a la previa: MLM19566313 cafe capuccino vainilla francesa 82; MLM19544520 cafe capuccino moka members 53; MLM25263480 cafe gourmet tostado y 50; MLM26912881 cafe blason espresso robusto 13; MLM16250244 nescafe taster s choice 2.

### 10.3 Intervalo de puesto por producto (neutro): qué se movió

| Producto | Puesto original previa → definitiva | p5–p95 previa | p5–p95 definitiva |
|---|---|---|---|
| MLM26912881 cafe blason espresso robusto | 1 → 1 | 1–2 | 1–2 |
| MLM41148521 cafe gourmet molido espresso | 2 → 2 | 2–5 | 2–4 ◄ |
| MLM25263480 cafe gourmet tostado y | 4 → 3 | 3–7 | 2–6 ◄ |
| MLM16250244 nescafe taster s choice | 6 → 4 | 3–8 | 2–8 ◄ |
| MLM19566313 cafe capuccino vainilla francesa | 7 → 5 | 5–8 | 4–8 ◄ |
| MLM19544520 cafe capuccino moka members | 5 → 6 | 4–7 | 4–9 ◄ |
| MLM19543513 cafe molido la parroquia | 3 → 7 | 2–6 | 2–10 ◄ |
| MLM16207894 nescafe reserva xiapan cafe | 8 → 8 | 5–11 | 4–11 ◄ |
| MLM20999002 cafe soluble nescafe clasico | 9 → 9 | 8–12 | 6–11 ◄ |
| MLM19663240 nescafe clasico cafe 100 | 10 → 10 | 8–11 | 8–10 ◄ |
| MLM16250253 nescafe decaf cafe 100 | 11 → 11 | 10–17 | 10–17 |
| MLM16207863 nescafe cafe de olla | 14 → 12 | 9–17 | 9–17 ◄ |
| MLM23633481 nescafe clasico ice cafe | 12 → 13 | 11–17 | 11–18 ◄ |
| MLM27068249 tripack juan valdez cafe | 16 → 14 | 13–18 | 12–18 ◄ |
| MLM16250252 nescafe clasico de cafe | 15 → 15 | 9–17 | 9–17 |
| MLM43007251 cafe molido 100 arabico | 17 → 16 | 14–18 | 13–18 ◄ |
| MLM16207890 nescafe reserva verarica cafe | 18 → 17 | 15–18 | 14–18 ◄ |
| MLM20075768 nescafe clasico cafe 100 | 13 → 18 | 11–17 | 13–18 ◄ |

(◄ = cambió el puesto original o el intervalo.)

### 10.4 Hechos negativos inestables

**54 pares (producto, aspecto)** con un hecho negativo que aparece en algunas réplicas y no en otras, mediana 131 réplicas de 200. **Antes: 54**, mediana 131. No cambia, y no podía cambiar: este descriptivo depende del remuestreo de los hechos, no de las reglas; la fila 13 no agrega ni quita hechos (siguen siendo 259), sólo hace que 12 de los negativos ya existentes lleguen a `~recomendar`. Lo que sí cambia es su consecuencia: antes, de esos 54 pares inestables, los de rendimiento/tamaño/preparación/molienda se evaporaban sin efecto sobre el ranking; ahora su aparición o desaparición mueve puestos, y eso es parte de la caída de ρ media en neutro.

### 10.5 Archivos de esta corrida

| Archivo | Contenido |
|---|---|
| `salidas/rankings_neutro_20260910.csv`, `salidas/rankings_solo_sabor_20260910.csv` | 200 × 18, configuración definitiva |
| `salidas/alpha_baja_cobertura_20260910.csv`, `salidas/resumen_20260910.json` | métricas, configuración definitiva |
| `salidas/*_pre_fila13.*` | la corrida previa (§1–§9), conservada |
| `docs/figuras/figura_robustez_intervalos_puesto_{neutro,solo_sabor}.svg/.png` | figura regenerada; la previa quedó como `*_pre_fila13.*` |
| `validacion_laf1/salidas/recongelado_20260910/despues/bootstrap_run.log` | consola completa de la corrida, con los controles |

Las secciones §1–§9 describen la corrida previa y se conservan tal cual como registro; para la tesis vale esta sección.
