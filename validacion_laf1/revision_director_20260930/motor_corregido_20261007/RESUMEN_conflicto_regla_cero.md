# Conflicto on/off y regla del cero (17/10/2026)

Script: `conflicto_onoff_regla_cero.py` (esta carpeta). Salida: `conflicto_onoff_regla_cero_20261017.json`.
El JSON del 14/10 (`conflicto_onoff_regla_cero_20261014.json`, solo neutro, sin script) se conserva y se reproduce exacto.

## Cómo se calcula
- Programas: los 14 programas por aspecto de la batería oficial del corpus principal (`salidas_8088/mc_asp_*.txt`,
  dataset `mlm_mlm194329_20260528_142014`, metodología `735f9b0c…`), evaluados en `laf-api` corregido (8088;
  control sintético 0,45 verificado el 17/10).
- Igual que la batería y la app: `zero_threshold_payload` → `laf-api` → `LAFGraphRankingMapper` (confianza del aspecto)
  → `normalized_multicriteria_ranking` (`post_laf_multicriteria_v1`, desempate por identificador).
- Conflicto off: se quitan las reglas con cabeza negada (`~…`) de los 14 programas; los hechos negativos quedan sin efecto.
- Control: con las reglas completas los puntajes coinciden con `validacion_laf1/salidas/battery_multicriterio_mlm194329_20260528_142014.json`
  en neutro y solo sabor (desvío máximo < 1e-9).

## Resultados
| Perfil | Posiciones que cambian | ρ on/off (rangos promedio) | Ganador | Top 3 con conflicto → sin conflicto |
|---|---|---|---|---|
| Neutro | 15/18 | 0,891 | Blasón Espresso Robusto 1 kg (se conserva) | Robusto, Espresso 400 g, Americano 1 kg → Robusto, La Parroquia molido 1 kg, Taster's Choice Caramel (Espresso 400 g 2.º→4.º; Americano 3.º→5.º) |
| Solo sabor | 15/18 | 0,933 (ordinal 0,930) | Members Mark Vainilla 1,8 kg (se conserva) | Vainilla, Americano 1 kg, Moka 1,8 kg → Vainilla, Moka, Robusto (Americano 2.º→5.º) |

En solo sabor hay empates exactos que se resuelven por identificador: con conflicto, Moka y Robusto (0,6384, 3.º–4.º);
sin conflicto, Moka y Robusto (0,6472, 2.º–3.º) y Americano y Taster's Choice (0,6403, 4.º–5.º). Parte de las 15
posiciones que cambian en solo sabor son, por eso, intercambios entre empatados.

## Regla del cero
Spearman entre el puntaje neutro y el número de aspectos con evidencia (8 a 14 por producto):
- **rangos promedio (estándar, como el resto del Cap. 6): ρ = 0,878** (0,8783)
- rangos ordinales con empates rotos por identificador: ρ = 0,845 (0,8452) — la cifra del 14/10 y de la versión (8)
- Pearson: 0,862

## Reproducir
```
cd "<repo>"
venv\Scripts\python.exe validacion_laf1\revision_director_20260930\motor_corregido_20261007\conflicto_onoff_regla_cero.py
```
