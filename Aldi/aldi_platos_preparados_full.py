import csv
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen


BASE_URL = "https://www.aldi.es"
CATEGORY_PATH = "/productos/platos-preparados-y-pizza/platos-preparados-calientes.html"
CATEGORY_URL = BASE_URL + CATEGORY_PATH
OUT = Path("aldi_modelo_comun.csv")
TMP_DIR = Path("_aldi_tmp")

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
# Generic helpers (same pattern as Eroski/Froiz, copied verbatim).
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
    if os.environ.get("ALDI_OFFLINE_ONLY") == "1":
        return ""
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as response:
        data = response.read()
    dest.write_bytes(data)
    return data.decode("utf-8", errors="ignore")


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
# Aldi-specific access.
#
# www.aldi.es is a Next.js app (Magnolia CMS + Algolia search). The category
# page for a "platos preparados" subcategory embeds a
# <script id="__NEXT_DATA__"> tag with the full Algolia InstantSearch initial
# state (props.pageProps.algoliaState.initialResults[indexName].results[0].hits)
# containing ALL products for that category inline as JSON -- no extra
# request needed for the listing. hitsPerPage is set to 1000 server-side, so
# a single page fetch is enough for a category of this size.
#
# NOTE: WebFetch-style markdown conversion silently strips the <script> tag,
# so raw HTML must be fetched via urllib (as fetch() does here) and the JSON
# extracted with a regex against the raw bytes/text, never via a
# markdown-converted view of the page.
#
# Product detail pages (/producto/<slug>.html) were investigated for a
# richer detail API (nutrition/EAN/ingredients/allergens), since the PDP's
# own __NEXT_DATA__ generally renders an unrelated/empty Magnolia CMS
# apiData entry. In this case the PDP *did* include a populated
# "PRODUCT_DETAIL_GET" entry in props.pageProps.apiData, keyed by the
# numeric objectID/SKU (not the longer variantID) -- but its "res.products[0]"
# payload carries exactly the same fields already present in the listing hit
# (name, price, salesUnit, brandName, assets, descriptions, categoryIDs)
# and NOT nutrition/EAN/ingredients/allergens. A handful of guesses at REST
# endpoints (/api/product/<id>, /api/products/<id>, /rest/es/v1/products/<id>,
# /api/nutrition/<id>) all returned 404/308-to-nowhere-useful. No client-side
# nutrition/EAN/ingredients/allergens API was found within bounded effort, so
# this scraper only fetches the category listing JSON (no per-product PDP
# fetch loop) and leaves ean/ingredients/allergens/nutrition columns blank,
# same valid fallback pattern documented in this repo for retailers whose
# detail data isn't publicly reachable.
# ---------------------------------------------------------------------------


def extract_next_data(page_html):
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page_html, flags=re.S
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (ValueError, TypeError):
        return None


def extract_hits(next_data):
    try:
        page_props = next_data["props"]["pageProps"]
        algolia_state = page_props["algoliaState"]
        initial_results = algolia_state["initialResults"]
        index_name = page_props["algoliaConfig"]["indexName"]
        results = initial_results[index_name]["results"]
        return results[0]["hits"]
    except (KeyError, IndexError, TypeError):
        return []


def image_url_from(hit):
    assets = hit.get("assets") or []
    for asset in assets:
        if isinstance(asset, dict) and asset.get("type") == "primary" and asset.get("url"):
            return asset["url"]
    for asset in assets:
        if isinstance(asset, dict) and asset.get("url"):
            return asset["url"]
    return ""

def back_image_url_from(hit):
    assets = hit.get("assets") or []
    for asset in assets:
        if isinstance(asset, dict) and asset.get("type") == "gallery" and asset.get("url"):
            return asset["url"]
    return ""


def article_number_from(hit):
    for ref in hit.get("productReferences") or []:
        if isinstance(ref, dict) and ref.get("type") == "KVArticleNumber" and ref.get("value"):
            return clean_text(ref["value"])
    return ""


