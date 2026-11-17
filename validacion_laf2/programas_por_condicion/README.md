# Programas LAF2 por condición de compra

Programas generados el 16 de noviembre de 2026 con el generador del repositorio (`webapp/recommender/services/laf2_programs.py`, que invoca `src/10_laf2_generate.py`) sobre la exportación `datos-v1`, con la configuración congelada del dominio Café (SHA-256 `735f9b0c…`) y el perfil del ejemplo del Capítulo 6: importancia 0,67 en las siete condiciones comerciales, sin límites de presupuesto.

Se generaron para los dos productos de la validación de LAF2 (`validacion_laf2/salidas/unificacion_una_etiqueta/despues/ranking_laf2.json`):

| Carpeta | Producto | Conjunto de datos | Publicaciones |
|---|---|---|---|
| `MLM19566313_mlm_mlm194329_20260528_142014/` | Members Mark Vainilla 1,8 kg | corpus principal | 26 |
| `MLM41148521_mlm_mlm194335_20260805_185233/` | Blasón Espresso molido 400 g | grano y molido | 9 |

Cada carpeta contiene:

- `programa_completo.txt`: programa combinado de respaldo, con dos etiquetas (confianza; preferencia). Se evalúa como precondición y como criterio de desempate; no aporta al puntaje.
- `condicion_<condición>.txt`: un programa independiente por condición (precio, descuento, cuotas, garantía, tienda oficial, factura, envío), con una sola etiqueta (confianza). Son los programas que se envían al motor para obtener el resultado de cada condición; los pesos del usuario se aplican fuera del motor.

Las condiciones sin evidencia en las publicaciones del producto (cuotas, factura y garantía en ambos casos) conservan solo sus dos reglas, sin hechos; la aplicación las excluye del denominador de la combinación.

`indice.json` resume el producto, la cantidad de publicaciones y el número de hechos y reglas de cada programa. Las cantidades de hechos por condición coinciden con las publicaciones que obtienen puntaje en esa condición en el registro de validación citado.
