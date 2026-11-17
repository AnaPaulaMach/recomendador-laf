# ADR-007 · LAF2 con una etiqueta por condición

- Fecha: 2026-09-13.
- Estado: aceptada por instrucción explícita de la autora en este cambio.
- Alcance: sólo `webapp/`. No se toca `src/`, `config/` ni `LAF/`.
- Replica en LAF2 la decisión que [ADR-002](ADR-002-LAF1-CONFIANZA-POR-ASPECTO.md)
  tomó para LAF1. Cierra la asimetría que ese ADR había dejado abierta
  («LAF2 conserva su ruta actual de dos etiquetas»).

## Contexto

Hasta este cambio los dos niveles pedían al motor cosas distintas:

- LAF1 por aspecto mandaba **una** etiqueta. `laf1_programs.generate_aspects`
  selecciona la evidencia del aspecto antes de construir el programa y proyecta
  la anotación `{α; β}` a `{α}`; `evaluators` exige `attribute_count == 1`.
- LAF2 por condición mandaba **dos**. `_evaluate_listings_multicriteria` pedía
  un programa por condición con la **máscara** de preferencias
  `{condición: 1,0; resto: 0,0}` y `zero_threshold_payload` borraba después los
  hechos que habían quedado con preferencia cero. Al motor viajaban las dos
  operaciones del perfil `budan_2017`.

Entre los hechos que sobrevivían a la máscara β era constante = 1, así que no
intervenía en el número que ordena: `combine_rankings` toma
`RankingEntry.confidence` —la confianza post-conflicto de la corrida—, no
`final_score`. La segunda etiqueta era, en esa ruta, presentación.

Sostener dos contratos distintos para el mismo motor obliga a explicar dos veces
lo mismo en la tesis y deja a LAF2 dependiendo de un borrado posterior
(`zero_threshold_payload`) en lugar de una selección declarada.

## Decisión

1. `LAF2ProgramService.generate_conditions` carga producto y publicaciones una
   sola vez. Devuelve el respaldo histórico completo y un programa por condición
   con peso > 0. Es el espejo de `LAF1ProgramService.generate_aspects`.
2. Cada programa por condición se arma por **selección explícita** sobre el
   programa del paso 10: se conservan sólo los hechos cuyo predicado es el de
   esa condición, su regla de agregación `compraBuena(X) :- <predicado>(X)` y la
   regla `recomendar(X) :- compraBuena(X)`. Las reglas de las otras condiciones
   no se generan en esa corrida; hoy tampoco disparaban, porque la máscara les
   dejaba el cuerpo sin hechos.
3. La anotación se proyecta a `{confianza}` con la **misma expresión regular**
   que `laf1_programs`. Las confianzas son las del constructor congelado de 10,
   con su redondeo: no se recalcula ninguna.
4. `evaluators` exige `attribute_count == 1` en la ruta por condición y envía el
   payload con **una sola operación**, la de confianza ya declarada en
   `BUDAN_2017_OPERATIONS`. No se modifica ningún operador. En esta ruta no se
   usa `zero_threshold_payload`.
5. Como el programa por condición ya no lleva β, deja de depender de los pesos
   del usuario. Los pesos siguen siendo externos y se aplican después, en
   `combine_rankings`, exactamente igual que antes.
6. Una condición sin ningún hecho en ese producto se detecta por
   `facts_count == 0` antes de parsear —el parser exige al menos un hecho— y
   sale del denominador con `conditions_without_evidence`, como hasta ahora.
   Las publicaciones que no cumplen ninguna condición activa se siguen
   completando al final con 0 desde el baseline.
7. La corrida combinada de respaldo de LAF2 se conserva **con dos etiquetas**,
   igual que en LAF1: es el baseline que da nombres, metadatos de compatibilidad
   y el desempate por confianza. No decide el puntaje.
