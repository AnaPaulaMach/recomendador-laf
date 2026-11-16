# Pruebas y criterios para responder a las observaciones del director

Fecha: 30 de septiembre de 2026. Investigación y experimentos locales; no se modificaron Prism, las reglas de producción ni datos de Supabase.

## Resultado principal

Una sola ejecución de LAF puede reproducir el diseño actual si mantiene cadenas y conclusiones independientes por aspecto y después aplica la misma suma ponderada. Se comprobó con el motor real, no sólo con una simulación. Un único número global y un vector de nodos intermedios son alternativas diferentes y no reproducen los puntajes actuales.

Las confianzas son parámetros heurísticos. Los registros permiten reconstruir cuándo se incorporaron y algunos motivos cualitativos, pero no una derivación única de cada decimal. Las pruebas de sensibilidad caracterizan el efecto de esos parámetros; no demuestran que sean óptimos.

## 1. Las variantes de «un solo programa»

| Variante | Qué devuelve LAF antes de aplicar preferencias | Resultado frente a lo actual |
|---|---|---|
| Diseño vigente: una ejecución por aspecto | Un `recomendar` por aspecto, con sus cadenas y conflictos | Control de referencia |
| Una ejecución con cadenas y terminales separados por aspecto | Un vector `recomendarPorSabor`, `recomendarPorAroma`, etc. | Equivalente en la prueba: diferencia de valores 0; mismos rankings |
| Una ejecución, leyendo `saborBueno`, `aromaBueno`, etc. | Valor de cada aspecto antes de completar sus rutas superiores | Los nodos intermedios se conservan, pero cambian los puntajes y algunas posiciones actuales |
| Una ejecución con el `recomendar` global | Un único valor que agrega las distintas rutas | Cambian los puntajes y el orden; se pierde la descomposición necesaria para las preferencias por aspecto |

### Prueba real de la variante equivalente

Se usó el programa congelado del corpus histórico `mlm_mlm194329_20260528_142014`: 18 productos, 14 aspectos, 259 hechos y 66 reglas en la fuente completa. A partir de ella se construyeron 14 programas aislados y una unión con 259 hechos y 84 reglas. Los nodos de dimensión y los terminales se identificaron por aspecto para que no agregaran rutas de aspectos diferentes.

Se realizaron 17 llamadas al calculador HTTP local: las 14 corridas independientes, la unión con terminales separados, el programa global y el programa de nodos de aspecto. La unión y las corridas aisladas produjeron los mismos valores acumulados y debilitados (`mu` y `delta`), para ambos signos y con las mismas multiplicidades. La diferencia observada fue 0, con tolerancia de control de 1e-9.

Se combinaron esos vectores para 17 perfiles: 14 de un solo aspecto, neutro, mixto y todo cero. Los rankings y puntajes fueron idénticos. Algunos perfiles individuales tienen menos productos con resultado y el perfil todo cero es vacío; no se afirma que se probaron todas las preferencias posibles. Una comprobación independiente también comparó los 14 vectores con la reconstrucción fresca desde Supabase realizada en el experimento de confianzas: mismos productos y diferencia 0.

Esto respalda la equivalencia en la configuración y corpus examinados. La razón estructural es que los componentes de cada aspecto permanecen independientes: reunirlos en una petición no introduce apoyos ni ataques entre componentes. Si se agregaran reglas entre aspectos, habría que revisar esa propiedad.

### Por qué leer el nodo de aspecto no es exactamente lo mismo

Los valores de `aspectoBueno` fueron iguales en el programa completo, el programa que contiene sólo esos niveles y las corridas aisladas. Sin embargo, el diseño vigente usa el terminal de recomendación, después de incorporar las reglas superiores y sus asimetrías. La suma ponderada de los nodos de aspecto difirió del puntaje neutral vigente hasta 0,173996 y cambió algunas posiciones.

Tampoco basta multiplicar el aspecto ya debilitado por las fuerzas superiores. Ejemplo real Blasón/sabor:

- `delta(saborBueno)` = 0,788198;
- multiplicación posterior por 0,90 × 0,90 = 0,638440;
- `delta(recomendar)` de la cadena completa = 0,631273.

Los soportes acumulados y los ataques de 0,92 × 0,92 hacen que esas operaciones no sean intercambiables. La unión con terminales independientes conserva la cadena entera, en lugar de aproximarla con esa multiplicación.

### El número global

La lectura del `recomendar` global difirió del puntaje neutral vigente hasta 0,750925. EXP10 ya había examinado otra vía: activar aspectos de forma binaria y leer esa conclusión global. Ese ensayo no examinaba la unión con terminales independientes.

