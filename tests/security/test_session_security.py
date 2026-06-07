from __future__ import annotations

from starlette.responses import Response

import pytest
from fastapi import HTTPException

from frw_api.auth.security import CSRF_COOKIE, SESSION_COOKIE, create_session, hash_secret
from frw_api.core.settings import get_settings
from frw_api.routers import auth as auth_router
from frw_api.routers.auth import (
    _fetch_google_profile,
    _google_oauth_configured,
    _google_redirect_uri,
    _is_allowed_google_admin,
    _safe_admin_redirect_path,
)


class _ScalarResult:
    def scalar_one(self):
        return "session-id"


class _SessionDb:
    def __init__(self):
        self.committed = False

    def execute(self, *_args, **_kwargs):
        return _ScalarResult()

    def commit(self):
        self.committed = True


class _JsonResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _OAuthClient:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, *_args, **_kwargs):
        return _JsonResponse(200, {"id_token": "id-token"})

    def get(self, *_args, **_kwargs):
        return _JsonResponse(
            200,
            {
                "aud": "client-id",
                "nonce": "nonce-value",
                "sub": "google-subject",
                "email": "owner@example.com",
                "email_verified": "true",
            },
        )


class _BadAudienceOAuthClient(_OAuthClient):
    def get(self, *_args, **_kwargs):
        payload = super().get(*_args, **_kwargs).json()
        payload["aud"] = "other-client"
        return _JsonResponse(200, payload)


def test_prod_alias_sets_secure_session_cookie(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    get_settings.cache_clear()
    response = Response()
    db = _SessionDb()

    create_session(db, response, "user-id", "OWNER")

    cookie = response.headers["set-cookie"]
    assert db.committed is True
    assert SESSION_COOKIE in cookie
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    get_settings.cache_clear()


def test_oauth_session_exposes_short_lived_csrf_cookie_only_when_requested(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    get_settings.cache_clear()
    response = Response()
    db = _SessionDb()

    create_session(db, response, "user-id", "admin", expose_csrf_cookie=True)

    cookies = response.headers.getlist("set-cookie")
    assert any(SESSION_COOKIE in cookie and "HttpOnly" in cookie for cookie in cookies)
    csrf_cookie = next(cookie for cookie in cookies if CSRF_COOKIE in cookie)
    assert "HttpOnly" not in csrf_cookie
    assert "Secure" in csrf_cookie
    assert "Max-Age=300" in csrf_cookie
    get_settings.cache_clear()


def test_google_oauth_requires_enable_and_client_credentials(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_ADMIN_ENABLED", "true")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    get_settings.cache_clear()

    assert _google_oauth_configured() is False

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    get_settings.cache_clear()
    assert _google_oauth_configured() is True
    get_settings.cache_clear()


def test_google_oauth_allows_only_explicit_admins_or_configured_domains(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("GOOGLE_OAUTH_ALLOWED_EMAILS", "analyst@example.com")
    monkeypatch.setenv("GOOGLE_OAUTH_ALLOWED_DOMAINS", "trusted.example")
    get_settings.cache_clear()

    assert _is_allowed_google_admin("owner@example.com") is True
    assert _is_allowed_google_admin("analyst@example.com") is True
    assert _is_allowed_google_admin("person@trusted.example") is True
    assert _is_allowed_google_admin("person@other.example") is False
    get_settings.cache_clear()


def test_google_oauth_redirects_are_internal_admin_paths(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://stonks.example")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_PATH", "/api/auth/google/callback")
    get_settings.cache_clear()

    assert _google_redirect_uri() == "https://stonks.example/api/auth/google/callback"
    assert _safe_admin_redirect_path("/admin/data-sources") == "/admin/data-sources"
    assert _safe_admin_redirect_path("https://evil.example/admin") == "/admin"
    assert _safe_admin_redirect_path("//evil.example/admin") == "/admin"
    assert _safe_admin_redirect_path("/en") == "/admin"
    get_settings.cache_clear()


def test_google_profile_exchange_validates_audience_and_nonce(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://stonks.example")
    monkeypatch.setenv("GOOGLE_OAUTH_ADMIN_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    get_settings.cache_clear()
    monkeypatch.setattr(auth_router.httpx, "Client", _OAuthClient)

    profile = _fetch_google_profile("code", expected_nonce_hash=hash_secret("nonce-value"))

    assert profile["email"] == "owner@example.com"
    assert profile["sub"] == "google-subject"

    monkeypatch.setattr(auth_router.httpx, "Client", _BadAudienceOAuthClient)
    with pytest.raises(HTTPException) as exc_info:
        _fetch_google_profile("code", expected_nonce_hash=hash_secret("nonce-value"))
    assert exc_info.value.status_code == 403
    get_settings.cache_clear()
