from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
import json
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.auth.security import (
    clear_session,
    create_session,
    get_current_user,
    hash_secret,
    verify_password,
    verify_totp,
)
from frw_api.core.settings import get_settings
from frw_api.db.session import get_db
from frw_api.services.audit import audit

router = APIRouter()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


class LoginRequest(BaseModel):
    email: str
    password: str
    totp_code: str | None = None


class GoogleAuthConfig(BaseModel):
    enabled: bool
    recommended: bool
    start_url: str | None = None
    fallback_password_login: bool = True
    private_yahoo_admin_eligible: bool = False
    allowed_hint: str | None = None


@router.get("/google/config")
def google_config() -> GoogleAuthConfig:
    settings = get_settings()
    enabled = _google_oauth_configured()
    return GoogleAuthConfig(
        enabled=enabled,
        recommended=enabled,
        start_url="/api/auth/google/start" if enabled else None,
        private_yahoo_admin_eligible=enabled and settings.yahoo_admin_enabled,
        allowed_hint=_google_allowed_hint(),
    )


@router.get("/google/start")
def google_start(
    response: Response,
    redirect_to: str = Query(default="/admin", max_length=256),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    if not _google_oauth_configured():
        return Response("Google OAuth admin login is not configured.", status_code=404)
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    redirect_target = _safe_admin_redirect_path(redirect_to)
    db.execute(
        text(
            """
            insert into oauth_login_state(state_hash, nonce_hash, provider, redirect_to, expires_at)
            values (:state_hash, :nonce_hash, 'google', :redirect_to, :expires_at)
            on conflict (state_hash) do nothing
            """
        ),
        {
            "state_hash": hash_secret(state),
            "nonce_hash": hash_secret(nonce),
            "redirect_to": redirect_target,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
    )
    audit(
        db,
        user=None,
        action="auth.google_login_started",
        target_table="oauth_login_state",
        target_pk=hash_secret(state),
        after={"redirect_to": redirect_target},
    )
    db.commit()
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": _google_redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "prompt": "select_account",
        "include_granted_scopes": "true",
    }
    response.status_code = 302
    response.headers["location"] = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return response


@router.get("/google/callback")
def google_callback(
    code: str | None = Query(default=None, max_length=4096),
    state: str | None = Query(default=None, max_length=512),
    error: str | None = Query(default=None, max_length=256),
    db: Session = Depends(get_db),
):
    if error:
        return RedirectResponse(f"/admin/login?{urlencode({'oauth_error': error})}")
    if not code or not state:
        return Response("Missing Google OAuth callback parameters.", status_code=400)
    if not _google_oauth_configured():
        return Response("Google OAuth admin login is not configured.", status_code=404)

    state_row = _consume_google_state(db, state)
    if not state_row:
        audit(db, user=None, action="auth.google_state_rejected", target_table="oauth_login_state", target_pk="unknown")
        db.commit()
        return Response("Invalid or expired OAuth state.", status_code=400)

    profile = _fetch_google_profile(code, expected_nonce_hash=str(state_row["nonce_hash"]))
    email = str(profile.get("email") or "").strip().lower()
    subject = str(profile.get("sub") or "").strip()
    email_verified = profile.get("email_verified") in (True, "true", "True", "1")
    if not email or not subject or not email_verified or not _is_allowed_google_admin(email):
        audit(
            db,
            user=None,
            action="auth.google_login_denied",
            target_table="app_user",
            target_pk=email or "unknown",
            after={"email_hash": hash_secret(email) if email else None, "email_verified": email_verified},
        )
        db.commit()
        return Response("Google account is not authorized for admin access.", status_code=403)

    user_row = _upsert_google_admin_user(db, email=email, subject=subject, profile=profile)
    redirect_to = _safe_admin_redirect_path(str(state_row["redirect_to"] or "/admin"))
    response = RedirectResponse(redirect_to, status_code=302)
    create_session(db, response, str(user_row["id"]), user_row["role"], expose_csrf_cookie=True)
    audit(
        db,
        user=None,
        action="auth.google_login_succeeded",
        target_table="app_user",
        target_pk=str(user_row["id"]),
        after={"email_hash": hash_secret(email), "role": user_row["role"]},
    )
    db.commit()
    return response


@router.post("/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    row = (
        db.execute(
            text(
                """
                select u.id, u.email, u.password_hash, u.role, u.totp_required, t.secret_ciphertext
                from app_user u
                left join user_totp_secret t on t.user_id = u.id
                where u.email = :email and u.active = true
                """
            ),
            {"email": payload.email},
        )
        .mappings()
        .first()
    )
    if not row or not verify_password(payload.password, row["password_hash"]):
        audit(db, user=None, action="auth.login_failed", target_table="app_user", target_pk=payload.email)
        db.commit()
        return Response("Invalid credentials", status_code=401)
    if row["role"] in ("owner", "admin") and row["totp_required"]:
        if not payload.totp_code:
            return {"status": "totp_required", "message": "TOTP code required for owner/admin."}
        if not row["secret_ciphertext"] or not verify_totp(row["secret_ciphertext"], payload.totp_code):
            audit(db, user=None, action="auth.totp_failed", target_table="app_user", target_pk=str(row["id"]))
            db.commit()
            return Response("Invalid TOTP code", status_code=401)
    csrf_token = create_session(db, response, str(row["id"]), row["role"])
    audit(
        db,
        user=None,
        action="auth.login_succeeded",
        target_table="app_user",
        target_pk=str(row["id"]),
        after={"email_hash": hash_secret(row["email"]), "role": row["role"]},
    )
    db.commit()
    return {"status": "ok", "csrf_token": csrf_token}


@router.post("/logout")
def logout(
    response: Response,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.execute(text("delete from app_session where id = :id"), {"id": user.session_id})
    audit(db, user=user, action="auth.logout", target_table="app_session", target_pk=user.session_id)
    db.commit()
    clear_session(response)
    return {"status": "ok"}


@router.get("/me")
def me(user=Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "role": user.role}


def _google_oauth_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.google_oauth_admin_enabled
        and settings.google_oauth_client_id
        and settings.google_oauth_client_secret
    )


def _google_redirect_uri() -> str:
    settings = get_settings()
    base = (settings.public_base_url or settings.app_base_url).rstrip("/")
    path = settings.google_oauth_redirect_path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def _google_allowed_hint() -> str | None:
    settings = get_settings()
    emails = settings.google_oauth_allowed_email_list
    domains = settings.google_oauth_allowed_domain_list
    if emails:
        return f"{len(emails)} explicit admin email(s)"
    if domains:
        return f"{len(domains)} allowed domain(s)"
    return None


def _safe_admin_redirect_path(value: str) -> str:
    candidate = (value or "/admin").strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/admin"
    if not (candidate == "/admin" or candidate.startswith("/admin/")):
        return "/admin"
    return candidate


def _consume_google_state(db: Session, state: str):
    state_hash = hash_secret(state)
    row = (
        db.execute(
            text(
                """
                update oauth_login_state
                set used_at = now()
                where state_hash = :state_hash
                  and provider = 'google'
                  and used_at is null
                  and expires_at > now()
                returning state_hash, nonce_hash, redirect_to
                """
            ),
            {"state_hash": state_hash},
        )
        .mappings()
        .first()
    )
    return row


def _fetch_google_profile(code: str, *, expected_nonce_hash: str) -> dict[str, object]:
    settings = get_settings()
    with httpx.Client(timeout=12, trust_env=False) as client:
        token_response = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": _google_redirect_uri(),
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        if token_response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google OAuth token exchange failed.",
            )
        token_payload = token_response.json()
        id_token = token_payload.get("id_token")
        if not id_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google OAuth token response did not include an ID token.",
            )
        claims_response = client.get(
            GOOGLE_TOKENINFO_URL,
            params={"id_token": id_token},
            headers={"Accept": "application/json"},
        )
        if claims_response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google OAuth ID token validation failed.",
            )
        claims = claims_response.json()
    if not isinstance(claims, dict):
        return {}
    if claims.get("aud") != settings.google_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google OAuth audience mismatch.",
        )
    if hash_secret(str(claims.get("nonce") or "")) != expected_nonce_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google OAuth nonce mismatch.",
        )
    return claims


