#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "tracked_entities.json"
SECTOR_KEYS = {"space", "drones", "quantum", "semiconductors", "oil-energy", "big-tech"}
ROUTE_KINDS = {"ticker", "reference_entity", "unsupported"}
ASSET_TYPES = {"Equity", "ETF", "Reference"}
SOURCE_TYPES = {"official", "regulated_filing"}
TRUST_TIERS = {"T0_OFFICIAL", "T1_REGULATED_FILING"}
SOURCE_POLICIES = {
    "metadata_only_unless_terms_allow_display",
    "metadata_or_public_filing_only",
    "reference_entity_metadata_only",
}
FETCH_KINDS = {"feed", "html_article", "html_index", "sec_submissions"}
RATE_LIMIT_PROVIDERS = {"company_ir", "sec_edgar"}
RATE_LIMIT_ENDPOINTS = {"html", "rss", "submissions"}
COPYRIGHT_MODES = {"official_public_metadata", "public_filing_metadata"}
REQUIRED_FIELDS = {
    "entity_id",
    "symbol",
    "display_symbol",
    "route_key",
    "route_kind",
    "name_en",
    "name_ko",
    "exchange",
    "asset_type",
    "currency",
    "country",
    "sector",
    "industry",
    "sector_keys",
    "tags",
    "aliases",
    "related_symbols",
    "official_domains",
    "sector_terms",
    "thesis_bull",
    "thesis_bear",
    "invalidation",
    "source_policy",
    "sources",
    "email_sources",
}
ROUTE_KEY_RE = re.compile(r"^[A-Z0-9_]{1,40}$")
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")


@dataclass
class RegistrySeen:
    entity_ids: set[str] = field(default_factory=set)
    symbols: set[str] = field(default_factory=set)
    route_keys: set[str] = field(default_factory=set)
    source_keys: set[str] = field(default_factory=set)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate tracked entity registry")
    parser.add_argument("--check-generated", action="store_true", help="Also verify generated artifacts are current")
    args = parser.parse_args()

    errors = validate_registry()
    if args.check_generated:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "generate_tracked_entities.py"), "--check"],
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        if result.returncode:
            errors.extend(line for line in result.stdout.splitlines() if line.strip())
            errors.extend(line for line in result.stderr.splitlines() if line.strip())

    if errors:
        for error in errors:
            print(error)
        return 1
    return 0


def validate_registry() -> list[str]:
    errors: list[str] = []
    payload = _load_json(REGISTRY_PATH, errors)
    if not payload:
        return errors
    if payload.get("version") != 1:
        errors.append("config/tracked_entities.json version must be 1")
    entities = payload.get("entities")
    if not isinstance(entities, list) or not entities:
        return ["config/tracked_entities.json must contain a non-empty entities array"]

    seen = RegistrySeen()
    for index, entity in enumerate(entities):
        _validate_entity(index, entity, errors, seen)
    _validate_related_symbols(entities, errors, seen)
    return errors


def _validate_entity(index: int, entity: Any, errors: list[str], seen: RegistrySeen) -> None:
    if not isinstance(entity, dict):
        errors.append(f"entities[{index}] must be an object")
        return
    label = str(entity.get("entity_id") or entity.get("symbol") or index)
    _validate_required_fields(label, entity, errors)
    _validate_identity_fields(label, entity, errors, seen)
    _validate_array_fields(label, entity, errors)
    entity_domains = _domain_set(entity.get("official_domains"))
    _validate_entity_lists(label, entity, errors)
    for source in entity.get("sources", []):
        _validate_source(label, source, entity_domains, errors, seen)
    for email_source in entity.get("email_sources", []):
        _validate_email_source(label, email_source, entity_domains, errors)


def _validate_required_fields(label: str, entity: dict[str, Any], errors: list[str]) -> None:
    missing = sorted(field_name for field_name in REQUIRED_FIELDS if field_name not in entity)
    if missing:
        errors.append(f"{label}: missing required fields: {', '.join(missing)}")


def _validate_identity_fields(
    label: str, entity: dict[str, Any], errors: list[str], seen: RegistrySeen
) -> None:
    entity_id = _string(entity, "entity_id")
    symbol = _string(entity, "symbol").upper()
    route_key = _string(entity, "route_key")
    _validate_unique(label, "entity_id", entity_id, seen.entity_ids, errors)
    _validate_unique(label, "symbol", symbol, seen.symbols, errors)
    _validate_unique(label, "route_key", route_key, seen.route_keys, errors)
    if symbol and not SYMBOL_RE.match(symbol):
        errors.append(f"{label}: invalid symbol {symbol}")
    if route_key and not ROUTE_KEY_RE.match(route_key):
        errors.append(f"{label}: invalid route_key {route_key}")
    _validate_allowed(label, "route_kind", _string(entity, "route_kind"), ROUTE_KINDS, errors)
    _validate_allowed(label, "asset_type", _string(entity, "asset_type"), ASSET_TYPES, errors)
    _validate_allowed(label, "source_policy", _string(entity, "source_policy"), SOURCE_POLICIES, errors)


