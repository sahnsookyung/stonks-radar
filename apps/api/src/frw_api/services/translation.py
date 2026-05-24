from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def mark_translations_stale(db: Session, *, source_object_id: str, new_content_hash: str) -> int:
    result = db.execute(
        text(
            """
            update content_translation
            set stale = true, public_allowed = false
            where source_object_id = :source_object_id
              and source_content_hash <> :new_content_hash
              and stale = false
            """
        ),
        {"source_object_id": source_object_id, "new_content_hash": new_content_hash},
    )
    return int(result.rowcount or 0)


def assert_public_translation_fresh(db: Session, *, source_object_id: str, locale: str) -> bool:
    return bool(
        db.execute(
            text(
                """
                select 1
                from content_translation
                where source_object_id = :source_object_id
                  and target_locale = :locale
                  and stale = false
                  and public_allowed = true
                  and review_status in ('approved','quality_gate_passed')
                limit 1
                """
            ),
            {"source_object_id": source_object_id, "locale": locale},
        ).scalar_one_or_none()
    )
