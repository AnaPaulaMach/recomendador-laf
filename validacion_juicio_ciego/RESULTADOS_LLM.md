# Experimento 1-bis — Lector automático (LLM) · RESULTADOS

**Observación secundaria.** No es un juez humano ni un criterio externo: es un
lector automático que evalúa a otro sistema automático. Se informa porque estaba
pre-registrado en `README_LLM.md` y porque **se corrió**; ocultarlo sería reporte
selectivo, tanto más cuanto que su resultado es **favorable** al sistema.

**Fecha:** 2026-09-10 · Snapshot `mlm_mlm194329_20260528_142014` · aspecto `sabor`
**Modelos:** `gpt-5.4-mini-2026-03-17` (temperatura 0) y `gpt-5.5-2026-04-23`
(temperatura por defecto: el proveedor no admite 0 en ese modelo, ver enmienda
del pre-registro)
**Material:** exactamente el mismo que leyó la jueza, con el mismo enmascarado y
la misma asignación A/B
**Prompt:** congelado en el apéndice de `README_LLM.md` **antes** de que nadie
mirara las respuestas de la jueza
**Salida cruda:** `salidas/llm_respuestas_solapamiento_20260910_1315.csv`
(100 llamadas, 49 s) · métricas en `llm_resumen_solapamiento_20260910_1315.json`

---

## 1. Alcance realizado y no realizado

| Fase | Estado |
|---|---|
| **Solapamiento** — los 20 pares que respondió la jueza | **completa**, 100 llamadas |
| **Ampliación** — los 151 pares elegibles | **NO REALIZADA: se agotó el crédito de la API** |

Sobre la ampliación, para que quede el registro exacto: hubo dos intentos. El
primero (script sin guardado incremental) hizo unas 600 llamadas y **no guardó
nada** — error de implementación, ya corregido. El segundo, con el script
arreglado, se interrumpió: quedaron 143 registros en
`salidas/llm_respuestas_completa_20260910_1322.csv`, de los cuales **96 son
errores `HTTP 429 · sin crédito`** y **47 respuestas**, que cubren sólo **7 pares
completos** de 151. Es insuficiente para calcular cualquier métrica y **no se
informa ninguna cifra a partir de ese archivo**; queda como rastro auditable.

**Consecuencia:** se pierde la precisión que motivaba todo este instrumento
(§2 del pre-registro). Lo que sigue son 20 pares, con intervalos anchos.

## 2. Control 1 — sesgo de posición

Cada par se preguntó dos veces, con los lados invertidos.

| Modelo | Inconsistentes | Tasa | ¿Pasa? |
|---|---:|---:|---|
| gpt-5.4-mini | 4 de 20 (P01, P06, P07, P10) | **20,0 %** | sí, en el límite |
| gpt-5.5 | 4 de 20 (P06, P07, P13, P16) | **20,0 %** | sí, en el límite |

> ⚠️ **Los dos quedaron exactamente sobre el umbral de descarte** (más del 20 %
> anulaba la corrida). En 1 de cada 5 pares el modelo cambia de respuesta si se
> invierten los lados. **Es un instrumento débil** y así hay que citarlo. Los dos
> modelos coinciden en fallar en P06 y P07, que son pares sin ninguna crítica
> mostrada — los mismos donde la jueza no pudo decidir.

**Ruido de muestreo** (sólo `gpt-5.5`, que no admite temperatura 0): repitiendo
la presentación idéntica, cambió de respuesta en **2 de 20 (10 %)**. Es decir que
de su 20 % de inconsistencia, aproximadamente la mitad es variabilidad del
modelo y la otra mitad sesgo de posición.

## 3. Control 2 — acuerdo con la lectura humana

| Modelo | Acuerdo con la jueza | ¿Habilita la ampliación (≥ 70 %)? |
|---|---:|---|
| gpt-5.4-mini | 9 de 12 = **75,0 %** | sí |
| gpt-5.5 | 11 de 13 = **84,6 %** | sí |

Los dos habilitaban la ampliación. No se pudo hacer por el crédito, no por el
control.

