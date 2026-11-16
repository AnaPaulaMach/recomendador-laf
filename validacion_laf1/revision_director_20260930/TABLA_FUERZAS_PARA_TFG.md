# Criterios de modelado y alcance de las fuerzas de las reglas

Borrador para revisión de la autora — 30 de septiembre de 2026. Propuesta de presentación académica; no incorporada al manuscrito.

## Texto introductorio propuesto

Las fuerzas de las reglas se adoptaron como parámetros heurísticos del prototipo. Expresan la fuerza asignada a los vínculos de inferencia de la estructura argumentativa; se distinguen de la confianza de extracción de cada mención y de las preferencias del usuario. Su interpretación considera la centralidad del vínculo en la evaluación del dominio, las asimetrías cualitativas de rechazo y la prudencia al asignar fuerzas a inferencias falibles. Se conserva un tratamiento simétrico cuando no se declara una diferencia entre signos. Los valores decimales no proceden de una estimación estadística ni de una escala de elicitación previamente registrada.

Las tablas siguientes explicitan los valores utilizados, una formulación del criterio de modelado y el alcance de su respaldo. La existencia de un vínculo, su tratamiento positivo o negativo y su magnitud numérica constituyen decisiones diferentes: la evidencia que permite incorporar un aspecto no determina por sí sola la fuerza de su regla. La evaluación de sensibilidad complementa esta justificación al mostrar qué recomendaciones cambian cuando se modifican los parámetros. La condición heurística de los decimales es común a las tablas; las observaciones por fila señalan los respaldos específicos y las excepciones.

**Nota para la revisión de este borrador.** La columna «Criterio de modelado» propone ahora una explicación académica de la configuración vigente. La columna «Respaldo y alcance» identifica qué parte está apoyada por registros previos. Esta separación evita presentar la propuesta actual de redacción como si fuera un procedimiento histórico de cálculo de cada decimal. La autora debe revisar y adoptar los criterios que representen su decisión de modelado.

## Tabla A. Reglas de evidencia a aspecto

| Familia de reglas | α positiva | α negativa | Criterio de modelado | Respaldo y alcance |
|---|---:|---:|---|---|
| Evidencia de reseñas → valoración de cada aspecto | 0,85 | 0,85 | Usar una fuerza común en el paso de la evidencia agregada a la valoración del aspecto, manteniendo un tratamiento simétrico de los signos. | Constante utilizada desde la implementación inicial. La magnitud es heurística; requiere distinguir su interpretación estructural actual de la descripción histórica como fiabilidad del pipeline. |

La confianza de extracción de cada mención ya pertenece al tratamiento de la evidencia. Por tanto, el 0,85 de esta tabla no debe interpretarse como una medición del desempeño del extractor ni obtenerse directamente de su porcentaje de aciertos.

## Tabla B. Reglas de aspecto a dimensión

