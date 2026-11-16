# Aplicación web del recomendador LAF

Este documento describe la instalación, la arquitectura y las herramientas de desarrollo de la aplicación.

Interfaz final del TFG, separada del pipeline experimental situado en `../src`.
Implementa un recorrido Django en dos niveles de decisión: primero qué **producto**
conviene, a partir de la evidencia de las reseñas (LAF 1); después qué **publicación**
de ese producto tiene mejores condiciones de compra (LAF 2).

1. preferencias de calidad (qué características importan);
2. ranking y detalle de productos («Ver por qué lo recomendamos»);
3. selección de producto;
4. presupuesto y preferencias de compra;
5. ranking y comparación de publicaciones, con su explicación;
6. grafo de derivación por característica o por condición;
7. trazabilidad de la corrida y descarga de los programas.

El ranking que ve el usuario sale del evaluador HTTP contra `laf-api` (el motor de
Budán, Simari, Viglizzo y Simari 2017 en Docker local) y está validado contra una
réplica independiente: interfaz = batería 18/18 en cinco perfiles para productos y
real = réplica 126/126 en tres snapshots para publicaciones. La publicación del
ranking está protegida por una compuerta (`LAF_API_RESULTS_VALIDATED`, ver
«Evaluadores»). El `MockRecommendationEvaluator` y los fixtures existen sólo como
infraestructura de pruebas y de la demostración offline.

## Instalación en Windows / PowerShell

Desde la raíz, en una descarga nueva (no recrear un entorno existente):

```powershell
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r .\webapp\requirements.txt
Set-Location .\webapp
npm.cmd ci
npm.cmd run build
.\..\venv\Scripts\python.exe manage.py migrate
```

No es necesario configurar Supabase para usar la demostración, pero el respaldo
con el fixture (`fixtures/<dominio>.json`, valores ilustrativos que no salen de
`laf-api`) debe pedirse explícitamente con `ALLOW_DEMO_FIXTURE=1`. Sin esa
variable, si Supabase no está configurado o no responde, la portada muestra «No se
pudo conectar con la base de datos» en lugar de datos de demostración. En el
despliegue (Railway) la variable debe quedar sin definir. La suite de tests la
habilita por defecto. Si se desea un archivo local de variables:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Django carga primero `webapp/.env` y después el `.env` de la raíz del pipeline,
sin reemplazar variables que ya hayan sido establecidas en PowerShell o por el
entorno de despliegue. Con Supabase configurado, la aplicación lee el catálogo,
el alcance humano de `products_seed`, los precios limpios y el trust agregado.
Los productos con `analysis_status=excluded` no entran al programa LAF 1.

## Ejecución

Desde `webapp/`, donde terminó la instalación:

```powershell
.\..\venv\Scripts\python.exe manage.py runserver
```

Abrir `http://127.0.0.1:8000/`.

Durante el desarrollo visual se pueden recompilar los assets en otra terminal:

```powershell
Set-Location .\webapp
npm.cmd run watch
```

Node/Vite sólo compila Tailwind, HTMX y Cytoscape. Toda la lógica del
recomendador y del servidor permanece en Python.

## Pruebas

```powershell
Set-Location .\webapp
.\scripts\check.ps1
```

Este comando ejecuta el chequeo de Django, todas las pruebas y la compilación
de los recursos del navegador. Las pruebas cubren contratos, valores nulos,
formularios, evaluador simulado,
generación/exportación de los pasos 08 y 10, exclusión de productos, recorte del grafo,
endpoints HTMX, recorrido LAF 1 → LAF 2 y funcionamiento sin Supabase.

## Arquitectura

```text
recommender/
├─ domain/       contratos tipados de evaluación
├─ services/     evaluadores y casos de uso
├─ repositories/ dominios, fixtures y adaptador Supabase
├─ graph/        contratos, normalización y recorte BFS
├─ web/          formularios, vistas, estado del recorrido y exportaciones
├─ templates/    presentación en español
├─ static/       assets compilados
└─ tests/        pruebas unitarias y de integración
```

