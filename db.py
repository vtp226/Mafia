"""
لایه‌ی دیتابیس (SQLite از طریق sqlite3 استاندارد پایتون)
"""
import os
import sqlite3
import time
import config

_conn = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        d = os.path.dirname(config.DB_PATH)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA foreign_keys = ON;")
        _conn.execute("PRAGMA journal_mode = WAL;")
        _init_schema(_conn)
    return _conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'registering',
            created_at INTEGER,
            started_at INTEGER,
            ended_at INTEGER
        );

        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            alias TEXT,
            role TEXT,
            status TEXT NOT NULL DEFAULT 'alive',
            registered_before_start INTEGER NOT NULL DEFAULT 0,
            last_action_time INTEGER NOT NULL DEFAULT 0,
            protected_until INTEGER NOT NULL DEFAULT 0,
            vote_immune_until INTEGER NOT NULL DEFAULT 0,
            journalist_used INTEGER NOT NULL DEFAULT 0,
            spy_last_check INTEGER NOT NULL DEFAULT 0,
            revealed INTEGER NOT NULL DEFAULT 0,
            state TEXT,
            created_at INTEGER,
            UNIQUE(game_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS death_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            victim_player_id INTEGER NOT NULL,
            created_at INTEGER,
            vote_session_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS vote_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            death_event_id INTEGER NOT NULL,
            requester_player_id INTEGER NOT NULL,
            UNIQUE(death_event_id, requester_player_id)
        );

        CREATE TABLE IF NOT EXISTS vote_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            trigger_type TEXT,
            started_at INTEGER,
            ends_at INTEGER,
            result TEXT
        );

        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            voter_player_id INTEGER NOT NULL,
            target_player_id INTEGER NOT NULL,
            UNIQUE(session_id, voter_player_id)
        );

        CREATE TABLE IF NOT EXISTS actions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            target_player_id INTEGER,
            created_at INTEGER
        );
    """)
    conn.commit()


def now() -> int:
    return int(time.time())
