# Preferencias antes de LAF y reglas con varios aspectos

Revisión del 30/09/2026. Fuentes: código y artefactos técnicos; no se usaron manuscritos locales. Las nuevas pruebas solo enviaron datos al calculador local `http://localhost:8088/api/graph`, sin acceder a la base de datos ni modificar producción.

**Sí hubo una evaluación anterior de preferencias antes de LAF**, incluida una alternativa que multiplicaba la confianza de cada hecho por su preferencia. No es correcto afirmar que todas esas posibilidades fueron descartadas o que poner preferencias antes del motor resulta imposible. Hay que distinguir las siguientes variantes.

## Qué se evaluó anteriormente

| Variante | Ubicación y significado del peso | Evidencia técnica | Alcance del resultado |
|---|---|---|---|
| Legacy / EXP1 | La preferencia del usuario viaja como segunda etiqueta `β` de los hechos; `α` permanece independiente. Las reglas de los programas ensayados llevan `β=1` | `experimentos_legacy_y_segundo_laf.py:63–94`; `salidas/prog_neutral.txt:622–649`; `EXPERIMENTOS_LEGACY_SEGUNDO_LAF.md:28–53` | Se probaron cambios del conflicto y leer confianza o `min(α,β)`. No es multiplicar confianza por peso |
| EXP3 | `β_hecho = w_a / Σw`, con confianza intacta | `legacy_preferencias_normalizadas.py:37–42,44–60`; documento anterior `:76–96` | La normalización evita parte de la saturación, pero no elimina `β_pos=β_neg` y su conflicto en un solo aspecto |
| EXP5 | Se cambia el álgebra de la segunda etiqueta, dejando la confianza como estaba | `exp5_cambiar_algebra_preferencia.py:37–57`; documento `:323–353` | Son pruebas sobre esa representación de preferencia; no sobre `α_hecho←w·α_hecho` |
| EXP6 | Una preferencia distinta para las críticas en la segunda etiqueta; además se prueba comparación lexicográfica posterior | `exp6_lexicografico_y_peso_criticas.py:1–11,65–80`; documento `:424–453` | Cambia la importancia de las críticas, no la confianza de los hechos ni los pesos de las reglas |
| EXP10 | Preferencia binaria: incluir o excluir hechos antes de una corrida global; leer confianza de `recomendar` | `exp10_programa_unico_binario.py:12–24`; `EXP10_PROGRAMA_UNICO_BINARIO.md:9–13` | Un filtro `0/1` no prueba el efecto continuo de `0,33` frente a `0,67` |
| `weighted_confidence` | Se excluye peso cero y se aplica `α_hecho←α_hecho·w`; se conserva la segunda etiqueta y se pone `β_hecho=1` | `webapp/recommender/services/preference_alternatives.py:66–83,187–200,260–266` | **Esta ponderación continua sí se implementó y se ejecutó**, pero su lectura conserva `min(α,β)`, con la limitación descrita debajo |
| EXP4, relacionado | Antes de LAF se calculan promedios ponderados de todos los soportes positivos y negativos; se crean solo `aFavor` y `enContra` por producto | `exp4_agrupar_fuera_luego_laf.py:1–13,51–61`; documento `:98–120` | Es una agregación externa anterior al conflicto, no ponderar cada rama conservando la argumentación por aspecto |

No encontré una batería histórica que multiplicara la confianza de las **reglas** por el peso continuo del usuario. La prueba nueva de esta carpeta sí evalúa ese caso en la regla puente `aspecto→dimensión`, una sola vez por camino. Tampoco debe confundirse la antigua `β` estructural experta de configuración con el peso que el usuario mueve en los sliders: los programas utilizados en los experimentos citados llevan esa segunda componente de las reglas neutralizada en `1`.

### Artefactos de ejecución de `weighted_confidence`

Carpeta histórica: `webapp/reports/recommendation_quality/20260829_172756_10cf385a-c810-4c3f-81f4-151788c3e575/comparacion_modelos/`.

- `experimento_preferencias.json:2–28,83–112`: fecha registrada 29/08/2026; dataset histórico, estrategia D; 20 casos, 13 aciertos exactos y esperado en el top-3 en los 20. Se identifica como desarrollo, sin evaluación ciega independiente.
- `resumen.md:7,13,22`: revisión humana asistida, significado `confianza×preferencia` y los mismos resultados.
- `sensibilidad_pesos.json:29–35,1242–1252`: 42 perfiles, variando cada uno de 14 aspectos en `0,33/0,67/1` con fondo `0,67`. Ningún aspecto cambia ganador o top-3 entre extremos, pero 10/14 cambian el puntaje del ganador. Por tanto, no era completamente insensible.
- `sensibilidad_pesos.md:15–17`: esta sensibilidad no evalúa calidad del ganador.

Estos resultados acreditan una evaluación anterior. La carpeta no contiene los payloads y grafos crudos de aquella comparación ni una versión de código certificada por ejecución. No son una nueva verificación del modelo vigente, y las expectativas humanas de desarrollo asistido no permiten concluir superioridad general.

