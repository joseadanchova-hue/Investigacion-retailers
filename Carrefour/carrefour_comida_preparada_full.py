import csv
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = "https://www.carrefour.es"
CATEGORY_URL = BASE_URL + "/supermercado/frescos/comida-preparada/cat20016/c"
OUT = Path("carrefour_modelo_comun.csv")
TMP_DIR = Path("_carrefour_tmp")

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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": CATEGORY_URL,
    "Connection": "keep-alive",
    "sale_point": "005290",
    "postal_code": "28232",
    "delivery_type": "A_DOMICILIO",
    "Cookie": os.environ.get(
        "CARREFOUR_COOKIE",
        "session_id=; JSESSIONID=; JSESSIONID_ALI11=; PROFILE_ID=",
    ),
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


def fetch(url, dest):
    if dest.exists() and dest.stat().st_size > 10000:
        return dest.read_text(encoding="utf-8", errors="ignore")
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=45) as response:
        data = response.read()
    dest.write_bytes(data)
    return data.decode("utf-8", errors="ignore")


def fetch_json(url, dest):
    if dest.exists() and dest.stat().st_size > 1000:
        return json.loads(dest.read_text(encoding="utf-8", errors="ignore"))
    req = Request(url, headers={**HEADERS, "Accept": "application/json, text/plain, */*"})
    with urlopen(req, timeout=45) as response:
        data = response.read()
    dest.write_bytes(data)
    return json.loads(data.decode("utf-8", errors="ignore"))


def fetch_plp_api(offset):
    url = (
        BASE_URL
        + "/cloud-api/plp-food-papi/v1/supermercado/frescos/comida-preparada/cat20016/c"
        + f"?offset={offset}&platform=desktop&maxRefLevel=3&preview=false"
    )
    return fetch_json(url, TMP_DIR / f"plp_api_offset{offset}.json")


def extract_state(page_html):
    marker = "window.__INITIAL_STATE__="
    start = page_html.find(marker)
    if start < 0:
        raise RuntimeError("No window.__INITIAL_STATE__ marker")
    after = page_html[start + len(marker) :]
    ends = [pos for pos in (after.find(";(function()"), after.find(";</script>")) if pos >= 0]
    if not ends:
        raise RuntimeError("No initial state terminator")
    return json.loads(after[: min(ends)])


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
    match = re.search(r"(\d+(?:\.\d+)?)\s*(kg|g|gr|ml|l|ud)\b", text)
    if not match:
        return "", ""
    unit = "g" if match.group(2) == "gr" else match.group(2)
    return match.group(1), unit


def find_first(obj, keys):
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] not in (None, "", [], {}):
                return obj[key]
        for value in obj.values():
            found = find_first(value, keys)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = find_first(value, keys)
            if found not in (None, "", [], {}):
                return found
    return None


def nutrition_from_html(page_html):
    out = {}
    graph = re.search(r'<div\b([^>]*class="[^"]*nutrition-graph__graphic-svg[^"]*"[^>]*)>', page_html)
    if graph:
        attrs = dict(re.findall(r'data-([a-z]+)="([^"]*)"', graph.group(1)))
        out.update(
            {
                "energy_kcal_100g": parse_number(attrs.get("cal")),
                "energy_kj_100g": parse_number(attrs.get("kj")),
                "fat_g_100g": parse_number(attrs.get("fa")),
                "carbs_g_100g": parse_number(attrs.get("h")),
                "protein_g_100g": parse_number(attrs.get("p")),
                "salt_g_100g": parse_number(attrs.get("s")),
                "fiber_g_100g": parse_number(attrs.get("fi")),
            }
        )
    labels = {
        "de las cuales Saturadas": "sat_fat_g_100g",
        "de las cuales Azúcares": "sugars_g_100g",
        "de las cuales AzÃºcares": "sugars_g_100g",
    }
    for label, column in labels.items():
        pos = page_html.find(label)
        if pos >= 0:
            snippet = page_html[pos : pos + 450]
            match = re.search(r'nutrition-legend__fright">\s*([^<]+)', snippet)
            if match:
                out[column] = parse_number(match.group(1))
    return out


