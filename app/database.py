from fastapi import HTTPException
import psycopg
from psycopg.rows import dict_row

from app.config import settings


def get_connection() -> psycopg.Connection:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="Database connection is not configured.")

    try:
        return psycopg.connect(
            settings.database_url,
            row_factory=dict_row,
            connect_timeout=5,
        )
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Could not connect to the database.") from exc