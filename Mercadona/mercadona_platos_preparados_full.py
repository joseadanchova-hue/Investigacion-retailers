import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = "https://tienda.mercadona.es"
CATEGORY_ID = 16  # "Pizzas y platos preparados"
OUT = Path("mercadona_modelo_comun.csv")
TMP_DIR = Path("_mercadona_tmp")

COLUMNS = [
    "retailer", "source_system", "capture_datetime", "product_id", "ean", "product_name", "brand",
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
}


def clean_text(value):
    if value is None:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def fetch_json(url, dest):
    if dest.exists() and dest.stat().st_size > 200:
        return json.loads(dest.read_text(encoding="utf-8", errors="ignore"))
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=45) as response:
        data = response.read()
    dest.write_bytes(data)
    return json.loads(data.decode("utf-8", errors="ignore"))


def fetch_categories_index():
    url = f"{BASE_URL}/api/categories/"
    return fetch_json(url, TMP_DIR / "categories_index.json")


def fetch_category(category_id):
    url = f"{BASE_URL}/api/categories/{category_id}/"
    return fetch_json(url, TMP_DIR / f"category_{category_id}.json")


def fetch_product(product_id):
    url = f"{BASE_URL}/api/products/{product_id}/"
    return fetch_json(url, TMP_DIR / f"product_{product_id}.json")


def parse_number(value):
    if value is None:
        return ""
    selected = "".join(ch for ch in str(value) if ch.isdigit() or ch in ",.-")
    if not selected:
        return ""
    if "," in selected:
        selected = selected.replace(".", "").replace(",", ".")
    try:
        number = float(selected)
    except ValueError:
        return ""
    return str(number).rstrip("0").rstrip(".")


def row_from_listing_product(product, subcategory_name, capture_datetime):
    price = product.get("price_instructions") or {}
    return {
        "retailer": "Mercadona",
        "source_system": "Mercadona API publica categorias+productos",
        "capture_datetime": capture_datetime,
        "product_id": clean_text(product.get("id")),
        "ean": "",
        "product_name": clean_text(product.get("display_name")),
        "brand": "",
        "product_url": product.get("share_url") or "",
        "parent_category_name": "Pizzas y platos preparados",
        "subcategory_name": subcategory_name,
        "block_name": subcategory_name,
        "category_path": f"/api/categories/{CATEGORY_ID}/",
        "categories_text": f"Pizzas y platos preparados > {subcategory_name}",
        "packaging": clean_text(product.get("packaging")),
        "unit_size": parse_number(price.get("unit_size")),
        "size_format": clean_text(price.get("size_format")),
        "is_pack": "true" if price.get("is_pack") else "",
        "pack_size": parse_number(price.get("pack_size")),
        "unit_name": clean_text(price.get("unit_name")),
        "total_units": parse_number(price.get("total_units")),
        "approx_size": "true" if price.get("approx_size") else "",
        "is_variable_weight": "",
        "unit_price": parse_number(price.get("unit_price")),
        "list_price": "",
        "reference_price": parse_number(price.get("reference_price")),
        "reference_format": clean_text(price.get("reference_format")),
        "bulk_price": parse_number(price.get("bulk_price")),
        "price_decreased": "true" if price.get("price_decreased") else "",
        "previous_unit_price": parse_number(price.get("previous_unit_price")),
        "legal_name": "",
        "description": "",
        "ingredients": "",
        "allergens": "",
        "storage_instructions": "",
        "usage_instructions": "",
        "supplier_name": "",
        "origin": "",
        "nutrients_text": "",
        "energy_kj_100g": "",
        "energy_kcal_100g": "",
        "fat_g_100g": "",
        "sat_fat_g_100g": "",
        "carbs_g_100g": "",
        "sugars_g_100g": "",
        "protein_g_100g": "",
        "salt_g_100g": "",
        "fiber_g_100g": "",
        "tipo_plato": "",
        "subtipo_plato": "",
        "cocina": "",
        "base_carbohidrato": "",
        "proteina_principal": "",
        "proteina_secundaria": "",
        "vegetales_clave": "",
        "salsa_o_sazonado": "",
        "nivel_conveniencia": "",
        "tipo_conservacion": "",
        "posicionamiento": "",
        "healthy_vs_indulgente": "",
        "observaciones": "",
        "back_image_url": "",
    }


