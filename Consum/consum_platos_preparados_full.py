import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


BASE_URL = "https://tienda.consum.es"
CATEGORY_ID = 1833  # "Platos preparados"
PAGE_LIMIT = 100
OUT = Path("consum_modelo_comun.csv")
TMP_DIR = Path("_consum_tmp")

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


def fetch_category_page(category_id, offset):
    url = (
        f"{BASE_URL}/api/rest/V1.0/catalog/product"
        f"?limit={PAGE_LIMIT}&offset={offset}&categories={category_id}"
    )
    return fetch_json(url, TMP_DIR / f"category_{category_id}_offset_{offset}.json")


def fetch_product_detail(code):
    url = f"{BASE_URL}/api/rest/V1.0/catalog/product/code/{code}?showRecommendations=false"
    return fetch_json(url, TMP_DIR / f"product_{code}.json")


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


def row_from_listing_product(product, capture_datetime):
    pd = product.get("productData") or {}
    price = product.get("priceData") or {}
    prices = price.get("prices") or []
    price_value = prices[0].get("value") if prices else {}
    categories = product.get("categories") or []
    category_name = clean_text(categories[0].get("name")) if categories else ""
    brand = pd.get("brand") or {}
    return {
        "retailer": "Consum",
        "source_system": "Consum API publica catalog/product",
        "capture_datetime": capture_datetime,
        "product_id": clean_text(product.get("code")),
        "ean": clean_text(product.get("ean")),
        "product_name": clean_text(pd.get("name")),
        "brand": clean_text(brand.get("name")),
        "product_url": pd.get("url") or "",
        "parent_category_name": "Platos preparados",
        "subcategory_name": category_name,
        "block_name": category_name,
        "category_path": f"/api/rest/V1.0/catalog/product?categories={CATEGORY_ID}",
        "categories_text": f"Platos preparados > {category_name}" if category_name else "Platos preparados",
        "packaging": "",
        "unit_size": "",
        "size_format": clean_text(price.get("unitPriceUnitType")),
        "is_pack": "",
        "pack_size": "",
        "unit_name": "",
        "total_units": "",
        "approx_size": "",
        "is_variable_weight": "",
        "unit_price": parse_number(price_value.get("centAmount") if isinstance(price_value, dict) else ""),
        "list_price": "",
        "reference_price": parse_number(price_value.get("centUnitAmount") if isinstance(price_value, dict) else ""),
        "reference_format": clean_text(price.get("unitPriceUnitType")),
        "bulk_price": "",
        "price_decreased": "",
        "previous_unit_price": "",
        "legal_name": "",
        "description": clean_text(pd.get("description")),
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
        "observaciones": (
            "" if pd.get("containAllergensIntolernacies") else
            "Consum no publica ingredientes/nutricion estructurados para este producto via API publica"
        ),
        "back_image_url": (product.get("media") or [{}])[1].get("url", "") if len(product.get("media") or []) > 1 else "",
    }


def detail_from_product_json(product):
    pd = product.get("productData") or {}
    brand = pd.get("brand") or {}
    return {
        "ean": clean_text(product.get("ean")),
        "brand": clean_text(brand.get("name")),
        "description": clean_text(pd.get("description")),
    }


def main():
    TMP_DIR.mkdir(exist_ok=True)
    captured = datetime.now(timezone.utc).isoformat()

    first_page = fetch_category_page(CATEGORY_ID, 0)
    total_count = first_page.get("totalCount") or 0
    print(f"total_productos={total_count}", flush=True)

    rows_by_id = {}
    for prod in first_page.get("products") or []:
        row = row_from_listing_product(prod, captured)
        rows_by_id[row["product_id"]] = row

    offset = PAGE_LIMIT
    while offset < total_count:
        page = fetch_category_page(CATEGORY_ID, offset)
        for prod in page.get("products") or []:
            row = row_from_listing_product(prod, captured)
            rows_by_id[row["product_id"]] = row
        print(f"offset={offset} rows_acumuladas={len(rows_by_id)}", flush=True)
        offset += PAGE_LIMIT
        time.sleep(0.3)

    rows = list(rows_by_id.values())
    print(f"total_filas={len(rows)}", flush=True)

    def fetch_and_merge(row):
        code = row["product_id"]
        try:
            product = fetch_product_detail(code)
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

    filled_ean = sum(1 for row in rows if row.get("ean"))
    filled_desc = sum(1 for row in rows if row.get("description"))
    print(f"csv={OUT.resolve()}")
    print(f"rows={len(rows)}")
    print(f"ean_rows={filled_ean} description_rows={filled_desc}")


if __name__ == "__main__":
    main()
