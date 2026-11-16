# Pregunta 1 — ¿Hay datos para que LAF2 decida algo?

Medido el 2026-09-03 contra Supabase con `suficiencia_datos.py` y `detalle_campos_crudos.py`
(salida cruda en `salidas/suficiencia_datos.json`). Los hechos se calcularon con el
`parse_item()` **real** de `src/10_laf2_generate.py`, y el universo de publicaciones es el mismo
que usa el webapp (`SupabaseRepository.laf2_generation_items`): filas de `items_clean` del
producto, unidas a su fila de `items_raw`, para los productos incluidos con posición ≤ 20.

## 1. Qué es LAF2 (verificado en `src/10_laf2_generate.py`)

- Compara las **publicaciones** (ítems) de **un producto ya elegido**. Una publicación = un
  vendedor ofreciendo ese producto a un precio y con ciertas condiciones.
- Hechos posibles por publicación: `precioBueno` (siempre; confianza 0,95 para el más barato del
  rango, 0,30 para el más caro, lineal), `tieneDescuento`, `tieneCuotas`, `tieneGarantiaLarga`
  (≥ 6 meses), `esTiendaOficial`, `tieneFactura`, `tieneEnvioGratis`.
- Reglas: una `compraBuena(X) :- condicion(X)` por condición (confianza 0,85) y una
  `recomendar(X) :- compraBuena(X)` (confianza 0,90). **No hay reglas negativas ni conflicto.**
- Preferencia del usuario: viaja como **segunda etiqueta** de cada hecho y de cada regla
  (`prefs_laf2.json` / preferencias del formulario web).

## 2. Cómo trata `10` los faltantes

Verificado en el código: un hecho binario **solo se escribe si la condición se cumple**. Si el
campo crudo es nulo, si es `False` o si el ítem no lo informa, el resultado es el mismo: **no hay
hecho**. Por lo tanto para LAF2 "no tiene envío gratis" y "no se sabe si tiene envío gratis" son
indistinguibles. Ejemplos:

| condición | campo crudo | qué hace `10` con el faltante |
|---|---|---|
| descuento | `original_price` (de `items_clean`) | nulo o ≤ precio → sin hecho |
| cuotas | `tags` contiene `3x/9x/12x_campaign` | tag ausente → sin hecho |
| garantía | `sale_terms[id=WARRANTY_TIME].value_struct` | ausente → 0 meses → sin hecho; < 6 meses → sin hecho |
| tienda oficial | `official_store_id` | nulo → sin hecho |
| factura | `sale_terms[id=INVOICE]` | ausente → sin hecho |
| envío gratis | `shipping_free_shipping` | nulo o `False` → sin hecho |

Consecuencia práctica: **una publicación sin condiciones queda solo con `precioBueno`**, y un
faltante nunca "castiga", solo deja de "premiar". Con reglas solo positivas eso es coherente
(no se puede afirmar lo que no se sabe), pero hay que decirlo en la tesis: LAF2 razona sobre
**lo que la publicación declara**, no sobre lo que tiene.

## 3. Tabla por snapshot

| | histórico | instantáneo | grano/molido |
|---|---:|---:|---:|
| productos incluidos (top 20) | 18 | 16 | 19 |
| publicaciones (`items_clean` con fila en `items_raw`) | 169 | 215 | 121 |
| publicaciones sin fila en `items_raw` | 0 | 0 | 0 |
| **productos con 1 sola publicación** (LAF2 no decide) | **3** | **1** | **7** |
| productos con ≥ 2 publicaciones y ≥ 2 vectores binarios distintos | 15 | 14 | 12 |
| productos con ≥ 2 publicaciones pero todas con el mismo vector (solo decide el precio) | 0 | 1 | 0 |

### Cobertura de cada condición (sobre todas las publicaciones del snapshot)

"Informado" = el campo crudo existe; "cumple" = `10` genera el hecho.

| condición | histórico informado / cumple | instantáneo | grano/molido |
|---|---|---|---|
| envío gratis | 100 % / **66 %** (112) | 100 % / **68 %** (146) | 100 % / **84 %** (102) |
| tienda oficial | 21 % / **21 %** (36) | 17 % / **17 %** (36) | 22 % / **22 %** (27) |
| descuento | 12 % / 12 % (20) | 12 % / 12 % (25) | 8 % / 8 % (10) |
| garantía ≥ 6 meses | 37 % informan plazo / **3 %** (5) | 34 % / **3 %** (7) | 43 % / **5 %** (6) |
| **cuotas** | 100 % tienen tags / **0 %** (0) | 100 % / **0 %** (0) | 100 % / **0 %** (0) |
| **factura** | 0 % / **0 %** (0) | 0 % / 0 % (0) | 0 % / 0 % (0) |