def flatten_more_info(groups):
    more = {}
    if not isinstance(groups, list):
        return more
    for group in groups:
        if not isinstance(group, dict):
            continue
        name = clean_text(group.get("nombre"))
        value = clean_text(group.get("valor"))
        if name and value:
            more[name] = value
        for item in group.get("listaInfo") or []:
            if isinstance(item, dict):
                item_name = clean_text(item.get("nombre"))
                item_value = clean_text(item.get("valor"))
                if item_name and item_value:
                    more[item_name] = item_value
    return more


def extract_more_info(page_html):
    more = {}
    for container in re.findall(
        r'<div class="nutrition-more-info__container">(.*?)</div></div>',
        page_html,
        flags=re.S,
    ):
        title_match = re.search(r'<p class="info-title">\s*(.*?)\s*</p>', container, flags=re.S)
        if not title_match:
            continue
        title = html_text(title_match.group(1))
        list_pairs = re.findall(
            r'class="nutrition-more-info__list-name">\s*(.*?)\s*</span>\s*'
            r'<span class="nutrition-more-info__list-value">\s*(.*?)\s*</span>',
            container,
            flags=re.S,
        )
        if list_pairs:
            for name, value in list_pairs:
                more[html_text(name).rstrip(":")] = html_text(value)
            continue
        txt_match = re.search(r'<p class="info-txt">\s*(.*?)\s*</p>', container, flags=re.S)
        if txt_match:
            more[title] = html_text(txt_match.group(1))
    return more


