"""Paths and constants for the automated scraping pipeline."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

RETAILERS = [
    {
        "name": "Eroski",
        "dir": REPO_ROOT / "Eroski",
        "script": "eroski_platos_preparados_full.py",
        "tmp_dir": REPO_ROOT / "Eroski" / "_eroski_tmp",
        "csv_name": "eroski_modelo_comun.csv",
    },
    {
        "name": "Carrefour",
        "dir": REPO_ROOT / "Carrefour",
        "script": "carrefour_comida_preparada_full.py",
        "tmp_dir": REPO_ROOT / "Carrefour" / "_carrefour_tmp",
        "csv_name": "carrefour_modelo_comun.csv",
    },
    {
        "name": "Mercadona",
        "dir": REPO_ROOT / "Mercadona",
        "script": "mercadona_platos_preparados_full.py",
        "tmp_dir": REPO_ROOT / "Mercadona" / "_mercadona_tmp",
        "csv_name": "mercadona_modelo_comun.csv",
    },
    {
        "name": "Consum",
        "dir": REPO_ROOT / "Consum",
        "script": "consum_platos_preparados_full.py",
        "tmp_dir": REPO_ROOT / "Consum" / "_consum_tmp",
        "csv_name": "consum_modelo_comun.csv",
    },
    {
        "name": "Dia",
        "dir": REPO_ROOT / "Dia",
        "script": "dia_platos_preparados_full.py",
        "tmp_dir": REPO_ROOT / "Dia" / "_dia_tmp",
        "csv_name": "dia_modelo_comun.csv",
    },
    {
        "name": "Alcampo",
        "dir": REPO_ROOT / "Alcampo",
        "script": "alcampo_platos_preparados_full.py",
        "tmp_dir": REPO_ROOT / "Alcampo" / "_alcampo_tmp",
        "csv_name": "alcampo_modelo_comun.csv",
    },
    {
        "name": "ElCorteIngles",
        "dir": REPO_ROOT / "ElCorteIngles",
        "script": "eci_platos_preparados_full.py",
        "tmp_dir": REPO_ROOT / "ElCorteIngles" / "_eci_tmp",
        "csv_name": "eci_modelo_comun.csv",
    },
]

DB_PATH = REPO_ROOT / "data" / "readymeals.db"
EXPORT_PATH = REPO_ROOT / "data" / "readymeals_export.xlsx"
LOG_DIR = REPO_ROOT / "logs"

SCRAPER_TIMEOUT_SECONDS = 3600

COLUMNS = [
    "source_system", "capture_datetime", "product_id", "ean", "product_name", "brand",
    "product_url", "parent_category_name", "subcategory_name", "block_name", "category_path",
    "categories_text", "packaging", "unit_size", "size_format", "is_pack", "pack_size",
    "unit_name", "total_units", "approx_size", "is_variable_weight", "unit_price", "list_price",
    "reference_price", "reference_format", "bulk_price", "price_decreased", "previous_unit_price",
    "legal_name", "description", "ingredients", "allergens", "storage_instructions",
    "usage_instructions", "supplier_name", "origin", "nutrients_text", "energy_kj_100g",
    "energy_kcal_100g", "fat_g_100g", "sat_fat_g_100g", "carbs_g_100g", "sugars_g_100g",
    "protein_g_100g", "salt_g_100g", "fiber_g_100g", "tipo_plato", "subtipo_plato", "cocina",
    "base_carbohidrato", "proteina_principal", "proteina_secundaria", "vegetales_clave",
    "salsa_o_sazonado", "nivel_conveniencia", "tipo_conservacion", "posicionamiento",
    "healthy_vs_indulgente", "observaciones", "back_image_url",
]
