from datetime import datetime, timedelta, timezone
import hashlib
import hmac

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash

from app.config import settings
from app.database import get_connection
from app.schemas import UserResponse


password_hasher = PasswordHash.recommended()
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def hash_otp(code: str) -> str:
    if not settings.jwt_secret:
        raise HTTPException(status_code=503, detail="JWT_SECRET is not configured.")
    return hmac.new(settings.jwt_secret.encode(), code.encode(), hashlib.sha256).hexdigest()


def create_access_token(user_id: int, email: str) -> str:
    if not settings.jwt_secret:
        raise HTTPException(status_code=503, detail="JWT_SECRET is not configured.")

    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": email,
            "role": "user",
            "iat": now,
            "exp": now + timedelta(minutes=settings.jwt_expiration_minutes),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def create_admin_access_token(email: str) -> str:
    if not settings.jwt_secret:
        raise HTTPException(status_code=503, detail="JWT_SECRET is not configured.")

    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "admin",
            "email": email,
            "role": "admin",
            "iat": now,
            "exp": now + timedelta(minutes=settings.jwt_expiration_minutes * 4),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, str]:
    unauthorized = HTTPException(
        status_code=401,
        detail="Admin access required or invalid token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not settings.jwt_secret:
        raise unauthorized

    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("role") != "admin":
            raise unauthorized
        return {"email": payload.get("email", ""), "role": "admin"}
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized



def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserResponse:
    unauthorized = HTTPException(
        status_code=401,
        detail="Invalid or missing access token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not settings.jwt_secret:
        raise unauthorized

    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized

    with get_connection() as connection:
        user = connection.execute(
            """
            SELECT id, name, email, phone, created_at
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        ).fetchone()

    if user is None:
        raise unauthorized
    return UserResponse.model_validate(user)