def detail_from_product_html(page_html):
    state = extract_state(page_html)
    product = ((state.get("pdp") or {}).get("product") or find_first(state, ["productData"]) or {})
    product = product if isinstance(product, dict) else {}
    offer = product.get("offer") if isinstance(product.get("offer"), dict) else {}
    nutrition = (
        product.get("nutrition")
        if isinstance(product.get("nutrition"), dict)
        else product.get("nutrition_info")
        if isinstance(product.get("nutrition_info"), dict)
        else {}
    )
    refactored = product.get("refactored_values") if isinstance(product.get("refactored_values"), dict) else {}
    more = extract_more_info(page_html)
    more.update(flatten_more_info(nutrition.get("masInfo")))
    more.update(flatten_more_info(nutrition.get("masInfoInforme")))
    ingredients = clean_text(refactored.get("ingredientes") or nutrition.get("ingredientes"))
    if not ingredients:
        match = re.search(
            r'nutrition-ingredients__content">(.*?)</p>',
            page_html,
            flags=re.S,
        )
        ingredients = html_text(match.group(1)) if match else ""
    nutrition_html = nutrition_from_html(page_html)
    energy = nutrition.get("valorEnergetico") if isinstance(nutrition.get("valorEnergetico"), dict) else {}
    fat = nutrition.get("grasas") if isinstance(nutrition.get("grasas"), dict) else {}
    carbs = nutrition.get("hidratos") if isinstance(nutrition.get("hidratos"), dict) else {}
    protein = nutrition.get("proteinas") if isinstance(nutrition.get("proteinas"), dict) else {}
    salt = nutrition.get("sal") if isinstance(nutrition.get("sal"), dict) else {}
    state_nutrition = {
        "energy_kcal_100g": parse_number((energy.get("kilocalorias") or {}).get("valor") if isinstance(energy.get("kilocalorias"), dict) else ""),
        "energy_kj_100g": parse_number((energy.get("kilojulios") or {}).get("valor") if isinstance(energy.get("kilojulios"), dict) else ""),
        "fat_g_100g": parse_number(fat.get("valor")),
        "carbs_g_100g": parse_number(carbs.get("valor")),
        "protein_g_100g": parse_number(protein.get("valor")),
        "salt_g_100g": parse_number(salt.get("valor")),
    }
    for item in fat.get("listaInfo") or []:
        if isinstance(item, dict) and "satur" in clean_text(item.get("nombre")).lower():
            state_nutrition["sat_fat_g_100g"] = parse_number(item.get("valor"))
    for item in carbs.get("listaInfo") or []:
        if isinstance(item, dict) and ("az" in clean_text(item.get("nombre")).lower()):
            state_nutrition["sugars_g_100g"] = parse_number(item.get("valor"))
    for key, value in state_nutrition.items():
        if value:
            nutrition_html[key] = value
    more_info_text = " | ".join(f"{k}: {v}" for k, v in more.items() if v)
    allergens = []
    alerg = nutrition.get("alergenos") if isinstance(nutrition.get("alergenos"), dict) else {}
    for label, key in (("Contiene", "contiene"), ("Puede contener", "puedeContener")):
        if alerg.get(key):
            allergens.append(f"{label}: {clean_text(alerg.get(key))}")
    legal_name = more.get("Denominación legal") or more.get("DenominaciÃ³n legal") or ""
    storage = more.get("Condiciones de conservación") or more.get("Condiciones de conservaciÃ³n") or ""
    usage = more.get("Modo de empleo") or more.get("Preparación") or more.get("PreparaciÃ³n") or ""
    origin = more.get("País de origen") or more.get("PaÃ­s de origen") or more.get("Origen") or ""
    brand_raw = product.get("brand")
    brand = brand_raw.get("description") if isinstance(brand_raw, dict) else clean_text(brand_raw)
    images = product.get("images") if isinstance(product.get("images"), list) else []
    large_images = [img.get("large") for img in images if isinstance(img, dict) and img.get("large")]
    return {
        "ean": clean_text(product.get("ean")),
        "brand": clean_text(brand),
        "unit_price": parse_number(offer.get("price")),
        "reference_price": parse_number(offer.get("price_per_unit")),
        "ingredients": ingredients,
        "allergens": " | ".join(allergens),
        "nutrients_text": more_info_text,
        "legal_name": legal_name,
        "storage_instructions": storage,
        "usage_instructions": usage,
        "origin": origin,
        "description": clean_text(product.get("description")),
        "back_image_url": large_images[1] if len(large_images) > 1 else "",
        "is_variable_weight": str(product.get("variable_weight")).lower()
        if product.get("variable_weight") is not None
        else "",
        "subtipo_plato": more.get("Tipo de producto de platos preparados", ""),
        "tipo_plato": more.get("Producto platos preparados", ""),
        "tipo_conservacion": storage,
        **nutrition_html,
    }


def rows_from_listing(state, capture_datetime):
    results = ((state.get("productCardList") or {}).get("results") or {})
    items = results.get("items") or []
    rows = []
    for item in items:
        name = clean_text(item.get("name"))
        unit_size, size_format = infer_size(name)
        images = item.get("images") if isinstance(item.get("images"), dict) else {}
        badge = item.get("badge") if isinstance(item.get("badge"), dict) else {}
        tags = []
        for tag in item.get("info_tags") or []:
            if isinstance(tag, dict) and tag.get("message"):
                tags.append(clean_text(tag.get("message")))
        observations = " | ".join(
            x
            for x in [
                f"Promocion: {clean_text(badge.get('name'))}" if badge.get("name") else "",
                clean_text(badge.get("description")),
                f"Tags: {' | '.join(tags)}" if tags else "",
                f"Imagen frontal: {images.get('desktop')}" if images.get("desktop") else "",
                f"sku_id: {item.get('sku_id')}" if item.get("sku_id") else "",
            ]
            if x
        )
        rows.append(
            {
                "retailer": "Carrefour",
                "source_system": "Carrefour HTML publico categoria+ficha",
                "capture_datetime": capture_datetime,
                "product_id": clean_text(item.get("product_id")),
                "ean": "",
                "product_name": name,
                "brand": clean_text(item.get("brand")),
                "product_url": urljoin(BASE_URL, item.get("url") or ""),
                "parent_category_name": "Frescos",
                "subcategory_name": "Comida Preparada",
                "block_name": "Comida Preparada",
                "category_path": "/supermercado/frescos/comida-preparada/cat20016/c",
                "categories_text": "Supermercado > Frescos > Comida Preparada",
                "packaging": name,
                "unit_size": unit_size,
                "size_format": size_format,
                "is_pack": "",
                "pack_size": "",
                "unit_name": clean_text(item.get("measure_unit")),
                "total_units": clean_text(item.get("sell_pack_unit")),
                "approx_size": "true" if "aprox" in name.lower() else "",
                "is_variable_weight": "",
                "unit_price": parse_number(item.get("price")),
                "list_price": parse_number(item.get("app_price")),
                "reference_price": parse_number(item.get("price_per_unit")),
                "reference_format": clean_text(item.get("measure_unit")),
                "bulk_price": "",
                "price_decreased": "true" if badge.get("name") else "",
                "previous_unit_price": "",
                "legal_name": "",
                "description": "",
                "ingredients": "",
                "allergens": " | ".join(tags),
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
                "observaciones": observations,
                "back_image_url": "",
            }
        )
    pagination = results.get("pagination") or {}
    return rows, int(pagination.get("total_results") or 0), int(pagination.get("page_size") or 24)


