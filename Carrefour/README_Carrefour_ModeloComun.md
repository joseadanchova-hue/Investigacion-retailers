# Carrefour Modelo Comun

Esta carpeta contiene solo los archivos necesarios para reproducir el resultado de Carrefour comida preparada y, si hace falta, volver a insertarlo en el Excel final.

## Archivos imprescindibles

- `carrefour_comida_preparada_full.py`: extractor principal. Descarga la categoria publica de Carrefour, entra en las fichas de producto y genera `carrefour_modelo_comun.csv`.
- `carrefour_modelo_comun.csv`: resultado en formato modelo comun, separado por `;`. Contiene 136 productos.
- `crear_xlsx_desde_csv.py`: convierte el CSV anterior en `carrefour_modelo_comun.xlsx`.
- `carrefour_modelo_comun.xlsx`: version Excel directa del resultado.

## Archivos para integrarlo en el Excel final

- `Prueba Scrapping Mercadona - vfinal.xlsx`: copia del Excel final ya actualizado.
- `update_loaded_tables_zip.py`: inserta/reemplaza las filas de Carrefour en `Carrefour_ModeloComun` y reconstruye `Retailers_Final` usando `carrefour_modelo_comun.csv`.
- `verify_loaded_counts.py`: comprueba que el Excel final contiene 136 filas Carrefour en `Carrefour_ModeloComun` y `Retailers_Final`.

## Orden de uso

1. Ejecutar `carrefour_comida_preparada_full.py` para regenerar `carrefour_modelo_comun.csv`.
2. Ejecutar `crear_xlsx_desde_csv.py` si se quiere abrir el resultado como Excel independiente.
3. Ejecutar `update_loaded_tables_zip.py` si se quiere insertar el CSV regenerado en `Prueba Scrapping Mercadona - vfinal.xlsx`.
4. Ejecutar `verify_loaded_counts.py` para comprobar los conteos finales.

## Nota

No se incluyen los scripts de pruebas de Power Query, diagnosticos COM ni backups intermedios porque no son necesarios para reproducir el resultado final.
