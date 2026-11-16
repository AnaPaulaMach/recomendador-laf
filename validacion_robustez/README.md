# Experimento 2 — Robustez del orden (bootstrap sobre reseñas) (PRE-REGISTRO)

**Estado: PRE-REGISTRO. Escrito ANTES de correr nada.**
**Fecha de redacción: 2026-09-10.** Pendiente de aprobación de Ana Paula Machado.

Definiciones operativas, procedimiento, métricas y criterio de fracaso fijados
antes de la primera réplica. Cualquier cambio posterior a la aprobación se anota
al pie, con fecha y motivo; el cuerpo no se edita.

---

## 1. Pregunta

¿Cuánto del orden que produce el sistema depende de **qué reseñas concretas** cayeron
en el corpus? Si al reemplazar el corpus por otro del mismo tamaño, extraído del
mismo pozo, el orden se desarma, entonces el ranking describe una muestra y no un
producto, y hay que decirlo.

Es el punto 5 del protocolo de comparación de `docs/GUIA_METODOLOGICA.md` §9
(«Robustez: repetir el cálculo con submuestras de reseñas y observar si el ranking
permanece estable»), que quedó sin ejecutar.

## 2. Qué NO mide

- No mide si el orden es **correcto** (eso es el experimento 1). Un sistema
  estable puede estar establemente equivocado.
- No mide error de extracción: las polaridades se toman como están.
- No mide incertidumbre de la elección de parámetros (`PRIOR_WEIGHT`, pesos del
  trust). Esos están congelados y no se remuestrean.
- No es un intervalo de confianza frecuentista sobre una población de reseñas
  bien definida. Es un bootstrap no paramétrico sobre el corpus observado, y su
  interpretación es «sensibilidad a la composición del corpus», no «probabilidad
  de que el puesto verdadero esté acá».

## 3. Entradas congeladas

| Elemento | Valor | Verificado en |
|---|---|---|
| `dataset_key` | `mlm_mlm194329_20260528_142014` | `docs/ESTADO_DATASETS_CAFE.md` |
| Productos | 18 incluidos | consulta 2026-09-10 |
| Estrategia de trust | D (`PRIOR_MEAN=0,50`, `PRIOR_WEIGHT=10`) | `src/06_trust.py:99-100` |
| Modelo de decisión | `post_laf_multicriteria_v1` | `webapp/.../evaluators.py` |
| Motor | `laf-api` de Javi, `http://localhost:8088/api/graph` | verificado 2026-09-10 |
| Perfiles | neutro (los 14 aspectos en 0,67) y «solo sabor» (sabor 1,0; resto 0,0) | decisión de Ana |
| Réplicas | **200** | ver §7 |
| Semilla | **20260910** | §5 |

Sobre el perfil neutro: la interfaz usa 0,67 y la batería usaba 0,5. Como
`normalized_multicriteria_ranking` divide por la suma de los pesos activos, con
pesos uniformes el orden y los puntajes son idénticos con 0,67 y con 0,5 (ya
comprobado en `docs/CHEQUEO_HUMANO_LAF1.md` §4). Se usa **0,67** por ser el de la
interfaz.

## 4. Definiciones operativas

### 4.1 Unidad de remuestreo

La **reseña**, no la mención. Para cada producto, su universo de remuestreo son las
reseñas distintas (`review_id`) que tienen **al menos una fila en `review_aspects`**
para ese producto, con cualquier aspecto y cualquier polaridad. Se remuestrea **con
reemplazo**, al **mismo tamaño** que el universo original de ese producto. Los
productos se remuestrean de forma independiente.

Todas las menciones de una reseña sorteada entran juntas: si una reseña habla de
sabor y de aroma, sus dos menciones viajan juntas en cada extracción. Ese es el
punto de remuestrear la reseña y no la mención.

### 4.2 Identidad de las copias (detalle crítico)

`06_trust.py` colapsa las repeticiones con la clave
`(review_id, product_id, aspect, polarity)` y se queda con el máximo. Si una reseña
sale sorteada tres veces y conserva su `review_id`, el colapso la vuelve a dejar en
**una sola** contribución y el bootstrap no remuestrea nada.

Por eso, en cada réplica, la copia *k* de la reseña *r* recibe un
**`review_id` sintético distinto** (`f"{r}#{k}"`), de modo que las tres copias
cuentan como tres contribuciones, igual que si fueran tres reseñas distintas que
dijeran lo mismo. Su `trust_score` es el de la reseña original.

**Este detalle se verifica explícitamente** con el control de §6.2: si la
sustitución de identidad estuviera mal, la réplica sin remuestreo no reproduciría
el ranking original.

### 4.3 Qué se recalcula y qué no

