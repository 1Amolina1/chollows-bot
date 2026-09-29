import datetime
import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("chollows.db")

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "data.db")


class Database:
    """
    Gestor de base de dades SQLite per persistir:
    - Productes seguits, preus màxims i llistes de sinònims/variants generats.
    - Temes de notícies tecnològiques.
    - Historial d'ofertes i notícies vistes (deduplicació).
    - Estat de la conversa interactiva del bot de Telegram.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 1. Productes seguits
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracked_products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    max_price REAL NOT NULL,
                    alternative_names TEXT NOT NULL DEFAULT '[]',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 2. Temes de notícies
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tracked_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
            """)

            # 3. Ofertes vistes (Deduplicació)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS seen_deals (
                    deal_id TEXT PRIMARY KEY,
                    source TEXT,
                    product_name TEXT,
                    title TEXT,
                    price REAL,
                    url TEXT,
                    first_seen_at TEXT NOT NULL
                )
            """)

            # 4. Notícies vistes (Deduplicació)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS seen_news (
                    news_id TEXT PRIMARY KEY,
                    topic TEXT,
                    title TEXT,
                    url TEXT,
                    first_seen_at TEXT NOT NULL
                )
            """)

            # 5. Estat de la conversa del Bot de Telegram (FSM)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_state (
                    chat_id INTEGER PRIMARY KEY,
                    state TEXT NOT NULL DEFAULT 'IDLE',
                    data TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                )
            """)

            # 6. Metadades del sistema
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.commit()

    def seed_initial_data(self):
        """Introdueix dades inicials d'exemple si la base de dades és buida."""
        products = self.get_active_products()
        if not products:
            logger.info("Inserint dades d'exemple a la base de dades...")
            self.add_product(
                name="iPhone 15 Pro",
                max_price=750.0,
                alternative_names=["Apple iPhone 15 Pro", "iPhone 15Pro", "15 Pro"],
            )
            self.add_product(
                name="PlayStation 5",
                max_price=380.0,
                alternative_names=["PS5", "Sony PS5", "PlayStation 5 Slim", "PS5 Slim"],
            )
            self.add_product(
                name="MacBook Air M2",
                max_price=800.0,
                alternative_names=["Apple MacBook Air M2", "MacBook Air", "Macbook M2"],
            )

        topics = self.get_active_topics()
        if not topics:
            self.add_topic("Intel·ligència Artificial")
            self.add_topic("Apple")
            self.add_topic("Ciberseguretat")

        if not self.get_setting("city"):
            self.set_setting("city", "Barcelona")
            self.set_setting("latitude", "41.3874")
            self.set_setting("longitude", "2.1686")

    # ================= PRODUCTS =================

    def add_product(self, name: str, max_price: float, alternative_names: Optional[List[str]] = None) -> bool:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        alt_json = json.dumps(alternative_names or [], ensure_ascii=False)
        clean_name = name.strip()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tracked_products (name, max_price, alternative_names, active, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    max_price = excluded.max_price,
                    alternative_names = CASE WHEN excluded.alternative_names != '[]' THEN excluded.alternative_names ELSE tracked_products.alternative_names END,
                    active = 1,
                    updated_at = excluded.updated_at
                """,
                (clean_name, float(max_price), alt_json, now, now),
            )
            conn.commit()
            return True

    def remove_product(self, name: str) -> bool:
        clean_name = name.strip().lower()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE tracked_products SET active = 0 WHERE LOWER(name) = ?", (clean_name,))
            affected = cursor.rowcount > 0
            conn.commit()
            return affected

    def update_product_price(self, name: str, new_price: float) -> bool:
        clean_name = name.strip().lower()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tracked_products SET max_price = ?, updated_at = ? WHERE LOWER(name) = ? AND active = 1",
                (float(new_price), now, clean_name),
            )
            affected = cursor.rowcount > 0
            conn.commit()
            return affected

    def get_active_products(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tracked_products WHERE active = 1 ORDER BY name ASC")
            rows = cursor.fetchall()
            products = []
            for r in rows:
                alts = json.loads(r["alternative_names"]) if r["alternative_names"] else []
                products.append({
                    "id": r["id"],
                    "name": r["name"],
                    "max_price": float(r["max_price"]),
                    "alternative_names": alts,
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                })
            return products

    def get_product(self, name: str) -> Optional[Dict[str, Any]]:
        clean_name = name.strip().lower()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tracked_products WHERE LOWER(name) = ? AND active = 1", (clean_name,))
            r = cursor.fetchone()
            if not r:
                return None
            return {
                "id": r["id"],
                "name": r["name"],
                "max_price": float(r["max_price"]),
                "alternative_names": json.loads(r["alternative_names"]),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }

    # ================= TOPICS =================

    def add_topic(self, name: str) -> bool:
        clean_name = name.strip()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tracked_topics (name, active, created_at)
                VALUES (?, 1, ?)
                ON CONFLICT(name) DO UPDATE SET active = 1
                """,
                (clean_name, now),
            )
            conn.commit()
            return True

    def remove_topic(self, name: str) -> bool:
        clean_name = name.strip().lower()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE tracked_topics SET active = 0 WHERE LOWER(name) = ?", (clean_name,))
            affected = cursor.rowcount > 0
            conn.commit()
            return affected

    def get_active_topics(self) -> List[str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM tracked_topics WHERE active = 1 ORDER BY name ASC")
            return [r["name"] for r in cursor.fetchall()]

    # ================= DEDUPLICATION =================

    def is_deal_seen(self, deal_id: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM seen_deals WHERE deal_id = ?", (deal_id,))
            return cursor.fetchone() is not None

    def mark_deal_seen(self, deal_id: str, source: str, product_name: str, title: str, price: float, url: str):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO seen_deals (deal_id, source, product_name, title, price, url, first_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (deal_id, source, product_name, title, float(price), url, now),
            )
            conn.commit()

    def is_news_seen(self, news_id: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM seen_news WHERE news_id = ?", (news_id,))
            return cursor.fetchone() is not None

    def mark_news_seen(self, news_id: str, topic: str, title: str, url: str):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO seen_news (news_id, topic, title, url, first_seen_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (news_id, topic, title, url, now),
            )
            conn.commit()

    # ================= BOT STATE (FSM) =================

    def get_bot_state(self, chat_id: int) -> Tuple[str, Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT state, data FROM bot_state WHERE chat_id = ?", (chat_id,))
            r = cursor.fetchone()
            if not r:
                return "IDLE", {}
            try:
                data = json.loads(r["data"])
            except Exception:
                data = {}
            return r["state"], data

    def set_bot_state(self, chat_id: int, state: str, data: Optional[Dict[str, Any]] = None):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        data_json = json.dumps(data or {}, ensure_ascii=False)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO bot_state (chat_id, state, data, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    state = excluded.state,
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (chat_id, state, data_json, now),
            )
            conn.commit()

    def clear_bot_state(self, chat_id: int):
        self.set_bot_state(chat_id, "IDLE", {})

    # ================= SETTINGS =================

    def get_setting(self, key: str, default: str = "") -> str:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            r = cursor.fetchone()
            if r:
                return r["value"]
            return default

    def set_setting(self, key: str, value: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, str(value)),
            )
            conn.commit()
