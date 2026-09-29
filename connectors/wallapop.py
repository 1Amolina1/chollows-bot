import inspect
import json
import logging
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from .base import BaseConnector, Deal

logger = logging.getLogger("chollows.wallapop")

# Diccionari de coordenades geogràfiques per a ciutats principals
DEFAULT_COORDINATES: Dict[str, Tuple[float, float]] = {
    "barcelona": (41.3874, 2.1686),
    "girona": (41.9794, 2.8214),
    "tarragona": (41.1189, 1.2445),
    "lleida": (41.6176, 0.6200),
    "madrid": (40.4168, -3.7038),
    "valencia": (39.4699, -0.3763),
    "valència": (39.4699, -0.3763),
    "zaragoza": (41.6488, -0.8891),
    "sevilla": (37.3891, -5.9845),
    "bilbao": (43.2630, -2.9350),
    "palma": (39.5696, 2.6502),
}


class WallapopConnector(BaseConnector):
    """
    Connector per a Wallapop amb filtratge per geolocalització i data:
    - Utilitza la llibreria 'wallapy' passant explícitament latitude, longitude,
      max_price, order_by='price_low_to_high' i time_filter='today'.
    - Crida a la URL de cerca interna:
      {base}/search?keywords=...&latitude=...&longitude=...&max_sale_price=...&order_by=price_low_to_high&time_filter=today
    - Fallback resilient d'alta disponibilitat en cas de bloqueig perimetral.
    """

    BASE_API_URL = "https://api.wallapop.com/api/v3/general/search"

    def __init__(
        self,
        city: str = "Barcelona",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ):
        self.city = city.strip()
        city_lower = self.city.lower()

        # Resolució de coordenades
        if latitude is not None and longitude is not None:
            self.latitude = float(latitude)
            self.longitude = float(longitude)
        elif city_lower in DEFAULT_COORDINATES:
            self.latitude, self.longitude = DEFAULT_COORDINATES[city_lower]
        else:
            # Per defecte: Barcelona (lat: 41.3874, lon: 2.1686)
            self.latitude = 41.3874
            self.longitude = 2.1686

        logger.info(
            f"WallapopConnector configurat per a ciutat '{self.city}' "
            f"(lat: {self.latitude}, lon: {self.longitude})"
        )

    @property
    def name(self) -> str:
        return "Wallapop"

    def search(self, product: str, alternative_names: List[str], max_price: float) -> List[Deal]:
        deals: List[Deal] = []
        seen_urls = set()

        # Reunim la llista de termes de cerca (producte principal + variants intel·ligents)
        queries = [product] + [name for name in alternative_names if name.lower() != product.lower()]
        queries = queries[:5]

        for query in queries:
            try:
                results = self._search_single_query(query, max_price)
                for deal in results:
                    if deal.url not in seen_urls and deal.price <= max_price:
                        seen_urls.add(deal.url)
                        deals.append(deal)
            except Exception as e:
                logger.warning(f"Error buscant a Wallapop per a '{query}': {e}")
                continue

        return deals

    def _search_single_query(self, query: str, max_price: float) -> List[Deal]:
        # 1. Intentem amb la llibreria wallapy (passant latitude, longitude, time_filter='today', etc.)
        try:
            results = self._search_via_wallapy(query, max_price)
            if results:
                return results
        except Exception as e:
            logger.info(f"wallapy no disponible o ha fallat ({e}). Provant API interna...")

        # 2. Intentem amb la URL de cerca interna de Wallapop amb latitude, longitude i time_filter='today'
        try:
            results = self._search_via_api(query, max_price)
            if results:
                return results
        except Exception as e:
            logger.info(f"API interna Wallapop ha fallat ({e}). Usant fallback indexat...")

        # 3. Fallback d'alta resiliència via anuncis indexats
        return self._search_via_indexed_listings(query, max_price)

    def _search_via_wallapy(self, query: str, max_price: float) -> List[Deal]:
        """
        Cerca mitjançant la llibreria wallapy passant explícitament:
        - latitude i longitude de la ciutat configurada
        - max_price des de la llista de seguiment
        - order_by='price_low_to_high'
        - time_filter='today' per a anuncis recents
        """
        from wallapy import check_wallapop

        keywords = query.split()
        excluded = ["roto", "reparar", "despiece", "funda", "caja vacia", "bloqueado", "icloud"]

        kwargs = {
            "product_name": query,
            "keywords": keywords,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "min_price": 1,
            "max_price": int(max_price),
            "order_by": "price_low_to_high",
            "time_filter": "today",
            "excluded_keywords": excluded,
            "max_total_items": 15,
        }

        # Inspecció flexible per si la versió de wallapy té paràmetres lleugerament adaptats
        try:
            results = check_wallapop(**kwargs)
        except TypeError:
            sig = inspect.signature(check_wallapop)
            valid_args = {k: v for k, v in kwargs.items() if k in sig.parameters}
            results = check_wallapop(**valid_args)

        deals = []
        if not results:
            return deals

        for item in results:
            title = item.get("title", "")
            price = float(item.get("price", 0.0))
            web_slug = item.get("web_slug", "")
            item_id = str(item.get("id", web_slug))
            url = f"https://es.wallapop.com/item/{web_slug}" if web_slug else item.get("url", "")
            location = item.get("city", "") or self.city

            if price > 0 and price <= max_price and url:
                deals.append(
                    Deal(
                        title=title,
                        price=price,
                        url=url,
                        source=self.name,
                        deal_id=f"wallapop_{item_id}",
                        location=location,
                    )
                )
        return deals

    def _search_via_api(self, query: str, max_price: float) -> List[Deal]:
        """
        Crida a la URL de cerca interna de Wallapop:
        {base}/search?keywords=...&latitude=...&longitude=...&max_sale_price=...&order_by=price_low_to_high&time_filter=today
        """
        params = {
            "keywords": query,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "max_sale_price": int(max_price),
            "order_by": "price_low_to_high",
            "time_filter": "today",
        }
        url = f"{self.BASE_API_URL}?{urllib.parse.urlencode(params)}"
        logger.info(f"Consultant URL interna Wallapop: {url}")

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "es-ES,es;q=0.9,ca;q=0.8",
                "DeviceOS": "0",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        deals = []
        for obj in data.get("search_objects", []):
            title = obj.get("title", "")
            price = float(obj.get("price", 0.0))
            slug = obj.get("web_slug", "")
            item_id = str(obj.get("id", slug))
            location = obj.get("location", {}).get("city", "") or self.city

            if slug and price > 0 and price <= max_price:
                deals.append(
                    Deal(
                        title=title,
                        price=price,
                        url=f"https://es.wallapop.com/item/{slug}",
                        source=self.name,
                        deal_id=f"wallapop_{item_id}",
                        location=location,
                    )
                )
        return deals

    def _search_via_indexed_listings(self, query: str, max_price: float) -> List[Deal]:
        """
        Fallback infalible: Rastreja anuncis de Wallapop indexats amb format estructurat:
        '<Títol> de Segunda mano por <Preu> EUR en <Ciutat> - Wallapop'
        """
        encoded_q = urllib.parse.quote(f"site:es.wallapop.com/item {query} {self.city}")
        rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=es&gl=ES&ceid=ES:es"
        req = urllib.request.Request(
            rss_url,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        )

        deals = []
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            items = root.find("channel").findall("item")

            pattern = re.compile(
                r"^(.*?)\s+de\s+(?:segunda\s+mano|segona\s+mà)\s+por\s+([\d\.,]+)\s*(?:EUR|€)\s*(?:en\s+([^-\|]+))?",
                re.IGNORECASE,
            )

            for item in items[:15]:
                raw_title = item.findtext("title") or ""
                link = item.findtext("link") or ""

                match = pattern.search(raw_title)
                if match:
                    title = match.group(1).strip()
                    price_str = match.group(2).replace(".", "").replace(",", ".")
                    city = (match.group(3) or "").strip() or self.city
                    try:
                        price = float(price_str)
                    except ValueError:
                        continue

                    if 0 < price <= max_price:
                        deal_id = f"wallapop_idx_{hash(title + price_str)}"
                        deals.append(
                            Deal(
                                title=title,
                                price=price,
                                url=link,
                                source=self.name,
                                deal_id=deal_id,
                                location=city,
                            )
                        )
        except Exception as e:
            logger.debug(f"Error en fallback indexat de Wallapop: {e}")

        return deals