def _is_allowed_google_admin(email: str) -> bool:
    settings = get_settings()
    normalized = email.strip().lower()
    if not normalized:
        return False
    if normalized in settings.google_oauth_allowed_email_list:
        return True
    domain = normalized.rsplit("@", 1)[-1] if "@" in normalized else ""
    return bool(domain and domain in settings.google_oauth_allowed_domain_list)


def _upsert_google_admin_user(
    db: Session,
    *,
    email: str,
    subject: str,
    profile: dict[str, object],
):
    settings = get_settings()
    role = "owner" if email == settings.admin_email.strip().lower() else "admin"
    metadata = {
        "name": profile.get("name"),
        "picture": profile.get("picture"),
        "email_verified": profile.get("email_verified"),
    }
    row = (
        db.execute(
            text(
                """
                insert into app_user(
                  email, password_hash, role, active, totp_required,
                  auth_provider, external_subject, last_login_at, auth_metadata
                )
                values (
                  :email, :password_hash, :role, true, false,
                  'google', :subject, now(), cast(:metadata as jsonb)
                )
                on conflict (email) do update set
                  role = case
                    when app_user.role = 'owner' then app_user.role
                    else excluded.role
                  end,
                  auth_provider = 'google',
                  external_subject = excluded.external_subject,
                  active = true,
                  last_login_at = now(),
                  auth_metadata = excluded.auth_metadata,
                  updated_at = now()
                returning id, email, role
                """
            ),
            {
                "email": email,
                "password_hash": f"oauth:google:{hash_secret(subject)}",
                "role": role,
                "subject": subject,
                "metadata": json.dumps(metadata),
            },
        )
        .mappings()
        .one()
    )
    return row