**Limitación de aquella implementación:** `weighted_confidence_payload` no elimina la segunda etiqueta. El runner usa el mapper común, cuyo veredicto es `min(confianza,preferencia)` (`laf_api.py:296–307`). Un elogio y una crítica del mismo aspecto pueden propagar `β=1` a ambos lados y terminar con `β=0`. En un programa global hay además múltiples derivaciones del mismo literal; el mapper escoge el mayor mínimo. Por eso una dificultad de esa implementación no es una demostración contra el método genérico de ponderar `α` antes de LAF.

## Nueva prueba acotada: una sola etiqueta y pesos continuos

Script nuevo: [preferencias_antes_laf.py](preferencias_antes_laf.py). [Resultados completos en JSON](preferencias_antes_laf/resultados.json), programas y grafos: `preferencias_antes_laf/`. Entrada histórica congelada de 18 productos y 14 aspectos, ya contrastada con la entrada fresca del mismo dataset en `RESULTADOS.md`.

Se comparan dos lugares para aplicar **una sola vez** el mismo factor en cada rama positiva y negativa:

1. `α_hecho←w_a·α_hecho`, con reglas intactas.
2. `α_regla aspecto→dimensión←w_a·α_regla`, con hechos intactos.

Ambas variantes usan una etiqueta; los hechos de peso cero se excluyen. Conservan las restantes reglas, sus asimetrías y un `recomendar` global. El producto nuevo se representa con hasta 12 cifras significativas, partiendo de los hechos originales redondeados a dos decimales. No se introduce un redondeo adicional a dos decimales del valor ponderado.

| Perfil | Diferencia máxima hechos vs regla puente | Relación con la suma ponderada posterior vigente |
|---|---:|---|
| Todos `0,67` | `8,88×10^-16` | Cambia el orden; gana Gourmet Espresso; diferencia máxima de puntaje `0,673221` |
| Todos `0,33` | `3,33×10^-16` | Cambia el orden; gana Blasón; diferencia máxima `0,455268` |
| Mixto `0/0,33/0,67/1` | `4,44×10^-16` | Cambia el orden; diferencia máxima `0,586211` |
| Solo sabor, peso `1` | `0` | Coincide exactamente |
| Solo aroma, peso `1` | `0` | Coincide exactamente |

Son viables técnicamente. En esta estructura simple, aplicar el peso al hecho o a la regla puente antes de la primera agregación produce los mismos soportes y resultados, salvo precisión de coma flotante. **No son equivalentes al ranking vigente.** Tampoco se comprobó cuál recomienda mejor: esta prueba mide comportamiento y sensibilidad, no exactitud humana.

La coincidencia entre ponderar hechos y ponderar la regla puente se comprobó **solo para la estructura actual y los cinco perfiles examinados**. No se extiende a una regla conjuntiva general: si se pondera cada premisa de dos aspectos, el soporte producto puede introducir `w_a·w_b`; ponderar una sola regla por un único factor introduce otra operación, salvo que se elija y justifique precisamente ese producto de pesos. Además la conjunción exige que estén presentes ambas premisas.

Un hallazgo relevante para elegir la semántica: reducir todos los pesos de `0,67` a `0,33` conserva sus proporciones, pero cambia el ganador en la ponderación interna global. El promedio ponderado normalizado posterior conserva el mismo resultado cuando todos los pesos se reescalan por un factor común. Si los sliders representan importancia relativa, esa invariancia es una propiedad deseable; si se desea importancia absoluta o umbrales de relevancia, habría que explicitar y validar otra interpretación.

No se debe multiplicar a la vez el hecho y varias reglas por el mismo peso sin intención expresa: un camino con varias ponderaciones introduciría potencias de ese peso. Si se aplica después de una agregación, tampoco se garantiza la equivalencia con aplicarlo antes: `w(P1⊕P2)` y `(wP1)⊕(wP2)` difieren para `⊕=X+Y−XY`.

La comparación histórica del 29/08 usa dos etiquetas y otra lectura final; la prueba nueva elimina esa segunda componente. Se trata de una evaluación nueva y acotada de la idea, **no de una réplica exacta ni de una verificación de equivalencia con los resultados de agosto**.

### Ejemplo sintético del orden de operaciones

La API confirma, con soportes positivos `0,8`, negativos `0,3` y peso `0,4`:

- Segunda etiqueta en hechos o reglas: confianza debilitada `0,714286`, preferencia debilitada `0`; el mínimo es `0`.
- Una etiqueta, escalando ambos soportes antes del conflicto: `D(0,32;0,12)=0,227273`.
- Conflicto primero y contribución ponderada después: `0,4·D(0,8;0,3)=0,285714`.

La última cifra es una **contribución antes de la normalización final**, no el score de un perfil de un solo aspecto. En el promedio normalizado, el único peso positivo se cancela con el denominador. El ejemplo demuestra que ponderación y conflicto no conmutan; no prueba que una interpretación sea universalmente incorrecta.

## Reglas de varios aspectos: qué cambia

