# Recomendador argumentativo LAF

Trabajo Final de Graduación de Ana Paula Machado, Licenciatura en Sistemas de Información (UNSE). Director: Maximiliano C. D. Budán.

El prototipo compara productos a partir de reseñas en español y, después, las publicaciones que ofrecen el producto elegido. Utiliza Labeled Argumentation Frameworks (LAF) para evaluar la evidencia y explicar los resultados. El dominio evaluado es café de Mercado Libre México.

Demostración desplegada: https://extraccion-argumentos-production.up.railway.app/

## Contenido del repositorio

| Carpeta | Contenido |
|---|---|
| `src/` | Pipeline analítico: limpieza de reseñas, extracción de aspectos y polaridades, cálculo de confianza y generación de los programas LAF1 (productos) y LAF2 (publicaciones). Los scripts se numeran en el orden de ejecución. |
| `config/` | Léxico de aspectos, decisiones de auditoría y estructura de reglas congeladas. |
| `database/` | Esquema SQL de la base (Supabase / PostgreSQL) y migraciones. |
| `artifacts_por_dominio/` | Preferencias, programas LAF y reportes generados por el pipeline para cada dominio. |
| `webapp/` | Aplicación web (Django) para declarar preferencias, comparar productos y publicaciones y explorar las explicaciones. Ver `webapp/README.md`. |
| `tests/` | Pruebas del pipeline. |
| `validacion_laf1/salidas/` | Batería de referencia que usan las pruebas de la aplicación. |
| `workflows_n8n/` | Exportaciones de los flujos de n8n que extraen productos, reseñas y descripciones desde la API de Mercado Libre hacia Supabase. |

El motor de evaluación `laf-api` no forma parte de este repositorio: es una implementación existente del formalismo LAF que se integra como servicio HTTP. La versión utilizada está en el fork https://github.com/AnaPaulaMach/LAF (commit `ce69811`).

## Ejecución

Requisitos: Python 3.11, PostgreSQL (Supabase) y el modelo `es_core_news_md` de spaCy.

```bash
pip install -r requirements.txt
python -m spacy download es_core_news_md
```

El entorno exacto de los experimentos está congelado en `requirements-lock.txt`.

Las credenciales se cargan desde variables de entorno (ver `.env.example`); no forman parte del código fuente. Para levantar la aplicación y el evaluador con Docker:

```bash
docker compose up
```

La aplicación incluye fixtures y un evaluador simulado para recorrer la interfaz sin servicios externos. Con el evaluador real levantado, la variable que habilita el ranking real se describe en `webapp/README.md`.

## Datos y reproducibilidad

Los datos de reseñas se almacenan en Supabase y no forman parte del código del repositorio. La exportación completa de las tablas está publicada como Release de este repositorio:

**[Release datos-v1](https://github.com/AnaPaulaMach/recomendador-laf/releases/tag/datos-v1)**: exportación de la base realizada el 16 de noviembre de 2026, un archivo CSV por tabla (UTF-8, con encabezado). Incluye un `README.md` que describe cada archivo, de qué flujo o script proviene y cómo cargarlo. Los archivos de más de 10 MB están comprimidos con gzip (`.csv.gz`).

| Grupo | Archivos |
|---|---|
| Identificación y semilla | `datasets.csv`, `products_seed.csv`, `product_review_decisions.csv` |
| Capa RAW (respuesta de la API de Mercado Libre) | `products_raw.csv.gz`, `items_raw.csv.gz`, `item_descriptions_raw.csv.gz`, `reviews_raw.csv.gz` |
| Capa CLEAN (depuración) | `items_clean.csv`, `reviews_clean.csv.gz` |
| Resultados del pipeline | `review_aspects.csv`, `review_trust.csv`, `product_aspect_trust.csv`, `trust_runs.csv`, `trust_dataset_state.csv` |
| Validación | `review_item_equivalence_audit.csv` (Anexo A) |

La columna `reviewer_id` de `reviews_raw` se eliminó antes de publicar; ningún archivo contiene identificadores de autor.

Para reproducir el pipeline con estos datos: crear una base PostgreSQL con `database/schema.sql`, cargar los CSV con `\copy` (el README del Release muestra el comando) y configurar `SUPABASE_URL` y `SUPABASE_KEY` en `.env`. Los flujos de extracción originales están en `workflows_n8n/`. Los registros de validación (`validacion_*/`) y la inspección heurística (`docs/EVALUACION_HEURISTICA_NIELSEN.md`) son los que cita la memoria del trabajo final.

## Licencia

El código de este repositorio se distribuye bajo la licencia MIT (ver `LICENSE`).

Los datos de productos, publicaciones y reseñas provienen de la API oficial de Mercado Libre y están sujetos a sus términos y condiciones. Se publican únicamente con fines académicos, para la verificación de este trabajo, y no bajo la licencia MIT. Los identificadores de autor de las reseñas se recibieron ofuscados y no se realizó ningún intento de reidentificación.
