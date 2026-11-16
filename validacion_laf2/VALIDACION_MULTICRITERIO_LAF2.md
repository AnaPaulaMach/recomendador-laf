# Multicriterio en LAF2 (camino i): réplica con componentes reales y propuesta de fix

Medido el 2026-09-03 con `battery_multicriterio_laf2.py` (Docker `laf-api`, Supabase, 42
productos con ≥ 2 publicaciones, 8 perfiles de sliders). Reusa el `build_laf2` del paso 10, el
parser, cliente y `LAFGraphRankingMapper` del webapp, y `zero_threshold_payload` +
`combine_rankings` de `post_laf_decision.py` **sin modificar nada**. Salida:
`salidas/battery_multicriterio_laf2.json`. Contexto: `TRAZA_PRODUCCION_LAF2.md` (camino actual)
y `PRUEBA_SIN_CUOTAS_FACTURA.md` (por qué hoy los sliders no ordenan).

## 1. La receta (idéntica a `_evaluate_products_multicriteria`)

1. Baseline: programa completo con las preferencias del usuario → Docker → mapper (grafo visual
   y traza `conf/pref`).
2. Por condición con peso > 0: programa con `{condición: 1.0, resto: 0.0}` → los hechos de las
   otras condiciones salen con pref 0,00 y `zero_threshold_payload` los quita → Docker → mapper.
   Puntaje de la publicación en esa condición = **confianza** de su `recomendar`.
3. `combine_rankings`: `score = Σ peso × confianza_condición / Σ pesos`.

## 2. Resultados

| | histórico | instantáneo | grano/molido |
|---|---:|---:|---:|
| productos con ≥ 2 publicaciones | 15 | 15 | 12 |
| productos con **todas** las publicaciones empatadas (neutral), camino actual `min` | 11 | 10 | 11 |
| ídem, multicriterio | **0** | **0** | **0** |
| productos donde el 1° cambia entre "solo precio / envío / oficial / garantía" | 13 | 8 | 9 |

Ejemplo, Taster's Choice Caramel (histórico, 7 publicaciones), sliders neutrales 0,5:

| publicación | condiciones | camino actual `min` | multicriterio |
|---|---|---:|---:|
| MLM4127889302 $139 | desc + oficial + envío | 0,500 | **0,386** |
| MLM2795694042 $179 | desc + oficial + 12 meses | 0,500 | 0,372 |
| MLM4993417822 $299 | envío | 0,500 | 0,171 |
| MLM1764872010 $349 | envío | 0,500 | 0,160 |
| MLM3548927042 $353 | envío | 0,500 | 0,159 |
| MLM2175868089 $447 | envío | 0,500 | 0,137 |
| MLM2261414253 $292 | – | 0,482 | 0,069 |

Con "solo precio": 0,727 / 0,665 / 0,482 / 0,467 / … (ordena por precio, gradual). Con "solo
garantía": queda solo MLM2795694042 con 0,627. Con "solo envío": las cinco con envío en 0,727 y las
dos sin envío **desaparecen** (ver §3.2).

Los puntajes absolutos con sliders neutrales son bajos (máximo 0,386) porque `cuotas` y
`factura` pesan en el denominador y aportan 0 (ver §3.1). El orden no cambia por eso.

## 3. Tres puntos que hay que decidir antes del fix (Ana)

### 3.1 Condición activa sin ningún hecho en el producto → hoy sería un error fatal

Verificado: cuando `zero_threshold_payload` deja el payload sin hechos, el Docker responde
**HTTP 400 "facts: must not be empty"** → `LAFApiError` → en `_evaluate_products_multicriteria`
eso descarta **todo** el ranking. En LAF2 pasa **siempre** con los sliders por defecto (cuotas y
factura nunca tienen hechos) y en 4–7 de 8 perfiles en todos los productos. Copiar la receta de
LAF1 tal cual **no daría ningún ranking**. Opciones medidas:

- **B "cero"**: la corrida vacía vale 0 para todas las publicaciones y el peso queda en el
  denominador. Orden correcto; puntajes absolutos bajos cuando hay condiciones muertas.
- **C "quitar"**: la condición sin evidencia sale del denominador. Mismo orden que B en 42/42
  productos y todos los perfiles probados; puntajes reescalados (más altos).

Recomiendo **C** con la condición registrada en metadata como `sin evidencia en este producto`:
es honesto ("no pude evaluar cuotas porque ninguna oferta las informa") y no castiga el puntaje
por algo que el catálogo no tiene. B también es defendible ("pediste cuotas y nadie las da").

### 3.2 Publicaciones que no cumplen ninguna condición activa desaparecen del ranking

