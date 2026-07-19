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
        # July 18: lineups now post per-SIDE the moment each team announces,
        # instead of waiting for both. Dedupe is therefore per (game, side).
        c.execute("""
            CREATE TABLE IF NOT EXISTS posted_lineup_sides (
                game_pk INTEGER,
                side TEXT,               -- 'away' or 'home'
                PRIMARY KEY (game_pk, side)
            )
        """)
        # Migration: games already posted under the old whole-game system
        # count as both sides posted, so nothing already announced reposts.
        c.execute("""
            INSERT OR IGNORE INTO posted_lineup_sides (game_pk, side)
            SELECT game_pk, 'away' FROM posted_lineups
        """)
        c.execute("""
            INSERT OR IGNORE INTO posted_lineup_sides (game_pk, side)
            SELECT game_pk, 'home' FROM posted_lineups
        """)


def lineup_side_posted(game_pk: int, side: str) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM posted_lineup_sides WHERE game_pk = ? AND side = ?",
            (game_pk, side),
        ).fetchone()
        return row is not None


def mark_lineup_side_posted(game_pk: int, side: str):
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO posted_lineup_sides (game_pk, side) VALUES (?, ?)",
            (game_pk, side),
        )


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
