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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            price REAL NOT NULL DEFAULT 0.00,
            image TEXT,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            add_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS order_head (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT NOT NULL,
            address TEXT NOT NULL,
            order_type TEXT NOT NULL DEFAULT 'online',
            total_price REAL NOT NULL DEFAULT 0.00,
            payment_mode TEXT NOT NULL,
            payment_status TEXT NOT NULL DEFAULT 'pending',
            paid_status INTEGER NOT NULL DEFAULT 0,
            order_datetime TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS order_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES order_head(id) ON DELETE CASCADE,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL,
            total_price REAL NOT NULL
        )
        """
    )
    # Seed initial admin if it doesn't exist
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM admins WHERE lower(username) = 'admin'")
    if not cursor.fetchone():
        try:
            from app.security import hash_password
            admin_hash = hash_password("Yash#1008")
        except Exception:
            import hashlib
            admin_hash = hashlib.sha256("Yash#1008".encode()).hexdigest()
        conn.execute(
            "INSERT INTO admins (username, password_hash, role) VALUES ('admin', ?, 'admin')",
            (admin_hash,),
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



from urllib.parse import urlparse
import dns.resolver


def _resolve_host_ip(hostname: str) -> str | None:
    try:
        import socket
        return socket.gethostbyname(hostname)
    except Exception:
        pass

    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
        resolver.lifetime = 5
        answers = resolver.resolve(hostname, "A")
        if answers:
            return answers[0].to_text()
    except Exception:
        pass
    return None


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
        parsed = urlparse(settings.database_url)
        connect_kwargs = {
            "row_factory": dict_row,
            "connect_timeout": 10,
        }
        if parsed.hostname:
            resolved_ip = _resolve_host_ip(parsed.hostname)
            if resolved_ip:
                connect_kwargs["hostaddr"] = resolved_ip

        with psycopg.connect(
            settings.database_url,
            **connect_kwargs,
        ) as connection:
            # Ensure schema and initial admin exist in PostgreSQL
            try:
                with connection.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS admins (
                            id BIGSERIAL PRIMARY KEY,
                            username VARCHAR(100) NOT NULL UNIQUE,
                            password_hash VARCHAR(255) NOT NULL,
                            role VARCHAR(50) NOT NULL DEFAULT 'admin',
                            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                        );
                        """
                    )
                    cur.execute("SELECT id FROM admins WHERE lower(username) = 'admin' LIMIT 1;")
                    if not cur.fetchone():
                        try:
                            from app.security import hash_password
                            admin_hash = hash_password("Yash#1008")
                        except Exception:
                            import hashlib
                            admin_hash = hashlib.sha256("Yash#1008".encode()).hexdigest()
                        cur.execute(
                            "INSERT INTO admins (username, password_hash, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING;",
                            ("admin", admin_hash, "admin"),
                        )
                connection.commit()
            except Exception:
                connection.rollback()
            yield connection
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail=f"Could not connect to the database: {exc}") from exc


