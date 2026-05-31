from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

DEFAULT_ENDPOINT = "daily_prices"
DEFAULT_INTERVAL = "1day"
STAGING_METADATA_RETENTION_DAYS = 14


@dataclass(frozen=True)
class StoredHistoryResult:
    provider: str
    series: list[dict[str, Any]]
    coverage: list[dict[str, Any]]
    source_policy_digest: str
    data_version: str
    snapshot_id: str | None
    snapshot_ids: list[str]
    coherence_status: str
    quality_state: str
    warnings: list[str]


@dataclass(frozen=True)
class ValidationResult:
    quality_state: str
    promotable: bool
    issues: list[dict[str, Any]]
    expected_sessions: dict[str, list[str]]
    summary: dict[str, Any]


@dataclass(frozen=True)
class CalculationReadiness:
    ready: bool
    reason: str | None
    snapshot_id: str | None
    coherence_status: str
    snapshot_ids: list[str]
    missing_symbols: list[str]
    missing_sessions: dict[str, list[str]]
    required_fx_pairs: list[dict[str, str]]
    fx_coverage_status: str
    symbols: list[str]
    start: str
    end: str
    base_currency: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "reason": self.reason,
            "snapshot_id": self.snapshot_id,
            "coherence_status": self.coherence_status,
            "snapshot_ids": self.snapshot_ids,
            "missing_symbols": self.missing_symbols,
            "missing_sessions": self.missing_sessions,
            "required_fx_pairs": self.required_fx_pairs,
            "fx_coverage_status": self.fx_coverage_status,
            "symbols": self.symbols,
            "start": self.start,
            "end": self.end,
            "base_currency": self.base_currency,
        }


class MarketHistoryCalculationNotReady(ValueError):
    def __init__(self, readiness: CalculationReadiness) -> None:
        self.readiness = readiness
        super().__init__(readiness.reason or "market history is not calculation ready")


def market_history_calculation_readiness(
    stored: StoredHistoryResult | None,
    *,
    symbols: list[str],
    start: date,
    end: date,
    base_currency: str = "USD",
) -> CalculationReadiness:
    normalized_symbols = list(dict.fromkeys(str(symbol).upper() for symbol in symbols if symbol))
    normalized_base_currency = (base_currency or "USD").upper()
    if stored is None:
        return CalculationReadiness(
            ready=False,
            reason="missing_market_history",
            snapshot_id=None,
            coherence_status="missing",
            snapshot_ids=[],
            missing_symbols=normalized_symbols,
            missing_sessions={},
            required_fx_pairs=[],
            fx_coverage_status="not_required",
            symbols=normalized_symbols,
            start=start.isoformat(),
            end=end.isoformat(),
            base_currency=normalized_base_currency,
        )

    series_by_symbol = {
        str(item.get("symbol") or "").upper(): item for item in stored.series if item.get("symbol")
    }
    missing_symbols = [symbol for symbol in normalized_symbols if symbol not in series_by_symbol]
    missing_sessions: dict[str, list[str]] = {}
    required_fx_pairs: list[dict[str, str]] = []
    seen_fx_pairs: set[tuple[str, str]] = set()
    for symbol in normalized_symbols:
        item = series_by_symbol.get(symbol)
        points = item.get("points", []) if item else []
        actual_dates = {
            str(point.get("date"))[:10]
            for point in points
            if isinstance(point, dict) and point.get("date")
        }
        expected_dates = [
            session.isoformat() for session in expected_market_sessions(symbol, start, end)
        ]
        missing = [session for session in expected_dates if session not in actual_dates]
        if missing:
            missing_sessions[symbol] = missing
        for point in points:
            if not isinstance(point, dict):
                continue
            currency = str(point.get("currency") or normalized_base_currency).upper()
            if currency == normalized_base_currency:
                continue
            pair = (currency, normalized_base_currency)
            if pair in seen_fx_pairs:
                continue
            seen_fx_pairs.add(pair)
            required_fx_pairs.append({"from": currency, "to": normalized_base_currency})

    fx_coverage_status = "unsupported_no_fx_snapshot_store" if required_fx_pairs else "not_required"
    reason = None
    if stored.coherence_status != "single_snapshot":
        reason = f"market_history_{stored.coherence_status}"
    elif missing_symbols:
        reason = "missing_market_history_symbols"
    elif missing_sessions:
        reason = "missing_market_sessions"
    elif required_fx_pairs:
        reason = "fx_coverage_unsupported"

    return CalculationReadiness(
        ready=reason is None,
        reason=reason,
        snapshot_id=stored.snapshot_id,
        coherence_status=stored.coherence_status,
        snapshot_ids=stored.snapshot_ids,
        missing_symbols=missing_symbols,
        missing_sessions=missing_sessions,
        required_fx_pairs=required_fx_pairs,
        fx_coverage_status=fx_coverage_status,
        symbols=normalized_symbols,
        start=start.isoformat(),
        end=end.isoformat(),
        base_currency=normalized_base_currency,
    )


def require_calculation_ready_market_history(
    stored: StoredHistoryResult | None,
    *,
    symbols: list[str],
    start: date,
    end: date,
    base_currency: str = "USD",
) -> CalculationReadiness:
    readiness = market_history_calculation_readiness(
        stored,
        symbols=symbols,
        start=start,
        end=end,
        base_currency=base_currency,
    )
    if not readiness.ready:
        raise MarketHistoryCalculationNotReady(readiness)
    return readiness