Una regla como `sensorialBueno(X) :- saborBueno(X), aromaBueno(X)` exige los dos antecedentes para derivarse. Es una interacción entre criterios, distinta de disponer de dos reglas simples con la misma conclusión.

**La confianza conjuntiva de esta implementación usa producto, no mínimo.** El perfil `BUDAN_2017_OPERATIONS` declara `supportFunction="X * Y"` para confianza y `min(X,Y)` para la segunda etiqueta (`laf_api.py:27–37`). Una prueba sintética real, `sinergiaBueno :- saborBueno, aromaBueno` con confianzas `0,8`, `0,6` y regla `0,9`, devuelve `0,432 = 0,8·0,6·0,9`, no `0,54 = min(0,8;0,6)·0,9`. La frase «soporte mínimo» de `EXP9_REGLAS_CONJUNTIVAS.md:6,39` no describe la etiqueta de confianza de esta ejecución. La conclusión lógica sobre falta de antecedentes sigue siendo pertinente.

EXP9 ensayó conjunciones de todos los aspectos de una dimensión, positivas o de ambos signos, y una conjunción de dimensiones para recomendar (`exp9_reglas_conjuntivas.py:25–49`). EXP9c ensayó pares positivos, pares de ambos signos y un híbrido de pares más simples (`exp9c_reglas_pares.py:7–24,36–38`). Hay resultados históricos registrados en `EXP9_REGLAS_CONJUNTIVAS.md:23–34,59–69` y `salidas/exp9c_pares_salida.txt`. Los pares mejoran la cobertura del neutral, pero sin regla simple no derivan con «solo sabor»; el híbrido agrega muchas rutas y vuelve a acercar valores al tope. **Eso limita esas variantes concretas; no descarta cualquier regla de dos aspectos ni un programa único.**

### Efecto sobre la equivalencia ya comprobada

La unión de terminales independientes coincide con 14 corridas porque los subprogramas no comparten predicados ni dependencias entre criterios. Las reglas existentes relevantes para cada criterio tienen un único antecedente y conservan su cadena. Esa condición no es automáticamente válida después de añadir una regla compuesta.

- Si la regla deriva una **conclusión nueva aguas abajo**, como `sinergiaBueno`, sin atacar ni alimentar los nodos anteriores, los valores de `saborBueno`, `aromaBueno` y sus terminales independientes pueden seguir iguales. La nueva conclusión conjunta requiere ambos aspectos en el mismo cálculo. Si se incorpora al score final, debe definirse cómo se pondera esa interacción.
- Si la regla alimenta una **dimensión compartida** o el **`recomendar` global**, cambia la evaluación conjunta de ese nivel. Los nodos originales de aspecto no necesariamente cambian si no hay un camino de retorno, pero el terminal que depende de la nueva conclusión sí puede cambiar.
- Si la regla apoya o ataca **un aspecto o uno de los terminales independientes**, ese criterio pasa a depender de otros. Aislar únicamente su evidencia ya no reproduce su evaluación completa. Habría que incluir toda la evidencia y reglas de las que depende, o modelar la interacción como otro criterio explícito.

La prueba sintética comprueba dos de estas situaciones de forma controlada: añadir una `sinergiaBueno` nueva conserva los nodos existentes y produce la sinergia `0,432`; añadir `~recomendarPorSabor :- aromaBueno` con regla `0,5` cambia el terminal de sabor de `0,75` a `0,642857`. Se mantuvo la evidencia de sabor: cambia por la conexión nueva con aroma.

Una suma ponderada de criterios independientes es compensatoria y no representa por sí sola sinergias, condiciones conjuntas o vetos. Si el dominio requiere una interacción, debe justificarla y evaluar su cobertura, tratamiento de evidencia ausente, efecto de peso cero, signo y lugar en la preferencia final. Puede hacerse con un programa conjunto, con un subprograma por criterio compuesto o con una segunda capa explícita. La elección depende del significado que se busca; no del número de llamadas al motor aislado de esa semántica.

## Formulación defendible

«Se compararon distintas formas de introducir la preferencia: como segunda etiqueta, como selección de evidencia, como ponderación de la confianza anterior al conflicto y como peso posterior. Las variantes no son equivalentes. La ponderación interna de confianza es ejecutable y fue evaluada, pero altera la semántica y el comportamiento frente al reescalado de pesos. El modelo elegido preserva la valoración de evidencia por criterio y aplica las preferencias en una decisión posterior. La equivalencia entre una o varias ejecuciones se comprobó para criterios independientes; requiere nueva validación si se incorporan reglas que conectan criterios».

Reproducir únicamente la prueba acotada nueva:

```powershell
./venv/Scripts/python.exe validacion_laf1/revision_director_20260930/alternativa_programa_unico/preferencias_antes_laf.py
```

No se recomienda sustituir el método vigente solo porque otra variante cambie ganadores o se parezca a él. Una adopción requiere acordar la semántica y evaluar calidad con casos independientes; la existencia del código o una comparación de sensibilidad no basta.
