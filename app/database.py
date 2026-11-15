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
            user_id INTEGER REFERENCES users(id),
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
            product_id INTEGER REFERENCES products(id),
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            unit_price REAL NOT NULL,
            total_price REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cart_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            quantity INTEGER NOT NULL DEFAULT 1,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, product_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            label TEXT NOT NULL DEFAULT 'Home',
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address_line1 TEXT NOT NULL,
            address_line2 TEXT,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            pincode TEXT NOT NULL,
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS order_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES order_head(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES products(id),
            product_name TEXT,
            rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
            review_title TEXT,
            comment TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # Check if user_id exists in order_head
    try:
        conn.execute("ALTER TABLE order_head ADD COLUMN user_id INTEGER REFERENCES users(id)")
    except Exception:
        pass
    # Check if product_id exists in order_details
    try:
        conn.execute("ALTER TABLE order_details ADD COLUMN product_id INTEGER REFERENCES products(id)")
    except Exception:
        pass
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
    # Seed initial products if none exist
    cursor.execute("SELECT COUNT(*) FROM products")
    count_row = cursor.fetchone()
    if count_row and count_row[0] == 0:
        default_products = [
            ("Mohera Belle", 2499.00, "/products/belle_poster.jpeg", "Grace captured in every drop. Designed for the effortlessly elegant woman.", "active"),
            ("Mohera Elan", 2499.00, "/products/elan_poster.jpeg", "Vivacious. Bold. Unapologetically you. High-energy fragrance.", "active"),
            ("Mohera Drive", 2499.00, "/products/drive_poster.jpeg", "Fuel your ambition. Built for the modern man with relentless momentum.", "active"),
            ("Mohera Titan", 2499.00, "/products/titan_poster.jpeg", "A presence carved in strength. Rich cedar, dark leather, and subtle warm spices.", "active"),
            ("Mohera Luna", 2799.00, "/products/luna_poster.jpeg", "Grace and allure for unforgettable evenings. Luminous, ethereal top notes.", "active"),
            ("Devinoire Aphira", 2999.00, "/products/devinoire/aphira.jpeg", "Devinoire luxury fragrance collection - Aphira.", "active"),
            ("Devinoire Ares", 2999.00, "/products/devinoire/ares.jpeg", "Devinoire luxury fragrance collection - Ares.", "active"),
            ("Devinoire Athena", 2999.00, "/products/devinoire/athena.jpeg", "Devinoire luxury fragrance collection - Athena.", "active"),
            ("Devinoire Hades", 2999.00, "/products/devinoire/hades.jpeg", "Devinoire luxury fragrance collection - Hades.", "active"),
            ("Devinoire Hera", 2999.00, "/products/devinoire/hera.jpeg", "Devinoire luxury fragrance collection - Hera.", "active"),
            ("Devinoire Nereus", 2999.00, "/products/devinoire/nereus.jpeg", "Devinoire luxury fragrance collection - Nereus.", "active"),
            ("Devinoire Orion", 2999.00, "/products/devinoire/orion.jpeg", "Devinoire luxury fragrance collection - Orion.", "active"),
            ("Devinoire Sephora", 2999.00, "/products/devinoire/sephora.jpeg", "Devinoire luxury fragrance collection - Sephora.", "active"),
        ]
        for prod in default_products:
            conn.execute(
                "INSERT INTO products (product_name, price, image, description, status) VALUES (?, ?, ?, ?, ?)",
                prod,
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

                        CREATE TABLE IF NOT EXISTS products (
                            id SERIAL PRIMARY KEY,
                            product_name VARCHAR(255) NOT NULL,
                            price NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
                            image VARCHAR(500),
                            description TEXT,
                            status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
                            add_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS order_head (
                            id SERIAL PRIMARY KEY,
                            customer_name VARCHAR(255) NOT NULL,
                            phone VARCHAR(50) NOT NULL,
                            email VARCHAR(255) NOT NULL,
                            address TEXT NOT NULL,
                            order_type VARCHAR(50) NOT NULL DEFAULT 'online',
                            total_price NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
                            payment_mode VARCHAR(50) NOT NULL,
                            payment_status VARCHAR(50) NOT NULL DEFAULT 'pending',
                            paid_status INT NOT NULL DEFAULT 0,
                            order_datetime TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS order_details (
                            id SERIAL PRIMARY KEY,
                            order_id INT NOT NULL REFERENCES order_head(id) ON DELETE CASCADE,
                            product_id INT REFERENCES products(id),
                            product_name VARCHAR(255) NOT NULL,
                            quantity INT NOT NULL DEFAULT 1,
                            unit_price NUMERIC(10, 2) NOT NULL,
                            total_price NUMERIC(10, 2) NOT NULL
                        );

                        CREATE TABLE IF NOT EXISTS cart_items (
                            id SERIAL PRIMARY KEY,
                            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                            product_id INT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                            quantity INT NOT NULL DEFAULT 1,
                            added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(user_id, product_id)
                        );

                        CREATE TABLE IF NOT EXISTS user_addresses (
                            id SERIAL PRIMARY KEY,
                            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                            label VARCHAR(50) NOT NULL DEFAULT 'Home',
                            full_name VARCHAR(160) NOT NULL,
                            phone VARCHAR(50) NOT NULL,
                            address_line1 VARCHAR(255) NOT NULL,
                            address_line2 VARCHAR(255),
                            city VARCHAR(100) NOT NULL,
                            state VARCHAR(100) NOT NULL,
                            pincode VARCHAR(20) NOT NULL,
                            is_default BOOLEAN NOT NULL DEFAULT FALSE,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                        );

                        CREATE TABLE IF NOT EXISTS order_reviews (
                            id SERIAL PRIMARY KEY,
                            order_id INT NOT NULL REFERENCES order_head(id) ON DELETE CASCADE,
                            user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                            product_id INT REFERENCES products(id),
                            product_name VARCHAR(255),
                            rating INT NOT NULL CHECK (rating >= 1 AND rating <= 5),
                            review_title VARCHAR(255),
                            comment TEXT NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                        );

                        ALTER TABLE order_head ADD COLUMN IF NOT EXISTS user_id INT REFERENCES users(id);
                        ALTER TABLE order_details ADD COLUMN IF NOT EXISTS product_id INT REFERENCES products(id);
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