def load_stored_market_history(
    db: Session | None,
    *,
    symbols: list[str],
    start: date,
    end: date,
    provider_order: list[str],
    display_mode: str,
    public_display_allowlist: set[str],
) -> StoredHistoryResult | None:
    if db is None or not symbols:
        return None
    if not _table_available(db, "market_price_bar"):
        return None
    stmt = text(
        """
            select
              bar.symbol,
              bar.price_date,
              bar.provider_key,
              bar.close,
              bar.adjusted_close,
              bar.volume,
              bar.currency_code,
              bar.exchange,
              bar.timezone,
              bar.provider_price_timestamp,
              bar.ingested_at,
              bar.source_revision,
              bar.quality_state,
              bar.market_data_snapshot_id,
              bar.source_policy_json,
              bar.quality_json,
              snap.batch_id as snapshot_batch_id,
              snap.provider_revision as snapshot_provider_revision,
              snap.content_hash as snapshot_content_hash,
              snap.quality_state as snapshot_quality_state
            from market_price_bar bar
            left join market_data_snapshot snap
              on snap.id = bar.market_data_snapshot_id
            where bar.symbol in :symbols
              and bar.interval = :interval
              and bar.price_date between :start and :end
              and bar.quality_state = 'valid'
            order by symbol, price_date, ingested_at desc
            """
    ).bindparams(bindparam("symbols", expanding=True))
    try:
        rows = (
            db.execute(
                stmt,
                {
                    "symbols": tuple(symbols),
                    "interval": DEFAULT_INTERVAL,
                    "start": start,
                    "end": end,
                },
            )
            .mappings()
            .all()
        )
    except SQLAlchemyError:
        db.rollback()
        return None
    provider_rank = {provider: index for index, provider in enumerate(provider_order)}
    chosen: dict[tuple[str, date], dict[str, Any]] = {}
    for row in rows:
        provider = str(row["provider_key"])
        policy = _policy_from_row(row.get("source_policy_json"))
        if (
            display_mode == "public"
            and provider not in public_display_allowlist
            and not bool(policy.get("raw_public_allowed"))
        ):
            continue
        key = (str(row["symbol"]), row["price_date"])
        existing = chosen.get(key)
        if existing is None or _provider_rank(provider, provider_rank) < _provider_rank(
            str(existing["provider_key"]), provider_rank
        ):
            chosen[key] = dict(row)

    series: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    policy_parts: list[str] = []
    version_parts: list[str] = []
    snapshot_ids: set[str] = set()
    quality_states: set[str] = set()
    unversioned_seen = False
    for symbol in symbols:
        symbol_rows = sorted(
            [row for (row_symbol, _price_date), row in chosen.items() if row_symbol == symbol],
            key=lambda item: item["price_date"],
        )
        if not symbol_rows:
            return None
        points = [_stored_point(row) for row in symbol_rows]
        providers = sorted({str(row["provider_key"]) for row in symbol_rows})
        symbol_snapshot_ids = sorted(
            {
                str(row["market_data_snapshot_id"])
                for row in symbol_rows
                if row.get("market_data_snapshot_id")
            }
        )
        snapshot_ids.update(symbol_snapshot_ids)
        unversioned_seen = unversioned_seen or any(
            not row.get("market_data_snapshot_id") for row in symbol_rows
        )
        quality_states.update(str(row.get("quality_state") or "valid") for row in symbol_rows)
        first_date = str(symbol_rows[0]["price_date"])
        latest_date = str(symbol_rows[-1]["price_date"])
        latest_ingested_at = max(
            str(row["ingested_at"]) for row in symbol_rows if row.get("ingested_at")
        )
        policy_json = [
            _stable_json(_policy_from_row(row.get("source_policy_json"))) for row in symbol_rows
        ]
        policy_parts.extend(policy_json)
        version_parts.append(
            f"{symbol}:{latest_date}:{latest_ingested_at}:{','.join(providers)}:{','.join(symbol_snapshot_ids)}"
        )
        series.append(
            {
                "symbol": symbol,
                "points": points,
                "source": "stored_normalized_daily_bars",
                "providers": providers,
                "snapshot_ids": symbol_snapshot_ids,
            }
        )
        coverage.append(
            {
                "symbol": symbol,
                "point_count": len(points),
                "first_date": first_date,
                "latest_date": latest_date,
                "providers": providers,
                "snapshot_ids": symbol_snapshot_ids,
                "latest_ingested_at": latest_ingested_at,
                "status": "stored",
                "quality_state": "valid",
            }
        )

    digest = _sha256("|".join(sorted(policy_parts)))
    data_version = _sha256("|".join(version_parts))[:16]
    sorted_snapshot_ids = sorted(snapshot_ids)
    if not sorted_snapshot_ids:
        coherence_status = "unversioned"
    elif len(sorted_snapshot_ids) == 1 and not unversioned_seen:
        coherence_status = "single_snapshot"
    else:
        coherence_status = "mixed_snapshots"
    warnings = []
    if coherence_status == "mixed_snapshots":
        warnings.append(
            "Stored history spans multiple market data snapshots; downstream calculations should pin a single snapshot."
        )
    elif coherence_status == "unversioned":
        warnings.append("Stored history contains legacy rows without market_data_snapshot_id.")
    return StoredHistoryResult(
        provider="stored_normalized_daily_bars",
        series=series,
        coverage=coverage,
        source_policy_digest=digest,
        data_version=data_version,
        snapshot_id=sorted_snapshot_ids[0] if len(sorted_snapshot_ids) == 1 else None,
        snapshot_ids=sorted_snapshot_ids,
        coherence_status=coherence_status,
        quality_state="valid" if quality_states <= {"valid"} else "mixed",
        warnings=warnings,
    )


