# Auditoria de generacion LAF1 con datasets reales

Fecha: 2026-08-13T14:25:28.841750+00:00
Estrategia: `D`
Metodologia congelada: `4be8a4f128dbac3d40b88dfa9204458b2bcfda40015608cf678bc69494062767`

Esta auditoria valida la generacion; no ejecuta el ranking algebraico.

| Dataset | 07 UI | Escenario | Productos | Con trust | Hechos | Reglas | Resultado |
|---|---|---|---:|---:|---:|---:|---|
| Colombia - grano/molido (`mco_mco409413_20260805_184739`) | OK | `neutral` | 16 | 15 | 114 | 64 | OK |
| Colombia - grano/molido (`mco_mco409413_20260805_184739`) | OK | `sensorial_alta` | 16 | 15 | 114 | 64 | OK |
| Colombia - grano/molido (`mco_mco409413_20260805_184739`) | OK | `uso_preparacion_alta` | 16 | 15 | 114 | 64 | OK |
| Mexico - historico mixto (`mlm_mlm194329_20260528_142014`) | OK | `neutral` | 18 | 18 | 258 | 64 | OK |
| Mexico - historico mixto (`mlm_mlm194329_20260528_142014`) | OK | `sensorial_alta` | 18 | 18 | 258 | 64 | OK |
| Mexico - historico mixto (`mlm_mlm194329_20260528_142014`) | OK | `uso_preparacion_alta` | 18 | 18 | 258 | 64 | OK |
| Mexico - instantaneo (`mlm_mlm194329_20260805_191308`) | OK | `neutral` | 16 | 16 | 205 | 64 | OK |
| Mexico - instantaneo (`mlm_mlm194329_20260805_191308`) | OK | `sensorial_alta` | 16 | 16 | 205 | 64 | OK |
| Mexico - instantaneo (`mlm_mlm194329_20260805_191308`) | OK | `uso_preparacion_alta` | 16 | 16 | 205 | 64 | OK |
| Mexico - grano/molido (`mlm_mlm194335_20260805_185233`) | OK | `neutral` | 19 | 19 | 275 | 64 | OK |
| Mexico - grano/molido (`mlm_mlm194335_20260805_185233`) | OK | `sensorial_alta` | 19 | 19 | 275 | 64 | OK |
| Mexico - grano/molido (`mlm_mlm194335_20260805_185233`) | OK | `uso_preparacion_alta` | 19 | 19 | 275 | 64 | OK |

## Comprobaciones realizadas

- `dataset_key` exacto en el encabezado;
- ejecución headless de 07 con 14 sliders y tres perfiles por dataset, sin sobrescribir el archivo persistido;
- igualdad entre productos listados y catálogo revisado del snapshot;
- preferencias de 07 en el encabezado y beta de cada hecho;
- igualdad exacta entre cada `agg_confidence` de Supabase y el trust del hecho, redondeado a dos decimales;
- reglas y alpha iguales a la configuración cuyo hash fue congelado por 06d;
- beta estructural igual a `1.00`.

## Cobertura geográfica y de tipos

Se verificaron México histórico mixto, México instantáneo, México grano/molido y Colombia grano/molido. No existe actualmente un snapshot real de café instantáneo de Colombia en la tabla `datasets`.

## Advertencias de cobertura

- `mco_mco409413_20260805_184739`: productos incluidos sin hechos de trust para la estrategia auditada: `mcou4152714259`.

Estos productos pertenecen al catálogo correcto, pero no pueden obtener una derivación LAF1 mientras no tengan evidencia agregada.
