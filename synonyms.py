import json
import logging
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from typing import List, Optional

logger = logging.getLogger("chollows.synonyms")

# Diccionari base d'expansió de termes tecnològics comuns
TECH_DICTIONARY = {
    "ps5": ["playstation 5", "sony ps5", "play 5", "ps5 slim", "sony playstation 5"],
    "playstation 5": ["ps5", "sony ps5", "playstation 5 slim", "sony playstation 5"],
    "ps4": ["playstation 4", "sony ps4", "play 4", "ps4 pro"],
    "switch": ["nintendo switch", "switch oled", "nintendo switch oled"],
    "nintendo switch": ["switch", "switch oled", "nintendo switch v2"],
    "xbox": ["xbox series x", "xbox series s", "microsoft xbox"],
    "xbox series x": ["series x", "xbox sx", "microsoft xbox series x"],
    "xbox series s": ["series s", "xbox ss", "microsoft xbox series s"],
    "steam deck": ["steamdeck", "valve steam deck", "steam deck oled"],
    "macbook": ["apple macbook", "macbook air", "macbook pro"],
    "macbook pro": ["mbp", "apple macbook pro", "macbook pro m1", "macbook pro m2", "macbook pro m3"],
    "macbook air": ["mba", "apple macbook air", "macbook air m1", "macbook air m2", "macbook air m3"],
    "ipad": ["apple ipad", "ipad pro", "ipad air"],
    "airpods": ["apple airpods", "airpods pro", "airpods max"],
    "airpods pro": ["airpods pro 2", "apple airpods pro"],
    "portatil": ["portàtil", "laptop", "notebook", "ordenador portatil"],
    "portàtil": ["portatil", "laptop", "notebook", "ordenador portatil"],
    "auriculars": ["auriculares", "cascos", "headphones"],
    "auriculares": ["auriculars", "cascos", "headphones"],
    "smartwatch": ["rellotge intel·ligent", "reloj inteligente", "smart watch"],
    "gpu": ["tarjeta grafica", "targeta gràfica", "placa de video"],
}


def remove_accents(text: str) -> str:
    """Elimina accents i diacrítics d'un text."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def generate_static_synonyms(product: str) -> List[str]:
    """
    Generador estàtic de sinònims i variants basat en regles heurístiques i diccionari.
    S'executa com a fallback d'alta fiabilitat si la Gemini API no està disponible.
    """
    variants = set()
    base = product.strip()
    norm_base = remove_accents(base.lower())

    # 1. Variant neta d'accents
    no_acc = remove_accents(base)
    if no_acc.lower() != base.lower():
        variants.add(no_acc)

    # 2. Consultem el diccionari de tecnologia per a coincidències exactes o parcials
    for key, values in TECH_DICTIONARY.items():
        if key in norm_base.split() or key == norm_base:
            for val in values:
                variants.add(val.title())

    # 3. Gestió de marques comunes (afegir o treure 'Apple', 'Sony', 'Nintendo', 'Samsung')
    brands = [
        ("apple", ["iphone", "ipad", "macbook", "airpods", "watch", "imac"]),
        ("sony", ["ps5", "playstation", "wh-1000xm", "bravia"]),
        ("nintendo", ["switch", "gameboy", "ds", "3ds"]),
        ("samsung", ["galaxy", "s24", "s23", "z flip", "z fold"]),
    ]
    for brand, terms in brands:
        has_brand = brand in norm_base
        if not has_brand and any(t in norm_base for t in terms):
            variants.add(f"{brand.capitalize()} {base}")
        elif has_brand:
            # Treure la marca
            without_brand = re.sub(rf"\b{brand}\b", "", base, flags=re.IGNORECASE).strip()
            if without_brand:
                variants.add(without_brand)

    # 4. Unir o separar números i lletres (ex: RTX4070 <-> RTX 4070, M2 <-> M 2)
    split_alphanum = re.sub(r"([a-zA-Z]+)(\d+)", r"\1 \2", base)
    if split_alphanum.lower() != base.lower():
        variants.add(split_alphanum)

    joined_alphanum = re.sub(r"([a-zA-Z]+)\s+(\d+)", r"\1\2", base)
    if joined_alphanum.lower() != base.lower():
        variants.add(joined_alphanum)

    # 5. Neteja de detalls de capacitat o configuració (ex: '128GB', '256 GB', '1TB')
    without_capacity = re.sub(r"\b\d+\s*(?:gb|tb|mb|ram)\b", "", base, flags=re.IGNORECASE).strip()
    if without_capacity and without_capacity.lower() != base.lower():
        variants.add(re.sub(r"\s+", " ", without_capacity))

    # 6. Neteja de paraules d'estat (nou, nuevo, usat, usado)
    without_status = re.sub(
        r"\b(nou|nuevo|nova|nueva|usat|usado|segona ma|segunda mano)\b",
        "",
        base,
        flags=re.IGNORECASE,
    ).strip()
    if without_status and without_status.lower() != base.lower():
        variants.add(re.sub(r"\s+", " ", without_status))

    # Filtrem i retornem variants no buides diferents del text original
    clean_list = [v.strip() for v in variants if v.strip() and v.strip().lower() != base.lower()]
    return clean_list[:6]


def generate_alternative_names(product: str, gemini_api_key: Optional[str] = None) -> List[str]:
    """
    Genera una llista d'alternatives de cerca intel·ligents per al producte.
    Crida a l'API de Gemini (Flash model) si hi ha clau disponible;
    en cas d'error o manca de quota, cau automàticament al generador estàtic.
    """
    api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "").strip()

    if not api_key:
        logger.info("GEMINI_API_KEY no configurada. S'utilitza el generador estàtic de regles.")
        return generate_static_synonyms(product)

    prompt = (
        f"Ets un expert en e-commerce i cerca d'ofertes i productes de segona mà a Espanya "
        f"(Wallapop, Chollometro, Amazon, eBay, PcComponentes).\n"
        f"Per al producte: \"{product}\", genera entre 4 i 7 variants intel·ligents de nom "
        f"que els usuaris o botigues solen fer servir en els seus anuncis.\n"
        f"Inclou:\n"
        f"- Sinònims comercials i marques (ex: 'PS5' -> 'PlayStation 5', 'Sony PS5')\n"
        f"- Abreviatures i sigles ('MacBook Pro' -> 'MBP')\n"
        f"- Variacions amb/sense espais o guions ('RTX 4070' -> 'RTX4070')\n"
        f"- Formes català/castellà/anglès\n"
        f"- Variants simplificades sense detalls concrets de GB o color per no perdre resultats.\n\n"
        f"Respon ÚNICAMENT amb un array JSON de cadenes de text (strings). "
        f"Exemple: [\"variant 1\", \"variant 2\", \"variant 3\"]"
    )

    models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash"]
    for model in models_to_try:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                },
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            text_resp = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            parsed = json.loads(text_resp)
            if isinstance(parsed, list) and len(parsed) > 0:
                variants = [str(item).strip() for item in parsed if str(item).strip()]
                # Deduplicació preservant ordre
                seen = {product.lower()}
                unique_variants = []
                for v in variants:
                    if v.lower() not in seen:
                        seen.add(v.lower())
                        unique_variants.append(v)

                if unique_variants:
                    logger.info(f"Gemini API ({model}) ha generat {len(unique_variants)} variants per a '{product}'")
                    return unique_variants
        except Exception as e:
            logger.warning(f"Error cridant Gemini API model {model}: {e}")
            continue

    logger.info("Fallades a l'API de Gemini. Executant fallback estàtic...")
    return generate_static_synonyms(product)
