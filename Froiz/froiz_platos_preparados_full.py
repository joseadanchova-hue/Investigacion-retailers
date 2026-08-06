import csv
import html
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


BASE_URL = "https://supermercado.froiz.com"
API_BASE_URL = "https://servicios.froiz.com"
CATEGORY_PATH = "/alimentacion/platos-preparados"
CATEGORY_URL = BASE_URL + CATEGORY_PATH
SECTION_SLUG = "platos-preparados"
PAGE_SIZE = 20
OUT = Path("froiz_modelo_comun.csv")
TMP_DIR = Path("_froiz_tmp")

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
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": CATEGORY_URL,
    "Connection": "keep-alive",
}


# ---------------------------------------------------------------------------
# Generic helpers (same pattern as Eroski/Carrefour, copied verbatim).
# ---------------------------------------------------------------------------


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())

    def text(self):
        return clean_text(" ".join(self.parts))


def clean_text(value):
    if value is None:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def html_text(fragment):
    parser = TextExtractor()
    parser.feed(fragment or "")
    return parser.text()


def fetch(url, dest, timeout=30):
    if dest.exists() and dest.stat().st_size > 10000:
        return dest.read_text(encoding="utf-8", errors="ignore")
    if os.environ.get("FROIZ_OFFLINE_ONLY") == "1":
        return ""
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as response:
        data = response.read()
    dest.write_bytes(data)
    return data.decode("utf-8", errors="ignore")


