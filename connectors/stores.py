import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import logging
from typing import List, Optional
from .base import BaseConnector, Deal

logger = logging.getLogger("chollows.stores")


class OnlineStoresConnector(BaseConnector):
    """
    Connector per a botigues online com Amazon.es, PcComponentes, MediaMarkt i El Corte Inglés.
    Empra rastreig de contingut indexat en temps real i anàlisi d'ofertes publicades.
    """

    @property
    def name(self) -> str:
        return "Botigues Online (Amazon / PcComponentes)"

    def search(self, product: str, alternative_names: List[str], max_price: float) -> List[Deal]:
        deals: List[Deal] = []
        seen_urls = set()

        queries = [product] + [name for name in alternative_names if name.lower() != product.lower()]
        for query in queries[:3]:
            try:
                results = self._search_store_deals(query, max_price)
                for d in results:
                    if d.url not in seen_urls:
                        seen_urls.add(d.url)
                        deals.append(d)
            except Exception as e:
                logger.warning(f"Error buscant botigues per a '{query}': {e}")

        return deals

    def _search_store_deals(self, query: str, max_price: float) -> List[Deal]:
        # Cerca combinada per trobar pàgines d'ofertes directes a Amazon i PcComponentes
        q_encoded = urllib.parse.quote(
            f'"{query}" (site:amazon.es OR site:pccomponentes.com OR site:mediamarkt.es) (oferta OR chollo OR precio OR rebaja)'
        )
        url = f"https://news.google.com/rss/search?q={q_encoded}&hl=es&gl=ES&ceid=ES:es"

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )

        deals = []
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()

        root = ET.fromstring(data)
        items = root.find("channel").findall("item")

        for item in items[:10]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""

            # Determinem la botiga d'origen
            source_store = "Botiga Online"
            if "amazon.es" in title.lower() or "amazon" in link.lower():
                source_store = "Amazon"
            elif "pccomponentes" in title.lower() or "pccomponentes" in link.lower():
                source_store = "PcComponentes"
            elif "mediamarkt" in title.lower():
                source_store = "MediaMarkt"

            price = self._extract_price(title)
            # Si no hi ha preu explícit al títol, però l'anunci és una oferta directa
            if price is not None and 0.0 < price <= max_price:
                deals.append(
                    Deal(
                        title=title,
                        price=price,
                        url=link,
                        source=source_store,
                        deal_id=f"store_{hash(link)}",
                    )
                )

        return deals

    def _extract_price(self, text: str) -> Optional[float]:
        # Patrons com: 699€, 699,99 €, 699 euros
        pattern = re.compile(r"([\d\.,]+)\s*(?:€|euros?)", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            raw = match.group(1).replace(".", "").replace(",", ".")
            try:
                val = float(raw)
                if 1.0 <= val <= 20000:
                    return val
            except ValueError:
                pass
        return None
