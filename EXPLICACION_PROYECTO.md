# Explicación del proyecto: Ready Meals Spain — Modelo Común

## ¿Qué es esto?

Este proyecto recopila datos de productos de **"platos preparados"** (ready meals / comida preparada) de varios **supermercados españoles**, normaliza esa información en un esquema común ("modelo común") y la consolida en un **Excel maestro** para su análisis (precios, información nutricional, categorización de tipo de plato, etc.).

Es la base de datos que alimenta un informe de precios y nutrición de la gama de platos preparados en España, comparando varios retailers.

Actualmente hay dos retailers implementados, cada uno en su propia carpeta:

- **`Eroski/`**
- **`Carrefour/`**

Cada carpeta es independiente y autocontenida: no comparten código, solo el mismo esquema de columnas y el mismo flujo de trabajo.

---

## Flujo de trabajo general (por retailer)

Cada retailer sigue el mismo patrón de 4 pasos, aunque no todos tienen implementados los 4:

1. **Scraping** — un script `*_full.py` descarga la web pública del supermercado (categoría "Platos preparados") y extrae los datos de cada producto → genera un CSV con el "modelo común".
2. **Conversión a Excel independiente** — `crear_xlsx_desde_csv.py` convierte ese CSV en un `.xlsx` suelto, solo para poder abrirlo/revisarlo fácilmente.
3. **Integración en el Excel maestro** — `update_loaded_tables_zip.py` (solo Carrefour) inserta/actualiza las filas de ese retailer dentro del Excel grande `Prueba Scrapping Mercadona - vfinal.xlsx`, en su hoja específica y en la hoja combinada `Retailers_Final`.
4. **Verificación** — `verify_loaded_counts.py` (solo Carrefour) comprueba que el número de filas cargadas en el Excel maestro coincide con lo esperado.

Eroski de momento solo tiene los pasos 1 y 2 (no tiene scripts de integración/verificación en el Excel maestro).

---

## Carpeta `Eroski/`

Extrae productos de la categoría pública **Frescos > Platos preparados** de Eroski (`supermercado.eroski.es`).

- **`eroski_platos_preparados_full.py`**: el scraper principal.
  - Descarga la(s) página(s) de listado de categoría (paginadas).
  - Extrae los enlaces a cada ficha de producto.
  - Entra en cada ficha (en paralelo, con varios "workers" simultáneos) y extrae: nombre, marca, precio, tamaño/formato, ingredientes, información nutricional (energía, grasas, azúcares, proteínas, sal, fibra...), instrucciones de conservación y uso, proveedor, etc.
  - Guarda una copia local (caché) de cada página HTML descargada en `_eroski_tmp/`, para no tener que volver a descargarla si se relanza el script (ahorra tiempo y no satura la web).
  - Si algo falla al leer un producto, reintenta varias veces y si aun así falla, lo anota en la columna `observaciones` en vez de perder la fila.
  - Guarda el resultado final en `eroski_modelo_comun.csv` (separado por `;`).
- **`eroski_modelo_comun.csv`**: el resultado del scraping, un producto por fila.
- **`crear_xlsx_desde_csv.py`**: convierte ese CSV en `eroski_modelo_comun.xlsx` para poder abrirlo directamente en Excel.
- **`eroski_modelo_comun.xlsx`**: versión Excel ya generada.
- **`_eroski_tmp/`**: caché de páginas HTML descargadas (categoría + fichas de producto), usada internamente por el scraper.

---

## Carpeta `Carrefour/`

Mismo concepto pero para la categoría de comida preparada de **Carrefour**.

- **`carrefour_comida_preparada_full.py`**: scraper principal, equivalente al de Eroski pero adaptado a la web de Carrefour. Genera `carrefour_modelo_comun.csv` (136 productos en la última ejecución conocida).
- **`carrefour_modelo_comun.csv`**: resultado del scraping.
- **`crear_xlsx_desde_csv.py`**: convierte el CSV en `carrefour_modelo_comun.xlsx` (versión Excel suelta).
- **`carrefour_modelo_comun.xlsx`**: versión Excel ya generada.
- **`Prueba Scrapping Mercadona - vfinal.xlsx`**: el **Excel maestro** del proyecto. Contiene (al menos) dos hojas relevantes:
  - `Carrefour_ModeloComun`: solo los datos de Carrefour.
  - `Retailers_Final`: la tabla combinada con los datos de **todos** los retailers juntos (Carrefour, y potencialmente otros como Mercadona/Eroski si se han cargado).
