# EXP 12 — Sensibilidad del ranking a las confianzas de las reglas

Fecha: 2026-09-13 · Snapshot `mlm_mlm194329_20260528_142014` (18 productos) · Configuración vigente
(fila 13 adoptada, hash `735f9b0c…`) · Camino de producción (una corrida LAF por aspecto, una etiqueta,
suma ponderada) · Control previo: la configuración sin perturbar reproduce la batería 18/18 en neutro y
solo sabor. Script: `exp12_sensibilidad_confianzas_reglas.py` · Datos:
`salidas/exp12_sensibilidad_confianzas_2026-09-13.json`.

**Pregunta.** Las confianzas de las reglas (0,85 constante en evidencia → aspecto; las de aspecto →
dimensión de la Tabla 4.X; las de dimensión → recomendar de la Tabla 4.Y) son heurísticas declaradas.
¿Cuánto cambia el ranking si se mueven?

## Resultados

Perturbaciones en bloque (todas las confianzas del nivel a la vez, tope 1,0):

| Variante | Perfil | ρ vs vigente | Cambian de puesto | Top 3 | Ganador |
|---|---|---:|---:|---|---|
| Evidencia→aspecto 0,75 (base 0,85) | neutro | 0,998 | 2/18 | igual | igual |
| | solo sabor | 0,998 | 2/18 | igual | **cambia** |
| | solo aroma | 0,998 | 2/18 | cambia | igual |
| Evidencia→aspecto 0,95 | neutro | 1,000 | 0/18 | igual | igual |
| | solo sabor | 1,000 | 0/18 | igual | igual |
| | solo aroma | 0,998 | 2/18 | igual | igual |
| Aspecto→dimensión −0,10 | neutro | 0,998 | 2/18 | igual | igual |
| | solo sabor | 0,998 | 2/18 | igual | **cambia** |
| | solo aroma | 0,998 | 2/18 | cambia | igual |
| Aspecto→dimensión +0,10 | neutro | 1,000 | 0/18 | igual | igual |
| | solo sabor | 1,000 | 0/18 | igual | igual |
| | solo aroma | 0,998 | 2/18 | igual | igual |
| Dimensión→recomendar −0,10 | neutro | 0,998 | 2/18 | igual | igual |
| | solo sabor | 0,998 | 2/18 | igual | **cambia** |
| | solo aroma | 0,998 | 2/18 | cambia | igual |
| Dimensión→recomendar +0,10 | neutro | 1,000 | 0/18 | igual | igual |
| | solo sabor | 1,000 | 0/18 | igual | igual |
| | solo aroma | 0,998 | 2/18 | igual | igual |

Perturbaciones aleatorias, 20 sorteos uniformes en [−0,05; +0,05] sobre cada confianza de aspecto→dimensión
y dimensión→recomendar (semilla 20260913):

| Perfil | ρ media (mín) | Cambian de puesto (media) | Top 3 igual | Ganador igual |
|---|---:|---:|---:|---:|
| neutro | 0,996 (0,990) | 3,1/18 | 20/20 | 20/20 |
| solo sabor | 1,000 (0,998) | 0,5/18 | 20/20 | 15/20 |
| solo aroma | 0,998 (0,996) | 1,7/18 | 6/20 | 20/20 |

## Lectura

1. **El orden global es insensible a las confianzas de las reglas** dentro de ±0,10: ρ ≥ 0,99 en todas las
   variantes y a lo sumo 2 de 18 productos cambian de puesto (3 en promedio con ruido aleatorio en neutro).
   Los valores concretos de las Tablas 4.X y 4.Y no fijan el orden; lo fijan la evidencia y las preferencias.
2. **Lo único que se mueve es la cabeza de los perfiles de un solo aspecto**, y por la razón ya conocida: en
   «solo sabor» los cuatro primeros están a menos de 0,01 (0,6412 / 0,6403 / 0,6313 / 0,6313) y en «solo
   aroma» el top 3 también está apretado. Cualquier perturbación reordena empates prácticos. Es el mismo
   fenómeno que el bootstrap (ganador de «solo sabor» sostenido en el 41 % de las réplicas) y lo cubre el
   resguardo del rótulo (ADR-004): con diferencia menor a 0,01 la interfaz no declara un único mejor.
3. Que subir todas las confianzas no cambie nada y bajarlas cambie 2 puestos se explica por el operador de
   conflicto, que no es lineal: con confianzas más bajas las críticas pesan relativamente más en los
   productos que las tienen.

## Qué NO dice

No dice que los valores sean «correctos»: dice que el ranking no depende de ellos en el rango probado. La
justificación de cada valor sigue siendo la de criterios declarados (ver Cap. 4, §4.5): heurísticos,
fijados por la autora en la estructura v6 (2026-07-02), confirmados en la revisión 09
(`config/laf_rule_review_decisions.json`), con dos regularidades verificables (las negativas nunca pesan
menos que las positivas; los vínculos más débiles son los de aspectos menos ligados a la calidad).
