# Experimento 1-bis — Lector automático (LLM) sobre los pares (PRE-REGISTRO)

**Estado: PRE-REGISTRO. Escrito ANTES de llamar a ninguna API.**
**Fecha de redacción: 2026-09-10.** Pendiente de aprobación de Ana Paula Machado.

Complementa `README.md` (experimento 1). Aquel quedó con **un** juez humano en
ciego; éste agrega un lector automático que puede cubrir **todos** los pares
elegibles, y define por adelantado cuándo su salida vale y cuándo se tira.

---

## 1. Qué es y qué no es

Un modelo de lenguaje lee **exactamente el mismo material anonimizado** que la
jueza humana y contesta la misma pregunta. Nada más.

**No es un juez.** No se informa como «juez», ni como «evaluador humano», ni se
promedia con la respuesta de Ana. Es un **instrumento de ampliación** cuya
validez se comprueba contra la lectura humana, nunca al revés. En la tesis se
nombra como «lector automático» y se declara el modelo usado.

**Por qué no reemplaza al humano.** El experimento 1 existe para traer un
criterio de fuera del sistema; toda la evaluación previa (`validacion_oe5/`)
compara el ranking contra estrellas y proporciones del mismo corpus, y eso es
circular. Un LLM leyendo los mismos fragmentos sigue siendo una máquina leyendo
texto para evaluar a otra máquina: no rompe la circularidad, la disimula. Se usa
por lo que sí aporta —**cobertura**— y no por lo que no aporta.

**Nota de procedencia, a favor del diseño:** la extracción de aspectos de este
TFG **no** usa LLM. `05_aspects.py` es léxico y reglas (las correcciones v15 a
v17 son reglas), y el LLM aparece únicamente como sugeridor opcional en la
curaduría del dominio, con decisión experta (`docs/GUIA_METODOLOGICA.md` §4.1).
Por lo tanto el lector automático no comparte componente con el extractor. Aun
así sigue siendo máquina contra máquina, y se informa como tal.

## 2. Por qué se agrega: la potencia

El experimento 1 con 20 pares no distingue un sistema del 70 % de uno del 90 %
(`README.md` §9). Sobre los **151 pares elegibles** el intervalo se angosta lo
suficiente para que la cifra signifique algo. Ésa es la única razón de existir de
este instrumento.

## 3. Entradas congeladas

Las mismas del experimento 1: snapshot `mlm_mlm194329_20260528_142014`, aspecto
`sabor`, estrategia D, puntaje LAF por aspecto, y la misma definición de par,
fragmento, elegibilidad y franja de distancia. **No se vuelve a sortear nada.**

- **20 pares de solapamiento:** los ya congelados en
  `salidas/tabla_pares_con_puntajes_sabor_20260910.csv`, con **la misma evidencia
  y la misma asignación A/B** que ve Ana (se leen de
  `salidas/fragmentos_usados_sabor_20260910.csv`).
- **151 pares completos:** todos los pares elegibles con |Δ| > 0. Su evidencia se
  muestrea con la misma regla del `README.md` §5.2 y la semilla
  `SEMILLA_FRAGMENTOS = 20260911`, continuando la secuencia; los 20 originales
  conservan la evidencia ya generada.

## 4. Procedimiento

1. Al modelo se le da la consigna (versión corta, sin las partes operativas
   dirigidas a una persona), los 15 fragmentos de A y los 15 de B, y se le pide
   **una sola respuesta**: `A`, `B` o `no_puedo_decidir`, más una justificación
   breve en texto libre.
2. **Cada par se pregunta dos veces, con los lados invertidos** (A↔B). Ver §5.
3. Temperatura 0. Sin memoria entre pares: cada par es una llamada independiente.
4. Se guardan, para cada llamada: modelo, fecha y hora, prompt exacto, respuesta
   cruda y respuesta normalizada.

**Reproducibilidad — declarada como limitación.** La salida de un LLM **no es
reproducible como una semilla**. Aunque se fije temperatura 0, el proveedor puede
cambiar el modelo detrás del mismo nombre. Por eso se registra el identificador
exacto del modelo y la fecha de la corrida, y se guarda **la salida cruda
completa**, que es lo único verdaderamente auditable. Cualquier re-corrida
posterior es una corrida nueva y se informa por separado.

## 5. Control 1 — sesgo de posición (validez del instrumento)

Un LLM puede responder por la posición del texto en el prompt y no por su
contenido. Se detecta así:

- Cada par se pregunta dos veces, invirtiendo qué lado se presenta primero.
- Un par es **consistente** si las dos respuestas son coherentes: mismo producto
  elegido en las dos presentaciones, o `no_puedo_decidir` en ambas.
