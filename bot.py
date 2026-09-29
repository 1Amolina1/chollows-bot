import argparse
import logging
import os
import sys
import time

from database import Database
from telegram_bot import BotHandler, TelegramClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("chollows.bot")


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


import http.server
import threading


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "running", "service": "chollows-bot"}')

    def log_message(self, format, *args):
        pass


def start_health_server(port: int):
    try:
        server = http.server.HTTPServer(("0.0.0.0", port), HealthHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        logger.info(f"Servidor HTTP de salut actiu al port {port} (compatible amb Render.com / Koyeb)")
    except Exception as e:
        logger.warning(f"No s'ha pogut iniciar el servidor HTTP al port {port}: {e}")


def run_bot(drain_only: bool = False):
    load_dotenv()
    port_env = os.environ.get("PORT")
    if port_env:
        try:
            start_health_server(int(port_env))
        except ValueError:
            pass

    token = (os.environ.get("TELEGRAM_TOKEN") or os.environ.get("BOTTOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("CHATID") or "").strip()
    gemini_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINIAPI") or "").strip()

    if not token:
        logger.error("FATAL: Variable d'entorn TELEGRAM_TOKEN (o BOTTOKEN) no trobada!")
        sys.exit(1)

    client = TelegramClient(token)
    db = Database()
    db.seed_initial_data()

    # Callback per si l'usuari demana 'report ara' des del bot
    def on_report_requested():
        from watch import run_daily_watch
        run_daily_watch(force=True)

    handler = BotHandler(
        telegram_client=client,
        database=db,
        authorized_chat_id=chat_id,
        gemini_api_key=gemini_key,
        on_report_requested=on_report_requested,
    )

    logger.info("Assistent de Telegram iniciat amb èxit!")
    offset = None

    if drain_only:
        logger.info("Mode --drain: Processant missatges pendents i sortint...")
        updates = client.get_updates(offset=offset, timeout=5)
        for u in updates:
            handler.process_update(u)
            offset = u["update_id"] + 1
        # Confirmem els missatges processats a Telegram
        if offset is not None:
            client.get_updates(offset=offset, timeout=0)
        logger.info(f"Processats {len(updates)} missatges. Finalitzat.")
        return

    # Mode long-polling continu
    logger.info("Mode Long-Polling actiu. Esperant missatges de l'usuari...")
    while True:
        try:
            updates = client.get_updates(offset=offset, timeout=25)
            for u in updates:
                handler.process_update(u)
                offset = u["update_id"] + 1
        except KeyboardInterrupt:
            logger.info("Bot aturat per l'usuari.")
            break
        except Exception as e:
            logger.error(f"Error al bucle de recepció: {e}")
            time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot interactiu de Telegram per a Chollows")
    parser.add_argument(
        "--drain",
        action="store_true",
        help="Processa tots els missatges acumulats pendents i surt immediatament (ideal per a GitHub Actions)",
    )
    args = parser.parse_args()
    run_bot(drain_only=args.drain)