def store_market_history_series(
    db: Session | None,
    *,
    provider_key: str,
    series: list[dict[str, Any]],
    requested_start: date,
    requested_end: date,
) -> dict[str, Any]:
    if db is None:
        return {"stored": 0, "storage_allowed": False, "reason": "no database session"}
    required_tables = {
        "market_price_bar",
        "market_fetch_run",
        "market_price_bar_candidate",
        "market_data_snapshot",
        "market_data_snapshot_member",
    }
    if not all(_table_available(db, table_name) for table_name in required_tables):
        return {"stored": 0, "storage_allowed": False, "reason": "market history tables missing"}
    policy = market_data_source_policy(db, provider_key=provider_key, endpoint_key=DEFAULT_ENDPOINT)
    if not bool(policy.get("normalized_storage_allowed")):
        return {
            "stored": 0,
            "storage_allowed": False,
            "reason": "source policy does not allow normalized storage",
            "source_policy": policy,
        }
    skipped = 0
    batch_id = str(uuid4())
    policy_json = _stable_json(policy)
    policy_digest = _sha256(policy_json)
    symbols: list[str] = []
    normalized_rows: list[dict[str, Any]] = []
    for item in series:
        symbol = str(item.get("symbol") or "").upper()
        points = item.get("points") if isinstance(item.get("points"), list) else []
        if not symbol or not points:
            skipped += 1
            continue
        symbols.append(symbol)
        staging_hash = _sha256(
            _stable_json({"provider_key": provider_key, "symbol": symbol, "points": points})
        )
        staging_metadata = _staging_metadata(
            provider_key=provider_key,
            symbol=symbol,
            points=points,
            source_hash=staging_hash,
            source_policy_digest=policy_digest,
        )
        db.execute(
            text(
                """
                insert into market_price_bar_staging (
                  batch_id,
                  provider_key,
                  symbol,
                  interval,
                  requested_start,
                  requested_end,
                  payload_json,
                  source_hash
                )
                values (
                  :batch_id,
                  :provider_key,
                  :symbol,
                  :interval,
                  :requested_start,
                  :requested_end,
                  cast(:payload_json as jsonb),
                  :source_hash
                )
                """
            ),
            {
                "batch_id": batch_id,
                "provider_key": provider_key,
                "symbol": symbol,
                "interval": DEFAULT_INTERVAL,
                "requested_start": requested_start,
                "requested_end": requested_end,
                "payload_json": _stable_json(staging_metadata),
                "source_hash": staging_hash,
            },
        )
        for point in points:
            row = _normalize_point(symbol, provider_key, point, policy)
            if row is None:
                skipped += 1
                continue
            normalized_rows.append(row)
    validation = validate_market_history_batch(
        normalized_rows,
        requested_start=requested_start,
        requested_end=requested_end,
    )
    content_hash = _sha256(_stable_json(normalized_rows))
    fetch_run_id = _insert_fetch_run(
        db,
        batch_id=batch_id,
        provider_key=provider_key,
        symbols=symbols,
        quota_reservation_tokens=_quota_tokens(normalized_rows),
        requested_start=requested_start,
        requested_end=requested_end,
        policy_digest=policy_digest,
        content_hash=content_hash,
        validation=validation,
    )
    candidate_ids = _insert_candidate_rows(
        db,
        fetch_run_id=fetch_run_id,
        batch_id=batch_id,
        rows=normalized_rows,
        policy_json=policy_json,
        quality_state=validation.quality_state,
    )
    if not validation.promotable:
        _mark_fetch_run(
            db,
            fetch_run_id=fetch_run_id,
            status="quarantined",
            quality_state=validation.quality_state,
            validation=validation,
        )
        _prune_staging_metadata(db)
        return {
            "stored": 0,
            "candidate_rows": len(candidate_ids),
            "skipped": skipped,
            "promoted": False,
            "quality_state": validation.quality_state,
            "validation_issues": validation.issues,
            "storage_allowed": True,
            "source_policy": policy,
            "source_policy_digest": policy_digest,
            "batch_id": batch_id,
            "fetch_run_id": fetch_run_id,
        }

    snapshot_id = _insert_snapshot(
        db,
        fetch_run_id=fetch_run_id,
        batch_id=batch_id,
        provider_key=provider_key,
        symbols=symbols,
        rows=normalized_rows,
        policy_digest=policy_digest,
        content_hash=content_hash,
        validation=validation,
    )
    stored = _promote_rows(
        db,
        rows=normalized_rows,
        policy_json=policy_json,
        snapshot_id=snapshot_id,
        candidate_ids=candidate_ids,
    )
    _mark_fetch_run(
        db,
        fetch_run_id=fetch_run_id,
        status="promoted",
        quality_state="valid",
        validation=validation,
    )
    _prune_staging_metadata(db)
    return {
        "stored": stored,
        "candidate_rows": len(candidate_ids),
        "skipped": skipped,
        "promoted": True,
        "quality_state": "valid",
        "storage_allowed": True,
        "source_policy": policy,
        "source_policy_digest": policy_digest,
        "snapshot_id": snapshot_id,
        "batch_id": batch_id,
        "fetch_run_id": fetch_run_id,
        "validation_issues": [],
    }