`RecommendationSession` guarda el estado importante en SQLite. Las vistas no
contienen fórmulas LAF, consultas complejas ni llamadas a scripts por
`subprocess`. `services/laf1_programs.py` y `services/laf2_programs.py`
reutilizan directamente las funciones de 08/10 y registran el hash de la
metodología congelada.


## Configuración multidominio

Los aspectos se leen en UTF-8 desde `../config/domains/<dominio>.json`. Los
archivos `.draft.json` y `.curation_rules.json` no se ofrecen como dominios
ejecutables. Para añadir un dominio se agrega su perfil y, durante la
demostración, un fixture opcional en `fixtures/<dominio>.json`; si falta, se usa
`fixtures/default.json`.

## Evaluadores

- `RecommendationEvaluator`: interfaz estable.
- `LAFHttpRecommendationEvaluator`: **evaluador HTTP de datos reales.** Genera un
  programa por característica activa con los constructores de 08/10, lo traduce al
  contrato JSON de `POST /api/graph`, ejecuta `laf-api` una vez por característica
  y combina los resultados con la suma ponderada (`post_laf_multicriteria_v1`).
- `LAF1PreparedRecommendationEvaluator`: genera y conserva los programas sin
  evaluar; es lo que se ve con la compuerta en `0`.
- `MockRecommendationEvaluator`: fixture determinista, estado `mock`. Sólo para
  las pruebas y la demostración offline; ninguna pantalla con snapshot real lo usa.
- `PythonLAFEvaluator`: punto de extensión no implementado.

Configuración de evaluación real local (adaptar el archivo elegido según la precedencia anterior):

```text
RECOMMENDATION_EVALUATOR=recommender.services.evaluators.LAFHttpRecommendationEvaluator
LAF_API_URL=http://127.0.0.1:8088/api/graph
LAF_API_RESULTS_VALIDATED=1
```

`LAF_API_RESULTS_VALIDATED` es una compuerta metodológica, no una opción de
conectividad. Con `0` (el valor de `.env.example`, deliberadamente conservador) la
aplicación genera y guarda los programas pero no publica ningún ranking: la
pantalla dice que el catálogo no puede ordenarse todavía. Con `1` publica el
ranking del evaluador HTTP. La compuerta se abrió el 2026-08-28, después de validar
soporte, agregación, conflicto, empates y los casos completos LAF1 y LAF2 contra
una réplica independiente,
y volvió a verificarse tras el recongelado del 2026-09-10 (interfaz = batería
18/18 en cinco perfiles; real = réplica 126/126). Quien clone el repositorio debe
ponerla en `1` a sabiendas, después de levantar `laf-api`.


## Auditoría de preferencias

El auditor vuelve a ejecutar LAF 1 sin modificar el recorrido guardado y compara
ganador, top 3, posiciones y estabilidad frente a cambios pequeños:

```powershell
.\..\venv\Scripts\python.exe manage.py audit_preferences --flow UUID --mode standard
```

Los modos disponibles son `quick`, `standard`, `pairwise` y `exhaustive`. Antes
de una corrida cartesiana conviene calcular su tamaño:

```powershell
.\..\venv\Scripts\python.exe manage.py audit_preferences --flow UUID --mode exhaustive --levels ui --dry-run
```

`ui` usa los cuatro valores de la interfaz (`0`, `0.33`, `0.67`, `1`) y
`binary` sólo los extremos. El modo exhaustivo exige además
`--confirm-exhaustive` y respeta `--max-cases` para evitar millones de llamadas
accidentales. Cada corrida produce `resumen.md`, `casos.csv` y
`auditoria_preferencias.json` bajo `reports/preference_audits/`.

## Auditoría de calidad de la recomendación

La sensibilidad no demuestra que el ganador sea correcto. La auditoría de
calidad ejecuta perfiles interpretables —neutral, cada aspecto por separado y
cada dimensión experta— y compara el ranking LAF con una línea base que usa
solamente la evidencia inicial, antes de aplicar reglas y operadores:

```powershell
.\..\venv\Scripts\python.exe manage.py audit_recommendation_quality --flow UUID
```

