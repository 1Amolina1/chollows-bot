import argparse
import html
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List
from zoneinfo import ZoneInfo

from connectors import (
    BaseConnector,
    ChollometroConnector,
    Deal,
    GoogleDealsConnector,
    NewsItem,
    OnlineStoresConnector,
    TechNewsAggregator,
    WallapopConnector,
)
from database import Database
from telegram_bot import TelegramClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("chollows.watch")


def is_scheduled_time_madrid(force: bool = False) -> bool:
    """
    Comprova si l'hora actual a la zona horària local (Europe/Madrid) són les 07:xx.
    Permet programar el workflow a les dues hores UTC potencials (05:00 i 06:00 UTC)
    per cobrir automàticament el canvi d'horari d'estiu (CEST) i d'hivern (CET).
    """
    if force:
        return True

    now = datetime.now(ZoneInfo("Europe/Madrid"))
    logger.info(f"Hora actual a Madrid/Barcelona: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # Permetem l'execució si estem a la franja de les 07:00 a les 07:59
    if now.hour == 7:
        return True

    logger.info("No són les 07:xx hora local. Finalitzant sense enviar report duplicat.")
    return False


def build_report_message(deals_by_product: Dict[str, List[Deal]], news_items: List[NewsItem]) -> str:
    now = datetime.now(ZoneInfo("Europe/Madrid"))
    dias_setmana = ["Dilluns", "Dimarts", "Dimecres", "Dijous", "Divendres", "Dissabte", "Diumenge"]
    mesos = ["gener", "febrer", "març", "abril", "maig", "juny", "juliol", "agost", "setembre", "octubre", "novembre", "desembre"]
    dia_nom = dias_setmana[now.weekday()]
    mes_nom = mesos[now.month - 1]
    data_formatada = f"{dia_nom}, {now.day} de {mes_nom} de {now.year}"

    lines = [
        f"🌅 <b>REPORT MATINAL - {data_formatada}</b>",
        f"<i>Bon dia! Aquí tens el teu resum diari de les 07:00:</i>\n",
    ]

    # SECCIÓ 🛒 CHOLLS
    lines.append("🛒 <b>CHOLLS I OFERTES DETECTADES</b>")
    lines.append("────────────────────")

    total_deals = sum(len(d) for d in deals_by_product.values())

    if total_deals == 0:
        lines.append("Res de nou avui ✅. He buscat a totes les plataformes però no hi ha noves ofertes per sota dels teus preus màxims.\n")
    else:
        for product_name, deals in deals_by_product.items():
            if not deals:
                continue

            lines.append(f"🎯 <b>{html.escape(product_name)}</b>")
            for deal in deals:
                loc_txt = f" ({html.escape(deal.location)})" if deal.location else ""
                disc_txt = f" (-{deal.discount_pct}%)" if deal.discount_pct else ""
                lines.append(f"• <b>{deal.formatted_price()}</b> | <b>{html.escape(deal.source)}</b>{loc_txt}{disc_txt}")
                lines.append(f"  <i>{html.escape(deal.title[:120])}</i>")
                lines.append(f'  🔗 <a href="{deal.url}">Veure oferta a {html.escape(deal.source)}</a>\n')

    # SECCIÓ 📰 NOTÍCIES TECH
    lines.append("📰 <b>NOTÍCIES TECH DESTACADES</b>")
    lines.append("────────────────────")

    if not news_items:
        lines.append("Sense noves notícies rellevants des de l'últim report.\n")
    else:
        news_by_topic: Dict[str, List[NewsItem]] = {}
        for item in news_items:
            news_by_topic.setdefault(item.topic, []).append(item)

        for topic, items in news_by_topic.items():
            lines.append(f"💡 <b>{html.escape(topic)}</b>")
            for item in items:
                lines.append(f'• <a href="{item.url}">{html.escape(item.title)}</a>')
                lines.append(f"  <i>Font: {html.escape(item.source)}</i>")
            lines.append("")

    lines.append("────────────────────")
    lines.append(f"✅ <i>Generat a les {now.strftime('%H:%M')} CET/CEST. Bona jornada!</i>")

    return "\n".join(lines)


def load_dotenv(env_path=".env"):
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v


def run_daily_watch(force: bool = False):
    load_dotenv()
    token = (os.environ.get("TELEGRAM_TOKEN") or os.environ.get("BOTTOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("CHATID") or "").strip()
    gemini_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINIAPI") or "").strip()

    missing = []
    if not token:
        missing.append("TELEGRAM_TOKEN (o BOTTOKEN)")
    if not chat_id:
        missing.append("TELEGRAM_CHAT_ID (o CHATID)")

    if missing:
        logger.error(
            f"FATAL: Falten els següents secrets de GitHub: {', '.join(missing)}\n"
            f"👉 Afegeix-los a: https://github.com/1Amolina1/chollows-bot/settings/secrets/actions\n"
            f"ℹ️ Assegura't de crear-los com a 'Repository secrets' (no 'Environment secrets') i amb el nom exacte."
        )
        sys.exit(1)

    if not gemini_key:
        logger.warning(
            "GEMINI_API_KEY no detectada als secrets. S'utilitzarà el generador estàtic de regles i diccionari."
        )

    if not is_scheduled_time_madrid(force=force):
        return

    db = Database()
    db.seed_initial_data()
    client = TelegramClient(token)

    # 1. Carreguem productes a seguir
    products = db.get_active_products()
    logger.info(f"Carregats {len(products)} productes per rastrejar.")

    # 2. Inicialitzem els connectors modulars
    city = os.environ.get("WALLAPOP_CITY") or db.get_setting("city", "Barcelona")
    lat_val = os.environ.get("WALLAPOP_LAT") or db.get_setting("latitude", "41.3874")
    lon_val = os.environ.get("WALLAPOP_LON") or db.get_setting("longitude", "2.1686")
    try:
        lat = float(lat_val)
        lon = float(lon_val)
    except ValueError:
        lat, lon = 41.3874, 2.1686

    logger.info(f"Configuració Wallapop: Ciutat={city}, Lat={lat}, Lon={lon}")

    connectors: List[BaseConnector] = [
        WallapopConnector(city=city, latitude=lat, longitude=lon),
        ChollometroConnector(),
        OnlineStoresConnector(),
        GoogleDealsConnector(),
    ]

    deals_by_product: Dict[str, List[Deal]] = {}

    for prod in products:
        prod_name = prod["name"]
        max_price = prod["max_price"]
        alts = prod["alternative_names"]
        logger.info(f"Cercant ofertes per a '{prod_name}' (màx {max_price}€)...")

        found_deals: List[Deal] = []

        for conn in connectors:
            try:
                results = conn.search(product=prod_name, alternative_names=alts, max_price=max_price)
                logger.info(f"Connector {conn.name} ha trobat {len(results)} ofertes per a '{prod_name}'.")

                for d in results:
                    # Comprovem deduplicació
                    if not db.is_deal_seen(d.deal_id):
                        found_deals.append(d)
                        # Marquem com a vist
                        db.mark_deal_seen(
                            deal_id=d.deal_id,
                            source=d.source,
                            product_name=prod_name,
                            title=d.title,
                            price=d.price,
                            url=d.url,
                        )
            except Exception as e:
                logger.error(f"Error crític al connector {conn.name} amb '{prod_name}': {e}")
                # El connector ha fallat, però el report NO es trenca!
                continue

        # Ordenem per preu més baix
        found_deals.sort(key=lambda x: x.price)
        deals_by_product[prod_name] = found_deals[:5]

    # 3. Carreguem temes i notícies tech
    topics = db.get_active_topics()
    logger.info(f"Carregats {len(topics)} temes de notícies tech: {topics}")

    news_aggregator = TechNewsAggregator(gemini_api_key=gemini_key)
    unseen_news = news_aggregator.fetch_latest_news(
        topics=topics,
        is_seen_fn=db.is_news_seen,
        max_per_topic=3,
    )

    # Marquem les notícies com a vistes
    for n in unseen_news:
        db.mark_news_seen(news_id=n.news_id, topic=n.topic, title=n.title, url=n.url)

    logger.info(f"Total notícies noves deduplicades trobades: {len(unseen_news)}")

    # 4. Generació i enviament del report
    report_text = build_report_message(deals_by_product, unseen_news)
    logger.info(f"Enviant report a Telegram (longitud: {len(report_text)} caràcters)...")

    success = client.send_long_message(chat_id=chat_id, text=report_text)
    if success:
        logger.info("Report matinal enviat amb èxit a Telegram! ✅")
    else:
        logger.error("Error enviant el report matinal a Telegram. ❌")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generador del report matinal de Chollows")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Força l'execució del report ignorant la comprovació de les 07:00 hora local",
    )
    args = parser.parse_args()
    run_daily_watch(force=args.force)