| Magnitud | ¿Se recalcula? | Por qué |
|---|---|---|
| `trust_score` de la reseña (t) | **No** | Es función de `relevance`, `likes`, `has_media` y `content_length` de esa reseña (`src/06_trust.py:334`). No depende de qué otras reseñas hay en el corpus, así que remuestrear no lo cambia. Se lee de `review_trust` y se reusa verbatim. |
| `extraction_confidence` de la mención | No | Propiedad de la extracción, idem. |
| W⁺ y W⁻ por (producto, aspecto) | **Sí** | Son sumas sobre el corpus remuestreado. |
| α⁺ y α⁻ (`agg_confidence` de D) | **Sí** | Vía `d_evidence_decomposition`. |
| `n_reviews`, `n_mentions`, `coverage_ratio` | **Sí** | Los recalcula `build_product_aspect_rows`. |
| Reglas, β, umbrales, operadores | **No** | Metodología congelada. |

Las funciones se **importan** de `src/06_trust.py` (`add_aspect_evidence`,
`group_review_evidence`, `build_product_aspect_rows`) y el programa LAF se construye
con `build_laf1` de `src/08_laf1_generate.py`. **No se reescribe ninguna fórmula.**
No se escribe nada en Supabase: `src/`, `config/`, `webapp/` y `LAF/` quedan intactos.

### 4.4 Ranking de una réplica

Idéntico al de la batería validada: por cada uno de los 14 aspectos se construye el
programa con `{aspecto: 1,0; resto: 0,0}`, se filtra con `zero_threshold_payload`,
se manda a `laf-api` y se lee el puntaje con `LAFGraphRankingMapper`; después se
combina con `combine_rankings` usando las preferencias del perfil como pesos. Las
14 corridas por aspecto **no dependen del perfil**, así que se hacen una vez por
réplica y sirven para los dos perfiles.

Un producto que en una réplica se queda sin ninguna mención de un aspecto no genera
hecho y aporta 0 en la suma ponderada de ese aspecto. Es el comportamiento real del
sistema (hallazgo R1 de `docs/CHEQUEO_HUMANO_LAF1.md`), y se conserva.

### 4.5 Puesto y empates

El puesto de un producto en una réplica es su posición 1–18 en el orden que devuelve
`combine_rankings`, que desempata por `entity_id` en minúsculas. Para la ρ de
Spearman, en cambio, se usan **rangos promediados** sobre el puntaje (no el puesto
desempatado por id), para que un empate real no se cuente como una diferencia de
orden que el sistema no afirma.

## 5. Semilla

Semilla maestra declarada: **`SEMILLA = 20260910`**. La réplica *i* usa
`random.Random(20260910 + i)`, con *i* de 1 a 200. La réplica **0** es la corrida de
control **sin remuestreo** (§6.2). Cada CSV de salida lleva su número de réplica y
su semilla en el encabezado.

## 6. Verificaciones obligatorias antes de aceptar cualquier resultado

### 6.1 Reconstrucción de los hechos — YA VERIFICADA (2026-09-10)

Reconstruir los hechos de la estrategia D fuera de Supabase, a partir de
`review_trust` + `review_aspects` con las funciones de `06_trust.py`, y compararlos
con `product_aspect_trust`:

> **259 hechos reconstruidos, 259 en la base, mismas claves
> (producto, aspecto, polaridad), y `agg_confidence`, `n_reviews`, `n_mentions` y
> `coverage_ratio` idénticos en los 259 (tolerancia 1e-9). Cero diferencias.**

### 6.2 Cadena completa — YA VERIFICADA (2026-09-10)

Pasar esos hechos reconstruidos por `build_laf1` → `laf-api` → `combine_rankings` y
comparar contra `validacion_laf1/salidas/battery_multicriterio_mlm194329_20260528_142014.json`:

> **Perfil neutral: orden idéntico 18/18 y puntajes idénticos a 6 decimales.
> Perfil solo_sabor: orden idéntico 18/18 y puntajes idénticos a 6 decimales.**

Esta comprobación se re-ejecuta como **réplica 0** dentro de la corrida definitiva,
y si fallara el script aborta antes de producir las 200 réplicas.

### 6.3 Control del propio remuestreo

En cada réplica se comprueba que, para cada producto, el número de reseñas
sorteadas es igual al del universo original. Si no, el script falla.

## 7. Costo — medido, no estimado

Medido el 2026-09-10 sobre el snapshot y el `laf-api` reales:

- una corrida de `laf-api` para un aspecto: **0,01–0,02 s** (31 hechos, 64 reglas);
- las **14 corridas por aspecto** de una réplica, incluyendo construir el programa
  y parsearlo: **0,27 s**.

Extrapolación: 200 réplicas ≈ **1 minuto** de motor, más el remuestreo y la
agregación en Python. **No hace falta bajar a 100 réplicas ni aproximar el motor.**
Se corren las 200. La lectura de Supabase se hace **una sola vez** al inicio
(12.050 filas de `review_trust` y 6.862 de `review_aspects`) y se cachea en memoria;
las réplicas no vuelven a tocar la base.

