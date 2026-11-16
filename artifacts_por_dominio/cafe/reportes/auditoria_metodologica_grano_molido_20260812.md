# Auditoría metodológica: café en grano y molido

Fecha: 2026-08-12

## Objetivo y alcance

Se revisaron las reseñas limpias de los productos incluidos por la revisión humana en dos snapshots independientes:

- México: `mlm_mlm194335_20260805_185233` — 8.024 reseñas, 19 productos.
- Colombia: `mco_mco409413_20260805_184739` — 846 reseñas, 16 productos.

La auditoría combina el descubrimiento de candidatos de `02_domain_discovery.py` con un conteo por familias léxicas normalizadas. Los conteos de “uso valorativo” son exploratorios: detectan palabras de preferencia o evaluación en la misma reseña, pero no sustituyen la extracción contextual de `05_aspects.py`.

## Evidencia

| Candidato | México: reseñas / productos | Colombia: reseñas / productos | Reseñas con señal valorativa | Decisión |
|---|---:|---:|---:|---|
| Tueste/tostado/tostión | 256 / 18 de 19 | 62 / 14 de 16 | 203 MX; 56 CO | Incorporar como aspecto sensorial |
| Acidez/ácido | 104 / 16 de 19 | 13 / 6 de 16 | 88 MX; 12 CO | Incorporar como aspecto sensorial |
| Origen/procedencia | 2 / 2 de 19 | 4 / 3 de 16 | 1 MX; 3 CO | No incorporar por ahora |
| Cuerpo | 111 / 16 de 19 | 7 / 6 de 16 | 88 MX; 3 CO | Ya cubierto por `intensidad` |
| Molienda/molido | 139 / 17 de 19 | 13 / 7 de 16 | 108 MX; 8 CO | Ya cubierto por `molienda` |
| Frescura/fresco | 73 / 14 de 19 | 13 / 10 de 16 | 52 MX; 12 CO | Ya cubierto por `caducidad` |

Ejemplos que justifican la separación conceptual:

- Tueste: “de mis preferencias por el tueste oscuro”; “nos pareció pasado de tostión”; “tostión media que conlleva a la suavidad”.
- Acidez: “acidez balanceada”; “con acidez como me gusta”; “esperaba algo más de acidez”.
- Origen: los pocos casos son mayormente descriptivos —“café de origen”, “origen colombiano”— y no muestran cobertura suficiente para construir un criterio general de ranking.

## Fundamento de la decisión

Un aspecto nuevo se acepta cuando cumple conjuntamente cuatro condiciones: es una propiedad del producto, aparece en varios productos, admite valoraciones positivas y negativas o preferencias de grado, y el usuario puede asignarle una importancia distinta de otros aspectos.

`tueste` y `acidez` cumplen esas condiciones y no son equivalentes a `intensidad` o `dulzor`: un café puede ser intenso con tueste medio, o poco amargo pero con acidez marcada. Por eso se agregan como sliders independientes dentro de la dimensión `sensorial`.

`origen` puede ser relevante como dato de catálogo o filtro futuro, pero el corpus actual no sustenta todavía un aspecto de opinión. Se mantiene como candidato rechazado provisionalmente. Si en otro snapshot aumenta su cobertura y aparecen preferencias explícitas por regiones o procedencias, debe reabrirse la decisión.

## Cambios metodológicos

- Se agregan `tueste` y `acidez` a `quality_aspects` y al léxico de café.
- Ambos se integran en la dimensión LAF1 `sensorial` con beta estructural neutral (`1.0`), de modo que la preferencia sigue viniendo únicamente de los sliders.
- Fuerzas alpha iniciales conservadoras: `0.85` para soporte positivo; `0.88` para rechazo por tueste y `0.85` para rechazo por acidez.
- No se agrega `origen`.

## Verificación posterior con la extracción contextual

Después de incorporar el léxico se volvió a ejecutar `05_aspects.py`. La extracción final confirmó:

| Dataset | Tueste | Acidez |
|---|---:|---:|
| México grano/molido | 268 (167 pos., 9 neg., 92 neu.) | 109 (61 pos., 6 neg., 42 neu.) |
| Colombia grano/molido | 64 (33 pos., 4 neg., 27 neu.) | 13 (8 pos., 1 neg., 4 neu.) |
| México instantáneo | 23 | 11 |
| México histórico mixto | 62 | 41 |

También se recalculó `06_trust.py` para los cuatro datasets de café, de modo que ninguna salida activa conserve aspectos o agregados anteriores a esta decisión. Finalmente se regeneraron los programas de auditoría, se validó la estructura y se volvió a congelar la categoría.

## Mejora futura: preferencias direccionales

El modelo actual pregunta cuánto importa que las reseñas valoren favorablemente un aspecto. No pregunta qué nivel concreto prefiere el usuario. Por ejemplo, dos productos pueden recibir soporte positivo por un tueste medio y por un tueste oscuro, respectivamente.

Se posterga para una etapa futura la incorporación de una segunda preferencia, independiente de la importancia:

- tueste: claro, medio u oscuro;
- acidez: baja, media o alta;
- intensidad: suave, media o fuerte;
- molienda: fina, media o gruesa.

Esta ampliación requerirá extracción estructurada del nivel mencionado, almacenamiento separado de aspecto/valor, reglas de coincidencia entre el nivel deseado y el observado, y nuevos controles en la interfaz. Hasta entonces, el slider debe interpretarse como importancia de la valoración favorable del aspecto, no como selección de un nivel.

## Presentación adaptativa en la aplicación

La aplicación conserva el perfil completo de la categoría, pero no presenta automáticamente todos sus sliders. Para el snapshot y la estrategia elegidos consulta `product_aspect_trust` y muestra solamente los aspectos que:

- tienen evidencia en al menos 2 productos distintos; y
- suman al menos 3 reseñas entre sus posturas positivas y negativas.

Los rótulos visibles pasan a ser `Calidad del tueste` y `Valoración de la acidez`. La pantalla aclara que las opciones dependen de la información encontrada en las reseñas del catálogo. Si Supabase no está configurado se mantiene el perfil completo del fixture de demostración; ante una caída transitoria se conserva el formulario completo para no interrumpir una sesión iniciada.

## Trazabilidad

Reportes fuente:

- `domain_discovery_cafe_grano_mx_20260805.json/.csv`
- `domain_discovery_cafe_grano_co_20260805.json/.csv`

Estos reportes se generaron con sufijos por corpus y `--no-draft`, por lo que no sobrescriben el descubrimiento histórico ni crean configuraciones provisionales.
