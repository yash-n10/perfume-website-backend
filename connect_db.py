import psycopg
from fastapi import HTTPException

from app.database import get_connection


def main() -> None:
    try:
        with get_connection() as connection:
            connection.execute("SELECT 1").fetchone()
    except (HTTPException, psycopg.Error) as error:
        cause = error.__cause__ if isinstance(error, HTTPException) else None
        message = str(cause or error.detail) if isinstance(error, HTTPException) else str(error)
        print(f"Database connection failed: {message}")
        raise SystemExit(1) from error

    print("Database connection successful.")


if __name__ == "__main__":
    main()