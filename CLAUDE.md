# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A collection of retailer-specific web scrapers for Spanish supermarket "platos preparados" (ready meals) product data, plus an automated pipeline (`pipeline/`) that runs the pipeline-registered scrapers, appends their results as a dated snapshot into a SQLite database (`data/readymeals.db`), regenerates a read-only Excel export (`data/readymeals_export.xlsx`), and is meant to be triggered weekly via Windows Task Scheduler (`run_pipeline.bat`). Power BI connects directly to `data/readymeals.db`; the Excel export is for people who just want to open a file. Each retailer lives in its own self-contained top-level folder — `Eroski/`, `Carrefour/`, `Mercadona/`, `Consum/`, `Dia/`, `Alcampo/`, `ElCorteIngles/`, `Aldi/`, `Froiz/`, `Masymas/` — with no shared package/build system; each folder's scripts run standalone with plain `python`. Of these, `Eroski`, `Carrefour`, `Mercadona`, `Consum`, `Dia`, `Alcampo`, and `ElCorteIngles` are registered in `pipeline/config.py`'s `RETAILERS` list and run automatically every pipeline execution; `Aldi`, `Froiz`, and `Masymas` have complete, working scrapers but are currently run manually only (see each folder's own `README_<Retailer>_ModeloComun.md` where present). See `EXPLICACION_PROYECTO.md` (Spanish) for a fuller narrative description.

Carrefour also has a legacy manual path that merges its CSV into a master Excel workbook (`Carrefour/Prueba Scrapping Mercadona - vfinal.xlsx`, sheet `Retailers_Final`) via raw zip/XML surgery. **Superseded by the pipeline's automatic Excel export** for the weekly flow; left in place only for manual use, not touched by `pipeline/`.

## Commands

### Automated pipeline (recommended)

```
python pipeline/orchestrator.py
```