## 4. Acuerdo con el sistema

Sobre los pares consistentes con veredicto:

| Modelo | Total | Grande | Mediana | Chica |
|---|---:|---:|---:|---:|
| gpt-5.4-mini | 12/15 = **80,0 %** | 5/5 = 100 % | 4/6 = 67 % | 3/4 = 75 % |
| gpt-5.5 | 11/15 = **73,3 %** | 3/4 = 75 % | 4/6 = 67 % | 4/5 = 80 % |

Acuerdo entre los dos modelos: **14 de 15 = 93,3 %**. No es acuerdo entre jueces:
son dos modelos del mismo proveedor, con datos de entrenamiento y familia
compartidos. Se informa como descriptivo y **no se calcula κ sobre ellos**.

## 5. Los tres lectores sobre el mismo subconjunto

Las cifras de §3 y §4 se calculan sobre conjuntos de pares distintos, así que no
son comparables entre sí. Sobre los **12 pares donde la jueza y los dos modelos
dieron veredicto**:

| Comparación | Acuerdo |
|---|---:|
| sistema – jueza | 6/12 = **50,0 %** |
| sistema – gpt-5.4-mini | 9/12 = **75,0 %** |
| sistema – gpt-5.5 | 8/12 = **66,7 %** |
| jueza – gpt-5.4-mini | 9/12 = 75,0 % |
| jueza – gpt-5.5 | 10/12 = 83,3 % |
| gpt-5.4-mini – gpt-5.5 | 11/12 = 91,7 % |

No hay contradicción aritmética: **el acuerdo no es transitivo**. El lector
automático queda *entre* la jueza y el sistema, más cerca del sistema que ella.

En la franja de diferencia grande (sólo 3 pares en este subconjunto): la jueza
coincide con el sistema en **1 de 3**, `gpt-5.4-mini` en **3 de 3**.

**Con 12 pares, esa diferencia no se distingue del azar.** No se afirma que el
lector automático «acierte más»: se informa que se comporta distinto.

## 6. Un detalle que sí explica algo

De los 20 pares, la jueza no pudo decidir en 6 — casi todos pares **sin ninguna
crítica mostrada de ningún lado**. Ahí ella se queda sin criterio (ver
`RESULTADOS_POST_HOC.md`: su criterio es la crítica). Los modelos, en cambio,
igual producen un veredicto en varios de esos pares, y en P12, P13 y P20
coinciden con el sistema.

Es decir: **el lector automático se parece más al sistema en parte porque no se
abstiene donde una persona sí lo hace.** Un modelo de lenguaje contesta siempre
que puede; una persona dice «con esto no me alcanza». Esa diferencia de conducta,
y no una mejor lectura, explica una porción del acuerdo mayor.

## 7. Qué se puede y qué no se puede decir

**Se puede:** el lector automático, con este material y con estos controles, se
comporta más parecido al sistema que la jueza humana, y bastante parecido a la
jueza. Los dos modelos coinciden mucho entre sí.

**No se puede:** afirmar que esto valide el ranking. Son 20 pares, con un
instrumento que se contradice a sí mismo en el 20 % de los casos, evaluando a
otro sistema automático. **No modifica en nada el resultado pre-registrado del
experimento 1**, que sigue siendo que el criterio de fracaso se cumplió.

## 8. Limitaciones

- No es un juez humano ni un criterio externo.
- **20 % de inconsistencia por posición**, justo en el límite de descarte.
- `gpt-5.5` corrió con temperatura por defecto: **su salida no es reproducible**;
  el proveedor puede además cambiar el modelo detrás del mismo nombre. Sólo la
  salida cruda guardada es auditable.
- Los dos modelos no son independientes entre sí.
- La ampliación a 151 pares, que era la única razón de existir del instrumento,
  **no se hizo**.
- Hereda todas las limitaciones del material: 15 fragmentos por lado, excerpts
  truncados a 200 caracteres, menciones `neu` incluidas, anonimización
  imperfecta, y —sobre todo— **el volumen de evidencia sigue siendo invisible**
  también para el modelo.