- **`update_loaded_tables_zip.py`**: script que **inserta los datos nuevos de Carrefour dentro del Excel maestro** sin romper el formato existente:
  - Hace primero una **copia de seguridad** con fecha/hora del Excel maestro antes de tocar nada.
  - En vez de reescribir el Excel con una librería normal (que perdería estilos y formato), abre el `.xlsx` como si fuera un **archivo ZIP** (que es lo que realmente es un `.xlsx` por dentro) y edita quirúrgicamente solo el XML de las hojas afectadas.
  - Quita las filas antiguas de Carrefour y pone las nuevas (del CSV recién generado), tanto en la hoja `Carrefour_ModeloComun` como en `Retailers_Final`.
  - Mantiene los estilos de celda (colores, formato) copiándolos de las filas existentes.
- **`verify_loaded_counts.py`**: comprueba, después de la integración, que el número de filas de Carrefour en el Excel maestro es el esperado (evita cargas incompletas o duplicadas).

---

## El "Modelo Común" (esquema de columnas compartido)

Todos los scrapers generan un CSV con **las mismas columnas**, para que los datos de cualquier retailer se puedan comparar y combinar directamente. Incluye, entre otras:

- **Identificación**: `retailer`, `product_id`, `ean`, `product_name`, `brand`, `product_url`.
- **Categoría**: `parent_category_name`, `subcategory_name`, `category_path`, `categories_text`.
- **Formato/tamaño**: `packaging`, `unit_size`, `size_format`, `pack_size`, `unit_name`.
- **Precio**: `unit_price`, `list_price`, `reference_price`, `bulk_price`, `price_decreased`, `previous_unit_price`.
- **Info nutricional** (por 100g): `energy_kcal_100g`, `fat_g_100g`, `sat_fat_g_100g`, `carbs_g_100g`, `sugars_g_100g`, `protein_g_100g`, `salt_g_100g`, `fiber_g_100g`, además de `nutrients_text` (texto bruto tal cual aparece en la web).
- **Descripción del producto**: `ingredients`, `allergens`, `storage_instructions`, `usage_instructions`, `supplier_name`, `origin`.
- **Clasificación cualitativa** (pensada para rellenarse después, manualmente o con ayuda de un LLM, no la rellena el scraper): `tipo_plato`, `subtipo_plato`, `cocina`, `base_carbohidrato`, `proteina_principal`, `proteina_secundaria`, `vegetales_clave`, `salsa_o_sazonado`, `nivel_conveniencia`, `tipo_conservacion`, `posicionamiento`, `healthy_vs_indulgente`.
- **Metadatos**: `capture_datetime` (cuándo se capturó el dato), `observaciones` (notas, errores, o enlace a imagen del producto).

Estas últimas columnas de clasificación cualitativa son el "gancho" para el informe de I+D: una vez tienes el dato bruto (precio + nutrición + ingredientes), alguien (o un agente/LLM) las rellena para poder segmentar y comparar la gama de platos preparados por tipo de cocina, proteína principal, nivel de "indulgencia" saludable, etc.

---

## ¿Qué NO hace este proyecto (todavía)?

- No tiene tests automatizados ni pipeline de build/CI.
- No hay un único comando que ejecute todo de punta a punta; cada retailer se ejecuta manualmente, paso a paso.
- Eroski todavía no tiene los scripts de integración/verificación en el Excel maestro (solo Carrefour).
- La clasificación cualitativa (tipo de plato, cocina, etc.) no se genera automáticamente por estos scripts — es un paso posterior, fuera de este repositorio.

---

## Resumen en una frase

Es un **conjunto de scrapers en Python** (uno por supermercado) que descargan y normalizan datos de productos de platos preparados en un **CSV común**, y unos scripts auxiliares que **integran esos datos en un Excel maestro** compartido para poder analizarlos y compararlos entre retailers.
