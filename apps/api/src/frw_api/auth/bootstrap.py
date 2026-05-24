from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from frw_api.auth.security import hash_password
from frw_api.core.settings import get_settings
from frw_api.db.session import SessionLocal

logger = logging.getLogger(__name__)


def ensure_bootstrap_admin() -> None:
    settings = get_settings()
    if not settings.admin_bootstrap_password or not settings.admin_totp_secret:
        logger.info(
            "bootstrap_admin_skipped: ADMIN_BOOTSTRAP_PASSWORD and ADMIN_TOTP_SECRET are required"
        )
        return
    try:
        with SessionLocal() as db:
            existing = db.execute(
                text("select id from app_user where email = :email"),
                {"email": settings.admin_email},
            ).scalar_one_or_none()
            if existing:
                return
            user_id = db.execute(
                text(
                    """
                    insert into app_user(email, password_hash, role, totp_required)
                    values (:email, :password_hash, 'owner', true)
                    returning id
                    """
                ),
                {
                    "email": settings.admin_email,
                    "password_hash": hash_password(settings.admin_bootstrap_password),
                },
            ).scalar_one()
            db.execute(
                text(
                    """
                    insert into user_totp_secret(user_id, secret_ciphertext)
                    values (:user_id, :secret)
                    """
                ),
                {"user_id": user_id, "secret": settings.admin_totp_secret},
            )
            db.commit()
            logger.info("bootstrap_admin_created")
    except SQLAlchemyError as exc:
        logger.warning("bootstrap_admin_unavailable: %s", exc.__class__.__name__)