def detail_from_product_json(product):
    details = product.get("details") if isinstance(product.get("details"), dict) else {}
    nutrition = product.get("nutrition_information") if isinstance(product.get("nutrition_information"), dict) else {}
    suppliers = details.get("suppliers") if isinstance(details.get("suppliers"), list) else []
    supplier_name = clean_text(suppliers[0].get("name")) if suppliers and isinstance(suppliers[0], dict) else ""
    return {
        "ean": clean_text(product.get("ean")),
        "brand": clean_text(details.get("brand") or product.get("brand")),
        "legal_name": clean_text(details.get("legal_name")),
        "description": clean_text(details.get("description")),
        "ingredients": clean_text(nutrition.get("ingredients")),
        "allergens": clean_text(nutrition.get("allergens")),
        "storage_instructions": clean_text(details.get("storage_instructions")),
        "usage_instructions": clean_text(details.get("usage_instructions")),
        "supplier_name": supplier_name,
        "origin": clean_text(details.get("origin") or product.get("origin")),
        "tipo_conservacion": clean_text(details.get("storage_instructions")),
    }


def main():
    TMP_DIR.mkdir(exist_ok=True)
    captured = datetime.now(timezone.utc).isoformat()

    index = fetch_categories_index()
    top_category = next((c for c in (index.get("results") or []) if c.get("id") == CATEGORY_ID), None)
    if top_category is None:
        raise RuntimeError(f"Categoria {CATEGORY_ID} no encontrada en el indice de categorias")
    subcategories = top_category.get("categories") or []
    print(f"subcategorias={len(subcategories)}", flush=True)

    rows_by_id = {}
    for sub in subcategories:
        sub_id = sub.get("id")
        sub_detail = fetch_category(sub_id)
        sub_name = clean_text(sub_detail.get("name") or sub.get("name"))
        for leaf in sub_detail.get("categories") or []:
            leaf_name = clean_text(leaf.get("name"))
            products = leaf.get("products") or []
            for product in products:
                row = row_from_listing_product(product, leaf_name or sub_name, captured)
                rows_by_id[row["product_id"]] = row
        print(f"subcategoria={sub_name} rows_acumuladas={len(rows_by_id)}", flush=True)
        time.sleep(0.3)

    rows = list(rows_by_id.values())
    print(f"total_productos={len(rows)}", flush=True)

    def fetch_and_merge(row):
        product_id = row["product_id"]
        try:
            product = fetch_product(product_id)
            detail = detail_from_product_json(product)
            for key, value in detail.items():
                if value not in ("", None):
                    row[key] = value
            return row, None
        except Exception as exc:
            row["observaciones"] = (row["observaciones"] + " | " if row["observaciones"] else "") + f"PDP error: {exc}"
            return row, exc

    completed = 0
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_and_merge, row): row for row in rows}
        for future in as_completed(futures):
            row, exc = future.result()
            completed += 1
            status = "ok" if exc is None else f"ERROR {exc}"
            print(f"PDP {completed}/{len(rows)} {status} {row['product_id']}", flush=True)
            if completed % 20 == 0:
                with OUT.open("w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
                    writer.writeheader()
                    writer.writerows([{col: r.get(col, "") for col in COLUMNS} for r in rows])

    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows([{col: row.get(col, "") for col in COLUMNS} for row in rows])

    filled_ingredients = sum(1 for row in rows if row.get("ingredients"))
    filled_ean = sum(1 for row in rows if row.get("ean"))
    print(f"csv={OUT.resolve()}")
    print(f"rows={len(rows)}")
    print(f"ingredients_rows={filled_ingredients} ean_rows={filled_ean}")


if __name__ == "__main__":
    main()
