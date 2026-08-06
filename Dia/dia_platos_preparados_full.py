import csv
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


BASE_URL = "https://www.dia.es"
TOP_CATEGORY_ID = "L116"  # "Platos preparados y pizzas"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
OUT = Path("dia_modelo_comun.csv")
TMP_DIR = Path("_dia_tmp")

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


def fetch_bytes(url, dest):
    if dest.exists() and dest.stat().st_size > 200:
        return dest.read_bytes()
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=45) as response:
        data = response.read()
    dest.write_bytes(data)
    return data


def fetch_json(url, dest):
    return json.loads(fetch_bytes(url, dest).decode("utf-8", errors="ignore"))


def fetch_subcategory_ids():
    xml = fetch_bytes(SITEMAP_URL, TMP_DIR / "sitemap.xml").decode("utf-8", errors="ignore")
    pattern = r"https://www\.dia\.es/platos-preparados-y-pizzas/[a-zA-Z0-9\-]+/c/(L\d+)"
    return sorted(set(re.findall(pattern, xml)))


def fetch_subcategory_listing(subcategory_id):
    url = f"{BASE_URL}/api/v1/plp-back/l1/all/{TOP_CATEGORY_ID}/reduced?category_id={subcategory_id}&page=1"
    return fetch_json(url, TMP_DIR / f"listing_{subcategory_id}.json")


def fetch_product_detail(product_id):
    url = f"{BASE_URL}/api/v1/pdp-back/{product_id}"
    return fetch_json(url, TMP_DIR / f"product_{product_id}.json")


def parse_number(value):
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return str(number).rstrip("0").rstrip(".")


def row_from_listing_product(product, subcategory_name, capture_datetime):
    prices = product.get("prices") or {}
    allergens = product.get("allergens") or []
    allergens_text = ", ".join(clean_text(a.get("name")) for a in allergens if isinstance(a, dict))
    return {
        "retailer": "Dia",
        "source_system": "Dia API publica plp-back+pdp-back",
        "capture_datetime": capture_datetime,
        "product_id": clean_text(product.get("object_id") or product.get("sku_id")),
        "ean": "",
        "product_name": clean_text(product.get("display_name")),
        "brand": clean_text(product.get("brand")),
        "product_url": (BASE_URL + product.get("url")) if product.get("url") else "",
        "parent_category_name": "Platos preparados y pizzas",
        "subcategory_name": subcategory_name,
        "block_name": subcategory_name,
        "category_path": f"/api/v1/plp-back/l1/all/{TOP_CATEGORY_ID}/reduced",
        "categories_text": f"Platos preparados y pizzas > {subcategory_name}",
        "packaging": "",
        "unit_size": "",
        "size_format": clean_text(prices.get("measure_unit")),
        "is_pack": "",
        "pack_size": "",
        "unit_name": "",
        "total_units": "",
        "approx_size": "",
        "is_variable_weight": "",
        "unit_price": parse_number(prices.get("price")),
        "list_price": parse_number(prices.get("strikethrough_price")),
        "reference_price": parse_number(prices.get("price_per_unit")),
        "reference_format": clean_text(prices.get("measure_unit")),
        "bulk_price": "",
        "price_decreased": "true" if prices.get("is_promo_price") else "",
        "previous_unit_price": "",
        "legal_name": "",
        "description": "",
        "ingredients": "",
        "allergens": allergens_text,
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
    allergens = product.get("allergens") or []
    allergens_text = ", ".join(clean_text(a.get("name")) for a in allergens if isinstance(a, dict))
    ingredients = (product.get("ingredients") or {}).get("text")
    instructions = product.get("instructions") or {}
    manufacturer = product.get("manufacturer_contact") or {}
    product_info = (product.get("product_info") or {}).get("product")
    nutrition = ((product.get("nutritional_info") or {}).get("nutritional_values")) or {}

    def find_value(title_fragment):
        for entry in nutrition.get("values") or []:
            if title_fragment.lower() in (entry.get("title") or "").lower():
                return entry.get("value_per_100_g", entry.get("value"))
            for item in entry.get("items") or []:
                if title_fragment.lower() in (item.get("title") or "").lower():
                    return item.get("value_per_100_g", item.get("value"))
        return None

    return {
        "brand": clean_text(product.get("primary_info", {}).get("title")),
        "description": clean_text(product_info),
        "ingredients": clean_text(ingredients),
        "allergens": allergens_text,
        "storage_instructions": clean_text(instructions.get("storage")),
        "usage_instructions": clean_text(instructions.get("preparation") or instructions.get("usage")),
        "supplier_name": clean_text(manufacturer.get("manufacturer_contact_name")),
        "origin": "",
        "energy_kj_100g": parse_number(nutrition.get("energy_value_kj")),
        "energy_kcal_100g": parse_number(nutrition.get("energy_value")),
        "fat_g_100g": parse_number(find_value("grasas")),
        "sat_fat_g_100g": parse_number(find_value("saturadas")),
        "carbs_g_100g": parse_number(find_value("hidratos de carbono")),
        "sugars_g_100g": parse_number(find_value("azúcares") or find_value("azucares")),
        "protein_g_100g": parse_number(find_value("proteínas") or find_value("proteinas")),
        "salt_g_100g": parse_number(find_value("sal")),
        "fiber_g_100g": parse_number(find_value("fibra")),
    }


def main():
    TMP_DIR.mkdir(exist_ok=True)
    captured = datetime.now(timezone.utc).isoformat()

    subcategory_ids = fetch_subcategory_ids()
    print(f"subcategorias={len(subcategory_ids)}", flush=True)

    rows_by_id = {}
    for sub_id in subcategory_ids:
        listing = fetch_subcategory_listing(sub_id)
        sub_name = clean_text((listing.get("current_subcategory") or {}).get("name")) or sub_id
        for product in listing.get("items") or []:
            row = row_from_listing_product(product, sub_name, captured)
            if row["product_id"]:
                rows_by_id[row["product_id"]] = row
        print(f"subcategoria={sub_name} rows_acumuladas={len(rows_by_id)}", flush=True)
        time.sleep(0.5)

    rows = list(rows_by_id.values())
    print(f"total_productos={len(rows)}", flush=True)

    def fetch_and_merge(row):
        product_id = row["product_id"]
        try:
            detail = fetch_product_detail(product_id)
            product = detail.get("product") or {}
            merged = detail_from_product_json(product)
            for key, value in merged.items():
                if value not in ("", None):
                    row[key] = value
            time.sleep(0.15)
            return row, None
        except Exception as exc:
            row["observaciones"] = (row["observaciones"] + " | " if row["observaciones"] else "") + f"PDP error: {exc}"
            return row, exc

    completed = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
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
    filled_nutrition = sum(1 for row in rows if row.get("energy_kcal_100g"))
    print(f"csv={OUT.resolve()}")
    print(f"rows={len(rows)}")
    print(f"ingredients_rows={filled_ingredients} nutrition_rows={filled_nutrition}")


if __name__ == "__main__":
    main()
