from datetime import datetime, timezone
import logging
import secrets
import smtplib

import sqlite3

try:
    import psycopg
    from psycopg.errors import UniqueViolation
except ImportError:
    psycopg = None
    UniqueViolation = sqlite3.IntegrityError


from fastapi import APIRouter, Depends, HTTPException, status
from app.config import settings

from app.database import get_connection
from app.email_service import send_otp_email
from app.schemas import (
    AuthResponse,
    LoginRequest,
    OtpSendRequest,
    OtpSendResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    SignupRequest,
    UserResponse,
)
from app.security import (
    create_access_token,
    get_current_user,
    hash_otp,
    hash_password,
    verify_password,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


def normalize_email(email: str) -> str:
    return email.strip().lower()


@router.post("/send-otp", response_model=OtpSendResponse)
def send_otp(payload: OtpSendRequest) -> OtpSendResponse:
    email = normalize_email(str(payload.email))
    code = f"{secrets.randbelow(10_000):04d}"
    otp_digest = hash_otp(code)

    with get_connection() as connection:
        existing_user = connection.execute(
            "SELECT id FROM users WHERE lower(email) = %s",
            (email,),
        ).fetchone()
        if existing_user:
            raise HTTPException(status_code=409, detail="An account with this email already exists.")

        rate = connection.execute(
            """
            SELECT COUNT(*) AS sent_count, MAX(created_at) AS last_sent_at
            FROM email_otps
            WHERE lower(email) = %s AND created_at > NOW() - INTERVAL '1 hour'
            """,
            (email,),
        ).fetchone()

        if rate["sent_count"] >= 5:
            raise HTTPException(status_code=429, detail="OTP send limit reached. Try again later.")

        last_sent_at = rate["last_sent_at"]
        if last_sent_at is not None:
            elapsed = (datetime.now(timezone.utc) - last_sent_at).total_seconds()
            remaining = settings.otp_resend_cooldown_seconds - int(elapsed)
            if remaining > 0:
                raise HTTPException(
                    status_code=429,
                    detail=f"Please wait {remaining} seconds before requesting another code.",
                    headers={"Retry-After": str(remaining)},
                )

        row = connection.execute(
            """
            INSERT INTO email_otps (email, otp_hash, expires_at)
            VALUES (%s, %s, NOW() + (%s * INTERVAL '1 minute'))
            RETURNING id
            """,
            (email, otp_digest, settings.otp_expiration_minutes),
        ).fetchone()
        challenge_id = row["id"]

    try:
        send_otp_email(email, code)
    except (OSError, RuntimeError, smtplib.SMTPException):
        logger.exception("Could not send email verification code")
        with get_connection() as connection:
            connection.execute("DELETE FROM email_otps WHERE id = %s", (challenge_id,))
        raise HTTPException(status_code=503, detail="Could not send the verification email.")

    return OtpSendResponse(
        message="Verification code sent.",
        expires_in_seconds=settings.otp_expiration_minutes * 60,
    )


@router.post("/verify-otp", response_model=OtpVerifyResponse)
def verify_otp(payload: OtpVerifyRequest) -> OtpVerifyResponse:
    email = normalize_email(str(payload.email))
    otp_digest = hash_otp(payload.code)
    is_invalid = False

    with get_connection() as connection:
        challenge = connection.execute(
            """
            SELECT id, otp_hash, expires_at, verified_at, attempts
            FROM email_otps
            WHERE lower(email) = %s
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            (email,),
        ).fetchone()

        if challenge is None or challenge["expires_at"] <= datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="Code is invalid or expired.")
        if challenge["verified_at"] is not None:
            return OtpVerifyResponse(verified=True)
        if challenge["attempts"] >= settings.otp_max_attempts:
            raise HTTPException(status_code=429, detail="Too many incorrect attempts. Request a new code.")

        if secrets.compare_digest(challenge["otp_hash"].strip(), otp_digest):
            connection.execute(
                "UPDATE email_otps SET verified_at = NOW() WHERE id = %s",
                (challenge["id"],),
            )
        else:
            connection.execute(
                "UPDATE email_otps SET attempts = attempts + 1 WHERE id = %s",
                (challenge["id"],),
            )
            is_invalid = True

    if is_invalid:
        raise HTTPException(status_code=400, detail="Code is invalid or expired.")
    return OtpVerifyResponse(verified=True)


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest) -> AuthResponse:
    email = normalize_email(str(payload.email))
    name = payload.name.strip()
    phone = payload.phone.strip()
    if not name or not phone:
        raise HTTPException(status_code=422, detail="Name and phone are required.")

    try:
        with get_connection() as connection:
            challenge = connection.execute(
                """
                SELECT id, verified_at
                FROM email_otps
                WHERE lower(email) = %s
                  AND verified_at IS NOT NULL
                  AND verified_at > NOW() - INTERVAL '15 minutes'
                  AND expires_at > NOW()
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                (email,),
            ).fetchone()
            if challenge is None:
                raise HTTPException(status_code=400, detail="Verify this email before signing up.")

            connection.execute("DELETE FROM email_otps WHERE id = %s", (challenge["id"],))
            user = connection.execute(
                """
                INSERT INTO users (name, email, phone, password_hash, email_verified_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, email, phone, created_at
                """,
                (name, email, phone, hash_password(payload.password), challenge["verified_at"]),
            ).fetchone()
    except UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc

    user_response = UserResponse.model_validate(user)
    token = create_access_token(user_response.id, str(user_response.email))
    return AuthResponse(access_token=token, user=user_response)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    email = normalize_email(str(payload.email))

    with get_connection() as connection:
        user = connection.execute(
            """
            SELECT id, name, email, phone, password_hash, created_at
            FROM users
            WHERE lower(email) = %s
            """,
            (email,),
        ).fetchone()

    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    user_response = UserResponse.model_validate(user)
    token = create_access_token(user_response.id, str(user_response.email))
    return AuthResponse(access_token=token, user=user_response)


@router.get("/me", response_model=UserResponse)
def get_me(user: UserResponse = Depends(get_current_user)) -> UserResponse:
    return user