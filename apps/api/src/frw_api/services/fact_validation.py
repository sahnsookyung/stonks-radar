from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import text
from sqlalchemy.orm import Session


class FactValidationError(ValueError):
    pass


def validate_fact_shape(db: Session, *, fact_type: str, predicate: str, object_json: dict[str, Any]) -> None:
    row = (
        db.execute(
            text(
                """
                select json_schema, allowed_predicates, active
                from fact_type_registry
                where fact_type = :fact_type
                """
            ),
            {"fact_type": fact_type},
        )
        .mappings()
        .first()
    )
    if not row or not row["active"]:
        raise FactValidationError(f"Unknown or inactive fact type: {fact_type}")
    if predicate not in row["allowed_predicates"]:
        raise FactValidationError(f"Predicate {predicate} is not allowed for {fact_type}")
    validator = Draft202012Validator(row["json_schema"])
    errors = sorted(validator.iter_errors(object_json), key=lambda err: err.path)
    if errors:
        raise FactValidationError(errors[0].message)