def row_from_hit(hit, captured):
    row = base_row(captured)
    name = clean_text(hit.get("name"))
    unit_size, size_format = infer_size(hit.get("salesUnit") or name)

    current_price = hit.get("currentPrice") if isinstance(hit.get("currentPrice"), dict) else {}
    unit_price = parse_number(current_price.get("priceValue"))
    base_prices = current_price.get("basePrice") if isinstance(current_price.get("basePrice"), list) else []
    reference_price, reference_format = "", ""
    if base_prices and isinstance(base_prices[0], dict):
        reference_price = parse_number(base_prices[0].get("basePriceValue"))
        reference_format = clean_text(base_prices[0].get("basePriceScale"))

    object_id = clean_text(hit.get("objectID"))
    slug = clean_text(hit.get("productSlug"))
    product_url = f"{BASE_URL}/producto/{slug}.html" if slug else ""

    categories = hit.get("hierarchicalCategories") if isinstance(hit.get("hierarchicalCategories"), dict) else {}
    lvl1 = categories.get("lvl1") or []
    categories_text = clean_text(lvl1[0]) if lvl1 else row.get("categories_text", "")

    description_parts = [
        clean_text(hit.get("shortDescription")),
        clean_text(hit.get("longDescription")),
    ]
    description = " | ".join(p for p in description_parts if p)

    article_number = article_number_from(hit)

    observations = []
    image_url = image_url_from(hit)
    if image_url:
        observations.append(f"Imagen frontal: {image_url}")
    if article_number:
        observations.append(f"KVArticleNumber: {article_number}")
    if hit.get("isAvailable") is False:
        observations.append("No disponible")

    row.update(
        {
            "product_id": object_id or article_number,
            "product_name": name,
            "brand": clean_text(hit.get("brandName")),
            "product_url": product_url,
            "packaging": clean_text(hit.get("salesUnit")) or name,
            "unit_size": unit_size,
            "size_format": size_format,
            "unit_name": clean_text(hit.get("salesUnit")),
            "total_units": "1",
            "approx_size": "true" if "aprox" in name.lower() else "",
            "unit_price": unit_price,
            "list_price": unit_price,
            "reference_price": reference_price,
            "reference_format": reference_format,
            "description": description,
            "categories_text": categories_text or row.get("categories_text", ""),
            "back_image_url": back_image_url_from(hit),
            "observaciones": " | ".join(observations),
        }
    )
    return row


def base_row(capture_datetime):
    return {
        "retailer": "Aldi",
        "source_system": "Aldi Algolia JSON embebido en categoria (Next.js __NEXT_DATA__)",
        "capture_datetime": capture_datetime,
        "parent_category_name": "Platos preparados y pizza",
        "subcategory_name": "Platos preparados calientes",
        "block_name": "Platos preparados calientes",
        "category_path": CATEGORY_PATH,
        "categories_text": "Platos preparados y pizzas > Platos preparados calientes",
        "is_pack": "",
        "pack_size": "",
        "is_variable_weight": "",
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
        "ean": "",
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

    page_html = fetch(CATEGORY_URL, TMP_DIR / "category_page_0.html", timeout=45)
    next_data = extract_next_data(page_html)
    hits = extract_hits(next_data) if next_data else []
    print(f"PLP hits={len(hits)}", flush=True)

    rows_by_id = {}
    excluded = 0
    for hit in hits:
        name = clean_text(hit.get("name"))
        if is_excluded_product(name):
            excluded += 1
            continue
        object_id = clean_text(hit.get("objectID")) or clean_text(hit.get("productSlug"))
        if not object_id:
            continue
        rows_by_id[object_id] = row_from_hit(hit, captured)

    rows = list(rows_by_id.values())
    save_rows(rows)

    filled_ingredients = sum(1 for row in rows if row.get("ingredients"))
    filled_nutrition = sum(1 for row in rows if row.get("energy_kcal_100g") or row.get("energy_kj_100g"))
    pending = sum(1 for row in rows if needs_detail(row))
    print(f"csv={OUT.resolve()}")
    print(f"rows={len(rows)} excluded_by_filter={excluded}")
    print(f"pending_rows={pending}")
    print(f"ingredients_rows={filled_ingredients} nutrition_rows={filled_nutrition}")


if __name__ == "__main__":
    main()