La línea base suma `confianza × preferencia` para evidencia positiva y resta
el mismo valor para la negativa. Sirve para localizar dónde la estructura LAF
cambia el orden sugerido por la evidencia directa; no es una verdad de
referencia. La corrida genera `resumen.md`, `casos.csv`,
`auditoria_calidad.json` y `casos_para_revision.json` bajo
`reports/recommendation_quality/`.

Para medir exactitud, una persona debe completar en
`casos_para_revision.json` los identificadores esperados, justificar la
decisión y cambiar `review_status` de `pending` a `approved`. Después se repite:

```powershell
.\..\venv\Scripts\python.exe manage.py audit_recommendation_quality `
  --flow UUID `
  --expectations ruta\casos_para_revision.json
```

El informe sólo calcula acierto sobre casos aprobados. Nunca adopta el propio
ganador de LAF como etiqueta esperada.

## Comparación experimental de modelos de preferencia

Para estudiar la contaminación de confianza desde aspectos desactivados se
compararon cuatro modelos de manera reproducible:

1. configuración actual;
2. exclusión de hechos cuya preferencia es cero;
3. confianza operativa ponderada por la preferencia;
4. decisión multicriterio normalizada después de ejecutar LAF por aspecto.

La comparación se ejecuta con un recorrido existente y un archivo de casos
aprobados:

```powershell
.\..\venv\Scripts\python.exe manage.py compare_preference_models `
  --flow UUID `
  --expectations ruta\casos_propuestos_para_aprobar.json
```

Cada corrida genera `resumen.md`, `casos_modelos.csv` y
`experimento_preferencias.json` bajo `reports/preference_models/`. El informe
marca explícitamente que los casos actuales son de desarrollo con revisión
humana asistida. La selección final exige casos nuevos revisados sin mostrar
las salidas de los modelos.

La alternativa seleccionada para LAF1 es
`post_laf_multicriteria_v1`: LAF evalúa cada aspecto activo y el ranking final
usa `Σ(peso normalizado × resultado LAF del aspecto)`. Un peso 0 desactiva el
aspecto; 0,33 y 0,67 continúan participando. La corrida completa se conserva
como traza técnica. Puede reproducirse temporalmente el comportamiento anterior
con `LAF_PRODUCT_DECISION_MODEL=legacy_min` y reiniciando Django.


## Seguridad y datos

`SUPABASE_KEY` sólo se lee en el servidor. No forma parte de las plantillas, el
JavaScript, el programa exportado ni las respuestas del grafo. Todas las
consultas de la generación real incluyen `dataset_key`; el alcance se filtra por
las decisiones humanas de `products_seed`. La demostración funciona offline.

## Limitaciones actuales

- El ranking de productos reales se publica únicamente con el evaluador HTTP y
  `LAF_API_RESULTS_VALIDATED=1`; requiere `laf-api` corriendo.
- Latencia medida en máquina local (`../validacion_desempeno/RESULTADOS.md`):
  1,85 s por consulta de productos (p95 2,26), 87 % en lectura de Supabase; el
  flujo web completo hasta ver el ranking, ≈3 s. No hay caché ni medición en
  despliegue remoto.
- La calidad del orden se evaluó con una jueza ciega (n = 1, la autora) y con
  bootstrap de reseñas (documentados en la memoria del trabajo final);
  no hay validación con usuarios ni panel de anotadores externos.
- El enlace a cada publicación se construye desde `item_id`
  (`articulo.mercadolibre.com.mx/MLM-…`) porque el relevamiento no guardó el
  permalink; si Mercado Libre cambia el esquema de URL, deja de resolver (ADR-006).
- Quedan 8 hallazgos de usabilidad de severidad 1–2 declarados en la memoria del trabajo final.
- `PythonLAFEvaluator` no está implementado; el fixture del mock sólo incluye un
  fragmento pequeño del grafo.
- No hay autenticación ni evaluación de concurrencia documentada aquí. La demostración remota es distinta de las mediciones locales; no inferir su disponibilidad actual de estos resultados.
- La exportación PNG se realiza en el navegador sobre el subgrafo visible.
