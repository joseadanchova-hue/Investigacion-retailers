import csv
import html
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


BASE_URL = "https://supermercado.eroski.es"
CATEGORY_PATH = "/es/supermercado/2059698-frescos/2059769-platos-preparados/"
CATEGORY_URL = BASE_URL + CATEGORY_PATH
OUT = Path("eroski_modelo_comun.csv")
TMP_DIR = Path("_eroski_tmp")

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
    if os.environ.get("EROSKI_OFFLINE_ONLY") == "1":
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


def infer_size(name):
    text = (name or "").lower().replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|kilo|g|gr|gramos|ml|l|litro|ud|uds)\b", text)
    if not match:
        return "", ""
    unit = match.group(2)
    unit = {"gr": "g", "gramos": "g", "kilo": "kg", "litro": "l", "uds": "ud"}.get(unit, unit)
    return match.group(1), unit


def reference_from_quantity(text):
    clean = clean_text(text).lower()
    match = re.search(r"1\s*(kilo|kg|litro|l|unidad|ud)\s*a\s*([\d.,]+)", clean)
    if not match:
        return "", ""
    unit = {"kilo": "kg", "litro": "l", "unidad": "ud"}.get(match.group(1), match.group(1))
    return parse_number(match.group(2)), unit


def extract_pages(first_html):
    pages = {0}
    for match in re.finditer(r"pageNumber=(\d+)", first_html):
        pages.add(int(match.group(1)))
    return sorted(pages)


def extract_product_links(page_html):
    products = {}
    pattern = re.compile(r'https?://supermercado\.eroski\.es(?::443)?/es/productdetail/(\d+)-([^"/?#]+)/(?:\?[^"]*)?')
    for match in pattern.finditer(page_html):
        product_id, slug = match.group(1), match.group(2)
        products[product_id] = {
            "product_id": product_id,
            "slug": slug,
            "product_url": f"{BASE_URL}/es/productdetail/{product_id}-{slug}/",
        }
    relative = re.compile(r'/es/productdetail/(\d+)-([^"/?#]+)/(?:\?[^"]*)?')
    for match in relative.finditer(page_html):
        product_id, slug = match.group(1), match.group(2)
        products[product_id] = {
            "product_id": product_id,
            "slug": slug,
            "product_url": f"{BASE_URL}/es/productdetail/{product_id}-{slug}/",
        }
    return list(products.values())


def extract_feature_text(page_html, class_name):
    match = re.search(
        rf'<div[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"[^>]*>.*?'
        r'<span class="title">.*?</span>\s*<p class="text">(.*?)</p>',
        page_html,
        flags=re.S,
    )
    return html_text(match.group(1)) if match else ""


def extract_feature_by_title(page_html, title):
    match = re.search(
        rf'<span class="title">\s*{re.escape(title)}\s*</span>\s*<p class="text">(.*?)</p>',
        page_html,
        flags=re.S | re.I,
    )
    return html_text(match.group(1)) if match else ""


def extract_company(page_html):
    block = re.search(r'feature-text feature-company.*?</div>\s*</div>\s*</div>', page_html, flags=re.S)
    if not block:
        return ""
    texts = [html_text(x) for x in re.findall(r'<p class="text">(.*?)</p>', block.group(0), flags=re.S)]
    texts = [x for x in texts if x and x.lower() not in {"nombre", "direccion", "dirección"}]
    return " | ".join(texts)


def extract_nutrition(page_html):
    out = {}
    block = re.search(
        r'<span class="title">\s*Información Nutricional\s*</span>\s*<ul class="list">(.*?)</ul>',
        page_html,
        flags=re.S | re.I,
    )
    if not block:
        return out
    pairs = []
    energy_seen = 0
    for match in re.finditer(r"<li>(.*?)<span>(.*?)</span>\s*</li>", block.group(1), flags=re.S):
        label = html_text(match.group(1))
        value = html_text(match.group(2))
        low = label.lower()
        pairs.append(f"{label}: {value}")
        number = parse_number(value)
        if low == "energía" or low == "energia":
            energy_seen += 1
            if "kilojulio" in value.lower() or energy_seen == 2:
                out["energy_kj_100g"] = number
            elif "kilocal" in value.lower() or energy_seen == 1:
                out["energy_kcal_100g"] = number
        elif low == "grasas":
            out["fat_g_100g"] = number
        elif "saturad" in low:
            out["sat_fat_g_100g"] = number
        elif low == "hidratos de carbono":
            out["carbs_g_100g"] = number
        elif "azúcar" in low or "azucar" in low:
            out["sugars_g_100g"] = number
        elif "proteína" in low or "proteina" in low:
            out["protein_g_100g"] = number
        elif low == "sal":
            out["salt_g_100g"] = number
        elif "fibra" in low:
            out["fiber_g_100g"] = number
    out["nutrients_text"] = " | ".join(pairs)
    return out