def fetch_json(url, dest, timeout=30):
    if dest.exists() and dest.stat().st_size > 50:
        return json.loads(dest.read_text(encoding="utf-8", errors="ignore"))
    if os.environ.get("FROIZ_OFFLINE_ONLY") == "1":
        return {}
    req = Request(url, headers={**HEADERS, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        data = response.read()
    dest.write_bytes(data)
    return json.loads(data.decode("utf-8", errors="ignore"))


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


_EXCLUDED_NAME_PATTERNS = [
    r"\bensaladas?\b", r"\bensaladillas?\b",
    r"\bgazpachos?\b", r"\bsalmorejos?\b", r"\bajoblancos?\b",
    r"\bkombuchas?\b", r"\bbatidos?\b", r"\bsmoothies?\b", r"\bzumos?\b",
    r"\bcaldos?\b", r"\bbebidas?\b",
    r"\bcremas?\s+de\b",  # "crema de calabaza", "crema de verduras", etc. -- drinkable cold/hot cream soups, not V-gama dishes
]
_EXCLUDED_NAME_RE = re.compile("|".join(_EXCLUDED_NAME_PATTERNS), re.IGNORECASE)


def is_excluded_product(name):
    if not name:
        return False
    return bool(_EXCLUDED_NAME_RE.search(name))


def infer_size(name):
    text = (name or "").lower().replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|kilo|g|gr|gramos|ml|l|litro|ud|uds)\b", text)
    if not match:
        return "", ""
    unit = match.group(2)
    unit = {"gr": "g", "gramos": "g", "kilo": "kg", "litro": "l", "uds": "ud"}.get(unit, unit)
    return match.group(1), unit


# ---------------------------------------------------------------------------
# Froiz-specific API access.
#
# supermercado.froiz.com is a Nuxt SSR app. The category listing page does
# NOT embed a clean JSON blob usable via json.loads() -- it embeds
# window.__NUXT__ as a minified "(function(a,b,c,...){...})(v1,v2,v3,...)"
# argument-substitution payload, which is not valid JSON and not worth
# reverse-engineering. Instead, the page's own JS bundles (_nuxt/*.js) call a
# separate, plain JSON REST API at https://servicios.froiz.com, discovered by
# grepping the bundles for "/api/":
#
#   GET https://servicios.froiz.com/api/products
#       ?section=platos-preparados&page=<n>&size=<n>
#       -> {"products": [...], "stats": {"totalPages": N, "productTotal": N}}
#
#   GET https://servicios.froiz.com/api/products/<product_id>
#       -> full product detail: nutrition, ingredients_and_allergens,
#          storage/usage instructions, brand, origin, etc.
#
# "section=platos-preparados" alone (without category/family) reliably
# returns the full category (confirmed 108 products / 6 pages of size 20 at
# time of writing; category="alimentacion"+section="platos-preparados" also
# works and is equivalent). No API key/session/store code is required for
# these public reads.
# ---------------------------------------------------------------------------


def fetch_listing_page(page):
    url = (
        f"{API_BASE_URL}/api/products"
        f"?section={SECTION_SLUG}&page={page}&size={PAGE_SIZE}"
    )
    return fetch_json(url, TMP_DIR / f"listing_page_{page}.json")


def fetch_product_detail(product_id):
    url = f"{API_BASE_URL}/api/products/{product_id}"
    return fetch_json(url, TMP_DIR / f"product_{product_id}.json")


def image_url_from(item):
    image = item.get("image") or ""
    if not image:
        return ""
    return urljoin(API_BASE_URL, image)


def row_from_listing_item(item, captured):
    row = base_row(captured)
    name = clean_text(item.get("name") or item.get("name_suggestion"))
    unit_size, size_format = infer_size(name)
    offer = item.get("offer") if isinstance(item.get("offer"), dict) else {}
    base_price = parse_number(item.get("base_price"))
    offer_price = parse_number(offer.get("price"))
    order_price = parse_number(item.get("order_price"))
    unit_price = offer_price or order_price or base_price
    price_decreased = "true" if offer_price and base_price and offer_price != base_price else ""

    product_id = str(item.get("id") or "")
    slug = clean_text(item.get("slug"))
    product_url = f"{BASE_URL}/product/{slug}" if slug else ""

    properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    pictograms = properties.get("pictograms") or []
    tags = [clean_text(p) for p in pictograms if clean_text(p)]

    observations = []
    image_url = image_url_from(item)
    if image_url:
        observations.append(f"Imagen frontal: {image_url}")
    if offer.get("description"):
        observations.append(f"Promocion: {clean_text(offer.get('description'))}")
    if tags:
        observations.append(f"Tags: {' | '.join(tags)}")

    row.update(
        {
            "product_id": product_id,
            "product_name": name,
            "brand": clean_text(item.get("brand_name")),
            "product_url": product_url,
            "packaging": name,
            "unit_size": unit_size,
            "size_format": size_format,
            "unit_name": clean_text(item.get("measurement_unit")),
            "total_units": "1",
            "approx_size": "true" if "aprox" in name.lower() else "",
            "unit_price": unit_price,
            "list_price": base_price,
            "reference_price": parse_number(item.get("measurement_unit_ratio")),
            "reference_format": clean_text(item.get("measurement_unit")),
            "price_decreased": price_decreased,
            "observaciones": " | ".join(observations),
        }
    )
    return row


def detail_from_product(product):
    details = product.get("details") if isinstance(product.get("details"), dict) else {}
    nutrition_list = product.get("nutritional_info") if isinstance(product.get("nutritional_info"), list) else []

    nutrition = {}
    pairs = []
    for item in nutrition_list:
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("infood_name"))
        quantity = item.get("quantity")
        unit = clean_text(item.get("measure_unit"))
        value = parse_number(quantity)
        pairs.append(f"{label}: {quantity} {unit}".strip())
        code = clean_text(item.get("infood_code")).upper()
        low = label.lower()
        if code == "FAT" or low == "grasas":
            nutrition["fat_g_100g"] = value
        elif code == "FASAT" or "saturad" in low:
            nutrition["sat_fat_g_100g"] = value
        elif code == "CHOAVL" or "hidratos de carbono" in low:
            nutrition["carbs_g_100g"] = value
        elif code == "SUGAR-" or "azúcar" in low or "azucar" in low:
            nutrition["sugars_g_100g"] = value
        elif code == "PRO-" or "proteína" in low or "proteina" in low:
            nutrition["protein_g_100g"] = value
        elif code == "SALTEQ" or low == "sal":
            nutrition["salt_g_100g"] = value
        elif code == "FIBTG" or "fibra" in low:
            nutrition["fiber_g_100g"] = value

    energy_kcal = parse_number(details.get("energy_Kcal"))
    energy_kj = parse_number(details.get("energy_KJ"))
    if energy_kcal:
        nutrition["energy_kcal_100g"] = energy_kcal
        pairs.insert(0, f"Energía (kcal): {details.get('energy_Kcal')}")
    if energy_kj:
        nutrition["energy_kj_100g"] = energy_kj
        pairs.insert(0, f"Energía (kJ): {details.get('energy_KJ')}")

    nutrition["nutrients_text"] = " | ".join(pairs)

    ean = clean_text(details.get("code"))
    ingredients_and_allergens = clean_text(details.get("ingredients_and_allergens"))
    allergens = clean_text(details.get("allergens"))
    origin = clean_text(details.get("country_of_origin") or details.get("country_of_origin_sentence"))
    storage = clean_text(details.get("conservation_conditions"))
    usage = clean_text(details.get("howto_use"))
    supplier = clean_text(details.get("operator_business_name"))
    legal_name = clean_text(details.get("denomination"))

    image_url = image_url_from(product)

    return {
        "ean": ean,
        "brand": clean_text(details.get("brand_name")) or clean_text(product.get("brand_name")),
        "legal_name": legal_name,
        "ingredients": ingredients_and_allergens,
        "allergens": allergens,
        "storage_instructions": storage,
        "usage_instructions": usage,
        "supplier_name": supplier,
        "origin": origin,
        "tipo_conservacion": storage,
        **nutrition,
        "back_image_url": image_url,
    }