Detalle de lo que hay detrás:

- **Cuotas: muerta en este catálogo.** Ninguna publicación de los tres snapshots tiene un tag
  `*_campaign` ni nada parecido a cuotas; los tags que aparecen son `kvs_primary`,
  `immediate_payment`, `cart_eligible`, `supermarket_eligible`, etc. El slider "cuotas" de la
  interfaz hoy **no cambia nada** en el ranking. (Verificado después en `raw_json`: tampoco
  están; ver §6.)
- **Factura: muerta.** Ningún `sale_terms` trae `INVOICE`. El slider "factura" tampoco hace nada.
- **Garantía: casi muerta con el umbral de 6 meses.** El plazo se informa en un tercio de las
  publicaciones, pero casi siempre es 30 días o 1 mes (café es un consumible). Los casos con
  12 meses son 3–5 por snapshot. Además `10` **ignora `WARRANTY_TYPE`**, que sí está en el 90 %
  de las filas y distingue "Sin garantía" (90/153 en histórico) de "Garantía de fábrica" (17) y
  "Garantía del vendedor" (49). Ese campo tiene más variedad útil que el plazo.
- **Descuento: raro** (1 de cada 10 publicaciones), pero cuando aparece discrimina.
- **Envío gratis y tienda oficial son las dos condiciones que realmente separan publicaciones**:
  envío está en 2 de cada 3 (así que también discrimina a las que NO lo tienen), tienda oficial en
  1 de cada 5.

## 4. Ejemplo real: Nescafé Taster's Choice Caramel (histórico, puesto 8, 7 publicaciones)

| publicación | precio | descuento | garantía | tienda oficial | envío gratis |
|---|---:|:-:|:-:|:-:|:-:|
| MLM4127889302 | $139 | sí | – | sí | sí |
| MLM2795694042 | $179 | sí | 12 meses | sí | **no** |
| MLM2261414253 | $292 | – | 1 mes | – | **no** |
| MLM4993417822 | $299 | – | – | – | sí |
| MLM1764872010 | $349 | – | – | – | sí |
| MLM3548927042 | $353 | – | – | – | sí |
| MLM2175868089 | $447 | – | 1 mes | – | sí |

Acá LAF2 tiene algo que decidir: la más barata también es oficial y con envío (debería ganar
siempre), la segunda es la única con garantía larga pero sin envío (debería subir si el usuario
pesa garantía y bajar si pesa envío), y las cuatro últimas solo se distinguen por precio. Es un
buen caso de prueba para la pregunta 3.

Contraejemplo: Nescafé Clásico bolsa (histórico, puesto 2) tiene **una** publicación: LAF2
devuelve un ranking de un elemento. En grano/molido pasa en 7 de 19 productos (los artesanales
de un solo vendedor: Santa Elena, Don Justo, ETNIA 52, Chiapas Caracolillo, Veracruzano, Grano de
Altura, Blasón grano 500 g).

## 5. Lectura honesta

1. **LAF2 tiene sentido, pero con menos condiciones de las que promete.** De 7 condiciones
   configuradas, 2 no existen en el catálogo (cuotas, factura) y 1 casi no existe con el umbral
   actual (garantía). Quedan **precio, envío gratis, tienda oficial y descuento** como las que
   deciden. Con eso, en 15/18, 14/16 y 12/19 productos hay al menos dos publicaciones con
   condiciones distintas, así que el ranking no es trivial en la mayoría del catálogo de
   instantáneo, y en dos tercios del de grano/molido.
2. **En 11 de 53 productos (3+1+7) LAF2 no decide nada** porque hay una sola publicación. Para
   esos casos la interfaz debería decirlo ("una sola oferta") en vez de mostrar un ranking de 1.