def detail_from_html(page_html, product_id, product_url):
    title = ""
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, flags=re.S)
    if h1:
        title = html_text(h1.group(1))
    if not title:
        img = re.search(rf'<img[^>]+(?:alt|title)="([^"]*{re.escape(product_id)}[^"]*)"', page_html, flags=re.S)
        if img:
            title = clean_text(img.group(1))
    if not title:
        img = re.search(rf'<img[^>]+(?:alt|title)="([^"]+)"[^>]+src="[^"]*/images/{re.escape(product_id)}\.jpg"', page_html, flags=re.S)
        if img:
            title = clean_text(img.group(1))

    unit_price = ""
    price_match = re.search(r'<span[^>]*itemprop="price"[^>]*class="offer-now"[^>]*>(.*?)</span>', page_html, flags=re.S)
    if price_match:
        unit_price = parse_number(price_match.group(1))

    quantity_match = re.search(r'<p class="quantity-text">(.*?)</p>', page_html, flags=re.S)
    reference_price, reference_format = reference_from_quantity(quantity_match.group(1) if quantity_match else "")

    image_url = ""
    image_match = re.search(r'data-product-img="([^"]+)"', page_html)
    if image_match:
        image_url = urljoin(BASE_URL, html.unescape(image_match.group(1)))
    if not image_url:
        image_url = f"{BASE_URL}/images/{product_id}.jpg"

    brand = ""
    metric_brand = re.search(r'&quot;item_brand&quot;:&quot;([^"&]+)&quot;', page_html)
    if metric_brand:
        brand = clean_text(metric_brand.group(1))
    elif title:
        for token in ("EROSKI SELEQTIA", "EROSKI", "AMEZTOI", "ALBIZABAL", "COCINA MAGUI", "LA COCINA DEL NORTE", "OTAR"):
            if token.lower() in title.lower():
                brand = token
                break

    unit_size, size_format = infer_size(title)
    nutrition = extract_nutrition(page_html)
    ingredients = extract_feature_text(page_html, "feature-text-ingredients")
    storage = extract_feature_text(page_html, "feature-text-preservation")
    usage = extract_feature_text(page_html, "feature-instruction")
    supplier = extract_company(page_html)

    observations = []
    if image_url:
        observations.append(f"Imagen frontal: {image_url}")
    observations.append(f"input value: {product_id}-{product_url.rstrip('/').split('/')[-1].split('-', 1)[1] if '-' in product_url else ''}")

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
        "approx_size": "true" if "aprox" in title.lower() else "",
        "unit_price": unit_price,
        "list_price": unit_price,
        "reference_price": reference_price,
        "reference_format": reference_format,
        "ingredients": ingredients,
        "storage_instructions": storage,
        "usage_instructions": usage,
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
        "observaciones": " | ".join(observations),
        "back_image_url": "",
    }


def base_row(capture_datetime):
    return {
        "retailer": "Eroski",
        "source_system": "Eroski HTML publico categoria+ficha",
        "capture_datetime": capture_datetime,
        "parent_category_name": "Frescos",
        "subcategory_name": "Platos preparados",
        "block_name": "Platos preparados",
        "category_path": CATEGORY_PATH,
        "categories_text": "Supermercado > Frescos > Platos preparados",
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
    first_html = fetch(CATEGORY_URL, TMP_DIR / "category_page_0.html", timeout=45)
    pages = extract_pages(first_html)
    rows_by_id = {}

    for page in pages:
        url = CATEGORY_URL if page == 0 else CATEGORY_URL + f"?pageNumber={page}"
        page_html = first_html if page == 0 else fetch(url, TMP_DIR / f"category_page_{page}.html", timeout=45)
        links = extract_product_links(page_html)
        print(f"PLP page={page} links={len(links)}", flush=True)
        for link in links:
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
    print(f"rows={len(rows)} pages={len(pages)}")
    print(f"pending_rows={pending}")
    print(f"ingredients_rows={filled_ingredients} nutrition_rows={filled_nutrition}")


if __name__ == "__main__":
    main()
