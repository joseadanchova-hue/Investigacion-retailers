# Este scraper requiere Playwright (navegador real con fingerprint reforzado) porque
# El Corte Ingles bloquea con Akamai ("Access Denied") a clientes HTTP simples e incluso
# a Playwright sin cabeceras sec-ch-ua realistas ni una visita previa a la home.
# Instalacion: pip install playwright && playwright install chromium

import csv
import html
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "https://www.elcorteingles.es"
CATEGORY_PATH = "/supermercado/alimentacion-general/platos-preparados/"
OUT = Path("eci_modelo_comun.csv")
TMP_DIR = Path("_eci_tmp")

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['es-ES','es']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}};
"""

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

EXTRA_HEADERS = {
    "Accept-Language": "es-ES,es;q=0.9",
    "sec-ch-ua": '"Chromium";v="125", "Not.A/Brand";v="24", "Google Chrome";v="125"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

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

SUBCATEGORIES = [
    "platos-preparados-refrigerados", "empanadas-y-sandwiches", "tortillas", "pizzas",
    "platos-preparados-de-carne", "platos-preparados-de-verduras-y-legumbres",
    "platos-preparados-de-pasta", "platos-preparados-de-arroz", "platos-preparados-diversos",
    "ensaladas-preparadas", "fabada", "garbanzos-guisados", "lentejas-guisadas",
    "callos-guisados", "alubias-guisadas", "albondigas",
    "platos-preparados-de-pescado-y-marisco", "pimientos-rellenos", "aperitivos", "sushi",
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
        viewport={"width": 1366, "height": 768},
        user_agent=USER_AGENT,
        extra_http_headers=EXTRA_HEADERS,
    )
    ctx.add_init_script(STEALTH_JS)
    return ctx


def goto_with_retry(page, url, attempts=3, **kwargs):
    last_exc = None
    for i in range(attempts):
        try:
            return page.goto(url, **kwargs)
        except Exception as exc:
            last_exc = exc
            time.sleep(3 * (i + 1))
    raise last_exc


def warm_up(page):
    goto_with_retry(page, f"{BASE_URL}/", timeout=45000, wait_until="load")
    page.wait_for_timeout(2500)


def fetch_subcategory_links(page, subcategory_slug):
    url = f"{BASE_URL}{CATEGORY_PATH}{subcategory_slug}/"
    goto_with_retry(page, url, timeout=45000, wait_until="load")
    page.wait_for_timeout(4000)

    def count_links():
        return page.eval_on_selector_all(
            "a[href^='/supermercado/B']",
            "els => new Set(els.map(e => e.getAttribute('href'))).size",
        )

    previous = -1
    stable_rounds = 0
    for _ in range(30):
        current = count_links()
        if current == previous:
            stable_rounds += 1
            if stable_rounds >= 2:
                break
        else:
            stable_rounds = 0
        previous = current
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1200)

    links = page.eval_on_selector_all(
        "a[href^='/supermercado/B']",
        "els => Array.from(new Set(els.map(e => e.getAttribute('href'))))",
    )
    return links


def row_from_link(href, subcategory_name, capture_datetime):
    m = re.search(r"/supermercado/(B\d+)-([a-z0-9\-]+)/?", href)
    product_id = m.group(1) if m else ""
    slug = m.group(2) if m else ""
    name_guess = clean_text(slug.replace("-", " "))
    return {
        "retailer": "El Corte Ingles",
        "source_system": "ECI supermercado (Playwright, HTML renderizado)",
        "capture_datetime": capture_datetime,
        "product_id": product_id,
        "ean": "",
        "product_name": name_guess,
        "brand": "",
        "product_url": f"{BASE_URL}{href}" if not href.startswith("http") else href,
        "parent_category_name": "Platos preparados",
        "subcategory_name": subcategory_name,
        "block_name": subcategory_name,
        "category_path": CATEGORY_PATH + subcategory_name,
        "categories_text": f"Platos preparados > {subcategory_name}",
        "packaging": "",
        "unit_size": "",
        "size_format": "",
        "is_pack": "",
        "pack_size": "",
        "unit_name": "",
        "total_units": "",
        "approx_size": "",
        "is_variable_weight": "",
        "unit_price": "",
        "list_price": "",
        "reference_price": "",
        "reference_format": "",
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


NUTRIENT_MATCHERS = [
    ("energy_kj_100g", re.compile(r"valor energ[eé]tico\s*([\d.,]+)\s*kj", re.I)),
    ("energy_kcal_100g", re.compile(r"valor energ[eé]tico\s*([\d.,]+)\s*kcal", re.I)),
    ("fat_g_100g", re.compile(r"\bgrasas\s+([\d.,]+)\s*g", re.I)),
    ("sat_fat_g_100g", re.compile(r"saturadas\s+([\d.,]+)\s*g", re.I)),
    ("carbs_g_100g", re.compile(r"hidratos\s+([\d.,]+)\s*g", re.I)),
    ("sugars_g_100g", re.compile(r"az[uú]cares\s+([\d.,]+)\s*g", re.I)),
    ("protein_g_100g", re.compile(r"prote[ií]nas\s+([\d.,]+)\s*g", re.I)),
    ("salt_g_100g", re.compile(r"\bsal\s+([\d.,]+)\s*g", re.I)),
    ("fiber_g_100g", re.compile(r"fibra\s+([\d.,]+)\s*g", re.I)),
]


def parse_nutrition(text):
    result = {key: "" for key, _ in NUTRIENT_MATCHERS}
    for key, pattern in NUTRIENT_MATCHERS:
        m = pattern.search(text)
        if m:
            result[key] = parse_number(m.group(1))
    return result


def section_between(text, start_label, end_labels):
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


def scrape_product_detail(page, url):
    goto_with_retry(page, url, timeout=45000, wait_until="load")
    page.wait_for_timeout(4000)

    detail = {
        "brand": "",
        "product_name": "",
        "packaging": "",
        "ingredients": "",
        "storage_instructions": "",
        "usage_instructions": "",
        "unit_price": "",
        "reference_price": "",
    }

    try:
        title = clean_text(page.locator("h1").first.inner_text(timeout=4000))
        detail["product_name"] = title
    except Exception:
        pass

    try:
        page.locator(".product_alimentary-button-border", has_text="Información nutricional").first.click(timeout=4000)
        page.wait_for_timeout(1200)
    except Exception:
        pass

    text = page.inner_text("body")

    nutrition = parse_nutrition(text)
    detail.update(nutrition)

    detail["ingredients"] = section_between(
        text, "Ingredientes", ["Información general", "Conservación", "Información de seguridad"]
    )
    detail["storage_instructions"] = section_between(
        text, "Conservación y utilización", ["Información de seguridad", "Añadir"]
    )
    detail["usage_instructions"] = detail["storage_instructions"]

    m = re.search(r"([\d.,]+)\s*€\s*/?\s*Kg", text)
    if m:
        detail["reference_price"] = parse_number(m.group(1))

    return detail


def main():
    TMP_DIR.mkdir(exist_ok=True)
    captured = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = new_context(browser)
        listing_page = ctx.new_page()
        warm_up(listing_page)

        rows_by_id = {}
        for slug in SUBCATEGORIES:
            links = fetch_subcategory_links(listing_page, slug)
            for href in links:
                row = row_from_link(href, slug, captured)
                if row["product_id"]:
                    rows_by_id[row["product_id"]] = row
            print(f"subcategoria={slug} rows_acumuladas={len(rows_by_id)}", flush=True)
            time.sleep(0.5)

        listing_page.close()
        rows = list(rows_by_id.values())
        print(f"total_productos={len(rows)}", flush=True)

        detail_page = ctx.new_page()
        completed = 0
        for row in rows:
            product_id = row["product_id"]
            cache_file = TMP_DIR / f"detail_{product_id}.json"
            try:
                import json as _json
                if cache_file.exists() and cache_file.stat().st_size > 50:
                    detail = _json.loads(cache_file.read_text(encoding="utf-8"))
                else:
                    # recicla la pestaña cada 40 productos: Chromium headless tiende a
                    # acumular memoria y termina "crasheando" tras muchas navegaciones seguidas
                    if completed and completed % 40 == 0:
                        detail_page.close()
                        detail_page = ctx.new_page()
                    detail = scrape_product_detail(detail_page, row["product_url"])
                    cache_file.write_text(_json.dumps(detail, ensure_ascii=False), encoding="utf-8")
                    time.sleep(0.6)
                for key, value in detail.items():
                    if value not in ("", None):
                        row[key] = value
                status = "ok"
            except Exception as exc:
                row["observaciones"] = (row["observaciones"] + " | " if row["observaciones"] else "") + f"PDP error: {exc}"
                status = f"ERROR {exc}"
                try:
                    detail_page.close()
                except Exception:
                    pass
                try:
                    detail_page = ctx.new_page()
                except Exception:
                    # el contexto/navegador entero murio: relanzar uno nuevo
                    try:
                        browser.close()
                    except Exception:
                        pass
                    browser = p.chromium.launch(
                        headless=True,
                        args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
                    )
                    ctx = new_context(browser)
                    detail_page = ctx.new_page()
            completed += 1
            print(f"PDP {completed}/{len(rows)} {status} {product_id}", flush=True)
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
