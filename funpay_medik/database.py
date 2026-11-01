from __future__ import annotations
import os
from pathlib import Path
from cryptography.fernet import Fernet
import aiosqlite

DB_PATH = os.getenv("DATABASE_PATH", "data/funpay_medik.sqlite3")
_cipher = None

def cipher():
    global _cipher
    if _cipher is None:
        key = os.getenv("AUTH_ENCRYPTION_KEY", "").strip()
        if not key:
            raise RuntimeError("AUTH_ENCRYPTION_KEY не задан в .env")
        _cipher = Fernet(key.encode())
    return _cipher

async def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
          telegram_id INTEGER PRIMARY KEY, telegram_name TEXT NOT NULL DEFAULT '',
          funpay_token BLOB, funpay_name TEXT, funpay_id TEXT,
          plan TEXT NOT NULL DEFAULT 'Обычный', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS settings (
          telegram_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
          PRIMARY KEY(telegram_id,key));
        CREATE TABLE IF NOT EXISTS tracked_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id INTEGER NOT NULL,
          category TEXT NOT NULL, subcategory TEXT NOT NULL DEFAULT '',
          enabled INTEGER NOT NULL DEFAULT 1, min_price REAL, max_price REAL,
          target_mode TEXT NOT NULL DEFAULT 'minimum', listing_id TEXT);
        CREATE TABLE IF NOT EXISTS order_reminders (
          order_id TEXT PRIMARY KEY, telegram_id INTEGER NOT NULL,
          sent_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
        await db.commit()

async def upsert_user(tg_id, name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users(telegram_id,telegram_name) VALUES(?,?) ON CONFLICT(telegram_id) DO UPDATE SET telegram_name=excluded.telegram_name",(tg_id,name))
        await db.commit()

async def save_session(tg_id, token, username, user_id=""):
    encrypted = cipher().encrypt(token.encode())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET funpay_token=?,funpay_name=?,funpay_id=? WHERE telegram_id=?",(encrypted,username,user_id,tg_id))
        await db.commit()

async def get_user(tg_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE telegram_id=?",(tg_id,))
        row = await cur.fetchone()
        if not row: return None
        result = dict(row)
        if result["funpay_token"]:
            try: result["funpay_token"] = cipher().decrypt(result["funpay_token"]).decode()
            except Exception: result["funpay_token"] = None
        return result

async def set_setting(tg_id,key,value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO settings VALUES(?,?,?) ON CONFLICT(telegram_id,key) DO UPDATE SET value=excluded.value",(tg_id,key,value))
        await db.commit()

async def get_setting(tg_id,key,default="0"):
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute("SELECT value FROM settings WHERE telegram_id=? AND key=?",(tg_id,key))
        row=await cur.fetchone()
        return row[0] if row else default
