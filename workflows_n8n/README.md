# Flujos de extracción (n8n)

Exportaciones de los flujos de n8n que construyen el corpus a partir de la API de Mercado Libre México y lo escriben en las tablas RAW de Supabase. Cada flujo se ejecuta con un disparador manual desde la interfaz de n8n.

| Archivo | Función |
|---|---|
| `WF00_FULL_Build_Dataset_Mas_vendidos.json` | Construye el conjunto de productos del dominio a partir de los más vendidos de la categoría. |
| `WF01_FULL_Extract_Reviews.json` | Extrae las reseñas de cada producto a través de una de sus publicaciones. |
| `WF02_FULL_Extract_Products.json` | Extrae los atributos de productos y publicaciones. |
| `WF03_FULL_Extract_Item_Descriptions.json` | Extrae las descripciones de las publicaciones. |
| `WF98_TFG_Validar_Equivalencia_Reviews.json` | Validación de la equivalencia de reseñas entre publicaciones de un mismo producto (Anexo A de la memoria). |

Para importarlos: n8n → Workflows → Import from file. Las credenciales (OAuth2 de Mercado Libre y cuenta de Supabase) no se incluyen en las exportaciones y deben configurarse en la instancia propia.