def validate_market_history_batch(
    rows: list[dict[str, Any]],
    *,
    requested_start: date,
    requested_end: date,
    now: datetime | None = None,
) -> ValidationResult:
    now = now or datetime.now(timezone.utc)
    issues: list[dict[str, Any]] = []
    expected_sessions: dict[str, list[str]] = {}
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(str(row["symbol"]), []).append(row)
    if not rows:
        issues.append(
            _issue(
                "batch",
                None,
                None,
                "quarantine",
                "empty_batch",
                "provider returned no normalized rows",
            )
        )
    for symbol, symbol_rows in by_symbol.items():
        symbol_rows.sort(key=lambda item: item["price_date"])
        seen_dates: set[date] = set()
        duplicate_dates: set[date] = set()
        currencies = {str(row.get("currency_code") or "") for row in symbol_rows}
        exchanges = {str(row.get("exchange") or "") for row in symbol_rows if row.get("exchange")}
        timezones = {str(row.get("timezone") or "") for row in symbol_rows if row.get("timezone")}
        expected = expected_market_sessions(symbol, requested_start, requested_end)
        expected_sessions[symbol] = [item.isoformat() for item in expected]
        actual_dates = {row["price_date"] for row in symbol_rows}
        for row in symbol_rows:
            price_date = row["price_date"]
            if price_date in seen_dates:
                duplicate_dates.add(price_date)
            seen_dates.add(price_date)
            issues.extend(_row_validation_issues(row, now=now))
        for duplicated in sorted(duplicate_dates):
            issues.append(
                _issue(
                    symbol,
                    duplicated,
                    None,
                    "quarantine",
                    "duplicate_date",
                    "duplicate provider bar date",
                )
            )
        if len(currencies) > 1:
            issues.append(
                _issue(
                    symbol,
                    None,
                    None,
                    "quarantine",
                    "currency_inconsistent",
                    "multiple currencies in one batch",
                )
            )
        if len(exchanges) > 1:
            issues.append(
                _issue(
                    symbol,
                    None,
                    None,
                    "suspect",
                    "exchange_inconsistent",
                    "multiple exchanges in one batch",
                )
            )
        if len(timezones) > 1:
            issues.append(
                _issue(
                    symbol,
                    None,
                    None,
                    "suspect",
                    "timezone_inconsistent",
                    "multiple timezones in one batch",
                )
            )
        missing = sorted(set(expected) - actual_dates)
        if expected:
            coverage_ratio = 1 - (len(missing) / len(expected))
            if len(missing) > 2 and coverage_ratio < 0.60:
                issues.append(
                    _issue(
                        symbol,
                        None,
                        None,
                        "suspect",
                        "expected_session_coverage_low",
                        "provider batch is missing too many expected sessions",
                        missing_dates=[item.isoformat() for item in missing[-10:]],
                        coverage_ratio=round(coverage_ratio, 3),
                    )
                )
        issues.extend(_day_over_day_issues(symbol, symbol_rows))
    severities = {str(issue["severity"]) for issue in issues}
    if "quarantine" in severities:
        quality_state = "quarantined"
    elif "suspect" in severities:
        quality_state = "suspect"
    else:
        quality_state = "valid"
    return ValidationResult(
        quality_state=quality_state,
        promotable=quality_state == "valid",
        issues=issues,
        expected_sessions=expected_sessions,
        summary={
            "quality_state": quality_state,
            "promotable": quality_state == "valid",
            "issue_count": len(issues),
            "issues": issues[:50],
            "symbols": sorted(by_symbol),
            "row_count": len(rows),
            "requested_start": requested_start.isoformat(),
            "requested_end": requested_end.isoformat(),
        },
    )


def expected_market_sessions(symbol: str, start: date, end: date) -> list[date]:
    calendar = _calendar_key(symbol)
    current = start
    sessions: list[date] = []
    while current <= end:
        if calendar == "crypto":
            sessions.append(current)
        elif current.weekday() < 5 and current not in _market_holidays(calendar, current.year):
            sessions.append(current)
        current += timedelta(days=1)
    return sessions


