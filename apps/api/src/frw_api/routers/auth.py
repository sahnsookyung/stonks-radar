from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, Response
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
from frw_api.db.session import get_db
from frw_api.services.audit import audit

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str
    totp_code: str | None = None


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
