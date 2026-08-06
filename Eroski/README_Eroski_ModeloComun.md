# Eroski Modelo Comun

Esta carpeta contiene los archivos separados para reproducir la extraccion de Eroski en la categoria Frescos > Platos preparados.

## Archivos

- `eroski_platos_preparados_full.py`: extractor principal. Recorre la categoria publica paginada de Eroski, entra en fichas de producto y genera `eroski_modelo_comun.csv`.
- `eroski_modelo_comun.csv`: salida en formato modelo comun, separada por `;`.
- `crear_xlsx_desde_csv.py`: convierte el CSV anterior en `eroski_modelo_comun.xlsx`.
- `eroski_modelo_comun.xlsx`: version Excel directa del resultado.

## Orden de uso

1. Ejecutar `eroski_platos_preparados_full.py`.
2. Ejecutar `crear_xlsx_desde_csv.py` si se quiere abrir el resultado como Excel independiente.

## Nota

No modifica el Excel principal ni las consultas de Carrefour. La fuente usada es HTML publico de categoria y ficha: `https://supermercado.eroski.es/es/supermercado/2059698-frescos/2059769-platos-preparados/`.
