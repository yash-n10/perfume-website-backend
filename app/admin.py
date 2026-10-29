from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import settings
from app.database import get_connection
from app.schemas import (
    AdminAuthResponse,
    AdminLoginRequest,
    EnquiryReportItem,
    UserResponse,
)
from app.security import create_admin_access_token, get_current_admin


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/login", response_model=AdminAuthResponse)
def admin_login(payload: AdminLoginRequest) -> AdminAuthResponse:
    """
    1. Admin Login API:
    Authenticates with admin credentials configured in settings and returns an admin JWT token.
    """
    clean_email = payload.email.strip().lower()
    expected_email = settings.admin_email.strip().lower()

    if clean_email != expected_email or payload.password != settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials.",
        )

    token = create_admin_access_token(clean_email)
    return AdminAuthResponse(
        access_token=token,
        token_type="bearer",
        role="admin",
        email=clean_email,
    )


@router.get("/users", response_model=list[UserResponse])
def get_all_users(
    admin: dict[str, str] = Depends(get_current_admin),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[UserResponse]:
    """
    2. User Data API:
    Retrieves registered users list from the database (protected by Admin JWT).
    """
    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT id, name, email, phone, created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        rows = cursor.fetchall() or []

    return [UserResponse.model_validate(row) for row in rows]


@router.get("/enquiries/report", response_model=list[EnquiryReportItem])
def get_enquiries_report(
    admin: dict[str, str] = Depends(get_current_admin),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[EnquiryReportItem]:
    """
    3. Enquiry Report API:
    Retrieves all customer and fragrance enquiries report with optional status filter (protected by Admin JWT).
    """
    with get_connection() as connection:
        if status_filter:
            cursor = connection.execute(
                """
                SELECT id, name, email, phone, enquiry, status, created_at, updated_at
                FROM enquiries
                WHERE status = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (status_filter, limit, offset),
            )
        else:
            cursor = connection.execute(
                """
                SELECT id, name, email, phone, enquiry, status, created_at, updated_at
                FROM enquiries
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
        rows = cursor.fetchall() or []

    return [EnquiryReportItem.model_validate(row) for row in rows]
