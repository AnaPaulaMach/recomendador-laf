# Motor corregido (propagación con δ) — corrida del 2026-10-07

Comparación entre el motor `laf-api` actual (main de Javi, contenedor `extraccionargumentos-laf-api-1`,
`localhost:8088`) y la rama `propagacion-delta-budan` del fork `AnaPaulaMach/LAF` (commit `ce69811`,
imagen `laf-api-delta:propagacion`, `localhost:8089`). El repositorio de Javi no se modificó.

## Qué cambia en la rama

`InferenceEngine.java` añade, después de construir el grafo y detectar conflictos, un reetiquetado que
resuelve las ecuaciones de Budán et al. (2017), Def. 8(iii) / Algoritmo 2: el soporte de cada conclusión usa
δ de sus premisas (no μ), y δ = μ ⊖ μ(opuesto). Modo conmutable: `LAF_PROPAGATION=accrued` restaura el
comportamiento anterior. Tests nuevos: `InferenceEngineWeakenedPropagationTest` (5). Suite completa: 46/46.

## Archivos de esta carpeta

| Archivo | Qué es |
|---|---|
| `comparar_motores.py` / `comparacion_motores_20261007.json` | Los 14 programas por aspecto de `alternativa_programa_unico/programas_por_aspecto` enviados a ambos motores; el nuevo coincide con la recurrencia manual de la Def. 8 en 198/198 pares producto-aspecto. |
| `battery_multicriterio_puerto.py` | Copia de `validacion_laf1/battery_multicriterio.py` parametrizada por `LAF_PORT`; escribe en `salidas_<puerto>/`, no toca `validacion_laf1/salidas/`. |
| `salidas_8088/` + `salida_bateria_8088.log` | Control: batería contra el motor actual. Reproduce el archivo oficial `salidas/battery_multicriterio_mlm194329_20260528_142014.json` en los 5 perfiles (orden 18/18, max\|Δscore\| = 0). |
| `salidas_8089/` + `salida_bateria_8089.log` | Batería contra el motor corregido. |
| `comparacion_bateria_oficial_vs_8089.json` | Oficial vs control vs corregido, por perfil. |
| `interfaz_vs_bateria_8089.py` / `interfaz_vs_bateria_8089_20261007.json` | Camino de producción (`get_evaluator()`, `LAF_API_RESULTS_VALIDATED=1`, `LAF_API_URL=8089`) vs batería 8089: 18/18 en los 5 perfiles, max\|Δscore\| ≤ 6e-17. |

## Resultado de la batería oficial (snapshot `mlm_mlm194329_20260528_142014`, estrategia D, hash `735f9b0c…`)

| Perfil | Control 8088 vs oficial | Corregido 8089 vs oficial: posiciones iguales | ρ Spearman | max \|Δscore\| | Top 3 |
|---|---|---:|---:|---:|---|
| neutral | 18/18, Δ=0 | 13/18 | 0,977 | 0,028 | igual (Blasón Espresso, Blasón gourmet molido, Café gourmet tostado) |
| solo_sabor | 18/18, Δ=0 | 18/18 | 1,000 | 0,029 | igual |
| solo_aroma | 18/18, Δ=0 | 16/18 | 0,998 | 0,026 | igual |
| sensorial | 18/18, Δ=0 | 14/18 | 0,996 | 0,017 | mismo ganador; 2.º y 3.º se intercambian (La Parroquia sube a 2.º) |
| pert_sabor_0.6 | 18/18, Δ=0 | 13/18 | 0,986 | 0,028 | igual |

