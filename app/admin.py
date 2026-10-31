from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import settings
from app.database import get_connection
from app.schemas import (
    AdminAuthResponse,
    AdminLoginRequest,
    EnquiryReportItem,
    EnquiryStatusUpdateRequest,
    UserResponse,
)
from app.security import create_admin_access_token, get_current_admin, verify_password


router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/login", response_model=AdminAuthResponse)
def admin_login(payload: AdminLoginRequest) -> AdminAuthResponse:
    """
    1. Admin Login API:
    Authenticates admin credentials from database (or config fallback) and returns an admin JWT token.
    Initial credentials: admin / Yash#1008
    """
    clean_username = payload.username.strip()
    authenticated = False
    admin_user = clean_username

    # 1. Attempt DB authentication against `admins` table
    try:
        with get_connection() as connection:
            cursor = connection.execute(
                """
                SELECT id, username, password_hash, role
                FROM admins
                WHERE lower(username) = lower(%s)
                LIMIT 1
                """,
                (clean_username,),
            )
            row = cursor.fetchone()
            if row:
                stored_hash = row.get("password_hash", "")
                if verify_password(payload.password, stored_hash):
                    authenticated = True
                    admin_user = row.get("username", clean_username)
                else:
                    # Also support sha256 fallback if seeded with sha256
                    import hashlib
                    if stored_hash == hashlib.sha256(payload.password.encode()).hexdigest():
                        authenticated = True
                        admin_user = row.get("username", clean_username)
    except Exception:
        # If DB query or table creation encountered a temporary issue, fallback to config credentials
        pass

    # 2. Config fallback check (initial credentials: admin / Yash#1008)
    if not authenticated:
        expected_user = getattr(settings, "admin_username", "admin").strip().lower()
        expected_pass = getattr(settings, "admin_password", "Yash#1008")
        if clean_username.lower() == expected_user and payload.password == expected_pass:
            authenticated = True
            admin_user = clean_username

    if not authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials.",
        )

    token = create_admin_access_token(admin_user)
    return AdminAuthResponse(
        access_token=token,
        token_type="bearer",
        role="admin",
        username=admin_user,
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


@router.patch("/enquiries/{enquiry_id}/status", response_model=EnquiryReportItem)
def update_enquiry_status(
    enquiry_id: int,
    payload: EnquiryStatusUpdateRequest,
    admin: dict[str, str] = Depends(get_current_admin),
) -> EnquiryReportItem:
    """
    4. Update Enquiry Status API:
    Allows admin to update an enquiry's status ('new', 'in_progress', 'resolved').
    """
    new_status = payload.status.strip().lower()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE enquiries
            SET status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id, name, email, phone, enquiry, status, created_at, updated_at
            """,
            (new_status, enquiry_id),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Enquiry not found.")

    return EnquiryReportItem.model_validate(row)