def _validate_unique(
    label: str, field_name: str, value: str, seen_values: set[str], errors: list[str]
) -> None:
    if value in seen_values:
        errors.append(f"{label}: duplicate {field_name} {value}")
    seen_values.add(value)


def _validate_allowed(
    label: str, field_name: str, value: str, allowed: set[str], errors: list[str]
) -> None:
    if value not in allowed:
        errors.append(f"{label}: invalid {field_name} {value}")


def _validate_array_fields(label: str, entity: dict[str, Any], errors: list[str]) -> None:
    array_fields = ("sector_keys", "tags", "aliases", "related_symbols", "official_domains", "sector_terms")
    for field_name in array_fields:
        if not isinstance(entity.get(field_name), list):
            errors.append(f"{label}: {field_name} must be an array")


def _validate_entity_lists(label: str, entity: dict[str, Any], errors: list[str]) -> None:
    for sector_key in entity.get("sector_keys", []):
        if sector_key not in SECTOR_KEYS:
            errors.append(f"{label}: invalid sector_key {sector_key}")
    for related in entity.get("related_symbols", []):
        if not isinstance(related, str):
            errors.append(f"{label}: related_symbols values must be strings")
    for domain in entity.get("official_domains", []):
        if not isinstance(domain, str) or "." not in domain:
            errors.append(f"{label}: invalid official domain {domain}")


def _validate_source(
    label: str,
    source: Any,
    entity_domains: set[str],
    errors: list[str],
    seen: RegistrySeen,
) -> None:
    if not isinstance(source, dict):
        errors.append(f"{label}: sources values must be objects")
        return
    source_key = _string(source, "source_key")
    _validate_source_key(label, source_key, errors, seen)
    _validate_source_enums(label, source_key, source, errors)
    source_domains = entity_domains | _domain_set(source.get("official_domains"))
    for url_key in ("base_url", "feed_url"):
        _validate_source_url(label, source_key, source, source_domains, url_key, errors)


def _validate_source_key(
    label: str, source_key: str, errors: list[str], seen: RegistrySeen
) -> None:
    if not source_key:
        errors.append(f"{label}: source missing source_key")
    elif source_key in seen.source_keys:
        errors.append(f"{label}: duplicate source_key {source_key}")
    seen.source_keys.add(source_key)


def _validate_source_enums(
    label: str, source_key: str, source: dict[str, Any], errors: list[str]
) -> None:
    for field_name, allowed in (
        ("source_type", SOURCE_TYPES),
        ("trust_tier", TRUST_TIERS),
        ("rate_limit_provider_key", RATE_LIMIT_PROVIDERS),
        ("rate_limit_endpoint_key", RATE_LIMIT_ENDPOINTS),
        ("copyright_mode", COPYRIGHT_MODES),
    ):
        value = _string(source, field_name)
        if value not in allowed:
            errors.append(f"{label}: source {source_key} invalid {field_name}: {value}")
    fetch_kind = _string(source, "fetch_kind")
    if fetch_kind and fetch_kind not in FETCH_KINDS:
        errors.append(f"{label}: source {source_key} invalid fetch_kind: {fetch_kind}")


def _validate_source_url(
    label: str,
    source_key: str,
    source: dict[str, Any],
    source_domains: set[str],
    url_key: str,
    errors: list[str],
) -> None:
    if not source.get(url_key):
        return
    url_value = str(source[url_key])
    if not _valid_url(url_value):
        errors.append(f"{label}: source {source_key} invalid {url_key}: {url_value}")
    elif not _host_allowed(url_value, source_domains):
        errors.append(
            f"{label}: source {source_key} {url_key} host is not in official domains: {url_value}"
        )


def _validate_email_source(
    label: str, email_source: Any, entity_domains: set[str], errors: list[str]
) -> None:
    if not isinstance(email_source, dict):
        errors.append(f"{label}: email_sources values must be objects")
        return
    signup_url = str(email_source.get("signup_url") or "")
    if signup_url and not _valid_url(signup_url):
        errors.append(f"{label}: invalid email signup_url {signup_url}")
    elif signup_url and not _host_allowed(signup_url, entity_domains):
        errors.append(f"{label}: email signup_url host is not in official domains: {signup_url}")


def _validate_related_symbols(
    entities: list[Any], errors: list[str], seen: RegistrySeen
) -> None:
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        label = str(entity.get("entity_id") or entity.get("symbol") or "")
        for related in entity.get("related_symbols", []):
            if related not in seen.symbols and related not in seen.entity_ids:
                errors.append(f"{label}: unresolved related_symbol {related}")


def _load_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        errors.append(f"{path.relative_to(ROOT)}: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{path.relative_to(ROOT)} must contain a JSON object")
        return None
    return payload


def _string(mapping: dict[str, Any], key: str) -> str:
    return str(mapping.get(key) or "").strip()


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _domain_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip().lower().removeprefix("www.") for item in value if str(item).strip()}


def _host_allowed(url: str, domains: set[str]) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


if __name__ == "__main__":
    raise SystemExit(main())