- Un par es **inconsistente** si al invertir los lados el modelo cambia de
  producto, o si contesta producto en una presentación y `no_puedo_decidir` en la
  otra.
- Los pares inconsistentes **no cuentan** para ninguna métrica y se informan
  aparte.

> **Criterio de descarte pre-registrado:** si más del **20 %** de los pares
> resultan inconsistentes, el instrumento se declara no confiable y **toda la
> corrida automática se descarta**. No se informa ninguna cifra de acuerdo
> sistema–LLM; se informa únicamente la tasa de inconsistencia.

## 6. Control 2 — acuerdo con la lectura humana (validez de la extrapolación)

Sobre los **20 pares de solapamiento** se mide el acuerdo entre el veredicto del
LLM y el de Ana, contando sólo los pares en que ambos dieron `A` o `B`.

> **Criterio de extrapolación pre-registrado:** la cifra de acuerdo
> sistema–LLM sobre los 151 pares se informa como estimación **sólo si** el
> acuerdo LLM–Ana en los 20 pares alcanza el **70 %**. Si no lo alcanza, se
> informa únicamente que **el lector automático no reproduce la lectura humana**,
> y la corrida de 151 queda como material de anexo, sin usarse como evidencia
> sobre el sistema.

Ese resultado negativo también es un resultado y se escribe como tal.

## 7. Orden de ejecución (no negociable)

1. Ana entrega su planilla de los 20 pares.
2. Recién entonces se corre el LLM.

**Motivo:** si el LLM corriera primero y su salida estuviera a la vista, la
lectura de Ana dejaría de ser ciega. El script verifica que exista
`respuestas/planilla_juez_1.csv` y **se niega a correr** si no está.

## 8. Modelos

Se corre con **dos modelos distintos** del proveedor disponible (`OPENAI_API_KEY`
del `.env`), declarados en la salida. Dos modelos del mismo proveedor **no son
lectores independientes**: comparten datos de entrenamiento y familia. Se usan
para detectar inestabilidad grosera, no como un panel. Se informa el acuerdo
entre ambos como descriptivo, **sin llamarlo acuerdo entre jueces y sin calcular
κ sobre ellos**.

## 9. Métricas

Para cada modelo, y sólo si pasa el control del §5:

1. Tasa de pares inconsistentes (control de posición).
2. Acuerdo LLM–Ana en los 20 pares de solapamiento, con IC 95 % de Wilson.
3. Acuerdo sistema–LLM sobre los 151 pares, con IC 95 % de Wilson, **informado
   sólo si se cumple el §6**.
4. Acuerdo sistema–LLM por franja de distancia (grande / mediana / chica) sobre
   los 151.
5. Tasa de `no_puedo_decidir` por franja.
6. Acuerdo entre los dos modelos (descriptivo).

## 10. Qué NO se hará

- No se promedia la respuesta del LLM con la de Ana ni se construye un
  «veredicto mayoritario» mezclando ambos.
- No se ajusta ningún parámetro, umbral, regla ni operador del sistema según
  este resultado. La metodología sigue congelada.
- No se reescribe el prompt después de ver los resultados. El prompt queda fijado
  antes de la primera llamada y se guarda con la salida.
- No se elige el modelo después de ver cuál da mejor acuerdo.

## 11. Entregables

| Archivo | Cuándo |
|---|---|
| `README_LLM.md` (este documento) | antes de correr |
| `juez_llm.py` | tras la aprobación |
| `salidas/llm_respuestas_<modelo>_<fecha>.csv` | salida cruda y normalizada, las dos presentaciones |
| `salidas/llm_resumen_<fecha>.json` | métricas del §9 |
| sección en `RESULTADOS.md` | junto con el resultado humano |

## 12. Limitaciones (a repetir en RESULTADOS.md)

- **No es un juez humano ni un criterio externo.** Es un lector automático que
  evalúa a otro sistema automático.
- **No es reproducible como una semilla**: el proveedor puede cambiar el modelo
  detrás del mismo nombre. Sólo la salida cruda guardada es auditable.
- **Los dos modelos no son independientes** entre sí.
- Un LLM puede tener preferencias sistemáticas por cierto vocabulario evaluativo
  («excelente», «delicioso») que no se corresponden con cómo una persona pesa la
  evidencia. El control del §5 detecta sesgo de posición, **no** este otro.
- Hereda todas las limitaciones del material: 15 fragmentos por lado, excerpts
  truncados a 200 caracteres, menciones `neu` incluidas, anonimización
  imperfecta.

---

## Apéndice — Prompt exacto (CONGELADO el 2026-09-10)