3. **Los sliders de cuotas y factura son placebo hoy.** Mover el peso no cambia nada porque nunca
   se genera el hecho. Esto es una observación, no un defecto de LAF: es del catálogo. Pero
   mostrar un control que no hace nada es un problema de interfaz y de honestidad metodológica
   que conviene documentar (o quitar los sliders para café, o mostrar "sin datos en este
   catálogo").
4. **Faltante = ausencia.** Es defendible con reglas positivas, pero hay que escribirlo.
   Alternativa futura (no aplicada): usar `WARRANTY_TYPE` ("Sin garantía" explícito) como
   evidencia negativa real, que sí existe en el 90 % de las filas.
5. **Riesgo para la pregunta 3.** Una publicación como MLM4127889302 acumula 4 hechos positivos
   (precio 0,95 + descuento + oficial + envío) con agregación `X+Y−XY` en confianza y
   `min(X+Y,1)` en preferencia; con 2 o más condiciones la preferencia agregada llega a 1 con
   sliders en 0,5. Eso se mide en la pregunta 3, no lo afirmo todavía.

## Cómo reproducir

```bash
venv\Scripts\python.exe validacion_laf2\suficiencia_datos.py
venv\Scripts\python.exe validacion_laf2\detalle_campos_crudos.py 5 8 7
```

Ambos fallan fuerte si Supabase no responde o si un snapshot tiene productos pendientes de
revisión (no hay caché).

## 6. Complemento (2026-09-03): ¿las cuotas están en otro campo? y ¿se pueden apagar para café?

**Cuotas.** `items_raw` tiene una columna `raw_json` con el ítem completo que devolvió la API
(`buscar_cuotas_raw_json.py`). Sus claves de primer nivel son: `accepts_mercadopago, category_id,
condition, currency_id, deal_ids, international_delivery_mode, inventory_id, item_id,
listing_type_id, min_purchase_unit, official_store_id, original_price, price, sale_terms,
seller_address, seller_id, shipping, site_id, tags, tier, user_product_id, warranty`. **No hay
ninguna clave `installments`** ni nada que hable de cuotas o meses sin intereses en los 526 ítems
de los tres snapshots; las únicas coincidencias son `accepts_mercadopago` (true en el 100 %, no
discrimina) y los "meses" de la garantía. Conclusión: las cuotas no se pueden recuperar de lo
guardado. En la API de Mercado Libre el objeto `installments` viene en la respuesta de búsqueda,
no en la del ítem (esto último no lo verifiqué contra la API; lo que sí verifiqué es que en
nuestros datos no está). Recuperarlo exigiría volver a extraer.

**Garantía.** La columna `warranty` (texto, ej. "Garantía de fábrica: 3 meses", "Sin garantía")
está en el 100 % de los ítems y `10` no la usa; es la misma información que `WARRANTY_TYPE` +
`WARRANTY_TIME` de `sale_terms`, en una sola cadena.

**Apagar cuotas y factura para café: hay dos mecanismos que ya existen, y ninguno es automático.**

1. `config/laf2_rule_structure.json` → `conditions.cuotas.status = "pending"` con un `reason`.
   `build_laf2` entonces escribe `% PENDIENTE cuotas: <razón>` en el programa y no genera la regla
   (verificado en el bucle de reglas de agregación); `06d` lo acepta como "pendiente", no como
   error. Pero el archivo es **compartido por todas las categorías** (celulares sí pueden tener
   cuotas) y el slider seguiría apareciendo, porque el formulario web lee `purchase_aspects` de
   `cafe.json`, no las condiciones.
2. Quitar `cuotas` y `factura` de `purchase_aspects` en `config/domains/cafe.json`. El slider
   desaparece (el formulario itera `domain.purchase_aspects`), `build_laf2` salta la regla (`if
   pref_key not in cfg["purchase_aspects"]: continue`) y `06d` solo avisa "Reglas LAF 2 no usadas
   por esta categoría". **Trampa verificada:** `recommendation.preference_keys` del archivo
   compartido incluye `cuotas`; con `cuotas` fuera de `purchase_aspects`, `06d` da error
   "preference_key desconocida". Habría que sobreescribir `laf2_rule_structure` dentro de
   `cafe.json` (el cargador lo permite: solo usa el compartido si el dominio no define el suyo) o
   cambiar el compartido para todas las categorías.

En ambos casos cambia el hash de la metodología congelada: `10` y el webapp **fallan** ("La
configuración de la categoría cambió después de 06d") hasta volver a correr `06d --freeze`. O
sea: es fácil de configurar, pero es un cambio metodológico que hay que congelar de nuevo y
documentar como decisión (v18 de curaduría), no un interruptor.

**Detección automática** ("apagar si nunca aparece") no existe para condiciones de compra. Para
los aspectos de calidad sí hay algo parecido en el webapp (`_quality_aspects` oculta sliders sin
evidencia en el snapshot, decisión v13). Replicarlo para LAF2 sería código nuevo en `webapp/`
(consultar `items_raw` del snapshot y ocultar la condición si ninguna publicación la cumple).
Es razonable y coherente con v13, pero es una decisión de Ana, no la aplico.
