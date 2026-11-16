# Alternativas de un solo programa: comparación aislada del 30/09/2026

**Sí se encontró una variante de una sola corrida que conserva el resultado del diseño por aspecto:** un programa con terminales independientes `recomendarPorSabor`, `recomendarPorAroma`, etc., seguido de la misma suma ponderada. Se probó con la API local real, sin modificar la aplicación ni el manuscrito.

La interpretación definitiva de la propuesta del director queda pendiente de su correo. Esta prueba compara arquitecturas concretas; no atribuye al director una fórmula todavía desconocida.

## Entrada y alcance

- Programa histórico recongelado el 10/09/2026: `../../salidas/recongelado_20260910/despues/programa_laf1_D.txt`.
- Dataset `mlm_mlm194329_20260528_142014`, estrategia D: 18 productos, 14 aspectos, 259 hechos y 66 reglas.
- SHA256 del archivo fuente: `1a45b07f10251a1b6bcceced4f8af464efbccd6cb80ab34cf11b8fbb8aecd0c2`.
- Ranking neutral guardado y verificado en la interfaz el 11/09/2026, según `interfaz_vs_bateria_20260911.json` y la batería guardada del mismo snapshot.
- Motor calculador: `http://localhost:8088/api/graph`, usando el parser y mapper actuales.
- Los scripts de esta carpeta no acceden a base de datos ni modifican producción. Después se contrastaron sus resultados con la lectura fresca de Supabase realizada en el experimento paralelo `../comparar_confianzas.py`; se usaron sus artefactos guardados, sin nuevas corridas. Los artefactos de esta alternativa están exclusivamente en esta carpeta.

El número de reglas corresponde a esta fuente del 10/09, posterior al documento de una etiqueta del 09/09. No se sustituyeron los datos por los de un snapshot nuevo.

**La comparación con la entrada actual quedó comprobada para este mismo dataset:** los 14 vectores `scores_por_aspecto` de la variante `vigente` en `../resultados_confianzas.json`, procedentes de la lectura fresca del 30/09, coinciden con los aislados históricos y con la unión. Se compararon las mismas identidades de productos en 28 pares de vectores, con diferencia máxima **0**. El hash de las entradas frescas es `a1cffee71fbb3f11a7c3474ec5ff0a8c6b2255dd1ce93473ba7f94b8a5c88152`. Esta verificación cierra el contraste de entrada actual; no extiende el resultado a otros datasets.

Los hechos enviados al motor conservan la confianza redondeada a **dos decimales**, tal como la escribe el generador. La equivalencia verificada se refiere a esa representación efectiva de la aplicación, no a una hipotética ejecución de confianza sin redondear.

## Variantes y resultados

| Variante | Qué devuelve LAF | Combinación de preferencias | Resultado observado |
|---|---|---|---|
| Referencia: una corrida por aspecto | Un `recomendar` independiente por criterio | Suma ponderada externa | Reproduce el ranking neutral guardado, diferencia máxima `5,55 × 10^-17` |
| Una corrida, terminales independientes por aspecto | Vector de `recomendarPorAspecto`, conservando todas las cadenas y sus asimetrías | Misma suma ponderada | **Igualdad exacta del vector respecto de la referencia**; mismo ranking y puntajes en 17 perfiles |
| Una corrida, lectura de `aspectoBueno` | Vector de confianza a nivel de aspecto, antes de las reglas superiores | Suma ponderada del vector intermedio | Los nodos coinciden exactamente entre programa completo, vector y corridas aisladas, pero **los puntajes y el orden final cambian** frente al diseño actual |
| Una corrida, `recomendar` global | Confianza que ya agrega y enfrenta varios aspectos | Fórmula posterior todavía por definir | El escalar global observado difiere del score multicriterio neutral hasta `0,750925`; no contiene por sí solo el vector necesario para la misma ponderación |

La variante intermedia conserva el top-3 neutral en esta entrada, pero cambia otras posiciones y los puntajes; diferencia máxima del score neutral `0,173996`. Coincidir en el top-3 no demuestra equivalencia.

La variante con terminales independientes reúne los mismos 259 hechos y 84 reglas. Se clonan por aspecto las reglas que antes conducían a dimensiones y terminales compartidos. Por ejemplo:

```text
sensorialPorSaborBueno(X) :- saborBueno(X). {0.90}
~sensorialPorSaborBueno(X) :- ~saborBueno(X). {0.92}
recomendarPorSabor(X) :- sensorialPorSaborBueno(X). {0.90}
~recomendarPorSabor(X) :- ~sensorialPorSaborBueno(X). {0.92}
```

Es un único programa enviado en una llamada a la API. Sus componentes no comparten predicados, aunque sí identificadores de productos. Así se preservan las agregaciones y conflictos dentro de cada criterio y se evita mezclarlos antes de aplicar los pesos.

## Qué se comprobó con el motor

Se realizaron 17 llamadas principales: 14 referencias independientes, una unión con terminales independientes, un programa completo con escalar global y un programa con vector intermedio.