Fijado **antes** de mirar las respuestas de la jueza humana, para que no pueda
haberse ajustado a ellas. Es una transcripción de la consigna que leyó Ana
(`materiales/INSTRUCCIONES.md`), sin las partes operativas dirigidas a una
persona (cómo abrir el HTML, cómo entregar la planilla, participación voluntaria)
y sin la estimación de tiempo. No se modifica después de la primera llamada.

**Mensaje de sistema:**

```
Sos una persona que toma café y está ayudando a evaluar un sistema
informático. Vas a comparar dos productos de café a partir de opiniones
reales de personas que los compraron. No vas a ver el nombre ni la marca de
los productos, ni las estrellas que les pusieron: solo los pedacitos de
reseña donde se habla del sabor.

No hay respuesta correcta. No se está evaluando si acertás: se está
comparando tu lectura con la de un programa, y si no coinciden el que queda
en problemas es el programa.

Contestá solo con lo que leés. Si las opiniones no te alcanzan para decidir,
respondé "no_puedo_decidir": es una respuesta válida y esperada.

Los fragmentos están cortados y a veces se entienden a medias. Es así a
propósito: es el texto exacto que lee el programa.

Respondé SIEMPRE en este formato exacto, sin nada más:
VEREDICTO: A | B | no_puedo_decidir
MOTIVO: <una o dos oraciones>
```

**Mensaje de usuario (por par):**

```
Producto A:
1. <fragmento>
...
15. <fragmento>

Producto B:
1. <fragmento>
...
15. <fragmento>

Según estas opiniones, ¿cuál tiene mejor sabor?
```

Parámetros: temperatura 0, una llamada independiente por presentación, sin
historial entre pares.

---

## Enmiendas posteriores a la aprobación

**2026-09-10 — desvío forzado por el proveedor: `gpt-5.5` no admite temperatura 0.**
Comprobado con una llamada mínima antes de la primera corrida real: la API
responde `Unsupported value: 'temperature' does not support 0 with this model.
Only the default (1) value is supported.` `gpt-5.4-mini` sí la admite.

En consecuencia:

- `gpt-5.4-mini` corre con **temperatura 0**, como decía §4.
- `gpt-5.5` corre con **su temperatura por defecto (1)**, y por lo tanto **su
  salida no es determinista**. Se declara en RESULTADOS y no se presenta como
  reproducible.
- **Control adicional para el modelo no determinista.** Sin esto, una respuesta
  inconsistente de `gpt-5.5` no podría atribuirse: no se sabría si cambió por la
  posición de los lados o simplemente por el muestreo. Por eso a `gpt-5.5` se le
  hace **una tercera llamada repitiendo la presentación 1 sin cambios**. Así se
  miden por separado:
  - **ruido de muestreo** = pares en que las dos llamadas idénticas difieren;
  - **sesgo de posición** = pares en que difiere la presentación invertida.
  El criterio de descarte del §5 (más del 20 % inconsistentes) se aplica sobre la
  comparación de presentaciones invertidas, como estaba escrito; el ruido se
  informa aparte como diagnóstico del instrumento.
- El **prompt no cambia** (sigue el del apéndice, congelado antes de ver las
  respuestas de la jueza).

**2026-09-10 — la ampliación a 151 pares NO se realizó: crédito agotado.**
La fase de solapamiento (20 pares, 100 llamadas) se completó y se informa en
`RESULTADOS_LLM.md`. Los dos modelos pasaron los dos controles y **habilitaban**
la ampliación (§6). No se hizo por falta de crédito en la cuenta de la API, no
por el diseño. Registro exacto: un primer intento hizo ~600 llamadas y no guardó
nada (el script escribía sólo al final; **corregido**: ahora escribe llamada por
llamada y admite `--reanudar`); un segundo intento dejó 143 registros en
`salidas/llm_respuestas_completa_20260910_1322.csv`, de los cuales 96 son errores
`HTTP 429 · sin crédito` y 47 respuestas que cubren apenas 7 pares completos.
**No se informa ninguna cifra a partir de ese archivo**; queda como rastro
auditable. Decisión de Ana: el experimento se cierra con la prueba humana más
esta observación secundaria.

**2026-09-10 — orden de ejecución en dos fases.** No es un cambio de diseño, es
el orden que el propio §6 implica: primero se corren **sólo los 20 pares de
solapamiento** y se evalúan los dos controles. La corrida de los 151 se lanza
**únicamente si el §6 se cumple**, porque si no se cumple su cifra no se informa
igual y no tiene sentido gastarla. Cada fase queda con su propio archivo de
salida.