8. No se tocan `combine_rankings`, el desempate, la cobertura, R3, la fila 13,
   el pipeline offline, el manifiesto congelado ni la configuración de dominio.
   Los adaptadores que no implementan `generate_conditions` conservan la ruta
   anterior (máscara + dos etiquetas), igual que ADR-002 dejó
   `_evaluate_products_multicriteria_reference` para LAF1.

## Contrato y compatibilidad

`aspect_programs`, `aspect_graphs` y `execution_payloads` siguen indexados por
condición de compra. Ahora los programas llevan una etiqueta, los grafos
guardados traen un atributo por nodo y los payloads ya no pasan por el borrado
de preferencia cero. `backup_laf_graph` conserva la corrida completa de dos
etiquetas.

En la fila del ranking, `metadata["label_count"]` pasa de `2` a `1`: describe la
corrida por condición que produjo el número, no el respaldo. Los campos
`confidence` y `preference` de la fila siguen siendo los metadatos históricos de
baseline, por compatibilidad; la explicación del puntaje son
`aspect_contributions` y los grafos guardados. El evaluador nuevo se identifica
como `laf-http-api-single-label-laf2-3.0.0` y el `run_id` agrega el sufijo
`-confidence-only-v1`, en paralelo con LAF1.

La vista «Ver por qué» no cambia. `listing_condition_graph` sigue devolviendo el
grafo guardado sin recalcular, y `hide_preference` —que `_friendly_relabel_laf2`
ya forzaba— ahora también es cierto estructuralmente: los nodos traen un solo
atributo.

## Verificación de identidad — 13/09/2026

Ningún número del ranking se movió. Todo con la API local
(`http://127.0.0.1:8088/api/graph`), la configuración real de `settings`/`.env`
y el café recongelado (`735f9b0c…`).

- Rankings de producción antes y después, con puntajes a 6 decimales:
  `validacion_laf2/salidas/unificacion_una_etiqueta/{antes,despues}/ranking_laf2.json`,
  producidos por `validacion_laf2/dump_unificacion_una_etiqueta.py`.
  Productos MLM19566313 (26 publicaciones, snapshot histórico) y MLM41148521
  (9 publicaciones, snapshot grano y molido), en tres perfiles: todo «bastante»,
  sólo precio, y envío + tienda oficial en prioridad.
- `validacion_laf2/comparar_unificacion_una_etiqueta.py`: **105 filas**
  ((26 + 9) × 3), mismo orden, mismo estado, mismas condiciones sin evidencia y
  |Δ puntaje| ≤ 1e-6; también coinciden las confianzas LAF por condición de cada
  contribución. Los únicos cambios son de presentación, y esperados:
  `evaluator_version` y `label_count`.
- `validacion_laf2/real_vs_replica.py`: **126/126** (45 + 45 + 36) en los tres
  snapshots, igual que antes del cambio.
- `validacion_laf2/verificar_vista_una_etiqueta.py`: recorre el flujo web dos
  veces sobre MLM19566313 —una con la ruta nueva y otra forzando la anterior— y
  compara la vista «Ver por qué»: misma oración por condición y mismo grafo por
  condición (mismos literales, mismas confianzas a 1e-6, mismas etiquetas y
  misma cantidad de aristas; el motor no garantiza el orden de la lista de
  nodos, así que se compara el conjunto). `hide_preference` es cierto en todos
  los nodos de las cuatro condiciones con evidencia.
- Suite Django completa: **205 pruebas, 0 fallos** (202 previas más las 3 de
  `recommender/tests/test_single_label_laf2.py`).
  `test_flow.test_local_audit_generates_and_exports_laf2_program` pasó a
  interceptar `generate_conditions`, que es la nueva costura de carga única.

## Límites

La equivalencia verificada corresponde a este snapshot, estos dos productos y
estos tres perfiles; no sustituye la validación de un cambio futuro de reglas.
La comprobación es sobre la **presentación de la evaluación**: no se revisó ni
se modificó la decisión multicriterio, el desempate ni la asimetría de
desempates entre LAF1 y LAF2, que sigue abierta.
