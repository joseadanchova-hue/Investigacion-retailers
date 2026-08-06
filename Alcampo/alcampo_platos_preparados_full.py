# Este scraper requiere Playwright (navegador real) porque Alcampo protege su API
# (webproductpagews) con cookies de sesion/WAF que un cliente HTTP plano no puede obtener.
# Instalacion: pip install playwright && playwright install chromium

import csv
import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "https://www.compraonline.alcampo.es"
CATEGORY_PATH = "/categories/comida-preparada/OC20022018"
OUT = Path("alcampo_modelo_comun.csv")
TMP_DIR = Path("_alcampo_tmp")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['es-ES','es']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = {runtime: {}};
"""

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

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


def clean_text(value):
    if value is None:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_number(value):
    if value is None or value == "":
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


def new_context(browser):
    ctx = browser.new_context(
        locale="es-ES",
        timezone_id="Europe/Madrid",
        viewport={"width": 1920, "height": 1080},
        user_agent=USER_AGENT,
        extra_http_headers={"Accept-Language": "es-ES,es;q=0.9"},
    )
    ctx.add_init_script(STEALTH_JS)
    return ctx


def fetch_listing_pages(page):
    """Recorre la categoria de comida preparada interceptando la API interna
    webproductpagews/v6/product-pages, paginando con pageToken hasta agotar resultados."""
    all_products = []
    seen_tokens = set()

    bucket = []
    page.on("response", lambda r: bucket.append(r.json()) if "product-pages" in r.url else None)
    page.goto(f"{BASE_URL}{CATEGORY_PATH}", timeout=60000, wait_until="load")
    for _ in range(10):
        page.wait_for_timeout(2000)
        page.mouse.wheel(0, 2000)
        if bucket:
            break

    if not bucket:
        return all_products

    payload = bucket[0]
    while payload:
        for group in payload.get("productGroups") or []:
            all_products.extend(group.get("decoratedProducts") or [])
        next_token = (payload.get("metadata") or {}).get("nextPageToken")
        if not next_token or next_token in seen_tokens:
            break
        seen_tokens.add(next_token)
        next_url = (
            f"{BASE_URL}/api/webproductpagews/v6/product-pages"
            f"?includeAdditionalPageInfo=false&maxPageSize=300&maxProductsToDecorate=50"
            f"&pageToken={next_token}&retailerCategoryId=OC20022018"
        )
        payload = page.evaluate(
            "url => fetch(url, {credentials: 'include'}).then(r => r.json())", next_url
        )
        time.sleep(0.4)

    return all_products


def row_from_listing_product(product, capture_datetime):
    price = product.get("price") or {}
    unit_price = (product.get("unitPrice") or {}).get("price") or {}
    category_path = product.get("categoryPath") or []
    category_names = [clean_text(c.get("name")) for c in category_path if isinstance(c, dict)]
    subcategory_name = category_names[-1] if category_names else ""
    retailer_id = clean_text(product.get("retailerProductId"))
    return {
        "retailer": "Alcampo",
        "source_system": "Alcampo API interna webproductpagews (via Playwright)",
        "capture_datetime": capture_datetime,
        "product_id": retailer_id,
        "ean": "",
        "product_name": clean_text(product.get("name")),
        "brand": clean_text(product.get("brand")),
        "product_url": f"{BASE_URL}/products/x/{retailer_id}" if retailer_id else "",
        "parent_category_name": "Comida preparada",
        "subcategory_name": subcategory_name,
        "block_name": subcategory_name,
        "category_path": " > ".join(category_names),
        "categories_text": "Comida preparada" + (f" > {subcategory_name}" if subcategory_name else ""),
        "packaging": clean_text(product.get("packSizeDescription")),
        "unit_size": "",
        "size_format": clean_text(product.get("packSizeDescription")),
        "is_pack": "",
        "pack_size": "",
        "unit_name": "",
        "total_units": "",
        "approx_size": "",
        "is_variable_weight": "",
        "unit_price": parse_number(price.get("amount")),
        "list_price": "",
        "reference_price": parse_number(unit_price.get("amount")),
        "reference_format": clean_text((product.get("unitPrice") or {}).get("unitName")),
        "bulk_price": "",
        "price_decreased": "",
        "previous_unit_price": "",
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


NUTRIENT_LABELS = {
    "energy_kj_100g": "valor energ",  # matches "Valor energético (Kj)"
    "energy_kcal_100g": "valor energ",
    "fat_g_100g": "grasas",
    "sat_fat_g_100g": "grasas saturadas",
    "carbs_g_100g": "hidratos de carbono",
    "sugars_g_100g": "az",  # azúcares (accent-insensitive)
    "protein_g_100g": "prote",  # proteínas
    "salt_g_100g": "sal",
    "fiber_g_100g": "fibra",
}


def parse_nutrition_block(text):
    result = {key: "" for key in NUTRIENT_LABELS}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines:
        low = line.lower()
        m = re.search(r"([\d.,]+)\s*(kj|kcal|g)\b", low)
        if not m:
            continue
        value = parse_number(m.group(1))
        if "valor energ" in low and "kj" in low:
            result["energy_kj_100g"] = value
        elif "valor energ" in low and "kcal" in low:
            result["energy_kcal_100g"] = value
        elif "grasas saturadas" in low:
            result["sat_fat_g_100g"] = value
        elif low.startswith("grasas"):
            result["fat_g_100g"] = value
        elif "hidratos de carbono" in low:
            result["carbs_g_100g"] = value
        elif low.startswith("az") or "car" in low and "azu" in low:
            result["sugars_g_100g"] = value
        elif low.startswith("prote"):
            result["protein_g_100g"] = value
        elif low.startswith("sal"):
            result["salt_g_100g"] = value
        elif low.startswith("fibra"):
            result["fiber_g_100g"] = value
    return result


def scrape_product_detail(page, product_id):
    url = f"{BASE_URL}/products/x/{product_id}"
    try:
        page.goto(url, timeout=15000, wait_until="domcontentloaded")
    except Exception:
        # If goto times out or fails, try a short retry
        try:
            page.goto(url, timeout=8000, wait_until="domcontentloaded")
        except Exception:
            page.wait_for_timeout(2000)
    try:
        page.wait_for_selector("text=Características", timeout=5000)
    except Exception:
        page.wait_for_timeout(2000)
    page.wait_for_timeout(800)
    text = page.inner_text("body")

    detail = {
        "description": "",
        "ingredients": "",
        "allergens": "",
        "storage_instructions": "",
        "usage_instructions": "",
        "supplier_name": "",
        "origin": "",
        "legal_name": "",
    }

    def section(start_label, end_labels):
        idx = text.find(start_label)
        if idx < 0:
            return ""
        idx += len(start_label)
        end_idx = len(text)
        for lbl in end_labels:
            pos = text.find(lbl, idx)
            if pos > 0:
                end_idx = min(end_idx, pos)
        return clean_text(text[idx:end_idx])

    detail["storage_instructions"] = section(
        "Almacenamiento y uso", ["Ingredientes", "Caracter", "Preparaci"]
    )
    detail["ingredients"] = section(
        "Ingredientes", ["Caracter", "Preparaci", "Datos nutricionales"]
    )
    detail["usage_instructions"] = section(
        "Preparación y uso", ["Datos nutricionales", "Opiniones"]
    )
    characteristics = section("Características", ["Preparaci", "Datos nutricionales"])
    detail["description"] = characteristics

    m = re.search(r"Nombre operador\s*/\s*Importador\s*([^\n\t]+)", text)
    if m:
        detail["supplier_name"] = clean_text(m.group(1))
    m = re.search(r"Denominación legal del alimento\s*([^\n\t]+)", text)
    if m:
        detail["legal_name"] = clean_text(m.group(1))
    m = re.search(r"Denominación de origen\s*([^\n\t]+)", text)
    if m:
        detail["origin"] = clean_text(m.group(1))

    nutrition_idx = text.find("Datos nutricionales")
    nutrition = {key: "" for key in NUTRIENT_LABELS}
    if nutrition_idx >= 0:
        end_idx = text.find("Opiniones", nutrition_idx)
        block = text[nutrition_idx: end_idx if end_idx > 0 else nutrition_idx + 700]
        nutrition = parse_nutrition_block(block)

    detail.update(nutrition)
    return detail


def main():
    TMP_DIR.mkdir(exist_ok=True)
    captured = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        ctx = new_context(browser)
        listing_page = ctx.new_page()
        raw_products = fetch_listing_pages(listing_page)
        print(f"total_productos_listado={len(raw_products)}", flush=True)
        listing_page.close()

        rows_by_id = {}
        for product in raw_products:
            row = row_from_listing_product(product, captured)
            if row["product_id"]:
                rows_by_id[row["product_id"]] = row

        rows = list(rows_by_id.values())
        (TMP_DIR / "listing_raw.json").write_text(
            json.dumps(raw_products, ensure_ascii=False), encoding="utf-8"
        )

        detail_page = ctx.new_page()
        completed = 0
        for row in rows:
            product_id = row["product_id"]
            cache_file = TMP_DIR / f"detail_{product_id}.json"
            product_start_time = time.time()
            try:
                if cache_file.exists() and cache_file.stat().st_size > 50:
                    detail = json.loads(cache_file.read_text(encoding="utf-8"))
                else:
                    # recicla la pestaña cada 40 productos: Chromium headless tiende a
                    # acumular memoria y termina "crasheando" tras muchas navegaciones seguidas
                    if completed and completed % 40 == 0:
                        detail_page.close()
                        detail_page = ctx.new_page()
                    detail = scrape_product_detail(detail_page, product_id)
                    cache_file.write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
                    time.sleep(0.6)
                for key, value in detail.items():
                    if value not in ("", None):
                        row[key] = value
                status = "ok"
            except Exception as exc:
                elapsed = time.time() - product_start_time
                row["observaciones"] = (row["observaciones"] + " | " if row["observaciones"] else "") + f"PDP error after {elapsed:.1f}s: {exc}"
                status = f"ERROR ({elapsed:.1f}s) {type(exc).__name__}"
                try:
                    detail_page.close()
                except Exception:
                    pass
                detail_page = ctx.new_page()
            completed += 1
            elapsed = time.time() - product_start_time
            print(f"PDP {completed}/{len(rows)} {status} {product_id} ({elapsed:.1f}s)", flush=True)
            if completed % 20 == 0:
                with OUT.open("w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
                    writer.writeheader()
                    writer.writerows([{col: r.get(col, "") for col in COLUMNS} for r in rows])

        detail_page.close()
        browser.close()

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
