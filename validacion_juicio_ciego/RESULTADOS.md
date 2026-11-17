# Experimento 1 — Juicio ciego por pares · RESULTADOS

**Fecha del análisis:** 2026-09-10  
**Snapshot:** `mlm_mlm194329_20260528_142014` · aspecto **sabor** · estrategia D  
**Tabla de pares:** `tabla_pares_con_puntajes_sabor_20260910.csv` · semillas 20260910 / 20260911 / 20260912  
**Jueces:** 1

> Las definiciones, las métricas y el criterio de fracaso están fijados en
> `README.md` **antes** de correr y antes de recibir respuestas. Este archivo
> sólo los aplica.

## 1. Resultado principal

- Pares con veredicto mayoritario: **14 de 20**.
- **Acuerdo sistema–jueces: 7/14 = 50.0 %** (IC 95 % de Wilson: 26.8 % – 73.2 %).

| Franja | Pares con mayoría | Acuerdo | IC 95 % | Excluidos |
|---|---:|---:|---|---:|
| grande | 4 | 1/4 = 25.0 % | 4.6 % – 69.9 % | 3 |
| mediana | 5 | 2/5 = 40.0 % | 11.8 % – 76.9 % | 2 |
| chica | 5 | 4/5 = 80.0 % | 37.6 % – 96.4 % | 1 |

**Criterio de fracaso pre-registrado** (acuerdo < 70 % en la franja grande): **SE CUMPLE**.

> El ranking por aspecto no refleja la lectura humana de la evidencia.
> Así debe escribirse en la tesis. No se ajustó ningún parámetro.

## 2. Acuerdo entre jueces

- **No aplica: hay un solo juez.** Fleiss κ necesita al menos dos personas, y la unanimidad de un juez consigo mismo es 100 % por definición. Este experimento **no mide acuerdo entre jueces**; la limitación está declarada en la enmienda del pre-registro.

| Juez | A | B | No puedo decidir | Ciclos de preferencia | Dijo reconocer producto |
|---|---:|---:|---:|---:|---:|
| juez_1 | 8 | 6 | 6 | 0 | 0 |

## 3. Par por par

| Par | Franja | Δ LAF | Sistema | juez_1 | Mayoría | ¿Coincide? |
|---|---|---:|---|---|---|---|
| P01 | chica | 0.0437 | B | B | B | sí |
| P02 | chica | 0.0507 | A | A | A | sí |
| P03 | chica | 0.0377 | A | A | A | sí |
| P04 | chica | 0.0154 | B | A | A | **no** |
| P05 | chica | 0.0202 | A | A | A | sí |
| P06 | chica | 0.0099 | A | no_puedo_decidir | excluido (mayoria de 'no puedo decidir') | — |
| P07 | grande | 0.1336 | A | no_puedo_decidir | excluido (mayoria de 'no puedo decidir') | — |
| P08 | grande | 0.1234 | A | B | B | **no** |
| P09 | grande | 0.1547 | B | B | B | sí |
| P10 | grande | 0.2425 | A | B | B | **no** |
| P11 | grande | 0.2628 | B | A | A | **no** |
| P12 | grande | 0.1659 | A | no_puedo_decidir | excluido (mayoria de 'no puedo decidir') | — |
| P13 | grande | 0.1179 | B | no_puedo_decidir | excluido (mayoria de 'no puedo decidir') | — |
| P14 | mediana | 0.0711 | B | A | A | **no** |
| P15 | mediana | 0.0939 | A | A | A | sí |
| P16 | mediana | 0.0980 | A | no_puedo_decidir | excluido (mayoria de 'no puedo decidir') | — |
| P17 | mediana | 0.0862 | B | A | A | **no** |
| P18 | mediana | 0.1080 | A | B | B | **no** |
| P19 | mediana | 0.0815 | B | B | B | sí |
| P20 | mediana | 0.0826 | A | no_puedo_decidir | excluido (mayoria de 'no puedo decidir') | — |

## 4. Comentarios de los jueces

- **juez_1 · P01:** Pero solo pq A tiene una de sabor medio neutral
- **juez_1 · P02:** Esta muy peleado pero B tiene una negativa y A no
- **juez_1 · P03:** Estuvo peleado pero la critica al sabor de B es mas fuerte
- **juez_1 · P04:** Esta muy peleado pero B tiene una negativa y A no
- **juez_1 · P05:** En B critican el sabor
- **juez_1 · P06:** no tienen criticas del sabor
- **juez_1 · P07:** no tienen criticas del sabor
- **juez_1 · P08:** Ambos 1 critica pero la de A es mas fuerte
- **juez_1 · P09:** El A tiene 2 o mas criticas
- **juez_1 · P10:** Ambos tienen criticas, fue dificil
- **juez_1 · P11:** Si bien A tiene mas criticas B tiene una de sabor que A no
- **juez_1 · P12:** no veo criticas
- **juez_1 · P13:** Ambos tienen una pequenia critica sobre intensidad
- **juez_1 · P14:** A no tiene criticas del producto solo algun que un reseniador leyo
- **juez_1 · P15:** A un apersonano le gusto el sabor de B
- **juez_1 · P16:** no tienen criticas
- **juez_1 · P17:** Esta muy peleado pero B tiene una negativa y A no
- **juez_1 · P18:** A tiene algunas criticas o neutrales
- **juez_1 · P19:** A tiene algunas criticas o neutrales
- **juez_1 · P20:** no veo criticas

## 5. Limitaciones

- **1 jueces.** Fleiss κ sobre 1 jueces y 20 ítems tiene un error estándar grande.
- **Poca potencia.** Con ~7 pares por franja, el intervalo de confianza del acuerdo es muy ancho: este experimento detecta un fracaso grosero, no distingue un 70 % de un 90 %. Está declarado en el pre-registro, §9.
- **Un solo aspecto** (`sabor`), no el ranking multicriterio de 14 aspectos que ve el usuario.
- **Los pares los eligió el sistema** a partir de su propio puntaje: el diseño garantiza cobertura de distancias, no representatividad del catálogo.
- **15 fragmentos por lado** son una muestra de hasta 477 menciones: el juez ve una ventana, el sistema ve todo.
- Los fragmentos vienen **truncados a 200 caracteres** desde la extracción, con casos conocidos de sentido invertido.
- La evidencia mostrada **incluye menciones `neu`** que el sistema descarta.
- **Anonimización imperfecta:** formatos y tipos de café quedan a la vista.
- Mide **acuerdo con una lectura humana de la evidencia**, no utilidad de la recomendación ni calidad de la explicación.

## 6. Análisis posterior

El desacuerdo entre la jueza y el sistema resultó **sistemático, no aleatorio**. El contraste de hipótesis que lo explica se hizo **después** de ver estas respuestas y por lo tanto no está pre-registrado: vive aparte, en `RESULTADOS_POST_HOC.md`, con esa advertencia al frente. Las cifras de este archivo no dependen de él.

Se corrió además un **lector automático (LLM)** sobre los mismos 20 pares, pre-registrado aparte en `README_LLM.md`. Es una observación **secundaria** —no es un juez humano— y se informa en `RESULTADOS_LLM.md`. Su ampliación a los 151 pares elegibles **no se realizó** por agotamiento del crédito de la API. Tampoco modifica las cifras de este archivo.
