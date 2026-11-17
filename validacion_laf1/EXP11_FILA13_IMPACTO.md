# EXP 11 — Fila 13: qué cambia si `valor` y `elaboración` pueden concluir `~recomendar`

Fecha: 2026-09-10 · Snapshot: `mlm_mlm194329_20260528_142014` (café México, 18 productos) ·
Estrategia D · Camino de producción (`post_laf_multicriteria_v1`: una corrida LAF por aspecto,
suma ponderada afuera) · Motor: laf-api local.
Script: `exp11_fila13_impacto.py` · Datos: `salidas/exp11_fila13_2026-09-10.json`.

**Estado: ADOPTADO (variante simétrica) el 2026-09-10.** Las dos reglas se agregaron a
`config/domains/cafe.json` con confianza 0,80 (`valor`) y 0,75 (`elaboracion`), se recongeló la
categoría (hash `735f9b0c…1432fb`) y se revalidó de punta a punta: batería, interfaz, OE5 y
bootstrap. Salidas del recongelado en `salidas/recongelado_20260910/` (ver `RESUMEN.md` ahí).
Rerun de este script tras el cambio (`salidas/exp11_fila13_2026-09-10.json`; el previo quedó como
`exp11_fila13_2026-09-10_pre_fila13.json`): la variante «actual» da **ρ = 1,000 contra
«fila13_simetrico» en los 6 perfiles**, es decir, lo aplicado es exactamente lo medido. El script
se adaptó en una línea: el `assert` de ausencia de `not_recommend` pasó a ser un aviso, porque el
dominio real ya trae el bloque.

Lo que sigue es el texto original de la simulación (2026-09-10, antes de adoptar). Control previo:
la variante «actual» reproducía la batería validada 18/18 en neutro y en solo sabor.

## 0. Qué es la fila 13

En `config/domains/cafe.json`, las dimensiones `valor` (rendimiento, tamaño) y `elaboracion`
(preparación, molienda) no tienen bloque `not_recommend`. Por eso `08_laf1_generate.py`
(líneas 357-360) no emite `~recomendar(X) :- ~valorBueno(X)` ni
`~recomendar(X) :- ~elaboracionBueno(X)`. Las críticas a esos cuatro aspectos llegan hasta
`~valorBueno` / `~elaboracionBueno` y ahí se detienen: **nunca debilitan `recomendar`**.
Las otras tres dimensiones (sensorial, producto, conservación) sí tienen la regla, con 0,90 / 0,90 / 0,92.

En este snapshot son **12 hechos negativos sin consumidor** (rendimiento 4, tamaño 3,
preparación 3, molienda 2), en 6 productos, con entre 1 y 10 menciones cada uno.

## 1. Variantes simuladas

| Variante | `~recomendar :- ~valorBueno` | `~recomendar :- ~elaboracionBueno` |
|---|---:|---:|
| actual | no existe | no existe |
| simétrica | 0,80 (= la de `recomendar :- valorBueno`) | 0,75 (= la de su positiva) |
| 0,90 | 0,90 (como las otras dimensiones) | 0,90 |

## 2. Efecto sobre el ranking

| Perfil | Variante | ρ vs actual | Cambian de puesto | Top 3 | Ganador |
|---|---|---:|---:|---|---|
| neutro (0,67 × 14) | simétrica | 0,936 | 11 / 18 | cambia | igual |
| neutro | 0,90 | 0,905 | 13 / 18 | cambia | igual |
| solo sabor | ambas | 1,000 | 0 / 18 | igual | igual |
| solo rendimiento | simétrica | 0,571 | 15 / 18 | cambia | **cambia** |
| solo rendimiento | 0,90 | 0,457 | 15 / 18 | cambia | **cambia** |
| solo preparación | simétrica | 0,718 | 15 / 18 | cambia | **cambia** |
| solo preparación | 0,90 | 0,629 | 15 / 18 | cambia | **cambia** |
| solo molienda | ambas | 0,893 | 3 / 18 | igual | igual |
| solo tamaño | ambas | 0,848 | 10 / 18 | igual | igual |

Movimientos grandes en neutro: La Parroquia 3.º → 7.º (simétrica) o 9.º (0,90);
Nescafé Clásico 100 % Puro Soluble 13.º → 18.º. Los demás se corren uno o dos puestos.

## 3. Lo que preocupa: la variante 0,90 apaga aspectos enteros

Score LAF de `recomendar` por aspecto, post-conflicto, variante 0,90:

| Producto | Aspecto | n críticas | actual | con fila 13 (0,90) |
|---|---|---:|---:|---:|
| La Parroquia | molienda | 3 | 0,286 | **0,000** |
| Nescafé Clásico Puro Soluble | molienda | 2 | 0,265 | **0,000** |
| Nescafé Clásico Puro Soluble | preparación | 1 | 0,255 | **0,000** |
| Nescafé Clásico ICE | tamaño | 1 | 0,265 | **0,000** |
| La Parroquia | rendimiento | 1 | 0,335 | 0,085 |
| La Parroquia | tamaño | 2 | 0,301 | 0,086 |

Con la regla negativa a 0,90 y la positiva a 0,75–0,80, **una sola crítica** basta para que la
ruta negativa supere a la positiva y el operador de conflicto deje la conclusión en 0. Es el
fenómeno R3 (el prior de la estrategia D infla la crítica única) amplificado por una asimetría
de confianzas a favor de la negación. La variante simétrica lo atenúa (La Parroquia molienda
0,286 → 0,062) pero no lo elimina.

## 4. Lectura

1. **La omisión no es inocua.** Hoy 12 críticas reales no pueden bajar a ningún producto.
   Con las reglas, el orden neutro cambia para 11–13 de 18 productos (ρ 0,91–0,94) y en los
   perfiles de un solo aspecto afectado cambia el ganador.
2. **Fila 13 y R3 son la misma decisión.** Agregar las reglas sin resolver R3 convierte una
   crítica aislada en un veto: el score del aspecto cae a 0. Si se agregan, conviene la
   confianza simétrica (no 0,90) y decidir R3 en el mismo acto.
3. **El costo de cambiar hoy es bajo, mañana no.** La cadena de validación está automatizada
   (batería 18/18, comparación OE5, bootstrap: minutos) y el Capítulo 6 todavía no está
   volcado. Lo único manual que habría que repetir es el chequeo humano de los perfiles
   afectados (una hora). Después de escribir el 6, cambiar obliga a rehacer sus tablas.

## 5. Qué NO dice este experimento

No dice cuál variante es «correcta»: eso es una decisión de modelado del dominio (¿una crítica
al rendimiento debe poder desaconsejar un café?) y le corresponde al director. Sólo mide cuánto
se mueve el ranking en cada caso y muestra que la asimetría 0,90 vs 0,75 es la que produce los
ceros.