| Vínculo | α positiva | α negativa | Criterio de modelado | Respaldo y alcance |
|---|---:|---:|---|---|
| Sabor → sensorial | 0,90 | 0,92 | Vincular la valoración del sabor con la experiencia sensorial y asignar mayor fuerza al rechazo por mal sabor. | La asimetría cualitativa está documentada en v6. Los decimales son elecciones heurísticas. |
| Aroma → sensorial | 0,85 | 0,85 | Incorporar las valoraciones del aroma a la experiencia sensorial con tratamiento simétrico. | Estructura y fuerza adoptadas en v6; simetría efectiva del generador. |
| Intensidad → sensorial | 0,80 | 0,80 | Incorporar la valoración de intensidad como componente de la experiencia sensorial, con fuerza común para ambos signos. | Configuración inicial v6; magnitud heurística. |
| Dulzor → sensorial | 0,80 | 0,80 | Incorporar la valoración contextual del dulzor o amargor a la experiencia sensorial, con fuerza común para ambos signos. | Configuración v6 y decisiones léxicas que evitan tratar «amargo» como negativo fijo. |
| Tueste → sensorial | 0,85 | 0,88 | Incorporar una propiedad sensorial diferenciada y conservar las fuerzas adoptadas al introducir el aspecto. | Auditoría de agosto: fuerzas iniciales conservadoras. La diferencia entre signos se conserva; no se le atribuye una causa específica no documentada. |
| Acidez → sensorial | 0,85 | 0,85 | Incorporar la valoración de acidez como criterio sensorial independiente, admitiendo apreciaciones favorables y desfavorables. | Auditoría de agosto: cobertura del aspecto y fuerzas iniciales conservadoras; tratamiento simétrico. |
| Rendimiento → valor | 0,85 | 0,85 | Relacionar la experiencia de rendimiento con la dimensión de rendimiento y valor. | Agrupación y fuerzas de v6; la evidencia de uso sustenta el vínculo, no su decimal. |
| Tamaño → valor | 0,75 | 0,75 | Considerar la valoración de cantidad o tamaño como un aporte complementario a la dimensión de rendimiento y valor. | Agrupación y fuerzas de v6; el criterio de centralidad organiza su interpretación, sin determinar el decimal. |
| Originalidad → producto | 0,88 | 0,90 | Incorporar la valoración de autenticidad y asignar mayor fuerza al rechazo asociado a adulteración. | La asimetría cualitativa está documentada en v6. Los decimales son elecciones heurísticas. |
| Presentación → producto | 0,80 | 0,80 | Incorporar las opiniones sobre empaque y presentación a la evaluación del producto, con tratamiento simétrico. | Agrupación y fuerzas de v6; magnitud heurística. |
| Variedad → producto | 0,75 | 0,75 | Incorporar las valoraciones sobre variedad o tipo como un aporte complementario a la evaluación del producto. | Agrupación y fuerzas de v6; el criterio de centralidad organiza su interpretación, sin determinar el decimal. |
| Preparación → elaboración | 0,80 | 0,85 | Vincular la experiencia de preparación o disolución con la elaboración y conservar la asimetría vigente. | Fuerzas presentes desde v6; la diferencia entre signos no dispone de un fundamento específico registrado. |
| Molienda → elaboración | 0,80 | 0,85 | Incorporar el grado de molido como propiedad de elaboración, con las fuerzas conservadoras adoptadas para su aplicabilidad parcial. | Incorporación apoyada por reseñas y revisión de julio. La evidencia fundamenta el aspecto; no deriva 0,80/0,85. |
| Caducidad → conservación | 0,85 | 0,92 | Relacionar frescura y caducidad con conservación y asignar mayor fuerza al rechazo por vencimiento. | La asimetría cualitativa está documentada en v6. Los decimales son elecciones heurísticas. |

**Nota de implementación.** Cuando la configuración no declara una fuerza negativa distinta, el generador utiliza la fuerza positiva para ambos signos. Todas las preferencias estructurales de las reglas están neutralizadas en 1,00; las preferencias efectivas proceden del usuario.

## Tabla C. Reglas de dimensión a recomendación

| Vínculo | α positiva | α negativa | Criterio de modelado | Respaldo y alcance |
|---|---:|---:|---|---|
| Sensorial → recomendar / no recomendar | 0,90 | 0,92 | Usar la evaluación sensorial como fundamento de recomendación y conservar mayor fuerza en la ruta de rechazo. | Fuerzas de v6 y criterio general de asimetría sensorial; sin calibración decimal. |
| Valor → recomendar / no recomendar | 0,80 | 0,80 | Permitir que las valoraciones de rendimiento y cantidad apoyen u objeten la recomendación con la misma fuerza final. | Negativa adoptada por simetría tras EXP11. El experimento respalda limitar una asimetría adicional; no estima la positiva original. |
| Producto → recomendar / no recomendar | 0,78 | 0,90 | Propagar las valoraciones de autenticidad, presentación y variedad hacia la recomendación, conservando la asimetría final vigente. | Configuración v6 y criterio general de rechazo por adulteración. La magnitud 0,78 es heurística. |
| Elaboración → recomendar / no recomendar | 0,75 | 0,75 | Permitir que las valoraciones de preparación y molienda apoyen u objeten la recomendación con la misma fuerza final. | Negativa adoptada por simetría tras EXP11. El experimento respalda limitar una asimetría adicional; no estima la positiva original. |
| Conservación → recomendar / no recomendar | 0,78 | 0,92 | Propagar la evaluación de conservación y mantener mayor fuerza para el rechazo asociado a vencimiento. | Configuración v6 y motivo cualitativo de rechazo documentado. Las magnitudes son heurísticas. |

**Regla de respaldo para aspectos sin dimensión.** La configuración contempla un apoyo directo a recomendar de 0,75. Se trata de una fuerza heurística de respaldo y no interviene en los 14 aspectos asignados a dimensiones en el ensayo del corpus histórico. Si se emplea en otro dominio o configuración, debe explicitarse su activación.

## Párrafo de cierre propuesto

La parametrización conserva un tratamiento simétrico cuando no se declara una diferencia entre signos y contempla asimetrías cualitativas para determinados motivos de rechazo. Los registros documentan estas decisiones y su evolución, pero no permiten derivar de forma única todos los valores decimales. En consecuencia, su defensa metodológica se basa en explicitar la elección heurística, mantener su trazabilidad y evaluar sus efectos sobre las recomendaciones. La estabilidad observada se circunscribe al corpus, los perfiles y las variantes examinados.

## Evidencia experimental para acompañar la tabla

