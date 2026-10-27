from fastapi import HTTPException

from app.config import settings
from app.database import get_connection

try:
    import psycopg
except ImportError:
    psycopg = None


def main() -> None:
    db_type = "PostgreSQL" if settings.database_url and not settings.database_url.startswith("sqlite") else "Local SQLite"
    print(f"Checking database connection ({db_type})...")
    try:
        with get_connection() as connection:
            connection.execute("SELECT 1").fetchone()
    except (HTTPException, Exception) as error:
        cause = error.__cause__ if isinstance(error, HTTPException) else None
        message = str(cause or error.detail) if isinstance(error, HTTPException) else str(error)
        print(f"Database connection failed: {message}")
        raise SystemExit(1) from error

    print(f"Database connection successful ({db_type}).")


if __name__ == "__main__":
    main()