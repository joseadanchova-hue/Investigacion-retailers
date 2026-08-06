# Aldi Modelo Comun

Esta carpeta contiene los archivos separados para reproducir la extraccion de Aldi en la categoria Platos preparados y pizza > Platos preparados calientes.

## Archivos

- `aldi_platos_preparados_full.py`: extractor principal. Descarga la pagina de categoria publica de Aldi y genera `aldi_modelo_comun.csv`.
- `aldi_modelo_comun.csv`: salida en formato modelo comun, separada por `;`.
- `crear_xlsx_desde_csv.py`: convierte el CSV anterior en `aldi_modelo_comun.xlsx`.
- `aldi_modelo_comun.xlsx`: version Excel directa del resultado.

## Orden de uso

1. Ejecutar `aldi_platos_preparados_full.py`.
2. Ejecutar `crear_xlsx_desde_csv.py` si se quiere abrir el resultado como Excel independiente.

## Enfoque tecnico

`www.aldi.es` es una app Next.js (Magnolia CMS + busqueda Algolia). La pagina de categoria
(`https://www.aldi.es/productos/platos-preparados-y-pizza/platos-preparados-calientes.html`)
incrusta en un `<script id="__NEXT_DATA__">` el estado inicial completo de Algolia
InstantSearch (`algoliaConfig.indexName: "an_prd_es_es_pen_products2"`, filtro
`categoryIDs:platos-preparados-calientes`, `hitsPerPage: 1000`), con **todos** los
productos de esa subcategoria ya incluidos como JSON en el propio HTML. No hace falta
ninguna peticion adicional para el listado: basta con descargar el HTML crudo via
`urllib` (no via herramientas que conviertan a markdown, que eliminan el `<script>`) y
extraer el JSON con una expresion regular.

Cada "hit" del listado aporta: `name`, `productSlug`, `objectID` (SKU numerico),
`brandName`, `currentPrice.priceValue`, `currentPrice.basePrice` (precio por kg/ud),
`salesUnit` (formato/peso), `shortDescription`/`longDescription`, `isAvailable`,
`assets` (imagenes), `hierarchicalCategories` y `productReferences` (numero de articulo
interno `KVArticleNumber`). Todo eso se usa para rellenar las columnas de nivel-listado
del modelo comun (nombre, precio, formato, marca, imagen, descripcion, url).

### Limitacion: sin datos de ficha de producto (nutricion / EAN / ingredientes / alergenos)

Se investigo la pagina de ficha de producto (`https://www.aldi.es/producto/<slug>.html`)
en busca de una API de detalle mas rica:

- El propio `__NEXT_DATA__` de la ficha incluye un array `props.pageProps.apiData` con
  una entrada `PRODUCT_DETAIL_GET` (identificada tambien en el bundle JS
  `pages/product-detail/[product]-*.js`, que referencia la clave de API
  `PRODUCT_DETAIL_GET`), consultada por `objectID`/SKU.
- Sin embargo, el payload de esa entrada (`res.products[0]`) contiene exactamente los
  mismos campos que ya vienen en el listado (nombre, precio, `salesUnit`, marca,
  imagenes, descripciones, categorias) -- **no** incluye nutricion, EAN, ingredientes
  ni alergenos.
- Se probaron ademas varios patrones de endpoint REST plausibles
  (`/api/product/<id>`, `/api/products/<id>`, `/rest/es/v1/products/<id>`,
  `/api/nutrition/<id>`, variantes con el `variantID` largo tipo GTIN
  `600008224276200`), todos devolvieron 404 o redirecciones sin contenido util.

Con esfuerzo acotado no se encontro una API publica que exponga esos datos, asi que este
scraper **no** hace ninguna peticion por producto: solo procesa el JSON de listado y deja
en blanco `ean`, `ingredients`, `allergens`, `storage_instructions`,
`usage_instructions`, `supplier_name`, `origin`, `legal_name`, `nutrients_text` y todas
las columnas `*_100g`. Este es el mismo patron de fallback valido ya usado en este repo
cuando la ficha de producto de un retailer no expone esos datos publicamente: se rellenan
solo los campos de nivel-listado y el resto queda pendiente de enriquecimiento manual/LLM
fuera de este repo.

## Filtro V-gama

Aplica el mismo filtro de exclusion por nombre que el resto de scrapers del repo
(ensaladas, gazpachos, salmorejos, ajoblancos, kombuchas, batidos, smoothies, zumos,
caldos, bebidas, cremas de verduras/etc.), descartando esos productos antes de generar
la fila de salida.

## Nota

No modifica ningun otro retailer ni el Excel maestro de Carrefour. La fuente usada es el
HTML publico de categoria de Aldi:
`https://www.aldi.es/productos/platos-preparados-y-pizza/platos-preparados-calientes.html`.
