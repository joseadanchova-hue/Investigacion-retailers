# Investigación Retailers — Ready Meals

Scrapers específicos por retailer para productos de "platos preparados" en supermercados
españoles, más un pipeline automatizado que ejecuta todos los scrapers soportados,
acumula los resultados en una base de datos SQLite (`data/readymeals.db`) como histórico
semanal, y regenera un export en Excel (`data/readymeals_export.xlsx`) listo para
consumir desde Power BI o abrir directamente.

Ver [`EXPLICACION_PROYECTO.md`](EXPLICACION_PROYECTO.md) para una descripción narrativa
completa (en español) y [`CLAUDE.md`](CLAUDE.md) para la guía técnica orientada a
agentes/desarrollo.

## Estructura del repo

Cada retailer vive en su propia carpeta de nivel superior, autocontenida (sin imports
cruzados entre carpetas):

| Carpeta | Scraper | En pipeline automático |
|---|---|---|
| `Eroski/` | `eroski_platos_preparados_full.py` | Sí |
| `Carrefour/` | `carrefour_comida_preparada_full.py` | Sí |
| `Mercadona/` | `mercadona_platos_preparados_full.py` | Sí |
| `Consum/` | `consum_platos_preparados_full.py` | Sí |
| `Dia/` | `dia_platos_preparados_full.py` | Sí |
| `Alcampo/` | `alcampo_platos_preparados_full.py` | Sí |
| `ElCorteIngles/` | `eci_platos_preparados_full.py` | Sí |
| `Aldi/` | `aldi_platos_preparados_full.py` | No (manual) |
| `Froiz/` | `froiz_platos_preparados_full.py` | No (manual) |
| `Masymas/` | `masymas_platos_preparados_full.py` | No (manual) |

Los retailers marcados "En pipeline automático" están registrados en
`pipeline/config.py` (`RETAILERS`) y se ejecutan cada vez que corre
`pipeline/orchestrator.py`. Aldi, Froiz y Masymas tienen scrapers funcionales pero se
ejecutan manualmente por ahora — añadir una entrada en `pipeline/config.py` es
suficiente para incorporarlos al pipeline automático (no requiere código adicional).

Otras carpetas relevantes:

- `pipeline/` — orquestador, esquema de base de datos y exportador Excel (código
  determinista, sin llamadas a IA).
- `data/` — base de datos SQLite y export Excel generados por el pipeline (no
  versionados; ver `.gitignore`).
- `logs/` — logs por ejecución del pipeline (no versionados).

## Requisitos

```
pip install -r requirements.txt
```

Los scrapers en sí solo usan la librería estándar de Python (`urllib`, `html.parser`,
`re`, `csv`); `openpyxl` se usa para generar los ficheros `.xlsx`.

## Uso

### Pipeline automatizado (recomendado)

```
python pipeline/orchestrator.py
```

Ejecuta cada scraper soportado, carga los resultados exitosos en
`data/readymeals.db` (tabla `snapshots`, histórico acumulativo) y regenera
`data/readymeals_export.xlsx`. Pensado para lanzarse semanalmente vía Task Scheduler
de Windows apuntando a `run_pipeline.bat` (en la raíz del repo).

### Scrapers individuales (manual)

Desde la carpeta del retailer correspondiente:

```
python <retailer>_platos_preparados_full.py   # scrapea -> <retailer>_modelo_comun.csv
python crear_xlsx_desde_csv.py                # csv -> xlsx (previsualización standalone)
```

## Configuración sensible

`Carrefour/carrefour_comida_preparada_full.py` requiere una cookie de sesión válida
para autenticar las peticiones. Se lee de la variable de entorno `CARREFOUR_COOKIE`
(con un valor vacío por defecto que no funcionará contra el sitio real). Ejemplo en
PowerShell:

```
$env:CARREFOUR_COOKIE = "session_id=...; JSESSIONID=...; JSESSIONID_ALI11=...; PROFILE_ID=..."
python carrefour_comida_preparada_full.py
```

Esta cookie caduca periódicamente; cuando el scraper empiece a fallar con errores HTTP,
hay que capturar una cookie de sesión nueva desde el navegador y actualizar la variable
de entorno (nunca hardcodearla en el script ni comitearla).

## Notas

- No hay build system ni tests automatizados en este repo.
- Los datos generados (CSV/XLSX por retailer, `data/*.db`, `data/*.xlsx`, `logs/`,
  cachés `_*_tmp/`) están excluidos de git — ver [`.gitignore`](.gitignore). Este repo
  versiona código, no datos de producto ni precios.
