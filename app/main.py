from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import router as auth_router
from app.config import settings
from app.database import get_connection
from app.email_service import send_otp_email
from app.enquiries import router as enquiries_router


app = FastAPI(title="MOHERA API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins if settings.cors_origins != "*" else ["*"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^https://.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(enquiries_router)


@app.get("/")
def read_root() -> dict[str, str]:
    return {
        "name": "MOHERA API",
        "status": "online",
        "docs": "/docs",
        "health": "/api/health",
        "db_check": "/api/db-check"
    }


@app.get("/api/health")
def health_check() -> dict[str, str]:
    # 1. Check database connectivity
    with get_connection() as connection:
        connection.execute("SELECT 1")
    
    # 2. Send test email to verify Gmail SMTP functionality
    send_otp_email("narayanyash10@gmail.com", "HEALTH-CHECK")
    
    return {
        "status": "ok",
        "database": "connected",
        "email": "test email sent to narayanyash10@gmail.com"
    }


@app.get("/api/db-check")
@app.get("/db-check")
def check_database() -> dict[str, str | bool]:

    is_postgres = bool(settings.database_url and not settings.database_url.startswith("sqlite"))
    db_type = "PostgreSQL" if is_postgres else "Local SQLite"
    
    with get_connection() as connection:
        cursor = connection.execute("SELECT 1 as test")
        row = cursor.fetchone()

    return {
        "connected": True,
        "database_type": db_type,
        "message": f"Successfully connected to {db_type} database.",
        "test_query_result": row["test"] if isinstance(row, dict) else row[0]
    }