`combine_rankings` solo incluye entidades que aparecen en alguna corrida por condición. Con "solo
envío", las publicaciones sin envío no tienen `recomendar` en esa corrida y **no salen** (68/214
en instantáneo; con "solo tienda oficial", 179/214). En LAF1 esto casi no se nota porque todo
producto tiene hechos en casi todos los aspectos. En LAF2 sí se nota. Opciones:

- dejarlo así (filtro implícito: "si solo te importa el envío, solo te muestro las que lo tienen");
- incluirlas con puntaje 0 al final del ranking, marcadas `not_recommended` (el baseline siempre
  las tiene, porque `precioBueno` existe para todas). Recomiendo esto: el usuario ve todas las
  ofertas y entiende por qué las últimas no califican.

### 3.3 `preference_keys` de la regla `recomendar` deja de importar

Con el multicriterio se lee la confianza, así que la media de sliders que hoy va en la preferencia
de `recomendar(X) :- compraBuena(X)` deja de afectar el orden. No hace falta tocar `10` ni la
configuración congelada para el fix. (El problema de "solo envío = 0 para todos" desaparece solo.)

## 4. Propuesta de fix mínimo (para tu OK; no aplicado)

Todo en `webapp/recommender/services/evaluators.py`, sin tocar `src/10` ni `config/`:

1. En `evaluate_listings`, misma compuerta que productos:
   `if self.results_validated and self.product_decision_model == DECISION_MODEL: return self._evaluate_listings_multicriteria(request)`.
2. `_evaluate_listings_multicriteria`: baseline + una variante por condición activa vía
   `laf2_programs.generate(EvaluationRequest(... preferences={cond: 1.0, resto 0.0}, selected_entity_id, budget_min, budget_max))`.
   Antes de llamar al Docker, si `zero_threshold_payload(...)["facts"]` está vacío → tratar como
   corrida vacía según 3.1 (no llamar a la API, no lanzar error).
3. `combine_rankings(baseline, evaluations, preferences_efectivas)` y, según 3.2, completar con las
   entidades del baseline ausentes con `final_score=0`.
4. Metadata: `decision_model`, `aspect_contributions`, y una lista `conditions_without_evidence`.
5. Opcional después: `LAF2ProgramService.generate_many` para no recargar Supabase por variante
   (hoy 1 + N lecturas; con 5 condiciones vivas son 6).

Tests de regresión (rojo → verde) que escribiría antes del cambio, con un cliente de API falso:

- ranking con dos publicaciones: `solo_envio` ordena primero la que tiene envío y **no falla**
  aunque `cuotas` no tenga hechos;
- una condición sin hechos no dispara `LAFApiError` y queda listada en metadata;
- una publicación sin ninguna condición activa aparece última con 0 (si elegís esa opción);
- `evaluate_listings` con `results_validated=False` sigue devolviendo ranking vacío.

Luego suite completa `webapp/manage.py test recommender` y verificación sobre datos reales con
esta misma batería (real = réplica), como se hizo en LAF1.

## 5. Qué NO verifiqué

- Cómo se comporta la explicación (`explanation.html`) y el grafo visual con el ranking
  multicriterio de publicaciones: en LAF1 usan el baseline; habría que confirmar que las plantillas
  de LAF2 leen `metadata.aspect_contributions` o ignoran el cambio sin romperse.
- Tiempo de respuesta en el webapp con 1 + N llamadas al Docker por producto (la batería hace
  ~8 llamadas por producto y perfil en segundos, no debería ser problema).

## Reproducir

```bash
venv\Scripts\python.exe validacion_laf2\battery_multicriterio_laf2.py
```

## 6. APLICADO (2026-09-03, con OK de Ana: variante C + completar con 0)

Cambios en `webapp/` (commit siguiente a este documento):

- `recommender/services/evaluators.py`: `evaluate_listings` bifurca a
  `_evaluate_listings_multicriteria` con la misma compuerta que productos
  (`results_validated and product_decision_model == DECISION_MODEL`). Baseline + una variante por
  condición con peso > 0; si tras `zero_threshold_payload` no quedan hechos, **no se llama a la
  API** y la condición sale del denominador (variante C) y va a
  `metadata["conditions_without_evidence"]`; `combine_rankings` real; las publicaciones ausentes se
  completan al final con 0 y `not_recommended` desde el baseline (`_complete_with_baseline`).
- `recommender/tests/test_laf_api.py`: 3 tests nuevos (rojo → verde): orden y puntajes
  multicriterio con `cuotas` sin hechos y 3 llamadas a la API; publicación sin condición activa
  última con 0; compuerta cerrada → `pending`. Rojo confirmado antes del fix: `0.5 != 0.733` y
  `0.5 != 0.0` (el camino viejo daba el `min` constante).