Responsividad: RESPONDE (neutral → Blasón; solo_aroma → Nescafé Taster's; solo_sabor → Capuccino vainilla).
Estabilidad: ESTABLE (neutral = pert_sabor_0.6). Discriminación (neutral): 16 scores distintos de 18, ninguno en 0.

## Lectura

- Los puntajes suben o quedan iguales en todos los productos: el motor anterior restaba la misma crítica en cada
  nivel de la cadena; el corregido la descuenta una vez, donde ocurre el conflicto.
- El podio no cambia en cuatro de cinco perfiles; en «sensorial» cambia el orden entre 2.º y 3.º.
- Estas cifras son del motor de la rama; no sustituyen los resultados entregados hasta que se adopte la
  corrección y se recongele. No se rehicieron aquí el remuestreo (`validacion_robustez`), EXP11/EXP12 ni OE5.

## Pendiente

1. Decisión con el director (corregir vs declarar variante).
2. Si se corrige: reconstruir `extraccionargumentos-laf-api` desde la rama, rehacer remuestreo, EXP12 y OE5,
   recongelar y actualizar Cap. 6; reescribir C24/C25 de la guía en rojo como diagnóstico de la versión anterior.
3. Avisar a Javi (cambio aditivo y conmutable).

## Ejemplo de las casas (Budán et al. 2017, Ejemplo 1) en los dos motores — `ejemplo_casas_budan_20261007.json`

Programa del artículo (arXiv págs. 14–16), dos etiquetas (confianza y preferencia), intervalos fijados como en la
Fig. 7 (vecinos de A = 0,5; vecinos de B = 0), r1–r12 para houseA y r13–r21 para houseB.

- Reproducen la Fig. 7 ambos motores: goodArea(houseB), ~goodArea(houseB), ~buy(houseB), buy(houseA).
- Difieren entre sí donde hay conflicto intermedio: goodArea(houseA) δ = (0,711, 0) actual vs (0,719, 1) rama δ;
  gangOperate(houseA) δ = 0,492 vs 0,5 (ciclo de conflicto: en la Def. 8 ~insecureArea queda en 0 y no debilita).
- ~goodArea(houseA) = 0,20 en la figura no es reproducible desde los valores impresos (ambos motores dan ≈0,1);
  la figura parece usar otro punto del intervalo [0, 0,5].
- **Segundo defecto del motor original, independiente de μ/δ:** buy(houseB) da preferencia 0,8 en ambos motores
  (artículo: 0,85) porque la regla r13 (buy ← goodArea) nunca se aplica. Sonda mínima: con `a(x). {0.5}`,
  `a(X) :- b(X).`, `d(X) :- a(X).` el motor original deja `a` sin agregar (0,5 en lugar de 0,75) y no deriva `d`.
  Ocurre cuando un literal está en el programa como hecho y además se deriva por regla. La rama
  `propagacion-delta-budan` solo reetiqueta y hereda la estructura, así que no lo corrige. No afecta los programas
  de producción del TFG (los hechos son hojas `resenaPositiva/Negativa`, nunca derivados); sí afectaría un programa
  único con dimensiones compartidas. Pendiente de informar a Javi.

## Recálculo de la cadena del Capítulo 6 con el motor corregido — 2026-10-08, carpeta `rerun_8089/`

Copias de los scripts oficiales apuntadas a `localhost:8089` y con salidas propias (no se tocó `validacion_robustez/salidas`,
`validacion_laf1/salidas` ni `validacion_oe5/salidas`). Control previo en cada script: réplica sin remuestreo = batería 8089, 18/18.

| Experimento | Oficial (motor actual) | Motor corregido (8089) |
|---|---|---|
| EXP12 sensibilidad, 6 variantes ±0,10 | ρ ≥ 0,998; a lo sumo 2 productos cambian; ganador y top 3 estables salvo solo sabor | ρ ≥ 0,986; hasta 6 productos cambian (agregación 0,95, solo aroma); ganador igual en todas; top 3 cambia en una (agregación 0,95, solo sabor) |
| EXP12 aleatorio, 20 perturbaciones ±0,05 | neutro ρ media 0,996 (mín 0,990); solo sabor 1,000, ganador 15/20; solo aroma 0,998, top 3 6/20 | neutro ρ media 0,994 (mín 0,979), ganador 20/20, top 3 20/20; solo sabor 1,000, 20/20, 20/20; solo aroma 1,000, 20/20, 20/20 |
| Bootstrap 200 réplicas, neutro | ρ media 0,929 (mín 0,823; p5 0,872; p95 0,971); top 3 48,5 %; ganador 94,5 % | ρ media 0,937 (mín 0,843; p5 0,892; p95 0,971); top 3 31,0 %; ganador 96,5 % |
| Bootstrap 200 réplicas, solo sabor | ρ media 0,956 (mín 0,867; p5 0,907; p95 0,990); top 3 49,5 %; ganador 41,0 % | ρ media 0,962 (mín 0,882; p5 0,923; p95 0,991); top 3 43,0 %; ganador 43,0 % |
| OE5 neutro, corpus principal | ρ con estrellas 0,463; con reseñas 4–5★ 0,571; puntajes distintos 18/18; coherencia interna 0,820; inversiones duras 32 | 0,424; 0,583; 16/18 distintos; coherencia 0,822; inversiones 29 |
| OE5 solo aroma | ρ estrellas 0,271; reseñas 0,205; coherencia 0,932 | 0,267; 0,214; 0,944 |
| OE5 estabilidad / responsividad | neutro vs perturbado 1,000; vs solo sabor 0,851; vs solo aroma 0,472 | 0,983; 0,789; 0,486 |

Lectura: ninguna conclusión del Capítulo 6 se invierte (criterio de fracaso del bootstrap no se cumple; el orden es más
sensible a las preferencias que a las fuerzas; sesgo de popularidad similar). Cambian frases concretas: «ρ ≥ 0,998 y a lo
sumo dos productos» pasa a «ρ ≥ 0,986 y hasta seis»; la tabla de perturbaciones aleatorias mejora (ganador 20/20 en los
tres perfiles); en el bootstrap el top 3 del perfil neutro se conserva menos (31,0 % frente a 48,5 %), la alerta secundaria
sigue activa; OE5 cambia en centésimas. Figuras de intervalos regeneradas en `rerun_8089/robustez_8089/`.

No rehecho: las 15 comparaciones de fuerzas del 30/09 (C10), EXP11 (fila 13: su decisión ya está adoptada), los
experimentos de arquitectura y preferencias (C13), LAF2 y el chequeo humano. Los dos conjuntos secundarios de OE5 se
reprocesan en la misma carpeta (`oe5_8089/`).

### OE5, perfil neutro, tres conjuntos (oficial → corregido)

| Indicador | Principal n=18 | Instantáneo n=16 | Grano/molido n=19 |
|---|---|---|---|
| ρ con estrellas | 0,463 → 0,424 | 0,556 → 0,535 | 0,339 → 0,296 |
| ρ con reseñas 4–5★ | 0,571 → 0,583 | 0,759 → 0,768 | 0,828 → 0,846 |
| ρ posición orientada vs reseñas calificadas | 0,571 → 0,583 | 0,759 → 0,768 | 0,835 → 0,854 |
| ρ con evidencia neta | 0,820 → 0,822 | 0,829 → 0,838 | 0,856 → 0,882 |
| Puntajes distintos | 18/18 → 16/18 | 15/16 → 16/16 | 19/19 → 19/19 |

Los bloques LaTeX con estas cifras están en `outputs/revision_director_20260930/CAMBIOS_TFG_LATEX_ROJO.md`, sección «Opción CORREGIR» (C04, C23–C25 corregir, C27–C30).

## Decisión (8 de octubre de 2026): el TFG queda con el motor corregido

- Rama `propagacion-delta-budan` fusionada en `main` del fork `AnaPaulaMach/LAF` (commit `ce69811`); el contenedor de
  producción `extraccionargumentos-laf-api` se reconstruyó desde ese `main` (puerto 8088).
- Salidas oficiales reemplazadas con la convención ya usada para la fila 13 (`_pre_fila13`): las anteriores quedan como
  `*_pre_delta_20260910.*` y las nuevas ocupan el nombre oficial: `validacion_laf1/salidas/battery_multicriterio_…json`,
  `validacion_oe5/salidas/metrics_*.json`. Las fechadas se copiaron con su fecha: `validacion_robustez/salidas/*_20261008.*`,
  `validacion_laf1/salidas/exp12_sensibilidad_confianzas_2026-10-08.json`, `recongelado_20260910/despues/interfaz_vs_bateria_8089_20261007.json`.
- Pendiente: C13 (arquitectura y preferencias) y C10 (15 comparaciones de fuerzas) con el motor corregido; exportar a PNG las
  figuras de intervalos (SVG en `validacion_robustez/salidas/`); registrar la versión del evaluador en el manifiesto congelado;
  avisar a Javi (incluido el segundo defecto).

## Reejecución de C09–C13 con el motor corregido — 2026-10-10

Scripts del 30/09 corridos tal cual contra el motor de producción (8088, ya corregido); salidas del 30/09 preservadas en
`pre_delta_20260930/`. Logs en `rerun_8089/*_20261010.log`.

- `comparar_confianzas.py` (C09–C12): control vigente = batería 18/18 (Δ 5,6e-17 y 0). Uniforme 0,85 reproduce
  exactamente los perfiles de un solo aspecto; ρ_ord mínimo 0,955 (λ=20, neutro; antes 0,944); el ganador del neutro
  se conserva en las 15 comparaciones (antes λ=20 lo invertía).
- `comparar_motor_local.py` (C13): una corrida con terminales por aspecto = 14 corridas aisladas (17 perfiles, Δ 0);
  neutro independiente = batería oficial (Δ 1,1e-16); lectura de `aspectoBueno` difiere hasta 0,165 (mixto 0,176);
  `recomendar` global difiere hasta 0,755. Para ello `comparacion_offline.json` tomó como referencia por aspecto los
  grafos del motor corregido (clave anterior conservada como `*_pre_delta_20260930`, `saved_ranking` → batería oficial).
- `preferencias_antes_laf.py` (C13): ponderar hechos y ponderar la regla puente **ya no son equivalentes** (hasta 0,047;
  antes 1e-16), porque el peso sobre el hecho actúa antes del conflicto de aspecto y la Def. 8 continúa con el debilitado;
  el ganador se conserva al pasar de 0,67 a 0,33 (antes cambiaba); regla conjunta sintética 0,405 = 0,75·0,6·0,9 (antes 0,432).
- Blasón, sabor: terminal 0,638440 = 0,788198·0,90·0,90, coincide con la recurrencia formal (antes 0,631273).
