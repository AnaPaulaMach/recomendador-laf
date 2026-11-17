# Validación LAF2 (experimentos, separado del pipeline)

LAF2 = ranking de **publicaciones** (ofertas de distintos vendedores) de un producto ya elegido,
según condiciones de compra: precio, descuento, cuotas, garantía, tienda oficial, factura, envío
gratis. Generador real: `src/10_laf2_generate.py`; en el webapp lo ejecuta `LAF2ProgramService`
+ `LAFHttpRecommendationEvaluator.evaluate_listings`. Esta carpeta **no modifica** `src/` ni
`webapp/`; reusa su código por importación.

## Orden de lectura

1. `SUFICIENCIA_DATOS.md` — pregunta 1: cuántas publicaciones por producto, qué condiciones
   existen en el catálogo y cómo trata `10` los faltantes. Resultado: deciden precio, envío,
   tienda oficial y descuento; cuotas y factura no existen en café; 11/53 productos tienen una
   sola publicación.
2. `ORDEN_Y_UNION.md` — pregunta 2: (a) LAF1 → LAF2 actual, (b) LAF2 primero, (c) unir. Pros,
   contras y datos; recomendación (a) con dos ajustes de interfaz. **Decisión pendiente de Ana.**
3. `PRUEBA_SIN_CUOTAS_FACTURA.md` — cómo sería quitar cuotas/factura (no aplicado), qué cambia
   (orden igual, puntajes no) y el **hallazgo principal**: la preferencia satura a 1 y la regla
   `recomendar` la recorta a una constante → el orden sale de la confianza, los sliders no ordenan;
   "solo envío" da 0 a todo. Tres caminos (multicriterio en LAF2, parches, dialéctica real).
4. `TRAZA_PRODUCCION_LAF2.md` — camino real: `.env` → `LAFHttpRecommendationEvaluator.evaluate_listings`
   → `_execute` (un programa + `min`, el equivalente del legacy de LAF1; sin bifurcación multicriterio).
5. `VALIDACION_MULTICRITERIO_LAF2.md` — réplica del camino (i) con componentes reales: empates 32→0,
   el 1° responde a los sliders en 30/42; tres decisiones pendientes (condición sin hechos → HTTP 400,
   publicaciones que desaparecen, `preference_keys`) y propuesta de fix mínimo + tests. **APLICADO** (§6): variante C + completar con 0;
   119 tests OK; real = réplica 126/126 (`real_vs_replica.py`). §7: interfaz (condiciones sin datos
   ocultas, rótulo "No cumple lo que pediste") y `generate_many`; 123 tests; flujo real `flujo_web_real.py`.

## Scripts

- `suficiencia_datos.py` — tabla por producto y cobertura por condición en los 3 snapshots
  (Supabase, sin caché, falla fuerte). Escribe `salidas/suficiencia_datos.json`.
- `buscar_cuotas_raw_json.py` — busca cuotas en `items_raw.raw_json` (no están).
- `battery_multicriterio_laf2.py` — réplica del multicriterio para LAF2 (baseline + una corrida por
  condición + `combine_rankings` real), variantes B/C para condiciones sin hechos. Escribe
  `salidas/battery_multicriterio_laf2.json` y `.log`.
- `flujo_web_real.py <product_id> [solo_envio]` — recorre el flujo web real (Django Client + .env + Docker) e imprime la pantalla.
- `ejemplos_descuento_garantia.py` — publicaciones reales con descuento y con garantía ≥ 6 meses.
- `real_vs_replica.py [snap]` — evaluador de PRODUCCIÓN (`get_evaluator()`, Django) vs réplica.
- `prueba_sin_cuotas_factura.py` — 2 configs en memoria × 8 perfiles × todos los productos con ≥ 2
  publicaciones, con parser/cliente/mapper reales y el Docker. Escribe `salidas/prueba_sin_cuotas_factura.json`.
- `trazar_nodos_publicacion.py <snap> <product_id> <item_id> [perfil]` — programa + nodos del grafo de una publicación.
- `detalle_campos_crudos.py [pos...]` — valores de `WARRANTY_TYPE`, tags de cuotas, y hechos
  publicación por publicación de productos del histórico.

## Cómo correrlo

```bash
venv\Scripts\python.exe validacion_laf2\suficiencia_datos.py
```

Snapshots: histórico `mlm_mlm194329_20260528_142014`, instantáneo `mlm_mlm194329_20260805_191308`,
grano/molido `mlm_mlm194335_20260805_185233`.

## Programas por condición

`programas_por_condicion/` contiene los programas LAF2 generados para los dos productos de esta validación (programa combinado y uno por condición de compra); su README describe cada archivo.
