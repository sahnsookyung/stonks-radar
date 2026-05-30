from __future__ import annotations

import httpx
import pytest

from frw_api.services.provider_limits import (
    ERROR_QUOTA_EXHAUSTED,
    ERROR_RATE_LIMITED,
    LimitRule,
    ProviderEndpointLimit,
    ProviderLimitError,
    ProviderLimitRegistry,
    ProviderQuotaGuard,
    provider_request,
)


@pytest.fixture(autouse=True)
def reset_quota_guard():
    ProviderQuotaGuard._default = None
    ProviderQuotaGuard.reset_memory()
    yield
    ProviderQuotaGuard._default = None
    ProviderQuotaGuard.reset_memory()


def _guard(limit: int) -> ProviderQuotaGuard:
    registry = ProviderLimitRegistry(
        (
            ProviderEndpointLimit(
                provider_key="test_provider",
                endpoint_key="test_endpoint",
                rules=(
                    LimitRule(
                        unit="request",
                        window_seconds=60,
                        limit=limit,
                        source_limit="test",
                        conservative_limit="test",
                    ),
                ),
                source_url="https://example.test",
                source_checked_at="2026-05-25",
            ),
        )
    )
    return ProviderQuotaGuard(registry)


def test_quota_guard_denies_before_second_request():
    guard = _guard(1)
    guard.reserve(provider_key="test_provider", endpoint_key="test_endpoint")

    with pytest.raises(ProviderLimitError) as exc_info:
        guard.reserve(provider_key="test_provider", endpoint_key="test_endpoint")

    assert exc_info.value.error_class == ERROR_QUOTA_EXHAUSTED
    assert exc_info.value.retry_after_seconds is not None


def test_nvidia_nim_default_limit_is_40_rpm():
    limit = ProviderLimitRegistry().get("nvidia_nim", "chat_completions")

    assert limit is not None
    request_rules = [rule for rule in limit.rules if rule.unit == "request" and rule.window_seconds == 60]
    assert request_rules
    assert request_rules[0].limit == 40


@pytest.mark.asyncio
async def test_provider_request_preserves_retry_after_header():
    ProviderQuotaGuard._default = _guard(10)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7"}, json={"error": "slow down"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderLimitError) as exc_info:
            await provider_request(
                client,
                "GET",
                "https://provider.test/data",
                provider_key="test_provider",
                endpoint_key="test_endpoint",
            )

    assert exc_info.value.error_class == ERROR_RATE_LIMITED
    assert exc_info.value.retry_after_seconds == 7
