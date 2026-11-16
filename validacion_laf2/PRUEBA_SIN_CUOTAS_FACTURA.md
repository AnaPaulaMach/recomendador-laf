# Prueba: LAF2 con y sin cuotas/factura, y qué hace hoy la preferencia

Corrido el 2026-09-03 con `prueba_sin_cuotas_factura.py` y `trazar_nodos_publicacion.py`
contra el Docker `laf-api` (perfil `budan_2017`) y Supabase. Todo en memoria: **no se tocó**
`config/`, `src/` ni `webapp/`. Se usó el `build_laf2` real del paso 10 y el parser, el
cliente HTTP y el `LAFGraphRankingMapper` reales del webapp. Salida cruda en
`salidas/prueba_sin_cuotas_factura.json`.

## 1. Cómo sería quitar cuotas y factura para café (no aplicado)

Dos ediciones en `config/domains/cafe.json`:

1. En `purchase_aspects`, borrar las claves `cuotas` y `factura`.
2. Agregar una clave `laf2_rule_structure` propia del dominio (el cargador
   `domain_config.py:172` solo usa el archivo compartido si el dominio no define la suya). Sería
   una copia de `config/laf2_rule_structure.json` con `scope: "cafe"`, sin las condiciones
   `cuotas` y `factura`, y con `recommendation.preference_keys` = `["precio", "garantia",
   "tienda_oficial"]` (así `06d` no falla por "preference_key desconocida").

Después: `06a` (materializa los programas de auditoría que `06d` exige que existan) y
`06d --freeze` para regenerar `category_freeze.json`. Sin eso, `10` y el webapp fallan con "La
configuración de la categoría cambió después de 06d". Es una decisión metodológica (v18 de
curaduría) y así hay que registrarla en `decisions` de `cafe.json`.

## 2. Qué pasa al quitarlas (medido)

| snapshot | productos con ≥ 2 publicaciones | mismo orden con 7 y con 5 condiciones | mismos puntajes |
|---|---:|---:|---:|
| histórico | 15 | 14 | 0 |
| instantáneo | 15 | 15 | 0 |
| grano/molido | 12 | 12 | 0 |

- **El orden no cambia** (41 de 42; el caso restante, Nescafé Clásico frasco en histórico,
  difiere en algún perfil que no revisé en detalle).
- **Los puntajes sí cambian en todos**, aunque cuotas y factura no generan ningún hecho. Motivo:
  la regla `recomendar(X) :- compraBuena(X)` lleva como preferencia el **promedio** de los sliders
  de `preference_keys` (precio, cuotas, garantía, tienda oficial). Al sacar `cuotas` del promedio,
  el número cambia para todas las publicaciones por igual. Por eso el slider de cuotas **no es un
  placebo exacto**: mueve el puntaje de todos (0,50 → 0,62 en el ejemplo) sin mover el orden.

Conclusión de esta parte: quitarlas es seguro para el ranking y más honesto para la interfaz, pero
no arregla nada de fondo. Lo de fondo es lo siguiente.

## 3. Hallazgo principal: la preferencia del usuario no ordena las publicaciones

### El mecanismo, trazado en el grafo (Taster's Choice Caramel, MLM4127889302, sliders en 0,67)

```
precioBueno        {0.95; 0.67}   ┐
tieneDescuento     {0.68; 0.67}   │  4 derivaciones de compraBuena, cada una
esTiendaOficial    {0.95; 0.67}   │  [conf = hecho × 0.85 ; pref = min(0.67, 0.67) = 0.67]
tieneEnvioGratis   {0.95; 0.67}   ┘
compraBuena AGREGADO  = [0.997 ; 1.0]     ← ⊕ conf: 1−Π(1−x) → 0.997 ; ⊕ pref: min(Σ,1) → 1.0 (SATURA)
recomendar            = [0.897 ; 0.67]    ← ⊙ con la regla {0.90; 0.67}: 0.997×0.9 ; min(1.0, 0.67) = 0.67
```

Dos cosas pasan en cadena:

1. **La preferencia agregada satura a 1** en cuanto una publicación cumple 2 o más condiciones
   (`min(X+Y,1)`): era el riesgo anotado, y ocurre.
2. **Luego la regla `recomendar` la recorta a una constante**: `min(1.0, promedio de sliders)`.
   Esa constante es la misma para todas las publicaciones. Resultado: `pref` de `recomendar` =
   0,67 para todas, sin importar qué condiciones tenga cada una.

Como el mapper puntúa con `min(conf, pref)` (`laf_api.py:296`, decisión de implementación, no
del paper), el puntaje es **0,67 para todas** salvo las que tienen confianza menor que eso (las
que cumplen una sola condición con precio alto). El orden real lo decide el desempate por
confianza (`laf_api.py`, orden `(-score, -conf, -pref)`), y **la confianza no ve los sliders**.

### Lo que se ve en los tres snapshots

| perfil de sliders | puntajes distintos por producto (mediana) | publicaciones con pref = 1 |
|---|---:|---:|
| neutral 0,5 | 1 | 0 |
| web por defecto 0,67 | 1–2 | 0 |

- En **30 de 42 productos** todas las publicaciones tienen **exactamente el mismo puntaje** con
  sliders neutrales. La interfaz mostraría una lista empatada ordenada por un desempate invisible.