## 8. Métricas

Salen todas de `bootstrap_ranking.py` y quedan en `RESULTADOS.md`.

Para cada uno de los dos perfiles:

1. **ρ de Spearman** entre el ranking de cada réplica y el ranking original:
   media, mínimo, percentil 5 y percentil 95, más el histograma.
2. **Estabilidad del top 3**: proporción de réplicas en las que el conjunto
   {1.º, 2.º, 3.º} original vuelve a ser el top 3 **como conjunto** (sin exigir el
   mismo orden interno). Se informa además la estabilidad del ganador (1.º solo).
3. **Intervalo de puesto por producto**: percentiles 5 y 95 del puesto de cada
   producto sobre las 200 réplicas, más mediana y puesto original.
4. **Variabilidad de α⁺ en aspectos de baja cobertura**: para `tueste` y `acidez`,
   por producto, media y percentiles 5/95 de `agg_confidence` positiva a lo largo
   de las réplicas, y proporción de réplicas en que el producto se queda **sin
   hecho** para ese aspecto.

Descriptivo adicional, ya que sale gratis y toca un hallazgo abierto: **frecuencia
con que aparece o desaparece un hecho negativo** por (producto, aspecto). Es la
magnitud detrás de R3 (`docs/CHEQUEO_HUMANO_LAF1.md`): el salto entre 0 y 1 crítica.
Se informa como observación, no como métrica de decisión.

## 9. Criterio de fracaso (pre-registrado)

> **Si la ρ media de Spearman en el perfil neutro es menor a 0,80, se declara que el
> orden depende de pocas reseñas y se escribe así en la tesis.**

Criterios secundarios, informados pero **no** decisorios: si el top 3 se conserva en
menos de la mitad de las réplicas, o si algún producto tiene un intervalo de puesto
del percentil 5 al 95 mayor a 8 posiciones, se señala explícitamente qué parte del
ranking no es informativa.

No se ajustará ningún parámetro en función de este resultado.

## 10. Figura

`RESULTADOS.md` incluye una figura de intervalos de puesto por producto: los 18
productos en el eje vertical ordenados por su puesto original, y para cada uno el
segmento del percentil 5 al 95 con una marca en el puesto original.

Se dibuja **SVG a mano** (no Mermaid: `docs/figuras/ESTILO_FIGURAS.md` deja
explícito que el ancho no es gobernable desde Mermaid) siguiendo esa guía: Arial,
`viewBox` de ancho entre 760 y 900, exportación a escala 3, tinta `#22292f`, líneas
`#5e6871`, un solo acento `#294f6d`. La fuente `.svg` y el `.png` quedan en
`docs/figuras/` con el resto, y una copia del PNG en `validacion_robustez/salidas/`.

## 11. Entregables

| Archivo | Contenido |
|---|---|
| `README.md` | este pre-registro |
| `bootstrap_ranking.py` | remuestreo, recálculo, ranking y métricas |
| `salidas/rankings_<perfil>_<fecha>.csv` | 200 réplicas × 18 productos: réplica, semilla, producto, puntaje, puesto |
| `salidas/alpha_baja_cobertura_<fecha>.csv` | α⁺ por réplica para `tueste` y `acidez` |
| `salidas/resumen_<fecha>.json` | todas las métricas de §8 |
| `docs/figuras/figuraX_intervalos_puesto.svg` / `.png` | figura de §10 |
| `RESULTADOS.md` | tablas, figura y limitaciones |

El script imprime al arrancar: `dataset_key`, fecha, semilla, número de réplicas,
reseñas y menciones usadas, y el resultado de los controles de §6.

## 12. Limitaciones (a repetir en RESULTADOS.md)

- El bootstrap remuestrea el corpus **observado**. Si el corpus tiene un sesgo
  sistemático (reseñas de 5 estrellas sobrerrepresentadas, productos con más
  ventas con más reseñas), el bootstrap lo reproduce en cada réplica: mide
  variabilidad de muestreo, **no** sesgo.
- Sólo remuestrea reseñas **con al menos una mención**. Las reseñas que no
  produjeron ninguna mención no participan y su ausencia no se cuestiona.
- Los errores de extracción (~83 % de acierto en polaridad, `docs/ESTADO_DATASETS_CAFE.md`)
  se copian tal cual en cada réplica: un fragmento mal clasificado sigue mal
  clasificado en las 200. La incertidumbre de extracción **no** está en estos
  intervalos.
- Los parámetros congelados (`PRIOR_WEIGHT`, pesos del trust, confianzas de las
  reglas) no se remuestrean.
- Un solo snapshot y dos perfiles.
- Estabilidad no es corrección: este experimento no dice si el orden es bueno.

---

## Enmiendas posteriores a la aprobación

(Ninguna todavía.)
