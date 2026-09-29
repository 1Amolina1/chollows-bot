import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import logging
from typing import List, Optional
from .base import BaseConnector, Deal

logger = logging.getLogger("chollows.google_deals")


class GoogleDealsConnector(BaseConnector):
    """
    Connector basat en alertes web de Google i Bing per detectar ofertes
    i descomptes publicats en blocs, fòrums i portals especialitzats.
    """

    @property
    def name(self) -> str:
        return "Web Alerts (Google / Bing)"

    def search(self, product: str, alternative_names: List[str], max_price: float) -> List[Deal]:
        deals: List[Deal] = []
        seen_urls = set()

        search_terms = [product] + [n for n in alternative_names if n.lower() != product.lower()]
        for term in search_terms[:2]:
            try:
                g_deals = self._search_google(term, max_price)
                for d in g_deals:
                    if d.url not in seen_urls:
                        seen_urls.add(d.url)
                        deals.append(d)
            except Exception as e:
                logger.warning(f"Error a Google Alerts per '{term}': {e}")

            try:
                b_deals = self._search_bing(term, max_price)
                for d in b_deals:
                    if d.url not in seen_urls:
                        seen_urls.add(d.url)
                        deals.append(d)
            except Exception as e:
                logger.warning(f"Error a Bing Alerts per '{term}': {e}")

        return deals

    def _search_google(self, query: str, max_price: float) -> List[Deal]:
        q_enc = urllib.parse.quote(f'"{query}" (chollo OR ganga OR oferta OR descuento)')
        url = f"https://news.google.com/rss/search?q={q_enc}&hl=es&gl=ES&ceid=ES:es"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()

        root = ET.fromstring(data)
        items = root.find("channel").findall("item")

        deals = []
        for item in items[:8]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""

            price = self._extract_price(title)
            if price is not None and 0.0 < price <= max_price:
                deals.append(
                    Deal(
                        title=title,
                        price=price,
                        url=link,
                        source="Google Alerts",
                        deal_id=f"g_alert_{hash(link)}",
                    )
                )
        return deals

    def _search_bing(self, query: str, max_price: float) -> List[Deal]:
        q_enc = urllib.parse.quote(f"{query} chollo ganga oferta")
        url = f"https://www.bing.com/news/search?q={q_enc}&format=rss"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        deals = []
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            root = ET.fromstring(data)
            items = root.find("channel").findall("item")
            for item in items[:5]:
                title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                price = self._extract_price(title)
                if price is not None and 0.0 < price <= max_price:
                    deals.append(
                        Deal(
                            title=title,
                            price=price,
                            url=link,
                            source="Bing Alerts",
                            deal_id=f"b_alert_{hash(link)}",
                        )
                    )
        except Exception:
            pass
        return deals

    def _extract_price(self, text: str) -> Optional[float]:
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
