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


BASE_URL = "https://www.supermasymasonline.com"
CATEGORY_PATH = "/refrigerado-y-congelado/platos-preparados/"
CATEGORY_URL = BASE_URL + CATEGORY_PATH
CATEGORY_ID = "0303"
PAGE_SIZE = 24
GRID_UPDATE_PATH = "/on/demandware.store/Sites-Masymas-Site/es_ES/Search-UpdateGrid"
OUT = Path("masymas_modelo_comun.csv")
TMP_DIR = Path("_masymas_tmp")

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
    if os.environ.get("MASYMAS_OFFLINE_ONLY") == "1":
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


def extract_total_results(first_html):
    match = re.search(r"(\d+)\s+resultados", first_html)
    if match:
        return int(match.group(1))
    return None


def extract_pages(total_results):
    if not total_results:
        return [0]
    starts = list(range(0, total_results, PAGE_SIZE))
    return starts


def extract_product_links(page_html):
    products = {}
    for match in re.finditer(
        r'"@type":"ListItem","position":(\d+),"url":"(https?://[^"]+/([^/"]+)\.html)"',
        page_html,
    ):
        url = match.group(2).replace("\\/", "/")
        slug_ref = match.group(3)
        # slug_ref like "0045843" only for the reference part after last '/'; product_id is the
        # trailing path segment before .html
        product_id = slug_ref
        products[product_id] = {
            "product_id": product_id,
            "product_url": url,
        }
    if not products:
        # fallback: plain hrefs ending in /NNNNNNN.html
        for match in re.finditer(r'href="(/[^"]+/(\d{6,8}))\.html"', page_html):
            path, product_id = match.group(1), match.group(2)
            products[product_id] = {
                "product_id": product_id,
                "product_url": urljoin(BASE_URL, path + ".html"),
            }
    return list(products.values())


def extract_json_ld_product(page_html):
    match = re.search(
        r'<script type="application/ld\+json">\s*(\{"@context":"http://schema.org/","@type":"Product".*?\})\s*</script>',
        page_html,
        flags=re.S,
    )
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return {}


def _find_label_positions(page_html):
    """Return list of (start_of_label_text, end_of_label_tag, label_text) for every
    title-green-product-info label in document order, decoding HTML entities so
    accented Spanish labels can be matched literally."""
    positions = []
    for match in re.finditer(r'<p class="title-green-product-info">(.*?)</p>', page_html, flags=re.S):
        label = clean_text(match.group(1))
        positions.append((match.start(), match.end(), label))
    return positions


def extract_labelled_block(page_html, label):
    positions = _find_label_positions(page_html)
    for i, (_, end, lbl) in enumerate(positions):
        if lbl.lower() == label.lower():
            next_start = positions[i + 1][0] if i + 1 < len(positions) else len(page_html)
            segment = page_html[end:next_start]
            # stop at the closing </div> of the containing "value content" block if present
            div_close = re.search(r"</div>", segment)
            if div_close:
                segment = segment[: div_close.start()]
            return html_text(segment)
    return ""


def extract_allergens(page_html):
    return extract_labelled_block(page_html, "Alérgenos")


def extract_nutrition(page_html):
    out = {}
    block = re.search(
        r'<div id="nutritionalInfo"[^>]*>\s*<table[^>]*>(.*?)</table>',
        page_html,
        flags=re.S | re.I,
    )
    if not block:
        return out
    pairs = []
    for match in re.finditer(r"<tr[^>]*>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>", block.group(1), flags=re.S):
        label = html_text(match.group(1))
        value = html_text(match.group(2))
        low = label.lower()
        pairs.append(f"{label}: {value}")
        number = parse_number(value)
        if "energetico" in low or "energ" in low:
            if "kcal" in value.lower():
                out["energy_kcal_100g"] = number
            elif "kj" in value.lower():
                out["energy_kj_100g"] = number
        elif low == "grasas":
            out["fat_g_100g"] = number
        elif "saturad" in low:
            out["sat_fat_g_100g"] = number
        elif "hidratos de carbono" in low:
            out["carbs_g_100g"] = number
        elif "azucar" in low or "azúcar" in low:
            out["sugars_g_100g"] = number
        elif "proteina" in low or "proteína" in low:
            out["protein_g_100g"] = number
        elif low == "sal":
            out["salt_g_100g"] = number
        elif "fibra" in low:
            out["fiber_g_100g"] = number
    out["nutrients_text"] = " | ".join(pairs)
    return out


