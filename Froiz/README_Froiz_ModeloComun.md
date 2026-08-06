# Froiz Modelo Comun

Esta carpeta contiene los archivos separados para reproducir la extraccion de Froiz en la categoria Alimentacion > Platos preparados.

## Archivos

- `froiz_platos_preparados_full.py`: extractor principal. Llama a la API JSON publica de Froiz (listado + ficha de producto) y genera `froiz_modelo_comun.csv`.
- `froiz_modelo_comun.csv`: salida en formato modelo comun, separada por `;`.
- `crear_xlsx_desde_csv.py`: convierte el CSV anterior en `froiz_modelo_comun.xlsx`.
- `froiz_modelo_comun.xlsx`: version Excel directa del resultado.

## Orden de uso

1. Ejecutar `froiz_platos_preparados_full.py`.
2. Ejecutar `crear_xlsx_desde_csv.py` si se quiere abrir el resultado como Excel independiente.

## Como funciona (caso A: API JSON descubierta)

A diferencia de lo que sugeria una inspeccion superficial inicial (tarjetas de producto sin `<a href>`, sin `data-id` y sin JSON embebido obvio en el HTML crudo de `https://supermercado.froiz.com/alimentacion/platos-preparados`), la pagina si tiene una fuente de datos estructurada aprovechable:

- La pagina es una SPA Nuxt.js que sirve `window.__NUXT__` en un formato de "argumentos de funcion" minificado (`(function(a,b,c,...){...})(v1,v2,v3,...)`), que **no** es JSON valido y no merece la pena parsear manualmente.
- En cambio, los bundles JS de la propia pagina (`/_nuxt/*.js`) llaman a una API REST publica y separada en `https://servicios.froiz.com`, descubierta buscando literales `/api/` dentro de esos bundles:
  - `GET https://servicios.froiz.com/api/products?section=platos-preparados&page=<n>&size=<n>`
    Devuelve el listado paginado (`products`) y estadisticas de paginacion (`stats.totalPages`, `stats.productTotal`). Confirmado: 108 productos, 6 paginas de tamano 20 en el momento de escribir esto (puede variar ligeramente con el catalogo).
  - `GET https://servicios.froiz.com/api/products/<product_id>`
    Devuelve la ficha completa: nutricion (`nutritional_info`, mas `energy_KJ`/`energy_Kcal` en `details`), `ingredients_and_allergens`, `allergens`, `conservation_conditions` (conservacion), `howto_use` (modo de empleo), `operator_business_name` (fabricante/distribuidor), `country_of_origin`, marca, denominacion legal, etc.
- No hace falta cookie de sesion ni codigo de tienda para estas lecturas publicas; solo cabeceras HTTP normales (User-Agent, Accept, Accept-Language).
- `section=platos-preparados` como unico filtro es suficiente y equivalente a combinar `category=alimentacion&section=platos-preparados`.

Este patron es analogo al de Carrefour (`fetch_json`/`extract_state`), salvo que aqui la API es un endpoint REST limpio en vez de un JSON embebido en el HTML.

## Campos NO disponibles

- `ean`: el campo `details.code` de la API viene `null` en todos los productos probados de esta categoria. Se deja en blanco; no es un fallo del scraper, es que Froiz no publica el EAN en esta API.
- Las columnas de clasificacion manual (`tipo_plato`, `subtipo_plato`, `cocina`, etc.) se dejan en blanco igual que en Eroski/Carrefour, para enriquecimiento posterior fuera de este repo.

## Nota

No modifica el Excel principal ni las consultas de Eroski/Carrefour. La fuente usada es la API publica JSON de Froiz: `https://servicios.froiz.com/api/products` (listado) y `https://servicios.froiz.com/api/products/<id>` (ficha), enlazadas desde `https://supermercado.froiz.com/alimentacion/platos-preparados`.