- **El top no cambia** entre "solo precio", "solo envío" y "solo tienda oficial" en 41 de 42
  productos. El único cambio (Nescafé sin gluten, "solo oficial") ocurre porque un slider en 0
  anula la preferencia de las publicaciones que no cumplen esa condición: los sliders en **0**
  sí actúan (borran), los valores intermedios no ordenan.
- **"Solo envío" da 0 a todas las publicaciones** y las marca `not_recommended`: `envio` y
  `descuento` **no están en `preference_keys`**, así que con los otros cuatro sliders en 0 el
  promedio es 0 y la regla `recomendar` aplasta todo. Un usuario que solo quiere envío gratis
  recibe "ninguna recomendada".

Ejemplo completo (histórico, Taster's Choice Caramel):

| publicación | condiciones | neutral 0,5 | solo precio | solo envío | solo garantía |
|---|---|---:|---:|---:|---:|
| MLM4127889302 $139 | desc + oficial + envío | 0,50 (conf 0,90) | 0,25 | 0,00 | 0,00 |
| MLM2795694042 $179 | desc + oficial + 12 meses | 0,50 (conf 0,90) | 0,25 | 0,00 | **0,25** |
| MLM4993417822 $299 | envío | 0,50 (conf 0,82) | 0,25 | 0,00 | 0,00 |
| MLM2261414253 $292 | – | 0,48 (conf 0,48) | 0,25 | 0,00 | 0,00 |

"Solo garantía" sí levanta a la única con garantía larga, pero porque todas las demás quedan en
0, no porque haya gradación. "Solo envío" no distingue a las que tienen envío de la que no.

### Por qué es el mismo problema que en LAF1

En LAF1 la preferencia de Budán quedó neutralizada porque los rivales del mismo aspecto la
compartían (`1−1 = 0`). Acá queda neutralizada por otra vía: la agregación la satura a 1 y la
regla final la recorta a una constante común. En los dos casos la causa es la misma que se
documentó en `validacion_laf1/EXPERIMENTOS_LEGACY_SEGUNDO_LAF.md` §0b y §10: la segunda etiqueta
de Budán está pensada para argumentos rivales de importancia distinta, y dentro de la Def. 8
`⊤` es absorbente en `⊕`, así que ninguna álgebra evita la saturación. La preferencia del usuario
**no sobrevive** dentro de las etiquetas cuando hay varios argumentos del mismo lado.

Además LAF2 hoy **no tiene argumentos en contra**: solo reglas positivas. Sin `~compraBuena` no hay
conflicto, y sin conflicto la parte "argumentativa" de LAF se reduce a agregar hechos positivos.

## 4. ¿Tiene sentido LAF2? Mi lectura (Ana decide)

**Como está, no cumple lo que promete**: ni ordena por preferencias (el orden sale de la
confianza, que es "cuántas condiciones cumple y qué tan barata es"), ni tiene dialéctica. Sí
tiene sentido el **problema** (elegir vendedor entre varias ofertas del mismo café, con datos
estructurados y deterministas) y sí hay datos para 42 de 53 productos. Lo que falla es el
**acople** de la preferencia, igual que en LAF1.

Tres caminos, del más barato al más ambicioso; los dos primeros son coherentes con lo ya
decidido en LAF1:

- **(i) Multicriterio también en LAF2** (mismo patrón que `post_laf_multicriteria_v1`): una
  corrida LAF por condición viva (precio, descuento, tienda oficial, envío, garantía), puntaje =
  confianza de `recomendar` en esa corrida, preferencia del usuario = **peso** en la suma. La
  preferencia vuelve a mandar, no hay saturación, y el grafo por condición sigue siendo LAF.
  Costo: replicar en `evaluate_listings` lo que ya existe en `evaluate_products`. Es la
  continuación natural de la decisión de LAF1 y la más fácil de defender ("misma solución al mismo
  problema").
- **(ii) Arreglos mínimos dentro del programa actual**: poner `envio` y `descuento` en
  `preference_keys` (evita el 0 total de "solo envío") y usar la confianza como desempate visible.
  No arregla que los valores intermedios no ordenen; solo tapa el caso peor.
- **(iii) Darle dialéctica real**: `shipping_free_shipping` está informado en el **100 %** de las
  publicaciones y `WARRANTY_TYPE = "Sin garantía"` en el 90 %, así que existen hechos negativos
  legítimos (`noTieneEnvioGratis`, `sinGarantia`) que hoy se tiran. Con reglas
  `~compraBuena(X) :- noTieneEnvioGratis(X)` habría conflicto y LAF2 sería argumentativo de
  verdad. Pero con la preferencia en las etiquetas volvería el aplanamiento medido en LAF1, así
  que (iii) solo tiene sentido **encima de (i)**.

Lo que no recomiendo: dejar LAF2 como está y describirlo en la tesis como "ranking por
preferencias de compra", porque los datos muestran que no lo es.

## 5. Qué NO verifiqué

- El caso Nescafé Clásico frasco (histórico) donde el orden difiere entre 7 y 5 condiciones en
  algún perfil.
- Cómo el webapp presenta los empates (si muestra el desempate por confianza o solo el puntaje).
- Si el Argumentation Studio (UI) da lo mismo que el Docker para este programa.

## Reproducir

```bash
venv\Scripts\python.exe validacion_laf2\prueba_sin_cuotas_factura.py
venv\Scripts\python.exe validacion_laf2\trazar_nodos_publicacion.py historico MLM16250244 MLM4127889302 web_default_0.67
```
