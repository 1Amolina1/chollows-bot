import html
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from database import Database
from synonyms import generate_alternative_names

logger = logging.getLogger("chollows.telegram")


class TelegramClient:
    """Client directe i lleuger per a l'API oficial de Telegram Bots."""

    def __init__(self, token: str):
        self.token = token.strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> bool:
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("ok", False)
        except Exception as e:
            logger.error(f"Error enviant missatge Telegram: {e}")
            return False

    def send_long_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> bool:
        """
        Divideix missatges que superen el límit de 4096 caràcters de Telegram
        tallant de manera neta per paràgrafs per no trencar etiquetes HTML.
        """
        max_length = 3800
        if len(text) <= max_length:
            return self.send_message(chat_id, text, parse_mode, disable_web_page_preview)

        # Dividim per blocs de paràgrafs
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = ""

        for p in paragraphs:
            if len(current_chunk) + len(p) + 2 > max_length:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                # Si un sol paràgraf és immens, el dividim per línies
                if len(p) > max_length:
                    lines = p.split("\n")
                    for line in lines:
                        if len(current_chunk) + len(line) + 1 > max_length:
                            chunks.append(current_chunk.strip())
                            current_chunk = line + "\n"
                        else:
                            current_chunk += line + "\n"
                else:
                    current_chunk = p + "\n\n"
            else:
                current_chunk += p + "\n\n"

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        all_ok = True
        for chunk in chunks:
            ok = self.send_message(chat_id, chunk, parse_mode, disable_web_page_preview)
            if not ok:
                all_ok = False
        return all_ok

    def get_updates(self, offset: Optional[int] = None, timeout: int = 15) -> List[Dict[str, Any]]:
        params = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset

        url = f"{self.base_url}/getUpdates?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "ChollowsBot/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout + 5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok"):
                    return data.get("result", [])
        except Exception as e:
            logger.error(f"Error obtenint actualitzacions de Telegram: {e}")
        return []