def base_row(capture_datetime):
    return {
        "retailer": "Froiz",
        "source_system": "Froiz API publica listado+ficha (servicios.froiz.com)",
        "capture_datetime": capture_datetime,
        "parent_category_name": "Alimentación",
        "subcategory_name": "Platos preparados",
        "block_name": "Platos preparados",
        "category_path": CATEGORY_PATH,
        "categories_text": "Supermercado > Alimentación > Platos preparados",
        "is_pack": "",
        "pack_size": "",
        "is_variable_weight": "",
        "bulk_price": "",
        "price_decreased": "",
        "previous_unit_price": "",
        "legal_name": "",
        "description": "",
        "allergens": "",
        "origin": "",
        "tipo_plato": "",
        "subtipo_plato": "",
        "cocina": "",
        "base_carbohidrato": "",
        "proteina_principal": "",
        "proteina_secundaria": "",
        "vegetales_clave": "",
        "salsa_o_sazonado": "",
        "nivel_conveniencia": "",
        "posicionamiento": "",
        "healthy_vs_indulgente": "",
    }


def needs_detail(row):
    return not row.get("product_name") or not row.get("unit_price")


def save_rows(rows):
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows([{col: (row or {}).get(col, "") for col in COLUMNS} for row in rows if row])


def main():
    TMP_DIR.mkdir(exist_ok=True)
    captured = datetime.now(timezone.utc).isoformat()

    first_page = fetch_listing_page(1)
    stats = first_page.get("stats") or {}
    total_pages = int(stats.get("totalPages") or 1)
    print(f"PLP page=1 productTotal={stats.get('productTotal')} totalPages={total_pages}", flush=True)

    items_by_id = {}
    for item in first_page.get("products") or []:
        if item.get("id") is not None and not is_excluded_product(clean_text(item.get("name") or item.get("name_suggestion"))):
            items_by_id[item["id"]] = item

    for page in range(2, total_pages + 1):
        page_data = fetch_listing_page(page)
        items = page_data.get("products") or []
        print(f"PLP page={page} items={len(items)}", flush=True)
        for item in items:
            if item.get("id") is not None and not is_excluded_product(clean_text(item.get("name") or item.get("name_suggestion"))):
                items_by_id[item["id"]] = item
        time.sleep(0.25)

    products = list(items_by_id.values())
    rows = [None] * len(products)

    def build_row(idx_item):
        idx, item = idx_item
        row = row_from_listing_item(item, captured)
        product_id = item.get("id")
        dest = TMP_DIR / f"product_{product_id}.json"
        last_error = ""
        for attempt in range(1, 4):
            try:
                detail_json = fetch_product_detail(product_id)
                detail = detail_from_product(detail_json)
                for key, value in detail.items():
                    if value not in ("", None):
                        row[key] = value
                status = f"PDP {idx}/{len(products)} ok {product_id}"
                break
            except Exception as exc:
                last_error = str(exc)
                time.sleep(1.0 * attempt)
        else:
            row["observaciones"] = (
                (row.get("observaciones") + " | ") if row.get("observaciones") else ""
            ) + f"PDP pendiente: {last_error}"
            status = f"PDP {idx}/{len(products)} ERROR {product_id}: {last_error}"
        return idx, row, status

    workers = 8
    done_since_save = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(build_row, pair) for pair in enumerate(products, 1)]
        for future in as_completed(futures):
            idx, row, status = future.result()
            rows[idx - 1] = row
            done_since_save += 1
            print(status, flush=True)
            if done_since_save >= 20:
                save_rows(rows)
                done_since_save = 0

    save_rows(rows)

    filled_ingredients = sum(1 for row in rows if row.get("ingredients"))
    filled_nutrition = sum(1 for row in rows if row.get("energy_kcal_100g") or row.get("energy_kj_100g"))
    pending = sum(1 for row in rows if needs_detail(row))
    print(f"csv={OUT.resolve()}")
    print(f"rows={len(rows)} pages={total_pages}")
    print(f"pending_rows={pending}")
    print(f"ingredients_rows={filled_ingredients} nutrition_rows={filled_nutrition}")


if __name__ == "__main__":
    main()