def _row_validation_issues(row: dict[str, Any], *, now: datetime) -> list[dict[str, Any]]:
    symbol = str(row["symbol"])
    price_date = row["price_date"]
    issues: list[dict[str, Any]] = []
    close = row.get("close")
    open_value = row.get("open")
    high = row.get("high")
    low = row.get("low")
    adjusted_close = row.get("adjusted_close")
    values = {"open": open_value, "high": high, "low": low, "close": close}
    for field, value in values.items():
        if value is not None and float(value) <= 0:
            issues.append(
                _issue(
                    symbol,
                    price_date,
                    field,
                    "quarantine",
                    "non_positive_ohlc",
                    f"{field} must be positive",
                )
            )
    if close is None or float(close) <= 0:
        issues.append(
            _issue(
                symbol, price_date, "close", "quarantine", "missing_close", "close must be positive"
            )
        )
    if high is not None and low is not None:
        if float(high) < float(low):
            issues.append(
                _issue(
                    symbol, price_date, None, "quarantine", "ohlc_invariant", "high is below low"
                )
            )
        comparison_values = [value for value in (open_value, close) if value is not None]
        if comparison_values and float(high) < max(float(value) for value in comparison_values):
            issues.append(
                _issue(
                    symbol,
                    price_date,
                    "high",
                    "quarantine",
                    "ohlc_invariant",
                    "high is below open or close",
                )
            )
        if comparison_values and float(low) > min(float(value) for value in comparison_values):
            issues.append(
                _issue(
                    symbol,
                    price_date,
                    "low",
                    "quarantine",
                    "ohlc_invariant",
                    "low is above open or close",
                )
            )
    if adjusted_close is not None and close:
        if float(adjusted_close) <= 0:
            issues.append(
                _issue(
                    symbol,
                    price_date,
                    "adjusted_close",
                    "quarantine",
                    "non_positive_adjusted_close",
                    "adjusted close must be positive",
                )
            )
        else:
            ratio = float(adjusted_close) / float(close)
            if ratio < 0.02 or ratio > 50:
                issues.append(
                    _issue(
                        symbol,
                        price_date,
                        "adjusted_close",
                        "suspect",
                        "adjusted_raw_implausible",
                        "adjusted/raw close ratio is implausible",
                        ratio=round(ratio, 6),
                    )
                )
    provider_timestamp = row.get("provider_price_timestamp")
    if isinstance(provider_timestamp, datetime):
        timestamp = (
            provider_timestamp
            if provider_timestamp.tzinfo
            else provider_timestamp.replace(tzinfo=timezone.utc)
        )
        if timestamp > now + timedelta(days=1):
            issues.append(
                _issue(
                    symbol,
                    price_date,
                    "provider_timestamp",
                    "suspect",
                    "provider_timestamp_future",
                    "provider timestamp is too far in the future",
                )
            )
        if timestamp.date() < price_date - timedelta(days=3):
            issues.append(
                _issue(
                    symbol,
                    price_date,
                    "provider_timestamp",
                    "suspect",
                    "provider_timestamp_stale",
                    "provider timestamp predates the price date",
                )
            )
    return issues


