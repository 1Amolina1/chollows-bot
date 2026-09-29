import hashlib
import json
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable, List, Optional
from .base import NewsItem

logger = logging.getLogger("chollows.news")


class TechNewsAggregator:
    """
    Agregador de notícies tecnològiques de Google News (en català i espanyol) i Bing News.
    Implementa:
    - Deduplicació persistent respecte de dies anteriors.
    - Suport de filtres per temàtiques personalitzades de l'usuari.
    - Rànquing intel·ligent opcional amb Gemini Flash (amb fallback per data de publicació).
    """

    def __init__(self, gemini_api_key: Optional[str] = None):
        self.gemini_api_key = gemini_api_key

    def fetch_latest_news(
        self,
        topics: List[str],
        is_seen_fn: Optional[Callable[[str], bool]] = None,
        max_per_topic: int = 3,
    ) -> List[NewsItem]:
        all_news: List[NewsItem] = []
        seen_in_run = set()

        for topic in topics:
            topic_news = self._fetch_topic_news(topic)
            unseen_topic_news = []

            for item in topic_news:
                if item.news_id in seen_in_run:
                    continue
                if is_seen_fn and is_seen_fn(item.news_id):
                    continue

                seen_in_run.add(item.news_id)
                unseen_topic_news.append(item)

            # Rànquing intel·ligent o selecció dels més recents
            ranked = self._rank_news(unseen_topic_news, topic, max_per_topic)
            all_news.extend(ranked)

        return all_news

    def _fetch_topic_news(self, topic: str) -> List[NewsItem]:
        items: List[NewsItem] = []

        # 1. Google News en català
        items.extend(self._fetch_google_news(topic, hl="ca", gl="ES", ceid="ES:ca"))

        # Si hem obtingut pocs resultats, complementem amb Google News en espanyol
        if len(items) < 3:
            items.extend(self._fetch_google_news(topic, hl="es", gl="ES", ceid="ES:es"))

        # Si encara falla, intentem Bing News
        if not items:
            items.extend(self._fetch_bing_news(topic))

        return items

    def _fetch_google_news(self, query: str, hl: str = "ca", gl: str = "ES", ceid: str = "ES:ca") -> List[NewsItem]:
        encoded = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl={hl}&gl={gl}&ceid={ceid}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        news_list = []
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            root = ET.fromstring(data)
            channel = root.find("channel")
            if channel is None:
                return news_list

            for item in channel.findall("item")[:15]:
                raw_title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                pub_date = item.findtext("pubDate") or ""
                source_elem = item.find("source")
                source_name = source_elem.text if source_elem is not None and source_elem.text else "Google News"

                # Neteja del títol (Google News sol afegir " - Nom de la Font" al final)
                title = raw_title
                if " - " in title:
                    title = title.rsplit(" - ", 1)[0].strip()

                news_id = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
                news_list.append(
                    NewsItem(
                        title=title,
                        url=link,
                        source=source_name,
                        topic=query,
                        published_at=pub_date,
                        news_id=news_id,
                    )
                )
        except Exception as e:
            logger.warning(f"Error a Google News ({hl}) per a '{query}': {e}")

        return news_list

    def _fetch_bing_news(self, query: str) -> List[NewsItem]:
        encoded = urllib.parse.quote(query)
        url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        news_list = []
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            root = ET.fromstring(data)
            channel = root.find("channel")
            if channel is None:
                return news_list

            for item in channel.findall("item")[:10]:
                title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                pub_date = item.findtext("pubDate") or ""
                news_id = hashlib.sha256(title.encode("utf-8")).hexdigest()[:16]
                news_list.append(
                    NewsItem(
                        title=title,
                        url=link,
                        source="Bing News",
                        topic=query,
                        published_at=pub_date,
                        news_id=news_id,
                    )
                )
        except Exception as e:
            logger.warning(f"Error a Bing News per a '{query}': {e}")

        return news_list

    def _rank_news(self, news: List[NewsItem], topic: str, max_items: int) -> List[NewsItem]:
        if not news:
            return []
        if len(news) <= max_items or not self.gemini_api_key:
            return news[:max_items]

        # Rànquing intel·ligent via Gemini Flash si hi ha API key disponible
        try:
            titles_dict = {i: item.title for i, item in enumerate(news[:10])}
            prompt = (
                f"Ets un editor tecnològic expert. Donat el tema '{topic}' i els següents titulars de notícies:\n"
                f"{json.dumps(titles_dict, ensure_ascii=False)}\n\n"
                f"Selecciona els {max_items} titulars MÉS rellevants, d'impacte tecnològic i no redundants.\n"
                f"Respon ÚNICAMENT amb un array JSON amb els índexs seleccionats (ex: [0, 2, 4])."
            )

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.gemini_api_key}"
            payload = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))

            text_resp = res_data["candidates"][0]["content"]["parts"][0]["text"]
            selected_indices = json.loads(text_resp)
            if isinstance(selected_indices, list):
                ranked = [news[i] for i in selected_indices if isinstance(i, int) and i < len(news)]
                if ranked:
                    return ranked[:max_items]
        except Exception as e:
            logger.debug(f"Gemini ranking fallback a ordenació estàtica: {e}")

        return news[:max_items]
