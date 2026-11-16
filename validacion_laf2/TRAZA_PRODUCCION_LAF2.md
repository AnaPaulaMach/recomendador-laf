# Traza del camino de producción de LAF2 (leído 2026-09-03, antes de medir)

Todo verificado leyendo el código en esta fecha. Números de línea aproximados.

## 1. Configuración (`webapp/laf_web/settings.py` + `.env`)

| variable | default en settings | valor en `.env` | efecto |
|---|---|---|---|
| `RECOMMENDATION_EVALUATOR` | `LAF1PreparedRecommendationEvaluator` | **`LAFHttpRecommendationEvaluator`** | la clase que corre LAF1 y LAF2 |
| `LAF_API_URL` | `http://127.0.0.1:8088/api/graph` | igual | Docker de Javi |
| `LAF_API_RESULTS_VALIDATED` | `0` | **`1`** | compuerta: con 0 el ranking se vacía antes de publicarse |
| `LAF_PRODUCT_DECISION_MODEL` | `post_laf_multicriteria_v1` | no está en `.env` → default | **solo afecta a productos (LAF1)** |

`use_cases.get_evaluator()` instancia `LAFHttpRecommendationEvaluator(fixtures, LAF1ProgramService,
LAF2ProgramService, LAFApiClient, results_validated=…, product_decision_model=…)`.

## 2. Entrada: `RecommendationWorkflow.evaluate_purchase` (`use_cases.py`)

La vista de compra (`views.py` ~917) llama `evaluate_purchase(session, preferences, budget_min,
budget_max)`, que construye `EvaluationRequest(domain, dataset_key, strategy, preferences,
selected_entity_id=producto elegido, budget_min, budget_max)` y llama
`evaluator.evaluate_listings(request)`. Guarda el resultado en `session.laf2_result` y pasa la
sesión a `LISTING_RANKING`. Las preferencias vienen del formulario `PurchasePreferencesForm`
(`forms.py:95`), un slider por clave de `purchase_aspects` de `cafe.json`, **valor inicial 0,67**.

## 3. Rama LAF2: `LAFHttpRecommendationEvaluator.evaluate_listings` (`evaluators.py:405`)

```
evaluate_listings(request)
 ├─ dataset de fixture → mock                       (no aplica a los 3 snapshots reales)
 ├─ generated = laf2_programs.generate(request)      LAF2ProgramService
 │    ├─ carga src/10_laf2_generate.py por importlib (mismo código que la CLI)
 │    ├─ load_domain_config_for_key(domain) + load_and_validate_freeze  (hash congelado)
 │    ├─ _complete_preferences: claves faltantes → 0.0 ; fuera de [0,1] → error
 │    ├─ repository.laf2_generation_items(dataset, product, budget)  items_clean ∩ items_raw
 │    ├─ step_10.parse_item(row, rule_structure) por publicación
 │    └─ step_10.build_laf2(items, preferences, ...)  → texto del programa + entities
 │         (entity.argument = safe_id(item_id); metadata: seller, price, installments, warranty, shipping)
 └─ _execute(request, generated, "laf2")             (evaluators.py:415) — EL MISMO que el legacy de LAF1
      ├─ parser.parse(text).to_request_payload()     LAFProgramParser
      ├─ graph = api_client.build_graph(payload)     POST al Docker, UNA sola llamada
      ├─ ranking = ranking_mapper.map(graph, entities)   LAFGraphRankingMapper
      │     · por publicación, el nodo `recomendar` de mayor min(conf, pref)   (laf_api.py:296)
      │     · orden (-score, -conf, -pref, id)                                  (laf_api.py:~358)
      │     · status = recommended si score > 0
      └─ _result(..., ranking = ranking si results_validated else ())
```

**Diferencia clave con LAF1:** `evaluate_products` tiene la bifurcación
`if results_validated and product_decision_model == DECISION_MODEL → _evaluate_products_multicriteria`.
**`evaluate_listings` no la tiene.** LAF2 siempre corre el camino de un solo programa + `min`, es
decir, el equivalente del **legacy** de LAF1. `LAF_PRODUCT_DECISION_MODEL` no lo toca.