def main():
    TMP_DIR.mkdir(exist_ok=True)
    captured = datetime.now(timezone.utc).isoformat()
    try:
        first_api = fetch_plp_api(0)
        first_state = {"productCardList": {"results": first_api.get("results") or {}}}
        first_rows, total, page_size = rows_from_listing(first_state, captured)
    except HTTPError as exc:
        if exc.code != 403 or not (TMP_DIR / "cat20016.html").exists():
            raise
        print("PLP offset=0 using cached public HTML because live API returned 403", flush=True)
        first_html = (TMP_DIR / "cat20016.html").read_text(encoding="utf-8", errors="ignore")
        first_state = extract_state(first_html)
        first_rows, total, page_size = rows_from_listing(first_state, captured)
    offsets = list(range(0, max(total, len(first_rows)), page_size or 24))
    rows_by_key = {}
    for offset in offsets:
        if offset == 0:
            state = first_state
        else:
            api_page = fetch_plp_api(offset)
            state = {"productCardList": {"results": api_page.get("results") or {}}}
        rows, _, _ = rows_from_listing(state, captured)
        print(f"PLP offset={offset} rows={len(rows)}", flush=True)
        for row in rows:
            rows_by_key[(row["product_id"], row["product_url"])] = row
        time.sleep(0.35)

    rows = list(rows_by_key.values())
    for idx, row in enumerate(rows, 1):
        slug = re.sub(r"[^0-9A-Za-z_-]+", "_", row["product_id"] or str(idx))
        dest = TMP_DIR / f"pdp_{slug}.html"
        try:
            detail = detail_from_product_html(fetch(row["product_url"], dest))
            for key, value in detail.items():
                if value not in ("", None):
                    row[key] = value
            print(f"PDP {idx}/{len(rows)} ok {row['product_id']}", flush=True)
        except Exception as exc:
            row["observaciones"] = (row["observaciones"] + " | " if row["observaciones"] else "") + f"PDP error: {exc}"
            print(f"PDP {idx}/{len(rows)} ERROR {row['product_id']}: {exc}", flush=True)
        time.sleep(0.35)

    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows([{col: row.get(col, "") for col in COLUMNS} for row in rows])

    filled_ingredients = sum(1 for row in rows if row.get("ingredients"))
    filled_nutrition = sum(1 for row in rows if row.get("energy_kcal_100g"))
    print(f"csv={OUT.resolve()}")
    print(f"rows={len(rows)} expected_total={total}")
    print(f"ingredients_rows={filled_ingredients} nutrition_rows={filled_nutrition}")


if __name__ == "__main__":
    main()