def detail_from_html(page_html, product_id, product_url):
    ld = extract_json_ld_product(page_html)

    title = ld.get("name", "")
    if not title:
        h1 = re.search(r'<h1[^>]*class="[^"]*product-name[^"]*"[^>]*>(.*?)</h1>', page_html, flags=re.S)
        if h1:
            title = html_text(h1.group(1))

    description = ld.get("description", "")

    brand = ""
    brand_obj = ld.get("brand")
    if isinstance(brand_obj, dict):
        brand = clean_text(brand_obj.get("name", ""))

    unit_price = ""
    offers = ld.get("offers")
    if isinstance(offers, dict) and offers.get("price"):
        unit_price = parse_number(offers.get("price"))
    if not unit_price:
        price_match = re.search(r'<p class="value[^"]*"\s+content="([\d.]+)"', page_html)
        if price_match:
            unit_price = parse_number(price_match.group(1))

    reference_price = ""
    reference_format = ""
    conv_match = re.search(r'conversion-factor">\s*El kilo le sale a\s*([\d.,]+)', page_html, flags=re.S)
    if conv_match:
        reference_price = parse_number(conv_match.group(1))
        reference_format = "kg"
    else:
        conv_match_l = re.search(r'conversion-factor">\s*El litro le sale a\s*([\d.,]+)', page_html, flags=re.S)
        if conv_match_l:
            reference_price = parse_number(conv_match_l.group(1))
            reference_format = "l"

    is_variable_weight = ""
    vw_match = re.search(r'data-variable-weight="(true|false)"', page_html)
    if vw_match:
        is_variable_weight = vw_match.group(1)

    unit_size, size_format = infer_size(title)

    supplier = extract_labelled_block(page_html, "Nombre del fabricante")
    ingredients = extract_labelled_block(page_html, "Descripción e ingredientes")
    storage = extract_labelled_block(page_html, "Instrucciones de conservación")
    allergens = extract_allergens(page_html)
    nutrition = extract_nutrition(page_html)

    return {
        "product_id": product_id,
        "ean": "",
        "product_name": title,
        "brand": brand,
        "product_url": product_url,
        "packaging": title,
        "unit_size": unit_size,
        "size_format": size_format,
        "unit_name": reference_format or size_format,
        "total_units": "1",
        "is_variable_weight": is_variable_weight,
        "unit_price": unit_price,
        "list_price": unit_price,
        "reference_price": reference_price,
        "reference_format": reference_format,
        "description": description,
        "ingredients": ingredients,
        "allergens": allergens,
        "storage_instructions": storage,
        "supplier_name": supplier,
        "nutrients_text": nutrition.get("nutrients_text", ""),
        "energy_kj_100g": nutrition.get("energy_kj_100g", ""),
        "energy_kcal_100g": nutrition.get("energy_kcal_100g", ""),
        "fat_g_100g": nutrition.get("fat_g_100g", ""),
        "sat_fat_g_100g": nutrition.get("sat_fat_g_100g", ""),
        "carbs_g_100g": nutrition.get("carbs_g_100g", ""),
        "sugars_g_100g": nutrition.get("sugars_g_100g", ""),
        "protein_g_100g": nutrition.get("protein_g_100g", ""),
        "salt_g_100g": nutrition.get("salt_g_100g", ""),
        "fiber_g_100g": nutrition.get("fiber_g_100g", ""),
        "tipo_conservacion": storage,
        "observaciones": "",
        "back_image_url": "",
    }


def base_row(capture_datetime):
    return {
        "retailer": "Masymas",
        "source_system": "Masymas HTML publico categoria+ficha",
        "capture_datetime": capture_datetime,
        "parent_category_name": "Refrigerado y congelado",
        "subcategory_name": "Platos preparados",
        "block_name": "Platos preparados",
        "category_path": CATEGORY_PATH,
        "categories_text": "Refrigerado y congelado > Platos preparados",
        "is_pack": "",
        "pack_size": "",
        "approx_size": "",
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
    first_html = fetch(CATEGORY_URL, TMP_DIR / "category_page_0.html", timeout=45)
    total_results = extract_total_results(first_html)
    starts = extract_pages(total_results)
    rows_by_id = {}

    for idx, start in enumerate(starts):
        if start == 0:
            page_html = first_html
        else:
            url = (
                f"{BASE_URL}{GRID_UPDATE_PATH}?cgid={CATEGORY_ID}&start={start}&sz={PAGE_SIZE}"
            )
            page_html = fetch(url, TMP_DIR / f"category_page_{start}.html", timeout=45)
        links = extract_product_links(page_html)
        print(f"PLP start={start} links={len(links)}", flush=True)
        for link in links:
            url = link.get("product_url", "")
            path_no_ext = url.rstrip("/")
            if path_no_ext.endswith(".html"):
                path_no_ext = path_no_ext[: -len(".html")]
            segments = path_no_ext.split("/")
            # URL shape: https://.../<name-slug>/<product_id>.html -- the name slug is the
            # second-to-last path segment (last segment is the numeric product id).
            slug = segments[-2] if len(segments) >= 2 else segments[-1]
            name_guess = clean_text(slug.replace("-", " "))
            if is_excluded_product(name_guess):
                continue
            rows_by_id[link["product_id"]] = link
        time.sleep(0.25)

    products = list(rows_by_id.values())
    rows = [None] * len(products)

    def build_row(idx_item):
        idx, item = idx_item
        row = base_row(captured)
        row.update(item)
        dest = TMP_DIR / f"pdp_{item['product_id']}.html"
        last_error = ""
        for attempt in range(1, 4):
            try:
                page_html = fetch(item["product_url"], dest, timeout=45)
                detail = detail_from_html(page_html, item["product_id"], item["product_url"])
                for key, value in detail.items():
                    if value not in ("", None):
                        row[key] = value
                if not needs_detail(row):
                    status = f"PDP {idx}/{len(products)} ok {item['product_id']}"
                    break
                last_error = "detalle descargado pero sin nombre/precio"
            except Exception as exc:
                last_error = str(exc)
            time.sleep(1.0 * attempt)
        else:
            row["observaciones"] = (
                (row.get("observaciones") + " | ") if row.get("observaciones") else ""
            ) + f"PDP pendiente: {last_error}"
            status = f"PDP {idx}/{len(products)} ERROR {item['product_id']}: {last_error}"
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
    print(f"rows={len(rows)} pages={len(starts)}")
    print(f"pending_rows={pending}")
    print(f"ingredients_rows={filled_ingredients} nutrition_rows={filled_nutrition}")


if __name__ == "__main__":
    main()
