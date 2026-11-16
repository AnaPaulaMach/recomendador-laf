# ¿Importan λ y π? — 2026-10-14, motor corregido (localhost:8088)

Estrategia D: α = (W⁺ + λπ)/(W + λ) (negativo con 1−π). Vigente λ = 10, π = 0,5 (`src/06_trust.py`).
Ranking oficial `post_laf_multicriteria_v1` (LAF por aspecto + suma ponderada), snapshot `mlm_mlm194329_20260528_142014`, 18 productos.

**Grilla (11):** λ ∈ {0, 2, 5, 10, 20, 50} con π = 0,5, y π ∈ {0,3, 0,4, 0,6, 0,7, 0,8} con λ = 10. En el repo solo había
una grilla previa parcial (λ ∈ {5, 10, 20}, `../../comparar_confianzas.py`); esta la contiene y la reproduce exactamente
(λ = 5: ρ neutro 0,979 / sabor 0,986; λ = 20: 0,955 / 0,990, ganador sabor = Capuccino moka).

**Método:** `lambda_pi_sensibilidad.py` (derivado de `comparar_confianzas.py`): inputs mínimos locales
(`../../inputs_minimos.json`, sin Supabase), λ y π cambiados en memoria sobre 06_trust, generador 08 real, motor LAF real
por aspecto, `combine_rankings` de producción. No escribe en `validacion_*/salidas/`.

**Controles:** sintético `b(x) :- a(x)` con 0,5·0,9 = **0,45** ✔; configuración vigente = batería oficial
`validacion_laf1/salidas/battery_multicriterio_mlm194329_20260528_142014.json`, orden 18/18 en neutro y solo sabor ✔.

| λ | π | Neutro: ganador | ρ | cambian | Solo sabor: ganador | ρ | cambian |
|---|---|---|---:|---:|---|---:|---:|
| 0 | 0,5 | Blasón Espresso 400 g * | 0,961 | 12 | Nescafé Decaf * (empate 5) | 0,418 | 17 |
| 2 | 0,5 | Blasón Espresso Robusto | 0,981 | 9 | Blasón Americano * | 0,913 | 16 |
| 5 | 0,5 | Blasón Espresso Robusto | 0,979 | 8 | Capuccino vainilla | 0,986 | 8 |
| **10** | **0,5** | **Blasón Espresso Robusto** | 1 | 0 | **Capuccino vainilla** | 1 | 0 |
| 20 | 0,5 | Blasón Espresso Robusto | 0,955 | 6 | Capuccino moka * (empate 2) | 0,990 | 4 |
| 50 | 0,5 | Blasón Espresso 400 g * | 0,839 | 15 | Capuccino moka * | 0,975 | 9 |
| 10 | 0,3 | Blasón Espresso Robusto | 0,932 | 11 | Capuccino vainilla | 0,994 | 3 |
| 10 | 0,4 | Blasón Espresso Robusto | 0,934 | 11 | Capuccino vainilla | 0,994 | 3 |
| 10 | 0,6 | Blasón Espresso Robusto | 0,979 | 8 | Blasón Americano * | 0,990 | 7 |
| 10 | 0,7 | Blasón Espresso Robusto | 0,963 | 13 | Blasón Americano * | 0,979 | 11 |
| 10 | 0,8 | Blasón Espresso Robusto | 0,940 | 11 | Blasón Americano * | 0,963 | 14 |

\* ganador distinto del vigente. «cambian» = productos (de 18) con puesto distinto al vigente.

## Lectura

- **Solo sabor: el ganador cambia en 7 de 11** (las 10 alternativas salvo λ = 5, π = 0,3, π = 0,4). Reproduce el «7 de 11»
  del director (sus scripts no están disponibles; no se puede confirmar que la grilla sea la misma). En λ = 0 (5 productos
  empatados en 0,6885) y λ = 20 (2 empatados) el primer puesto lo decide el desempate. ρ ≥ 0,913 salvo λ = 0 (0,418).
  Top 3 (conjunto) cambia en 6 de 10. Margen 1.º–2.º vigente: 0,0068.
- **Neutro: el ganador cambia en 2 de 11** (λ = 0 y λ = 50, ambos a Blasón Espresso 400 g). ρ ≥ 0,839 (≥ 0,932 sin λ = 50).
  Top 3 (conjunto) cambia en 6 de 10. Margen 1.º–2.º vigente: 0,020.
- Respuesta corta: λ y π mueven poco el orden global pero sí el primer puesto de solo sabor, donde los primeros están a
  menos de una centésima.

## Archivos

- `lambda_pi_sensibilidad.py` — script; `corrida.log` — salida de consola.
- `resultados_lambda_pi.json` — rankings completos (18 productos, puntajes) por configuración y perfil, comparaciones, hashes de insumos.
- `bloque_latex.tex` — tabla booktabs + párrafo, en azul.
