import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import logging
from typing import List, Optional
from .base import BaseConnector, Deal

logger = logging.getLogger("chollows.chollometro")


class ChollometroConnector(BaseConnector):
    """
    Connector per a Chollometro i Dealabs (plataforma Pepper).
    Analitza els canals RSS en directe i la cerca web per trobar ofertes
    de botigues com Amazon, MediaMarkt, PcComponentes, AliExpress, etc.
    """

    FEEDS = [
        "https://www.chollometro.com/rss",
        "https://www.chollometro.com/rss/nuevos",
        "https://www.dealabs.com/rss",
    ]

    @property
    def name(self) -> str:
        return "Chollometro"

    def search(self, product: str, alternative_names: List[str], max_price: float) -> List[Deal]:
        deals: List[Deal] = []
        seen_urls = set()

        all_names = [product] + [n for n in alternative_names if n.lower() != product.lower()]

        # 1. Cerca en els canals RSS de destacats i nous
        for feed_url in self.FEEDS:
            try:
                feed_deals = self._parse_feed(feed_url, all_names, max_price)
                for d in feed_deals:
                    if d.url not in seen_urls:
                        seen_urls.add(d.url)
                        deals.append(d)
            except Exception as e:
                logger.warning(f"Error analitzant feed {feed_url}: {e}")

        # 2. Cerca activa per paraules clau a Chollometro
        for name in all_names[:3]:
            try:
                search_deals = self._search_web(name, max_price)
                for d in search_deals:
                    if d.url not in seen_urls:
                        seen_urls.add(d.url)
                        deals.append(d)
            except Exception as e:
                logger.warning(f"Error a la cerca web de Chollometro per '{name}': {e}")

        return deals

    def _parse_feed(self, feed_url: str, search_terms: List[str], max_price: float) -> List[Deal]:
        deals = []
        req = urllib.request.Request(
            feed_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()

        root = ET.fromstring(data)
        items = root.find("channel").findall("item")

        for item in items:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            desc = item.findtext("description") or ""

            # Comprovem si el títol o descripció coincideix amb algun dels termes
            matched_term = self._matches_any_term(title, desc, search_terms)
            if not matched_term:
                continue

            price = self._extract_price(title, desc)
            if price is not None and 0.0 <= price <= max_price:
                deal_id = f"chollometro_{hash(link)}"
                discount = self._extract_discount(title, desc)
                deals.append(
                    Deal(
                        title=title,
                        price=price,
                        url=link,
                        source=self.name,
                        deal_id=deal_id,
                        discount_pct=discount,
                    )
                )

        return deals

    def _search_web(self, query: str, max_price: float) -> List[Deal]:
        """Cerca a la pàgina de cerca pública de Chollometro."""
        encoded = urllib.parse.quote(query)
        url = f"https://www.chollometro.com/search?q={encoded}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9",
            },
        )
        deals = []
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            # Extracció d'enllaços d'ofertes i títols mitjançant expressions regulars robustes
            # Chollometro utilitza enllaços del tipus /ofertas/titol-id
            pattern = re.compile(
                r'href="(https://www\.chollometro\.com/ofertas/[^"]+)"[^>]*title="([^"]+)"',
                re.IGNORECASE,
            )
            matches = pattern.findall(html)

            # També cerquem preus
            price_re = re.compile(r'class="[^\"]*size--all-xl[^\"]*">([^<]+)</span>')
            prices = price_re.findall(html)

            for i, (link, title) in enumerate(matches[:10]):
                price = None
                if i < len(prices):
                    price = self._parse_price_text(prices[i])
                if price is None:
                    price = self._extract_price(title, "")

                if price is not None and 0.0 <= price <= max_price:
                    deal_id = f"chollometro_{hash(link)}"
                    deals.append(
                        Deal(
                            title=title,
                            price=price,
                            url=link,
                            source=self.name,
                            deal_id=deal_id,
                        )
                    )
        except Exception as e:
            logger.debug(f"Error cercant a Chollometro web per a {query}: {e}")

        return deals

    def _matches_any_term(self, title: str, desc: str, terms: List[str]) -> Optional[str]:
        text = f"{title} {desc}".lower()
        for term in terms:
            words = term.lower().split()
            # Comprovem que totes les paraules significatives del terme siguin presents
            significant = [w for w in words if len(w) > 2]
            if not significant:
                if term.lower() in text:
                    return term
            elif all(w in text for w in significant):
                return term
        return None

    def _extract_price(self, title: str, desc: str) -> Optional[float]:
        text = f"{title} {desc}"

        if re.search(r"\b(gratis|de balde|free)\b", text, re.IGNORECASE):
            return 0.0

        # Patrons com: 749,99€, 749.99 €, 749€, por 749€, a 749 euros
        patterns = [
            r"([\d\.,]+)\s*€",
            r"por\s+([\d\.,]+)\s*(?:€|euros?)",
            r"a\s+([\d\.,]+)\s*(?:€|euros?)",
            r"(?:€|EUR)\s*([\d\.,]+)",
        ]

        for p in patterns:
            match = re.search(p, text, re.IGNORECASE)
            if match:
                price_str = match.group(1).replace(".", "").replace(",", ".")
                try:
                    p_val = float(price_str)
                    if 0.5 <= p_val <= 100000:
                        return p_val
                except ValueError:
                    continue
        return None

    def _parse_price_text(self, text: str) -> Optional[float]:
        cleaned = re.sub(r"[^\d\.,]", "", text).strip()
        cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _extract_discount(self, title: str, desc: str) -> Optional[int]:
        match = re.search(r"-(\d{1,2})%", f"{title} {desc}")
        if match:
            return int(match.group(1))
        return None