def _day_over_day_issues(symbol: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for row in rows:
        close = (
            row.get("adjusted_close") if row.get("adjusted_close") is not None else row.get("close")
        )
        if previous is not None:
            previous_close = (
                previous.get("adjusted_close")
                if previous.get("adjusted_close") is not None
                else previous.get("close")
            )
            if previous_close and close:
                move = abs(float(close) / float(previous_close) - 1)
                if move > 0.45:
                    issues.append(
                        _issue(
                            symbol,
                            row["price_date"],
                            "close",
                            "suspect",
                            "max_day_over_day_movement",
                            "day-over-day close movement exceeds the quarantine threshold",
                            move=round(move, 6),
                            previous_date=str(previous["price_date"]),
                        )
                    )
        previous = row
    return issues


def _issue(
    symbol: str,
    price_date: date | None,
    field: str | None,
    severity: str,
    code: str,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": symbol,
        "severity": severity,
        "code": code,
        "message": message,
    }
    if price_date is not None:
        payload["date"] = price_date.isoformat()
    if field is not None:
        payload["field"] = field
    payload.update(details)
    return payload


def _calendar_key(symbol: str) -> str:
    upper = symbol.upper()
    if upper.endswith("-USD") or upper.startswith(("BTC", "ETH")):
        return "crypto"
    if upper.endswith(".KS") or upper.endswith(".KQ"):
        return "korea"
    if upper.endswith(".T") or upper.endswith(".JP"):
        return "japan"
    return "us"


def _market_holidays(calendar: str, year: int) -> set[date]:
    if calendar == "korea":
        return _observed_fixed_holidays(
            year, ((1, 1), (3, 1), (5, 5), (6, 6), (8, 15), (10, 3), (10, 9), (12, 25))
        )
    if calendar == "japan":
        return _observed_fixed_holidays(
            year, ((1, 1), (2, 11), (2, 23), (4, 29), (5, 3), (5, 4), (5, 5), (11, 3), (11, 23))
        )
    if calendar == "us":
        holidays = _observed_fixed_holidays(year, ((1, 1), (6, 19), (7, 4), (12, 25)))
        holidays.update(
            {
                _nth_weekday(year, 1, 0, 3),
                _nth_weekday(year, 2, 0, 3),
                _last_weekday(year, 5, 0),
                _nth_weekday(year, 9, 0, 1),
                _nth_weekday(year, 11, 3, 4),
            }
        )
        return holidays
    return set()


def _observed_fixed_holidays(year: int, values: tuple[tuple[int, int], ...]) -> set[date]:
    holidays: set[date] = set()
    for month, day in values:
        holiday = date(year, month, day)
        holidays.add(holiday)
        if holiday.weekday() == 5:
            holidays.add(holiday - timedelta(days=1))
        elif holiday.weekday() == 6:
            holidays.add(holiday + timedelta(days=1))
    return holidays


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return current + timedelta(days=offset + (n - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + int(month == 12), 1 if month == 12 else month + 1, 1)
    current = next_month - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _quota_tokens(rows: list[dict[str, Any]]) -> list[str]:
    tokens: list[str] = []
    for row in rows:
        value = row.get("source_revision")
        if not value:
            continue
        try:
            token = str(UUID(str(value)))
        except (TypeError, ValueError):
            continue
        tokens.append(token)
    return list(dict.fromkeys(tokens))


def _insert_fetch_run(
    db: Session,
    *,
    batch_id: str,
    provider_key: str,
    symbols: list[str],
    quota_reservation_tokens: list[str],
    requested_start: date,
    requested_end: date,
    policy_digest: str,
    content_hash: str,
    validation: ValidationResult,
) -> str:
    row = db.execute(
        text(
            """
            insert into market_fetch_run(
              batch_id, provider_key, endpoint_key, requested_symbols,
              quota_reservation_tokens, requested_start, requested_end, fetch_completed_at, status,
              quality_state, source_policy_digest, content_hash, validation_summary
            )
            values (
              :batch_id, :provider_key, :endpoint_key, :symbols,
              cast(:quota_reservation_tokens as uuid[]), :requested_start, :requested_end, now(), :status,
              :quality_state, :source_policy_digest, :content_hash,
              cast(:validation_summary as jsonb)
            )
            returning id
            """
        ),
        {
            "batch_id": batch_id,
            "provider_key": provider_key,
            "endpoint_key": DEFAULT_ENDPOINT,
            "symbols": list(dict.fromkeys(symbols)),
            "quota_reservation_tokens": quota_reservation_tokens,
            "requested_start": requested_start,
            "requested_end": requested_end,
            "status": "validated" if validation.promotable else "quarantined",
            "quality_state": validation.quality_state,
            "source_policy_digest": policy_digest,
            "content_hash": content_hash,
            "validation_summary": _stable_json(validation.summary),
        },
    ).scalar_one()
    return str(row)


def _insert_candidate_rows(
    db: Session,
    *,
    fetch_run_id: str,
    batch_id: str,
    rows: list[dict[str, Any]],
    policy_json: str,
    quality_state: str,
) -> dict[tuple[str, date], int]:
    candidate_ids: dict[tuple[str, date], int] = {}
    for row in rows:
        candidate_quality = "valid" if quality_state == "valid" else quality_state
        candidate_id = db.execute(
            text(
                """
                insert into market_price_bar_candidate (
                  fetch_run_id,
                  batch_id,
                  provider_key,
                  symbol,
                  interval,
                  price_date,
                  open,
                  high,
                  low,
                  close,
                  adjusted_close,
                  volume,
                  currency_code,
                  exchange,
                  timezone,
                  provider_price_timestamp,
                  source_hash,
                  source_revision,
                  quality_state,
                  quality_json,
                  source_policy_json
                )
                values (
                  :fetch_run_id,
                  :batch_id,
                  :provider_key,
                  :symbol,
                  :interval,
                  :price_date,
                  :open,
                  :high,
                  :low,
                  :close,
                  :adjusted_close,
                  :volume,
                  :currency_code,
                  :exchange,
                  :timezone,
                  :provider_price_timestamp,
                  :source_hash,
                  :source_revision,
                  :quality_state,
                  cast(:quality_json as jsonb),
                  cast(:source_policy_json as jsonb)
                )
                on conflict (batch_id, provider_key, symbol, interval, price_date) do nothing
                returning id
                """
            ),
            {
                **row,
                "fetch_run_id": fetch_run_id,
                "batch_id": batch_id,
                "interval": DEFAULT_INTERVAL,
                "quality_state": candidate_quality,
                "quality_json": _stable_json(
                    row["quality_json"] | {"candidate_quality_state": candidate_quality}
                ),
                "source_policy_json": policy_json,
            },
        ).scalar_one_or_none()
        if candidate_id is not None:
            candidate_ids[(str(row["symbol"]), row["price_date"])] = int(candidate_id)
    return candidate_ids


def _insert_snapshot(
    db: Session,
    *,
    fetch_run_id: str,
    batch_id: str,
    provider_key: str,
    symbols: list[str],
    rows: list[dict[str, Any]],
    policy_digest: str,
    content_hash: str,
    validation: ValidationResult,
) -> str:
    price_dates = [row["price_date"] for row in rows]
    snapshot_id = db.execute(
        text(
            """
            insert into market_data_snapshot(
              fetch_run_id, batch_id, provider_key, endpoint_key, interval,
              symbols, price_start, price_end, provider_batch_id,
              provider_revision, quality_state, promoted_at, source_policy_digest,
              content_hash, manifest_json
            )
            values (
              :fetch_run_id, :batch_id, :provider_key, :endpoint_key, :interval,
              :symbols, :price_start, :price_end, :provider_batch_id,
              :provider_revision, 'valid', now(), :source_policy_digest,
              :content_hash, cast(:manifest_json as jsonb)
            )
            returning id
            """
        ),
        {
            "fetch_run_id": fetch_run_id,
            "batch_id": batch_id,
            "provider_key": provider_key,
            "endpoint_key": DEFAULT_ENDPOINT,
            "interval": DEFAULT_INTERVAL,
            "symbols": list(dict.fromkeys(symbols)),
            "price_start": min(price_dates),
            "price_end": max(price_dates),
            "provider_batch_id": batch_id,
            "provider_revision": content_hash[:16],
            "source_policy_digest": policy_digest,
            "content_hash": content_hash,
            "manifest_json": _stable_json(validation.summary),
        },
    ).scalar_one()
    return str(snapshot_id)


def _promote_rows(
    db: Session,
    *,
    rows: list[dict[str, Any]],
    policy_json: str,
    snapshot_id: str,
    candidate_ids: dict[tuple[str, date], int],
) -> int:
    stored = 0
    latest_by_symbol: dict[str, date] = {}
    for row in rows:
        db.execute(
            text(
                """
                insert into market_price_bar (
                  symbol,
                  interval,
                  price_date,
                  provider_key,
                  open,
                  high,
                  low,
                  close,
                  adjusted_close,
                  volume,
                  currency_code,
                  exchange,
                  timezone,
                  provider_price_timestamp,
                  source_hash,
                  source_revision,
                  is_adjusted,
                  is_suspect,
                  quality_state,
                  market_data_snapshot_id,
                  quality_json,
                  source_policy_json,
                  updated_at
                )
                values (
                  :symbol,
                  :interval,
                  :price_date,
                  :provider_key,
                  :open,
                  :high,
                  :low,
                  :close,
                  :adjusted_close,
                  :volume,
                  :currency_code,
                  :exchange,
                  :timezone,
                  :provider_price_timestamp,
                  :source_hash,
                  :source_revision,
                  :is_adjusted,
                  false,
                  'valid',
                  :market_data_snapshot_id,
                  cast(:quality_json as jsonb),
                  cast(:source_policy_json as jsonb),
                  now()
                )
                on conflict (symbol, interval, price_date, provider_key) do update set
                  open = excluded.open,
                  high = excluded.high,
                  low = excluded.low,
                  close = excluded.close,
                  adjusted_close = excluded.adjusted_close,
                  volume = excluded.volume,
                  currency_code = excluded.currency_code,
                  exchange = excluded.exchange,
                  timezone = excluded.timezone,
                  provider_price_timestamp = excluded.provider_price_timestamp,
                  source_hash = excluded.source_hash,
                  source_revision = excluded.source_revision,
                  is_adjusted = excluded.is_adjusted,
                  is_suspect = false,
                  quality_state = 'valid',
                  market_data_snapshot_id = excluded.market_data_snapshot_id,
                  quality_json = excluded.quality_json,
                  source_policy_json = excluded.source_policy_json,
                  ingested_at = now(),
                  updated_at = now()
                """
            ),
            {
                **row,
                "interval": DEFAULT_INTERVAL,
                "market_data_snapshot_id": snapshot_id,
                "quality_json": _stable_json(row["quality_json"] | {"snapshot_id": snapshot_id}),
                "source_policy_json": policy_json,
            },
        )
        candidate_id = candidate_ids.get((str(row["symbol"]), row["price_date"]))
        if candidate_id is not None:
            db.execute(
                text(
                    """
                    insert into market_data_snapshot_member(
                      snapshot_id,
                      candidate_id,
                      symbol,
                      interval,
                      price_date,
                      provider_key,
                      quality_state
                    )
                    values (
                      :snapshot_id,
                      :candidate_id,
                      :symbol,
                      :interval,
                      :price_date,
                      :provider_key,
                      'valid'
                    )
                    on conflict (snapshot_id, symbol, interval, price_date) do nothing
                    """
                ),
                {
                    "snapshot_id": snapshot_id,
                    "candidate_id": candidate_id,
                    "symbol": row["symbol"],
                    "interval": DEFAULT_INTERVAL,
                    "price_date": row["price_date"],
                    "provider_key": row["provider_key"],
                },
            )
        symbol = str(row["symbol"])
        latest_by_symbol[symbol] = max(
            latest_by_symbol.get(symbol, row["price_date"]), row["price_date"]
        )
        stored += 1
    for symbol, latest_price_date in latest_by_symbol.items():
        db.execute(
            text(
                """
                insert into market_data_version (
                  symbol,
                  interval,
                  version,
                  latest_price_date,
                  updated_at,
                  source_policy_digest
                )
                values (:symbol, :interval, 1, :latest_price_date, now(), :source_policy_digest)
                on conflict (symbol, interval) do update set
                  version = market_data_version.version + 1,
                  latest_price_date = greatest(market_data_version.latest_price_date, excluded.latest_price_date),
                  updated_at = now(),
                  source_policy_digest = excluded.source_policy_digest
                """
            ),
            {
                "symbol": symbol,
                "interval": DEFAULT_INTERVAL,
                "latest_price_date": latest_price_date,
                "source_policy_digest": _sha256(policy_json),
            },
        )
    return stored


def _mark_fetch_run(
    db: Session,
    *,
    fetch_run_id: str,
    status: str,
    quality_state: str,
    validation: ValidationResult,
) -> None:
    db.execute(
        text(
            """
            update market_fetch_run
            set status = :status,
                quality_state = :quality_state,
                validation_summary = cast(:validation_summary as jsonb),
                updated_at = now()
            where id = :fetch_run_id
            """
        ),
        {
            "fetch_run_id": fetch_run_id,
            "status": status,
            "quality_state": quality_state,
            "validation_summary": _stable_json(validation.summary),
        },
    )


def _staging_metadata(
    *,
    provider_key: str,
    symbol: str,
    points: list[dict[str, Any]],
    source_hash: str,
    source_policy_digest: str,
) -> dict[str, Any]:
    dates = sorted(str(point.get("date") or "")[:10] for point in points if point.get("date"))
    return {
        "provider_key": provider_key,
        "symbol": symbol,
        "point_count": len(points),
        "first_date": dates[0] if dates else None,
        "latest_date": dates[-1] if dates else None,
        "source_hash": source_hash,
        "source_policy_digest": source_policy_digest,
        "payload_retained": False,
        "retention_note": "Normalized bars are durable; staging keeps compact audit metadata only.",
    }


def _prune_staging_metadata(db: Session) -> None:
    if (
        getattr(getattr(db, "bind", None), "dialect", None) is not None
        and db.bind.dialect.name != "postgresql"
    ):
        return
    try:
        db.execute(
            text(
                """
                delete from market_price_bar_staging
                where created_at < now() - (:retention_days * interval '1 day')
                """
            ),
            {"retention_days": STAGING_METADATA_RETENTION_DAYS},
        )
    except SQLAlchemyError:
        db.rollback()


def market_data_source_policy(
    db: Session, *, provider_key: str, endpoint_key: str
) -> dict[str, Any]:
    if _table_available(db, "market_data_source_policy"):
        try:
            row = (
                db.execute(
                    text(
                        """
                    select
                      provider_key,
                      endpoint_key,
                      entitlement_status,
                      live_test_status,
                      internal_calculation_allowed,
                      normalized_storage_allowed,
                      raw_storage_allowed,
                      raw_public_allowed,
                      derived_public_allowed,
                      retention_days,
                      attribution_required,
                      source_url,
                      notes
                    from market_data_source_policy
                    where provider_key = :provider_key
                      and endpoint_key = :endpoint_key
                    """
                    ),
                    {"provider_key": provider_key, "endpoint_key": endpoint_key},
                )
                .mappings()
                .one_or_none()
            )
            if row:
                return dict(row)
        except SQLAlchemyError:
            db.rollback()
    return default_market_data_source_policy(provider_key, endpoint_key)


def default_market_data_source_policy(
    provider_key: str, endpoint_key: str = DEFAULT_ENDPOINT
) -> dict[str, Any]:
    normalized_allowed = provider_key in {"twelve_data", "alpha_vantage", "fmp"}
    return {
        "provider_key": provider_key,
        "endpoint_key": endpoint_key,
        "entitlement_status": "policy_approved_pending_live_test"
        if normalized_allowed
        else "pending_review",
        "live_test_status": "untested",
        "internal_calculation_allowed": normalized_allowed,
        "normalized_storage_allowed": normalized_allowed,
        "raw_storage_allowed": False,
        "raw_public_allowed": False,
        "derived_public_allowed": False,
        "retention_days": None,
        "attribution_required": provider_key == "twelve_data",
        "source_url": "",
        "notes": "Default conservative market-data policy.",
    }


def _normalize_point(
    symbol: str, provider_key: str, point: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any] | None:
    row_date = _parse_date(point.get("date"))
    close = _parse_float(point.get("close"))
    if row_date is None or close is None or close <= 0:
        return None
    adjusted_close = _parse_float(point.get("adjusted_close"))
    open_value = _parse_float(point.get("open"))
    high = _parse_float(point.get("high"))
    low = _parse_float(point.get("low"))
    volume = _parse_float(point.get("volume"))
    provider_timestamp = _parse_datetime(point.get("provider_timestamp"))
    row = {
        "symbol": symbol,
        "price_date": row_date,
        "provider_key": provider_key,
        "open": open_value,
        "high": high,
        "low": low,
        "close": close,
        "adjusted_close": adjusted_close,
        "volume": volume,
        "currency_code": str(point.get("currency") or "USD")[:12],
        "exchange": str(point.get("exchange") or "")[:64] or None,
        "timezone": str(point.get("timezone") or "America/New_York")[:64],
        "provider_price_timestamp": provider_timestamp,
        "source_revision": str(point.get("source_revision") or "")[:128] or None,
        "is_adjusted": adjusted_close is not None,
        "quality_json": {
            "source": provider_key,
            "normalized_storage_allowed": bool(policy.get("normalized_storage_allowed")),
            "raw_public_allowed": bool(policy.get("raw_public_allowed")),
        },
    }
    row["source_hash"] = _sha256(
        _stable_json({key: value for key, value in row.items() if key != "quality_json"})
    )
    return row


def _stored_point(row: dict[str, Any]) -> dict[str, Any]:
    point = {
        "date": str(row["price_date"]),
        "close": float(
            row["adjusted_close"] if row.get("adjusted_close") is not None else row["close"]
        ),
        "volume": float(row["volume"]) if row.get("volume") is not None else None,
        "provider": row["provider_key"],
        "currency": row.get("currency_code") or "USD",
        "exchange": row.get("exchange"),
        "timezone": row.get("timezone") or "America/New_York",
        "provider_timestamp": row["provider_price_timestamp"].isoformat()
        if hasattr(row.get("provider_price_timestamp"), "isoformat")
        else row.get("provider_price_timestamp"),
        "source_revision": row.get("source_revision"),
    }
    return {key: value for key, value in point.items() if value is not None}


def _table_available(db: Session, table_name: str) -> bool:
    try:
        row = db.execute(
            text("select to_regclass(:table_name)"), {"table_name": table_name}
        ).scalar_one_or_none()
        return row is not None
    except SQLAlchemyError:
        db.rollback()
        return False


def _provider_rank(provider: str, provider_rank: dict[str, int]) -> int:
    return provider_rank.get(provider, 999)


def _policy_from_row(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value in (None, ""):
        return None
    text_value = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