class BotHandler:
    """
    Gestor interactiu de comandes i màquina d'estats del bot de Telegram.
    Permet afegir productes amb diàleg pas a pas, treure'ls, modificar preus
    i gestionar temes de tecnologia sense tocar mai cap fitxer.
    """

    def __init__(
        self,
        telegram_client: TelegramClient,
        database: Database,
        authorized_chat_id: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        on_report_requested: Optional[Callable[[], None]] = None,
    ):
        self.client = telegram_client
        self.db = database
        self.authorized_chat_id = str(authorized_chat_id).strip() if authorized_chat_id else None
        self.gemini_api_key = gemini_api_key
        self.on_report_requested = on_report_requested

    def process_update(self, update: Dict[str, Any]):
        message = update.get("message")
        if not message:
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        text = (message.get("text") or "").strip()

        if not chat_id or not text:
            return

        # Seguretat: Verificació de Chat ID autoritzat
        if self.authorized_chat_id:
            if str(chat_id) != self.authorized_chat_id:
                logger.warning(f"Intent d'accés no autoritzat des de chat_id: {chat_id}")
                self.client.send_message(
                    chat_id,
                    f"⛔ <b>Accés no autoritzat.</b>\nEl teu Chat ID és: <code>{chat_id}</code>.\n"
                    f"Si ets el propietari, afegeix aquest ID al teu secret <code>TELEGRAM_CHAT_ID</code>.",
                )
                return

        # Obtenim l'estat actual de la conversa
        state, state_data = self.db.get_bot_state(chat_id)

        # Gestió de cancel·lació universal
        if text.lower() in ["cancel·lar", "cancelar", "cancel", "/cancel"]:
            self.db.clear_bot_state(chat_id)
            self.client.send_message(chat_id, "🚫 Operació cancel·lada. En què et puc ajudar?")
            return

        # Enviament a la màquina d'estats
        if state == "WAITING_PRODUCT":
            self._handle_state_waiting_product(chat_id, text)
        elif state == "WAITING_PRICE":
            self._handle_state_waiting_price(chat_id, text, state_data)
        else:
            self._handle_idle_command(chat_id, text)

    def _handle_idle_command(self, chat_id: int, text: str):
        lower_text = text.lower()

        # 1. Comanda de benvinguda o ajuda
        if lower_text in ["/start", "/help", "ajuda", "hola", "help", "/ajuda"]:
            self._send_welcome(chat_id)
            return

        # 2. Comanda per veure la llista de seguiment (flexible)
        m_list = (
            re.search(r"(?:mostra|veure|enseny[a-z\']*|llista|qu[eè]).*(?:segueixes|productes|llista|guardat)", lower_text)
            or lower_text in ["/llista", "llista", "/productes", "productes", "status", "/status"]
        )
        if m_list and not lower_text.startswith("mostra temes") and not lower_text.startswith("mostra ciutat"):
            self._send_tracked_list(chat_id)
            return

        # 3. Sol·licitud de report immediat
        if lower_text in ["report ara", "executa report", "busca ara", "/report", "report"]:
            self.client.send_message(chat_id, "⏳ <i>Iniciant la cerca d'ofertes i notícies ara mateix...</i>")
            if self.on_report_requested:
                self.on_report_requested()
            return

        # 4. Gestió de temes tecnològics
        # Afegir tema
        m_add_topic = re.match(r"(?:afegir|nou)\s+tema\s+(.+)", text, re.IGNORECASE) or re.match(r"/tema\s+(.+)", text, re.IGNORECASE)
        if m_add_topic:
            topic_name = m_add_topic.group(1).strip()
            self.db.add_topic(topic_name)
            topics = self.db.get_active_topics()
            topics_txt = "\n".join([f"• {t}" for t in topics])
            self.client.send_message(
                chat_id,
                f"✅ Afegit el tema tecnològic: <b>{html.escape(topic_name)}</b>.\n\n"
                f"📰 <b>Temes actuals que segueixo:</b>\n{topics_txt}",
            )
            return

        # Treure tema
        m_del_topic = re.match(r"(?:treure|eliminar|borrar)\s+tema\s+(.+)", text, re.IGNORECASE)
        if m_del_topic:
            topic_name = m_del_topic.group(1).strip()
            removed = self.db.remove_topic(topic_name)
            if removed:
                topics = self.db.get_active_topics()
                topics_txt = "\n".join([f"• {t}" for t in topics]) if topics else "<i>Cap tema configurat</i>"
                self.client.send_message(
                    chat_id,
                    f"🗑️ Eliminat el tema: <b>{html.escape(topic_name)}</b>.\n\n"
                    f"📰 <b>Temes actuals:</b>\n{topics_txt}",
                )
            else:
                self.client.send_message(chat_id, f"⚠️ No he trobat el tema '{html.escape(topic_name)}' a la llista.")
            return

        # Llistar temes
        if lower_text in ["mostra temes", "temes", "/temes"]:
            topics = self.db.get_active_topics()
            topics_txt = "\n".join([f"• {t}" for t in topics]) if topics else "<i>Cap tema configurat</i>"
            self.client.send_message(chat_id, f"📰 <b>Temes de notícies tech que segueixo:</b>\n\n{topics_txt}")
            return

        # 5. Gestió de ciutat i coordenades per a Wallapop
        m_city = re.match(r"(?:canviar\s+ciutat\s+a|configurar\s+ciutat\s+a)\s+(.+)", text, re.IGNORECASE) or re.match(r"/ciutat\s+(.+)", text, re.IGNORECASE)
        if m_city:
            new_city = m_city.group(1).strip()
            from connectors.wallapop import DEFAULT_COORDINATES
            coords = DEFAULT_COORDINATES.get(new_city.lower(), (41.3874, 2.1686))
            self.db.set_setting("city", new_city.capitalize())
            self.db.set_setting("latitude", str(coords[0]))
            self.db.set_setting("longitude", str(coords[1]))
            self.client.send_message(
                chat_id,
                f"📍 <b>Ciutat actualitzada!</b>\n"
                f"Cercaré anuncis a <b>{html.escape(new_city.capitalize())}</b> "
                f"(lat: {coords[0]}, lon: {coords[1]}).",
            )
            return

        if lower_text in ["mostra ciutat", "ciutat", "/ciutat", "on busques"]:
            curr_city = self.db.get_setting("city", "Barcelona")
            curr_lat = self.db.get_setting("latitude", "41.3874")
            curr_lon = self.db.get_setting("longitude", "2.1686")
            self.client.send_message(
                chat_id,
                f"📍 <b>Ubicació configurada per a Wallapop:</b>\n"
                f"• Ciutat: <b>{html.escape(curr_city)}</b>\n"
                f"• Coordenades: <code>{curr_lat}, {curr_lon}</code>\n\n"
                f"💡 <i>Pots canviar-la dient: 'canviar ciutat a [ciutat]'</i>",
            )
            return

        # 6. Modificació de preu: "canviar preu de [producte] a X€" o "/preu [producte] [preu]"
        m_price = re.match(
            r"(?:canviar\s+preu\s+de|modificar\s+preu\s+de)\s+(.+?)\s+a\s+([\d\.,]+)\s*€?",
            text,
            re.IGNORECASE,
        ) or re.match(r"/preu\s+(.+?)\s+([\d\.,]+)\s*€?", text, re.IGNORECASE)
        if m_price:
            prod_name = m_price.group(1).strip()
            new_price_str = m_price.group(2).replace(".", "").replace(",", ".")
            try:
                new_price = float(new_price_str)
                updated = self.db.update_product_price(prod_name, new_price)
                if updated:
                    self.client.send_message(
                        chat_id,
                        f"✏️ <b>Preu actualitzat!</b> Ara cercaré <b>{html.escape(prod_name)}</b> fins a <b>{new_price:.2f}€</b>.",
                    )
                    self._send_tracked_list(chat_id)
                else:
                    self.client.send_message(
                        chat_id,
                        f"⚠️ No he trobat <b>{html.escape(prod_name)}</b> entre els teus productes actius.",
                    )
            except ValueError:
                self.client.send_message(chat_id, "⚠️ El preu especificat no és un número vàlid.")
            return

        # 6. Eliminar producte: "treure [producte]" o "eliminar [producte]"
        m_remove = re.match(r"(?:treure|eliminar|borrar|esborrar)\s+(.+)", text, re.IGNORECASE) or re.match(r"/treure\s+(.+)", text, re.IGNORECASE)
        if m_remove and not lower_text.startswith("treure tema"):
            prod_name = m_remove.group(1).strip()
            removed = self.db.remove_product(prod_name)
            if removed:
                self.client.send_message(
                    chat_id,
                    f"🗑️ He deixat de seguir: <b>{html.escape(prod_name)}</b>.",
                )
                self._send_tracked_list(chat_id)
            else:
                self.client.send_message(
                    chat_id,
                    f"⚠️ No he trobat el producte <b>{html.escape(prod_name)}</b> a la teva llista.",
                )
            return

        # 7. Afegir producte complet en una sola frase:
        # Ex: "afegir iPhone 15 Pro fins a 750€" o "afegir PS5 380"
        m_add_full = re.match(
            r"(?:afegir|seguir|nou\s+producte|/afegir)\s+(.+?)(?:\s+(?:fins\s+a|a|per|max|màx)?\s+([\d\.,]+)\s*€?)$",
            text,
            re.IGNORECASE,
        )
        if m_add_full:
            prod_name = m_add_full.group(1).strip()
            price_str = m_add_full.group(2).replace(".", "").replace(",", ".")
            try:
                price = float(price_str)
                self._save_product_with_variants(chat_id, prod_name, price)
                return
            except ValueError:
                pass

        # 8. Usuari diu "afegir [producte]" (sense preu encara)
        m_add_prod_only = re.match(r"(?:afegir|seguir|/afegir)\s+(.+)", text, re.IGNORECASE)
        if m_add_prod_only and not lower_text.startswith("afegir tema"):
            prod_name = m_add_prod_only.group(1).strip()
            self.db.set_bot_state(chat_id, "WAITING_PRICE", {"product": prod_name})
            self.client.send_message(
                chat_id,
                f"Quin <b>PREU MÀXIM</b> consideres chollo per a <b>{html.escape(prod_name)}</b>? (ex: 750 o 750€)",
            )
            return

        # 9. Usuari demana iniciar el diàleg d'afegir: "vull seguir un producte", "afegir", "nou"
        if lower_text in [
            "vull seguir un producte",
            "seguir producte",
            "afegir producte",
            "afegir",
            "/afegir",
            "nou producte",
            "crear alerta",
        ]:
            self.db.set_bot_state(chat_id, "WAITING_PRODUCT", {})
            self.client.send_message(
                chat_id,
                "Quin producte vols que busqui? (ex: <i>iPhone 15 Pro, PS5, MacBook Air M2...</i>)",
            )
            return

        # Missatge no reconegut
        self.client.send_message(
            chat_id,
            "No he entès la teva petició 🤔\n\n"
            "Escriu <b>'afegir'</b> o <b>'vull seguir un producte'</b> per afegir-ne un, "
            "o escriu <b>'mostra què em segueixes'</b> per veure la teva llista.",
        )

    def _handle_state_waiting_product(self, chat_id: int, text: str):
        product_name = text.strip()
        if len(product_name) < 2:
            self.client.send_message(chat_id, "El nom del producte és massa curt. Torna a indicar-lo:")
            return

        self.db.set_bot_state(chat_id, "WAITING_PRICE", {"product": product_name})
        self.client.send_message(
            chat_id,
            f"Quin <b>PREU MÀXIM</b> consideres \"chollo\" per a <b>{html.escape(product_name)}</b>? (Escriu el número, ex: 350 o 350€)",
        )

    def _handle_state_waiting_price(self, chat_id: int, text: str, state_data: Dict[str, Any]):
        product_name = state_data.get("product")
        if not product_name:
            self.db.clear_bot_state(chat_id)
            self.client.send_message(chat_id, "S'ha produït un error amb l'estat. Si us plau, torna a dir 'afegir'.")
            return

        match = re.search(r"([\d\.,]+)", text)
        if not match:
            self.client.send_message(
                chat_id,
                "⚠️ No he pogut identificar el preu. Si us plau, escriu un número vàlid (ex: 350 o 350€):",
            )
            return

        price_str = match.group(1).replace(".", "").replace(",", ".")
        try:
            price = float(price_str)
            if price <= 0:
                raise ValueError
        except ValueError:
            self.client.send_message(chat_id, "⚠️ El preu ha de ser un número superior a 0€.")
            return

        self._save_product_with_variants(chat_id, product_name, price)

    def _save_product_with_variants(self, chat_id: int, product_name: str, price: float):
        self.client.send_message(
            chat_id,
            f"⏳ <i>Analitzant i generant variants intel·ligents per a '{html.escape(product_name)}'...</i>",
        )

        variants = generate_alternative_names(product_name, self.gemini_api_key)
        self.db.add_product(product_name, price, variants)
        self.db.clear_bot_state(chat_id)

        variants_txt = "\n".join([f"  • {html.escape(v)}" for v in variants]) if variants else "  • Cap variant addicional"

        # Resposta exacta sol·licitada
        confirm_msg = (
            f"Perfecte, seguiré <b>{html.escape(product_name)}</b> fins a <b>{price:.2f}€</b>. "
            f"Ja el tinc afegit.\n\n"
            f"🔍 <b>Variants de cerca que faré servir cada matí:</b>\n{variants_txt}\n\n"
            f"<b>Què més vols seguir?</b>"
        )
        self.client.send_message(chat_id, confirm_msg)

    def _send_tracked_list(self, chat_id: int):
        products = self.db.get_active_products()
        topics = self.db.get_active_topics()

        if not products and not topics:
            self.client.send_message(
                chat_id,
                "Ara mateix no segueixes cap producte ni tema.\n"
                "Digues-me <b>'vull seguir un producte'</b> per començar!",
            )
            return

        msg_lines = ["📋 <b>ELS TEUS SEGUIMENTS ACTUALS:</b>\n"]
        if products:
            msg_lines.append("🛒 <b>Productes i Cholls:</b>")
            for p in products:
                alts = p["alternative_names"]
                alts_str = f" <i>(cerca: {', '.join(alts)})</i>" if alts else ""
                msg_lines.append(f"• <b>{html.escape(p['name'])}</b> fins a <b>{p['max_price']:.2f}€</b>{alts_str}")
        else:
            msg_lines.append("🛒 <b>Productes:</b> <i>Cap producte actiu.</i>")

        msg_lines.append("")
        if topics:
            msg_lines.append("📰 <b>Temes de notícies tech:</b>")
            for t in topics:
                msg_lines.append(f"• {html.escape(t)}")
        else:
            msg_lines.append("📰 <b>Notícies:</b> <i>Cap tema configurat.</i>")

        curr_city = self.db.get_setting("city", "Barcelona")
        curr_lat = self.db.get_setting("latitude", "41.3874")
        curr_lon = self.db.get_setting("longitude", "2.1686")
        msg_lines.append(f"\n📍 <b>Ubicació Wallapop:</b> {html.escape(curr_city)} ({curr_lat}, {curr_lon})")

        msg_lines.append("\n💡 <i>Pots escriure: 'treure [producte]', 'canviar preu de [producte] a X€', 'canviar ciutat a [ciutat]' o 'afegir tema [tema]'</i>")
        self.client.send_long_message(chat_id, "\n".join(msg_lines))

    def _send_welcome(self, chat_id: int):
        welcome_text = (
            "👋 <b>Hola! Sóc el teu assistent personal de Cholls i Notícies Tech.</b>\n\n"
            "Cada matí a les <b>07:00</b> t'enviaré un report complet amb les millors ofertes "
            "per sota del teu preu màxim i l'actualitat tecnològica més rellevant.\n\n"
            "💬 <b>Com parlar amb mi:</b>\n"
            "• <i>'vull seguir un producte'</i> o <i>'afegir'</i> → Et guiaré pas a pas.\n"
            "• <i>'afegir iPhone 15 Pro 750€'</i> → Afegir directament.\n"
            "• <i>'mostra què em segueixes'</i> → Mostra la teva llista.\n"
            "• <i>'canviar preu de PS5 a 350€'</i> → Actualitza el preu màxim.\n"
            "• <i>'treure iPhone 15 Pro'</i> → Deixa de seguir un producte.\n"
            "• <i>'afegir tema IA'</i> / <i>'treure tema IA'</i> → Personalitza notícies.\n"
            "• <i>'report ara'</i> → Executa i envia el report ara mateix!\n\n"
            "Què vols fer primer?"
        )
        self.client.send_message(chat_id, welcome_text)
