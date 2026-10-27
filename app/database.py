import os
import sqlite3
from contextlib import contextmanager
from typing import Generator
from fastapi import HTTPException
try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None


from app.config import settings

SQLITE_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "local_app.db")


def init_sqlite_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            email_verified_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS email_otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            otp_hash TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            verified_at TIMESTAMP,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS enquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            enquiry TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


class SQLiteCursorWrapper:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    def fetchone(self) -> dict | None:
        row = self._cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self) -> list[dict]:
        return [dict(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        for row in self._cursor:
            yield dict(row)


class SQLiteConnectionWrapper:
    """A wrapper around sqlite3.Connection to provide a psycopg-like dictionary cursor interface."""
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: tuple | list = ()):
        converted_sql = sql.replace("%s", "?")
        converted_sql = converted_sql.replace("FOR UPDATE", "")
        # Handle interval conversion if any
        converted_sql = converted_sql.replace("INTERVAL '1 hour'", "'-1 hour'")
        converted_sql = converted_sql.replace("INTERVAL '15 minutes'", "'-15 minutes'")
        converted_sql = converted_sql.replace("NOW()", "CURRENT_TIMESTAMP")
        cursor = self._conn.cursor()
        cursor.execute(converted_sql, params)
        return SQLiteCursorWrapper(cursor)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()



@contextmanager
def get_connection() -> Generator:
    # Use SQLite if database_url is empty, starts with sqlite, or live DB is bypassed
    if not settings.database_url or settings.database_url.startswith("sqlite"):
        conn = sqlite3.connect(SQLITE_DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        init_sqlite_db(conn)
        wrapped = SQLiteConnectionWrapper(conn)
        try:
            yield wrapped
            wrapped.commit()
        except Exception:
            wrapped.rollback()
            raise
        finally:
            wrapped.close()
        return

    if not psycopg:
        raise HTTPException(
            status_code=503,
            detail="psycopg is not installed to connect to PostgreSQL. Install psycopg or unset DATABASE_URL to use local DB."
        )

    try:
        with psycopg.connect(
            settings.database_url,
            row_factory=dict_row,
            connect_timeout=5,
        ) as connection:
            yield connection
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Could not connect to the database.") from exc