- `recommender/tests/test_flow.py`: la expectativa `generate.assert_called_once()` pasó a
  `1 + len(purchase_aspects)` (baseline + 7 variantes), que es el comportamiento nuevo.
- Suite completa: **119 tests OK**.

**Real = réplica** (`real_vs_replica.py`, evaluador de producción vía `get_evaluator()` con el
`.env` real, perfiles neutral / solo precio / solo envío): histórico 45/45, instantáneo 45/45,
grano/molido 36/36 coincidencias exactas de orden y puntaje con la batería (variante C), y
además el sistema real completa con 0 las publicaciones que la réplica omitía (p. ej. Taster's
Choice "solo envío": 7 publicaciones, 2 completadas con 0).

Pendiente (no verificado): plantillas de explicación y grafo de LAF2 con el ranking nuevo;
`LAF2ProgramService.generate_many` para no recargar Supabase 1 + N veces; chequeo humano de Ana en
la interfaz.

## 7. Interfaz y Supabase (2026-09-03, pedido de Ana; commit `3911719`)

- **Una sola carga de Supabase por evaluación:** `LAF2ProgramService.generate_many` (mismo patrón
  que LAF1) carga producto y publicaciones una vez y genera el baseline + N variantes;
  `_evaluate_listings_multicriteria` lo usa. Test: 3 variantes → `laf2_generation_items` llamado 1 vez.
- **Formulario de compra:** `_purchase_aspects` (misma regla que `_quality_aspects`, decisión v13)
  consulta `LAF2ProgramService.available_purchase_condition_keys` (nuevo
  `SupabaseRepository.laf2_dataset_items` + `parse_item` real) con caché, y oculta las condiciones
  que ninguna publicación del catálogo cumple. En café desaparecen cuotas y factura y se muestra
  una línea: "Ninguna publicación de este catálogo informa financiación (cuotas sin interés) ni
  factura, así que no se comparan." El texto técnico "¿cómo se calcula?" describe la suma ponderada.
- **Ranking de publicaciones:** rótulo "No cumple lo que pediste" para las publicaciones con
  puntaje 0 (`not_recommended`), y aviso cuando una condición activa no tiene evidencia en el
  producto (solo puede pasar con garantía/descuento, porque cuotas/factura ya no llegan al formulario).
- Tests nuevos: `generate_many`, `available_purchase_condition_keys`, formulario limitado, rótulo.
  El test de flujo ahora parchea `generate_many` y la disponibilidad. **Suite: 123 OK.**
- **Flujo real** (`flujo_web_real.py`, Django `Client` con `.env` real + Docker, Taster's Choice
  Caramel): formulario con 5 controles y la nota; ranking `validated`, `post_laf_multicriteria_v1`;
  perfil mixto → $139 (desc+oficial+envío) 0,54 primero, $292 sin condiciones 0,048 último; perfil
  "solo envío" → 5 con envío en 0,727 y las 2 sin envío al final con "No cumple lo que pediste".
  Capturas vistas en el navegador (puerto 8001).

**Observación para decidir (no aplicada):** con un solo slider activo, las publicaciones que lo
cumplen empatan exactamente (0,727) y `combine_rankings` desempata por `entity_id`, así que con
"solo envío" queda primera la de $349 y no la de $139. Opciones: desempatar por la confianza del
baseline (que ya incorpora el precio) o mostrar el empate. Textos fijos que siguen nombrando
cuotas: subtítulo de "Dónde comprarlo" y la columna "Cuotas: No informadas".

## 8. Desempate y textos fijos (2026-09-03, OK de Ana)

- **Desempate por confianza del programa completo** en `_complete_with_baseline` (`evaluators.py`,
  solo publicaciones; `combine_rankings` de LAF1 no se toca): orden `(-puntaje, -confianza baseline,
  id)`. Test rojo→verde `test_listing_ties_are_broken_by_baseline_confidence_not_by_id` (sin el
  cambio daba `['A','Z']`, con el cambio `['Z','A']`). Flujo real "solo envío" en Taster's Choice:
  antes primera la de $349; ahora $139, $299, $349, $353, $447 (todas 0,727) y las dos sin envío al
  final con "No cumple lo que pediste". Justificación: a igualdad en lo que pidió la persona, la
  confianza del programa completo ya incorpora el precio (más barata, más confianza).
- **Textos fijos**: subtítulos "Comparamos precio y condiciones de compra…" y "Revisá precio y
  condiciones de compra…"; la columna/fila "Cuotas" solo aparece si alguna publicación las informa
  (`show_installments`), y en la oferta única solo si no es "No informadas".
- Suite: **124 tests OK**.