## 4. Qué hace el multicriterio de LAF1 que hay que replicar (`evaluators.py:289–396`, `post_laf_decision.py`)

1. `active_aspects` = claves con peso > 0, ordenadas.
2. Genera N+1 programas con `laf1_programs.generate_many`: el completo (baseline) y uno por aspecto
   con `{aspecto: 1.0}` (los demás quedan en 0).
3. Baseline → Docker → mapper (sirve para el grafo visual y para `confidence/preference` de traza).
4. Por aspecto: `zero_threshold_payload` **quita los hechos con preferencia 0** (los de los otros
   aspectos) → Docker → mapper → `AspectEvaluation(aspect, weight=pref del usuario, ranking)`.
   Si el ranking del aspecto está vacío → `LAFApiError` → resultado sin ranking.
5. `combine_rankings(baseline, evaluations, preferences)`: por entidad,
   `score = Σ peso × confianza_del_aspecto / Σ pesos` (la **confianza** post-conflicto del
   `recomendar` de esa corrida, no `min(conf,pref)`; comentario en `post_laf_decision.py:~110`).
   Entidad sin `recomendar` en un aspecto → 0 en ese aspecto. Metadata: `decision_model`,
   `aspect_contributions`, `source_laf_confidence/preference`.

`LAF2ProgramService` **no tiene `generate_many`**; `_evaluate_products_multicriteria` ya prevé ese
caso y cae a llamar `generate` una vez por variante (más lento: recarga Supabase por variante).

## 5. Compuertas y publicación

- `results_validated=False` → ranking vacío, `evaluation_status="pending"`, la plantilla
  muestra "No mostramos un ranking provisional". Con `.env` actual está en 1.
- Error de parseo o de API → `ranking=()`, `program_status="generated"`, se publica el programa
  pero no el orden.
- La plantilla `listing_ranking.html` muestra por publicación: vendedor, precio, cuotas, garantía,
  envío y **un rótulo por posición** (`match_label`: 1 → "Mejor opción para vos", 2 → "Buena
  coincidencia", resto "Coincidencia media"). **No muestra el puntaje** → los empates medidos en
  `PRUEBA_SIN_CUOTAS_FACTURA.md` son invisibles para el usuario: ve un orden que en realidad es el
  desempate por confianza.
- Un producto con una sola publicación tiene plantilla propia (`single_listing.html`; no revisé
  cuándo se elige).

## 6. Lo que implica para el fix (i)

Puntos de cambio mínimos, todos en `webapp/` (no en `src/10`):

1. `evaluate_listings`: misma bifurcación que productos → `_evaluate_listings_multicriteria`.
2. Variantes: baseline con las preferencias completas + una por condición activa con
   `{condición: 1.0, resto 0.0}`. Con `build_laf2`, los hechos de las otras condiciones salen con
   pref 0,00 y `zero_threshold_payload` los quita; la regla `recomendar` queda con pref =
   media de `preference_keys` (0 o 0,25), pero **no importa porque se lee la confianza**.
3. **Caso nuevo respecto de LAF1:** en LAF2 puede haber una condición activa que **ninguna**
   publicación cumple (ej. garantía larga en 38 de 42 productos). En LAF1 eso dispara
   `LAFApiError` y se pierde todo el ranking. En LAF2 hay que decidir: tratar la corrida vacía como
   "todas 0 en esa condición" (contribución 0, el peso sigue en el denominador) o quitar la
   condición del denominador. Es una decisión de Ana; la batería mide las dos.
4. `combine_rankings` se reutiliza tal cual; `entity_id` = `item_id`.
5. Idealmente `LAF2ProgramService.generate_many` para no recargar Supabase por variante.

Siguiente paso: `battery_multicriterio_laf2.py` replica 1–4 con componentes reales, sin tocar
`webapp/`, y mide si el orden responde a los sliders y si desaparecen los empates.
