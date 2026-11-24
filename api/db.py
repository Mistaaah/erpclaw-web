"""Database connection management for erpclaw-web API."""

import os
import sqlite3
from pathlib import Path

# Web app's own database (users, sessions, roles)
WEB_DB_PATH = os.environ.get(
    "ERPCLAW_WEB_DB",
    os.path.expanduser("~/.openclaw/erpclaw-web/web.sqlite"),
)

# ERPClaw's data database (the actual ERP data)
ERP_DB_PATH = os.environ.get(
    "ERPCLAW_DB",
    os.path.expanduser("~/.openclaw/erpclaw/data.sqlite"),
)

# ERP business data lives in the Railway Postgres database. The web app's own
# auth/session data remains in its local SQLite database.
ERP_DATABASE_URL = os.environ.get("ERPCLAW_DB_URL")


def get_erp_pg_db():
    """Open a read-only transaction against the authoritative ERP Postgres DB."""
    if not ERP_DATABASE_URL:
        raise RuntimeError("ERPCLAW_DB_URL is not configured")
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError as exc:
        raise RuntimeError("Postgres support is unavailable") from exc
    try:
        conn = psycopg2.connect(
            ERP_DATABASE_URL,
            connect_timeout=5,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    except psycopg2.OperationalError as exc:
        raise RuntimeError("ERP database unavailable") from exc
    conn.set_session(readonly=True, autocommit=False)
    return conn


def get_web_db() -> sqlite3.Connection:
    """Get connection to the web app's own database (auth, sessions)."""
    Path(WEB_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(WEB_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_erp_db() -> sqlite3.Connection:
    """Get read-only connection to ERPClaw's data database."""
    if not Path(ERP_DB_PATH).exists():
        raise FileNotFoundError(f"ERPClaw database not found at {ERP_DB_PATH}")
    conn = sqlite3.connect(f"file:{ERP_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
