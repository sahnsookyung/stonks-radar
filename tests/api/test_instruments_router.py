from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from frw_api.routers.instruments import InstrumentReviewCreateRequest, create_review_request


class _MappingResult:
    def __init__(self, row: dict[str, object] | None):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _InsertResult:
    def __init__(self, row_id: str):
        self._row_id = row_id

    def scalar_one(self) -> str:
        return self._row_id


class _ReviewDb:
    def __init__(self, existing: dict[str, object] | None = None):
        self.existing = existing
        self.executions: list[dict[str, object]] = []
        self.committed = False

    def execute(self, _statement, params=None):
        self.executions.append(params or {})
        if len(self.executions) == 1:
            return _MappingResult(self.existing)
        return _InsertResult("00000000-0000-0000-0000-000000000123")

    def commit(self):
        self.committed = True


def _request():
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="203.0.113.42"))


def test_create_review_request_dedupes_open_requests():
    row_id = "00000000-0000-0000-0000-000000000999"
    db = _ReviewDb(existing={"id": UUID(row_id), "status": "queued"})

    result = create_review_request(
        InstrumentReviewCreateRequest(query=" QQQM ", context_screen="BUILDER"),
        _request(),
        db,
    )

    assert result == {"id": row_id, "status": "queued", "deduped": True}
    assert len(db.executions) == 1
    assert not db.committed


def test_create_review_request_normalizes_insert_payload():
    db = _ReviewDb()

    result = create_review_request(
        InstrumentReviewCreateRequest(
            query=" QQQM ",
            context_screen="BUILDER",
            optional_notes="  missing Nasdaq ETF alias  ",
        ),
        _request(),
        db,
    )

    assert result == {"id": "00000000-0000-0000-0000-000000000123", "status": "queued"}
    assert db.executions[1]["query"] == "QQQM"
    assert db.executions[1]["optional_notes"] == "missing Nasdaq ETF alias"
    assert db.committed
