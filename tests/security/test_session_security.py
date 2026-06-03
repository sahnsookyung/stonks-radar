from __future__ import annotations

from starlette.responses import Response

from frw_api.auth.security import SESSION_COOKIE, create_session
from frw_api.core.settings import get_settings


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