Un único escalar global no permite recuperar por sí solo cuánto vino de cada aspecto. Para aplicar preferencias distintas a sabor, aroma y los demás criterios hace falta conservar información por criterio. Una fórmula posterior que vuelva a utilizar esa información estaría trabajando con un vector, aunque la aplicación lo presente como un único programa.

La variante equivalente quedó preparada como experimento. Todavía no fue incorporada al generador ni a las explicaciones de la aplicación. La intención exacta del director debe aclararse antes de decidir esa integración.

## 2. Qué se puede justificar de las fuerzas elegidas

### Historia recuperada

El historial disponible está en la copia técnica local, HEAD `1cc1dd6` del 26/09/2026. La constante 0,85 de evidencia hacia aspecto aparece en el commit inicial `675eae7` del 01/07. Los valores superiores originales se incorporan juntos en `8e39738` del 02/07, con la configuración v6/v7. Molienda se añade posteriormente; tueste y acidez se incorporan en agosto. Las negativas finales de valor y elaboración se adoptan el 10/09 después de EXP11.

No se encontró una escala previa de elicitación, medición empírica o cálculo que derive específicamente 0,78 en vez de 0,80, o 0,88 en vez de 0,90. Los documentos que llaman a los valores «fuerzas conservadoras» o «decisión experta» permiten identificar una elección de modelado, pero no una calibración numérica.

### Tabla de trazabilidad por familias

| Vínculo o familia | Positiva / negativa | Fundamento documental recuperable |
|---|---:|---|
| Evidencia → aspecto, todos | 0,85 / 0,85 | Constante inicial; no hay medición que derive 0,85 |
| Sabor → sensorial | 0,90 / 0,92 | Mal sabor como razón fuerte para desaconsejar; no deriva los decimales |
| Aroma → sensorial | 0,85 / 0,85 | Valores iniciales; no hay motivo numérico específico registrado |
| Intensidad y dulzor → sensorial | 0,80 / 0,80 | Valores iniciales; no hay motivo numérico específico registrado |
| Tueste → sensorial | 0,85 / 0,88 | Incorporación de agosto, denominada conservadora; no deriva 0,03 de diferencia |
| Acidez → sensorial | 0,85 / 0,85 | Incorporación de agosto, denominada conservadora |
| Rendimiento → valor | 0,85 / 0,85 | Valor inicial, sin derivación exacta |
| Tamaño → valor | 0,75 / 0,75 | Valor inicial; el manuscrito actual declara menor centralidad, pero el registro original no explica el decimal |
| Originalidad → producto | 0,88 / 0,90 | Adulteración como razón fuerte para desaconsejar; no deriva los decimales |
| Presentación → producto | 0,80 / 0,80 | Valores iniciales, sin derivación exacta |
| Variedad → producto | 0,75 / 0,75 | Valor inicial; el manuscrito actual declara menor centralidad, sin derivación exacta original |
| Preparación → elaboración | 0,80 / 0,85 | Asimetría desde el origen, sin explicación numérica específica |
| Molienda → elaboración | 0,80 / 0,85 | Evidencia para incorporar el aspecto y fuerza conservadora; no deriva esos valores |
| Caducidad → conservación | 0,85 / 0,92 | Vencimiento como razón fuerte para desaconsejar; no deriva los decimales |
| Sensorial → recomendar | 0,90 / 0,92 | Asimetría coherente con el criterio general, sin calibración exacta |
| Valor → recomendar | 0,80 / 0,80 | Positiva inicial; negativa adoptada por simetría después de EXP11 |
| Producto → recomendar | 0,78 / 0,90 | Valores iniciales; no se recuperó motivo específico para 0,78 |
| Elaboración → recomendar | 0,75 / 0,75 | Positiva inicial; negativa adoptada por simetría después de EXP11 |
| Conservación → recomendar | 0,78 / 0,92 | Rechazo fuerte por vencimiento; no se recuperó derivación de 0,78/0,92 |

Cuando el JSON no especifica una negativa diferente, el generador hereda la positiva. El apoyo directo de aspectos sin dimensión está configurado en 0,75; no interviene en los 14 aspectos asignados del ensayo.

### Excepción con apoyo experimental concreto

EXP11 compara negativas finales de valor/elaboración en 0,90 con sus alternativas simétricas 0,80/0,75. La fuerza negativa mayor podía volver decisiva una crítica aislada. Esto fundamenta limitar aquella asimetría y conservar la simetría; no demuestra que las positivas originales sean óptimas.

