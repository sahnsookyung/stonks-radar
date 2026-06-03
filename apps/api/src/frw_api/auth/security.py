from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.core.settings import get_settings
from frw_api.db.session import get_db

SESSION_COOKIE = "frw_session"
PBKDF2_ITERATIONS = 260_000


def hash_secret(value: str) -> str:
    return hmac.new(get_settings().session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    peppered = (password + get_settings().password_pepper).encode()
    digest = hashlib.pbkdf2_hmac("sha256", peppered, salt.encode(), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iteration_s, salt, digest_hex = encoded.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    peppered = (password + get_settings().password_pepper).encode()
    digest = hashlib.pbkdf2_hmac("sha256", peppered, salt.encode(), int(iteration_s))
    return hmac.compare_digest(digest.hex(), digest_hex)


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    normalized = code.replace(" ", "")
    if len(normalized) != 6 or not normalized.isdigit():
        return False
    now_counter = int(time.time() // 30)
    for offset in range(-window, window + 1):
        if hmac.compare_digest(_totp_at(secret, now_counter + offset), normalized):
            return True
    return False


def _totp_at(secret: str, counter: int) -> str:
    key = base64.b32decode(secret.upper().replace(" ", ""), casefold=True)
    msg = counter.to_bytes(8, "big")
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{code % 1_000_000:06d}"


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    role: str
    session_id: str
    csrf_token: str


def create_session(db: Session, response: Response, user_id: str, role: str) -> str:
    token = new_session_token()
    csrf_token = new_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=12)
    db.execute(
        text(
            """
            insert into app_session(user_id, session_hash, csrf_hash, role, expires_at)
            values (:user_id, :session_hash, :csrf_hash, :role, :expires_at)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "session_hash": hash_secret(token),
            "csrf_hash": hash_secret(csrf_token),
            "role": role,
            "expires_at": expires_at,
        },
    ).scalar_one()
    db.commit()
    secure = get_settings().is_production
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=12 * 60 * 60,
        path="/",
    )
    return csrf_token


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def get_current_user(
    request: Request,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    row = (
        db.execute(
            text(
                """
                select s.id as session_id, s.csrf_hash, s.role, u.id as user_id, u.email, u.active
                from app_session s
                join app_user u on u.id = s.user_id
                where s.session_hash = :session_hash and s.expires_at > now()
                """
            ),
            {"session_hash": hash_secret(session_token)},
        )
        .mappings()
        .first()
    )
    if not row or not row["active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    request.state.session_id = str(row["session_id"])
    return CurrentUser(
        id=str(row["user_id"]),
        email=row["email"],
        role=row["role"],
        session_id=str(row["session_id"]),
        csrf_token=row["csrf_hash"],
    )


def require_csrf(
    user: CurrentUser = Depends(get_current_user),
    csrf_token: str | None = Header(default=None, alias="x-csrf-token"),
) -> CurrentUser:
    if not csrf_token or not hmac.compare_digest(hash_secret(csrf_token), user.csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    return user


def require_role(*roles: str):
    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency


def random_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")
