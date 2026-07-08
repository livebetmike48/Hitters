import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "hitters_bot.db")


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS posted_lineups (
                game_pk INTEGER PRIMARY KEY
            )
        """)


def lineup_already_posted(game_pk: int) -> bool:
    with _conn() as c:
        row = c.execute("SELECT 1 FROM posted_lineups WHERE game_pk = ?", (game_pk,)).fetchone()
        return row is not None


def mark_lineup_posted(game_pk: int):
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO posted_lineups (game_pk) VALUES (?)", (game_pk,))


def set_config(key: str, value: str):
    with _conn() as c:
        c.execute(
            "INSERT INTO config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_config(key: str):
    with _conn() as c:
        row = c.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
