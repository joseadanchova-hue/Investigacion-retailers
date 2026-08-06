# Masymas Modelo Comun

Esta carpeta contiene los archivos separados para reproducir la extraccion de Masymas en la categoria Refrigerado y congelado > Platos preparados.

## Archivos

- `masymas_platos_preparados_full.py`: extractor principal. Recorre la categoria publica paginada de Masymas, entra en fichas de producto y genera `masymas_modelo_comun.csv`.
- `masymas_modelo_comun.csv`: salida en formato modelo comun, separada por `;`.
- `crear_xlsx_desde_csv.py`: convierte el CSV anterior en `masymas_modelo_comun.xlsx`.
- `masymas_modelo_comun.xlsx`: version Excel directa del resultado.

## Orden de uso

1. Ejecutar `masymas_platos_preparados_full.py`.
2. Ejecutar `crear_xlsx_desde_csv.py` si se quiere abrir el resultado como Excel independiente.

## Notas especificas de Masymas

- La fuente usada es HTML publico de categoria y ficha: `https://www.supermasymasonline.com/refrigerado-y-congelado/platos-preparados/`. El sitio corresponde al escaparate regional de Asturias (dominio `supermasymasonline.com`); no requiere login ni cookie de sesion, y no se ha observado Cloudflare/CAPTCHA.
- La tienda usa Salesforce Commerce Cloud (Demandware). La pagina de categoria trae un bloque `<script type="application/ld+json">` de tipo `ItemList` con las URLs de producto de esa pagina (24 por pagina). La paginacion adicional se resuelve llamando al endpoint interno de grid `on/demandware.store/Sites-Masymas-Site/es_ES/Search-UpdateGrid?cgid=0303&start=N&sz=24`, donde `cgid=0303` es el id de categoria de "Platos preparados" y `N` es el offset (0, 24, 48, ...) hasta cubrir el total de resultados anunciado en la propia pagina ("153 resultados").
- La ficha de producto tambien incluye un bloque JSON-LD `Product` (`name`, `description`, `sku`, `brand`, `offers.price`) que se usa como fuente principal para nombre, descripcion, marca y precio; es mas fiable que el HTML visual.
- El precio por kg/litro se lee del texto "El kilo le sale a X €" / "El litro le sale a X €" (clase `conversion-factor`) y se guarda en `reference_price`/`reference_format`.
- Ingredientes, alergenos, instrucciones de conservacion y nombre del fabricante viven en bloques con la clase `title-green-product-info` seguidos del contenido; el texto de esas etiquetas viene HTML-escapado (`&oacute;`, `&eacute;`), por lo que el extractor decodifica las entidades antes de comparar el nombre de la etiqueta en vez de buscar el acento literal en el HTML crudo.
- La informacion nutricional aparece en una tabla simple (`<table>` dentro de `div#nutritionalInfo`) con filas `Valor energetico` (aparece dos veces: kJ y kcal, diferenciadas por el sufijo del valor), `Grasas`, `Grasas saturadas`, `Hidratos de Carbono`, `Azucares`, `Proteinas`, `Sal`, `Fibra`.
- No se encontro EAN en la ficha de producto publica; la columna `ean` queda siempre vacia (igual convencion que en Eroski/Carrefour cuando el dato no esta disponible).
- No todas las fichas incluyen las pestanas de "Detalles" (ingredientes/alergenos/conservacion) o "Informacion nutricional" — algunos productos simples (p. ej. masas, algunos congelados) solo muestran precio/descripcion. En esos casos las columnas correspondientes quedan vacias sin que eso cuente como fallo del scraper.
- El aviso legal de codigo postal opcional que muestra el sitio no bloquea la navegacion ni el precio mostrado, por lo que se ignora (no se gestionan cookies ni cabeceras especiales mas alla de un User-Agent de navegador normal, igual que en Eroski).

## Nota

No modifica el Excel principal ni las consultas de Carrefour/Eroski. `pipeline/config.py` no ha sido tocado por este cambio; el registro de Masymas en el pipeline automatizado se gestiona en una tarea aparte.