No manual per-retailer steps required. Each run:
- Clears each pipeline-registered retailer's HTML cache (`_eroski_tmp/`, `_carrefour_tmp/`, `_mercadona_tmp/`, `_consum_tmp/`, `_dia_tmp/`, `_alcampo_tmp/`, `_eci_tmp/`) and runs each scraper as a subprocess.
- Loads any retailer whose scraper exited cleanly and produced a fresh CSV into `data/readymeals.db` (table `snapshots`), tagged with a `run_id` and `snapshot_datetime`. A failure in one retailer (e.g. Carrefour's session cookie expiring) is logged and skipped — it never blocks the other retailers or crashes the run. Every run appends; nothing is overwritten, so the DB accumulates full price/product history.
- Regenerates `data/readymeals_export.xlsx` (via `pipeline/export.py`) from each retailer's most recent *successful* snapshot — one sheet per pipeline-registered retailer plus `Todos`. Pure SQL + openpyxl, no AI involved, deterministic every run. A retailer with no successful run yet just gets an empty (header-only) sheet.
- Logs land in `logs/run_<run_id>.log` (orchestrator summary) and `logs/run_<run_id>_<retailer>.log` (raw scraper stdout/stderr).

For unattended weekly execution, point a Windows Task Scheduler weekly trigger at `run_pipeline.bat` (repo root) — it `cd`s into the repo and calls `python pipeline\orchestrator.py`. Use "Run whether user is logged on or not" and "Do not start a new instance".

Carrefour's scraper reads its session cookie from the `CARREFOUR_COOKIE` environment variable (`Carrefour/carrefour_comida_preparada_full.py`); the cookie will eventually expire, failing that retailer's run with an HTTP error (visible in logs and `run_log.status='failed'`). No auto-renewal — capture a fresh cookie from the browser and update the environment variable when it happens. Never hardcode the cookie value back into the script or commit it.

### Manual per-retailer scripts (legacy / still available)

No build, lint, or test tooling exists in this repo. Requires `openpyxl` (`pip install openpyxl`, or `pip install -r requirements.txt`); the scrapers themselves use only the Python standard library (`urllib`, `html.parser`, `re`, `csv`).

Per-retailer, run from inside that retailer's folder, e.g. Carrefour:

```
python carrefour_comida_preparada_full.py   # scrape -> carrefour_modelo_comun.csv
python crear_xlsx_desde_csv.py              # csv -> carrefour_modelo_comun.xlsx (standalone preview)
python update_loaded_tables_zip.py          # merge csv into Prueba Scrapping Mercadona - vfinal.xlsx
python verify_loaded_counts.py              # sanity-check row counts in the merged workbook
```

Eroski only has the first two steps; it has no merge/verify scripts against a master workbook.

## Architecture

**Scraping pattern (`*_full.py`, e.g. `carrefour_comida_preparada_full.py`, `eroski_platos_preparados_full.py`):**
- Pure stdlib HTTP via `urllib.request`, HTML parsed with regex + a small `HTMLParser` subclass (`TextExtractor`) — no BeautifulSoup/requests.
- Fetches are disk-cached into `_<retailer>_tmp/` keyed by page number / product id; `fetch()` skips re-downloading if a cached file already exceeds a size threshold, making re-runs incremental and mostly offline once warm. `_OFFLINE_ONLY` env var (e.g. `EROSKI_OFFLINE_ONLY=1`) forces cache-only mode.
- Flow: fetch category listing page(s) → extract product detail URLs/ids → fetch each product detail page (parallel `ThreadPoolExecutor`, default 8 workers) → parse into the fixed `COLUMNS` schema (identifiers, pricing, nutrition per 100g, ingredients, plus manually-curated classification fields like `tipo_plato`, `cocina`, `proteina_principal` typically left blank for later manual/LLM enrichment).
- Retries per-product (typically 3 attempts with backoff) via `needs_detail()` checks; failures land in the `observaciones` column rather than dropping the row.
- Rows checkpoint to the output CSV every ~20 completions so long scrapes survive interruption, then written fully via `save_rows()`.
- Output CSV is `;`-delimited, UTF-8-BOM (`utf-8-sig`), named `<retailer>_modelo_comun.csv`, matching the shared `COLUMNS` schema — this is the contract every downstream script and the pipeline depend on.

**Pipeline pattern (`pipeline/orchestrator.py`, `db.py`, `config.py`, `export.py`):**
- `orchestrator.py` never imports scraper code — only invokes each `*_full.py` as a subprocess (`cwd` set to that retailer's folder) and reads its output CSV, so this doesn't violate the "no cross-folder imports" rule below.
- Before each run, deletes the retailer's `_<retailer>_tmp/` cache dir and any pre-existing `*_modelo_comun.csv`, so a scraper can never "succeed" by silently reusing stale output.
- A retailer's CSV is only trusted if its subprocess exits 0, the CSV exists, and its mtime is after the run's start time — otherwise it's logged `failed` in `run_log` and skipped, without affecting the other retailer.
- `db.py` defines one wide `snapshots` table (`run_id`, `snapshot_datetime`, `retailer` + all `COLUMNS` as `TEXT`) that every successful run appends to — never updates or deletes. A companion `run_log` table records per-run/per-retailer success/failure for auditing.
- `export.py` reads (not writes) `snapshots`/`run_log` to rebuild `data/readymeals_export.xlsx` from scratch each run via plain `openpyxl.Workbook()` — no styling to preserve, so no zip/XML surgery needed here (unlike the legacy Carrefour path below). Written to a temp file then `os.replace()`d in, so a crash mid-write never leaves a corrupt export.
- `config.py` is the single place defining both retailers' folder/script/tmp-dir/csv-name and the DB/export paths — if a new retailer is added, also add an entry here.

**Legacy Excel merge pattern (`update_loaded_tables_zip.py`, Carrefour only, manual/not run by the pipeline):**
- Does NOT use openpyxl to write (it would strip/rebuild styling and unrelated sheets); instead treats the `.xlsx` as a raw zip of OOXML parts and surgically rewrites only the target sheet's XML (`patch_sheet`), preserving existing cell styles by index and updating `<dimension>`/table `ref` ranges.
- Reads current `Retailers_Final` data with openpyxl (read-only), strips existing rows for the retailer being updated, appends the freshly-scraped CSV rows, writes both the retailer sheet and the combined `Retailers_Final` sheet. Always backs up the workbook first (`<name>.backup_loaded_tables_<timestamp>.xlsx`).
- `verify_loaded_counts.py` is the post-hoc row-count check against that workbook.

## Working in this repo

- Each retailer folder is reproducible in isolation — don't introduce cross-folder imports; shared logic (COLUMNS-style schema, HTML text extraction helpers) is intentionally duplicated per retailer rather than factored into a shared module.
- When adding a new retailer: a new top-level `<Retailer>/` folder with a `<retailer>_modelo_comun_full.py`-style scraper producing the same `;`-delimited `COLUMNS` CSV, a `crear_xlsx_desde_csv.py` copy for standalone preview, an entry in `pipeline/config.py`'s `RETAILERS` list (this alone gets it into the automated DB + Excel export — no per-retailer pipeline code needed), and optionally `update_loaded_tables_zip.py`/`verify_loaded_counts.py` copies if it needs manual merging into a master workbook.
- Classification columns (`tipo_plato`, `subtipo_plato`, `cocina`, `base_carbohidrato`, `proteina_principal`, `proteina_secundaria`, `vegetales_clave`, `salsa_o_sazonado`, `nivel_conveniencia`, `tipo_conservacion`, `posicionamiento`, `healthy_vs_indulgente`, `observaciones`) are largely left blank by the scrapers, populated by a separate, out-of-repo enrichment/reporting step (the "Agente reportes I+D" in `EXPLICACION_PROYECTO.md`).
- `pipeline/export.py` and the SQLite writes in `pipeline/db.py` are intentionally free of any AI/LLM calls — they must stay pure, deterministic backend code so the weekly run costs no tokens.