Para cada aspecto se compararon todos los nodos terminales positivos y negativos: multiplicidad, valores acumulados `mu` y debilitados `delta`. Las diferencias fueron **0**, dentro de la tolerancia fijada `10^-9`. Los terminales de las referencias y la unión son únicos por literal; por tanto, el mapper no necesita escoger entre derivaciones rivales para esos puntajes.

Se aplicaron después 17 perfiles: neutral, 14 de un solo aspecto, uno mixto con pesos `0 / 0,33 / 0,67 / 1` y todos los pesos en cero. La unión y las referencias independientes produjeron las mismas posiciones y puntajes en todos ellos. Estos perfiles comparan la regla externa de decisión sobre vectores ya calculados; no son 17 nuevas lecturas de la base de datos.

El perfil con todos los pesos cero verifica igualdad de un **resultado vacío**. Neutral y mixto contienen los 18 productos; varios perfiles individuales tienen un universo parcial porque el mapper no produce una conclusión positiva para todos los productos. Por ejemplo, solo acidez contiene 6 productos; molienda y tueste, 7; variedad, 10; dulzor, 12; caducidad y rendimiento, 15; preparación, 16; tamaño, 17. La igualdad se comprobó sobre el mismo universo presente en cada variante: no se afirmaron 18 productos en cada uno de los 17 perfiles.

En el programa global hay 29 literales `recomendar` o `~recomendar` con varios nodos. Se guardan todos sus valores, aristas y la selección del mapper. En esta ejecución ningún nodo escogido por el mapper tenía otra agregación saliente hacia el mismo literal. Esto no constituye una demostración general de corrección del mapper para cualquier programa futuro.

## Por qué multiplicar un aspecto debilitado no conserva la cadena

Ejemplo real: Blasón, sabor, hechos positivos `0,94` y negativos `0,06` del programa fuente. Con `D(P,N) = max((P-N)/(1-N),0)`:

| Nivel | Acumulado positivo | Acumulado negativo | Debilitado positivo |
|---|---:|---:|---:|
| `saborBueno` | `0,94 × 0,85 = 0,799` | `0,06 × 0,85 = 0,051` | `0,7881981033` |
| `sensorialBueno` | `0,799 × 0,90 = 0,7191` | `0,051 × 0,92 = 0,04692` | `0,7052713308` |
| `recomendar` | `0,7191 × 0,90 = 0,64719` | `0,04692 × 0,92 = 0,0431664` | `0,6312734001` |

En cambio, `0,7881981033 × 0,90 × 0,90 = 0,6384404636`: difiere en `0,0071670635`. La API real confirma el terminal `0,6312734001`. El soporte utiliza valores acumulados de ambas polaridades; el conflicto se calcula en cada nivel. Un único debilitado pierde información sobre esas dos entradas.

Incluso con factores simétricos la dificultad persiste. Como ejemplo matemático, `D(0,5;0)=D(0,75;0,5)=0,5`, pero aplicar un factor `0,8` a ambos soportes produce respectivamente `D(0,4;0)=0,4` y `D(0,6;0,4)=1/3`. Por ello no existe una simple transformación del debilitado original que reproduzca todos los casos.

Tampoco una agregación escalar simétrica conserva la distribución por criterio. Los vectores `(0,9;0,1)` y `(0,1;0,9)` tienen el mismo agregado `X+Y-XY = 0,91`, pero con pesos `(0,8;0,2)` sus sumas ponderadas son `0,74` y `0,26`. Es un contraejemplo matemático, no una nueva observación del corpus.

## Qué falta antes de incorporar la variante

1. Confirmar con el correo si «un solo programa» significa terminales independientes, lectura de aspectos o un `recomendar` global, y cuál es la fórmula de preferencia propuesta.
2. Repetir la equivalencia en los demás snapshots. El contraste con la entrada actual de este dataset ya quedó cerrado con diferencia cero mediante los resultados de la lectura fresca del 30/09.
3. Probar explícitamente entradas sintéticas de frontera: `0/1`, empate completo, solo evidencia negativa, aspecto sin evidencia y reglas futuras con varios antecedentes o ciclos. La entrada real ya contiene ausencias y ambos signos, pero no cubre todas las fronteras.
4. Si se elige incorporar: adaptar generación, extracción de terminales, persistencia y explicación; verificar que cada aspecto siga mostrando su evidencia y que los pesos cero produzcan el comportamiento previsto.
5. La equivalencia técnica no justifica por sí sola los valores de confianza de las reglas. Su sensibilidad y fundamento se estudian en un experimento separado.

## Reproducibilidad

Desde la raíz del repositorio:

```powershell
./venv/Scripts/python.exe validacion_laf1/revision_director_20260930/alternativa_programa_unico/comparar_estructura_offline.py
./venv/Scripts/python.exe validacion_laf1/revision_director_20260930/alternativa_programa_unico/comparar_motor_local.py
```

El primer script solo utiliza la biblioteca estándar y no ejecuta LAF. El segundo envía los programas preparados al calculador local y guarda los grafos completos en `grafos_motor/` y los nodos, selecciones y rankings en `comparacion_motor_local.json`. `comparacion_offline.json` conserva el diagnóstico previo a la prueba con motor; sus pendientes se resuelven o se delimitan en este informe y en el resultado de la API.