La comparación del 30/09/2026 usó el corpus histórico de café de México, 18 productos y los perfiles neutro, solo sabor y solo aroma. El control vigente reprodujo la batería de referencia en neutro y solo sabor, tanto en orden como en puntajes dentro de la precisión numérica. Al reemplazar las fuerzas de las reglas por un valor uniforme de 0,85, manteniendo λ=10, se obtuvieron estos resultados:

| Perfil | ρ del orden frente a la configuración vigente | Productos que cambian de puesto | Ganador conservado | Conjunto de los tres primeros conservado | Orden de los tres primeros conservado |
|---|---:|---:|---|---|---|
| Neutro | 0,986 | 3 de 18 | Sí | Sí | Sí |
| Solo sabor | 0,998 | 2 de 18 | No | Sí | No |
| Solo aroma | 0,998 | 2 de 18 | Sí | No | No |

**Lectura propuesta.** La sustitución por fuerzas uniformes mantuvo una elevada concordancia global en los tres perfiles, pero modificó posiciones y determinadas recomendaciones iniciales. En solo sabor, el ganador cambió y la diferencia entre primero y segundo de la variante uniforme fue 0,000914. Por tanto, la prueba permite describir sensibilidad y cercanía de las alternativas; no permite afirmar que el ordenamiento sea independiente de las fuerzas exactas. Las comparaciones adicionales con fuerzas uniformes de 0,60 y 1,00 y con λ=5 y λ=20 amplían el alcance del análisis, sin identificar por sí mismas una magnitud única para cada regla.

EXP11 aporta un respaldo específico al criterio de simetría final de valor y elaboración. La variante con negativas de 0,90, frente a positivas de 0,80/0,75, produjo puntajes nulos por aspecto en ciertos casos con críticas aisladas. El recongelado posterior adoptó las negativas simétricas; su JSON de control reproduce la variante vigente en los seis perfiles examinados. Esta evidencia fundamenta aquella decisión comparativa y debe diferenciarse de la elección inicial de las fuerzas positivas.

## Ubicación sugerida y alcance de la defensa

El capítulo 4 ya contiene las tablas numéricas de aspecto a dimensión y de dimensión a recomendación, junto con criterios de centralidad, asimetría y prudencia. Conviene enriquecer esas dos tablas con una columna breve de criterio o incorporar las notas comunes de este borrador, evitando duplicar las listas de valores. El nivel evidencia a aspecto puede explicitarse en el texto. El párrafo introductorio y el cierre pertenecen a la metodología. Los resultados de sensibilidad corresponden a la evaluación del capítulo 6; la tabla completa de trazabilidad y las referencias a los artefactos pueden ampliarse en un anexo.

Esta presentación permite responder de manera precisa qué representan los parámetros, qué decisiones están documentadas y qué efectos se midieron. El respaldo disponible es parcial para la selección numérica exacta: no contiene una escala de elicitación previa ni una estimación independiente de cada fuerza. Por ello, la tabla mejora la transparencia y la defensa de las decisiones, pero no elimina la posibilidad de preguntas sobre los coeficientes. Si se requiere un fundamento más fuerte para la granularidad decimal, corresponde explicitar un procedimiento de selección o revisión de fuerzas y volver a evaluar sus resultados.

## Fuentes verificadas para este borrador

- [Configuración vigente del dominio, notas y fuerzas](config/domains/cafe.json).
- [Registro de revisión de reglas y decisiones](config/laf_rule_review_decisions.json).
- [Auditoría de incorporación de tueste y acidez, 12/08/2026](artifacts_por_dominio/cafe/reportes/auditoria_metodologica_grano_molido_20260812.md).
- [EXP11: comparación y adopción de las rutas negativas de valor y elaboración](validacion_laf1/EXP11_FILA13_IMPACTO.md) y [JSON posterior al recongelado](validacion_laf1/salidas/exp11_fila13_2026-09-10.json).
- [Resultados de sensibilidad del 30/09/2026](validacion_laf1/revision_director_20260930/resultados_confianzas.json).
- Historial local consultado: `675eae7` (01/07/2026), `8e39738` (02/07/2026), `ab9c111` (01/08/2026), `14a470c` (12/08/2026), `5a782dc` (14/08/2026) y `40f48d8` (10/09/2026). Consulta realizada sobre HEAD `1cc1dd6` (26/09/2026).

Las notas antiguas que describen 0,85 como fiabilidad de extracción requieren armonización con la interpretación estructural actual antes de emplearse como explicación del manuscrito. Asimismo, la omisión antigua de las rutas negativas de valor/elaboración debe narrarse como una decisión revisada y corregida, sin recuperar como fundamento una intención inicial que el registro histórico posterior contradice.
