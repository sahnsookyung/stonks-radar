from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.auth.security import CurrentUser


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def audit(
    db: Session,
    *,
    user: CurrentUser | None,
    action: str,
    target_table: str | None = None,
    target_pk: str | None = None,
    before: Any = None,
    after: Any = None,
    request_id: str | None = None,
) -> None:
    db.execute(
        text(
            """
            insert into audit_log(
              actor_user_id, actor_role, action, target_table, target_pk,
              before_hash, after_hash, request_id
            )
            values (
              :actor_user_id, :actor_role, :action, :target_table, :target_pk,
              :before_hash, :after_hash, :request_id
            )
            """
        ),
        {
            "actor_user_id": user.id if user else None,
            "actor_role": user.role if user else None,
            "action": action,
            "target_table": target_table,
            "target_pk": target_pk,
            "before_hash": stable_hash(before) if before is not None else None,
            "after_hash": stable_hash(after) if after is not None else None,
            "request_id": request_id,
        },
    )