Una explicación anterior llamó intencional a la omisión de esas rutas negativas. Un registro histórico atribuye a la autora que se había olvidado de agregarlas. Por eso no debe reconstruirse aquella omisión como una elección deliberada original.

### Qué escribiría en la tesis

No hace falta inventar un motivo distinto para cada regla. Sí debe quedar trazable cada valor en una tabla, con criterios por familias y explicación de las excepciones. Se deben separar la existencia del vínculo, la relación entre fuerzas y el decimal exacto.

Propuesta de texto para revisión, sin incorporarlo a Prism:

> Las fuerzas de las reglas se establecieron como parámetros heurísticos de modelado, no como probabilidades calibradas ni coeficientes estimados a partir del corpus. Los registros documentan los valores adoptados y algunos criterios cualitativos, especialmente la mayor fuerza de rechazo asociada al mal sabor, la adulteración y el vencimiento. Estos criterios no determinan de manera única cada valor decimal. Por ello se explicitan las decisiones por familias de reglas y se evalúa la sensibilidad del resultado frente a configuraciones alternativas. Esta evaluación caracteriza la estabilidad de las recomendaciones en las condiciones examinadas, sin demostrar que las fuerzas elegidas sean óptimas.

La literatura del formalismo explica el álgebra; no proporciona por sí sola los coeficientes particulares del dominio. Budán et al. describen atributos dependientes del dominio y una función de asignación inicial dentro del modelo ([manuscrito de los autores](https://arxiv.org/pdf/1903.01865)). Eso permite instanciar el modelo; no constituye una estimación de las fuerzas del dominio Café. Si se necesitara defender un decimal como valor óptimo o estimación empírica, habría que definir un objetivo y una referencia independiente para calibrarlo. No conviene seleccionar coeficientes porque conservan un ranking esperado y luego usar ese mismo ranking como validación.

Las notas antiguas llamaban al 0,85 fiabilidad de extracción. El capítulo IV vivo de Prism distingue ahora esa fuerza estructural de la extracción `e_i`, que ya participa en `w_i=t_i e_i`. Conviene mantener la semántica actual y reconocer la precisión de interpretación, sin afirmar que los registros originales ya la expresaban así.

## 3. Comparación nueva de confianzas y de λ

### Protocolo y controles

Se leyeron una vez las entradas mínimas actuales del corpus histórico desde Supabase: 18 productos, 12.050 puntuaciones de reseñas y 6.862 menciones. No se leyó ni almacenó texto de las reseñas para este ensayo. Los inputs están en `inputs_minimos.json`, sin claves de acceso.

Se reutilizaron el agregador de `06_trust.py`, el generador de `08_laf1_generate.py`, los operadores, cliente, mapper y suma ponderada de la aplicación. Cada programa enviado tuvo una sola etiqueta. Para cada configuración se evaluaron 14 aspectos y se combinaron para neutro, sólo sabor y sólo aroma: 84 llamadas al motor para seis configuraciones.

La reconstrucción vigente reprodujo la batería registrada en los controles neutro y sólo sabor: mismos 18 puestos y diferencias máximas de puntaje de 1,11e-16 y 0, respectivamente.

- En las uniformes se sustituyeron todas las fuerzas de reglas por 0,60, 0,85 o 1,00. Los hechos, datos, preferencias, λ=10 y operadores permanecieron iguales. Esto elimina también las asimetrías, por lo que es una comparación con un modelo simplificado, no sólo un cambio de escala.
- Para λ=5 y λ=20 se conservaron las reglas y se reconstruyeron los hechos D a partir de las mismas menciones y puntuaciones. La media a priori siguió en 0,5. λ=10 es la referencia vigente.
- Ninguna función de escritura de Supabase fue utilizada. Las constantes se modificaron únicamente dentro del proceso experimental y se restauraron en `finally`.
- Se conservaron los programas y los grafos reales de las 84 evaluaciones.

### Resultados frente a la configuración vigente

`ρ` compara el orden final de 18 productos, con el desempate determinista del sistema. «Top 3» indica el mismo conjunto; el CSV y JSON distinguen también su orden. Los resultados completos incluyen correlación sobre scores con rangos promedio para empates.

| Variante | Perfil | ρ | Cambian de puesto | Mismo ganador | Mismo conjunto top 3 |
|---|---|---:|---:|---|---|
| Uniforme 0,85 | Neutro | 0,986 | 3 | Sí | Sí |
| Uniforme 0,85 | Sólo sabor | 0,998 | 2 | No | Sí |
| Uniforme 0,85 | Sólo aroma | 0,998 | 2 | Sí | No |
| Uniforme 0,60 | Neutro | 0,994 | 6 | Sí | Sí |
| Uniforme 0,60 | Sólo sabor | 0,973 | 11 | No | Sí |
| Uniforme 0,60 | Sólo aroma | 0,986 | 6 | Sí | No |
| Uniforme 1,00 | Neutro | 0,973 | 9 | Sí | No |
| Uniforme 1,00 | Sólo sabor | 0,986 | 8 | Sí | No |
| Uniforme 1,00 | Sólo aroma | 0,973 | 8 | No | Sí |
| λ=5 | Neutro | 0,981 | 7 | Sí | Sí |
| λ=5 | Sólo sabor | 0,990 | 7 | No | Sí |
| λ=5 | Sólo aroma | 0,977 | 7 | Sí | No |
| λ=20 | Neutro | 0,944 | 12 | No | Sí |
| λ=20 | Sólo sabor | 0,988 | 6 | No, con empate primero-segundo | Sí |
| λ=20 | Sólo aroma | 0,967 | 8 | Sí | No |

En λ=20/neutro se invierten los dos primeros con una diferencia de puntaje de 0,000134. En λ=20/sólo sabor los dos primeros empatan exactamente; el sistema los ordena por identificador. En λ=5/sólo aroma hay también empate entre los dos primeros. El generador discretiza los hechos a dos decimales antes de enviarlos al motor. Esas diferencias deben interpretarse junto al margen y a esa discretización, no como distinciones fuertes de preferencia.

La uniforme 0,85 conserva el orden del top 3 neutro, pero cambia el ganador de sabor y la composición del top 3 de aroma. Los números influyen en algunos resultados. El ensayo no respalda afirmar que el ordenamiento es independiente de las fuerzas, ni establece superioridad de la configuración vigente: no hay una referencia externa que determine cuál ranking es el correcto.

EXP12 sigue siendo evidencia de sensibilidad local en los rangos originalmente examinados. Esta comparación añade una simplificación uniforme y pruebas de estrés más amplias; λ es un parámetro distinto de las fuerzas de reglas.

### Identificación y reproducción

- SHA-256 del archivo de configuración: `05968e84b55c2c2c78d1f3c94ee50db055f7a0d3990aa19721b83a3055665781`.
- SHA-256 de inputs mínimos: `a1cffee71fbb3f11a7c3474ec5ff0a8c6b2255dd1ce93473ba7f94b8a5c88152`.
- Imagen del motor local: `sha256:92f7447b519d6372e4f0508b8bebef7a2d4439be86e56c75742bfec51e5ac26d`; metadatos mínimos en `motor.json`.
- Script: `comparar_confianzas.py`.
- Resultados completos: `resultados_confianzas.json` y `comparacion_confianzas.csv`.
- Scripts de programa único: `alternativa_programa_unico/comparar_estructura_offline.py` y `comparar_motor_local.py`.
- Informe de programa único: `alternativa_programa_unico/RESULTADOS.md`.

Desde la raíz del repositorio, con el motor local disponible en 8088:

```powershell
.\venv\Scripts\python.exe validacion_laf1\revision_director_20260930\comparar_confianzas.py
.\venv\Scripts\python.exe validacion_laf1\revision_director_20260930\alternativa_programa_unico\comparar_motor_local.py
```

El primer script reutiliza el cache mínimo si existe; para usar una fuente diferente hay que identificarla explícitamente. Los resultados corresponden a este snapshot de café y esta configuración, no a una validación entre dominios ni con usuarios.

## Cambios propuestos para revisar, sin editar el manuscrito

1. Capítulo IV: conservar la tabla de fuerzas, aclarar su carácter heurístico y describir los criterios por familias y las excepciones documentadas. Evitar una justificación histórica que no esté registrada.
2. Capítulo IV: sustituir la afirmación «el ordenamiento tampoco depende» de los valores por una conclusión de estabilidad acotada a los ensayos, incluyendo la sensibilidad de primeras posiciones.
3. Capítulo VI: dar una referencia visible a EXP12 y añadir la comparación uniforme, los extremos y λ, con los empates y límites señalados.
4. Sobre programa único: presentar la alternativa equivalente comprobada y preguntar al director si se refiere a esa forma de una ejecución o a una única confianza global. La decisión de integrar esa variante queda separada del resultado del experimento.
