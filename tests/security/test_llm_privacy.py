import pytest

from frw_api.core.settings import get_settings
from frw_api.services.llm_router import LLMRoutingError, LLMRouter, LLMTask


def test_secrets_never_route():
    router = LLMRouter(db=None)  # type: ignore[arg-type]
    task = LLMTask(
        task_type="public_summary",
        input_class="SECRETS",
        prompt_version="v1",
        schema_key="public_summary",
        schema={"type": "object"},
    )
    with pytest.raises(LLMRoutingError):
        import asyncio

        asyncio.run(router.run_json(task, messages=[]))


def test_openrouter_paid_model_is_blocked_when_paid_usage_disabled(monkeypatch):
    import asyncio

    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "paid_usage_allowed", False)
    router = LLMRouter(db=None)  # type: ignore[arg-type]

    with pytest.raises(LLMRoutingError, match="free model"):
        asyncio.run(
            router._call_provider(
                {"provider_key": "openrouter", "model_key": "paid/model"},
                messages=[],
            )
        )


def test_nvidia_nim_uses_openai_compatible_endpoint(monkeypatch):
    import asyncio

    settings = get_settings()
    monkeypatch.setattr(settings, "nvidia_api_key", "test-key")
    monkeypatch.setattr(settings, "nvidia_nim_api_key", None)
    monkeypatch.setattr(settings, "nvidia_nim_base_url", "https://integrate.api.nvidia.com/v1")
    router = LLMRouter(db=None)  # type: ignore[arg-type]
    captured = {}

    async def fake_call(provider, base_url, api_key, model, messages):
        captured.update(
            {
                "provider": provider,
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
                "messages": messages,
            }
        )
        return {"ok": True}

    monkeypatch.setattr(router, "_call_openai_compatible", fake_call)
    payload = asyncio.run(
        router._call_provider(
            {"provider_key": "nvidia_nim", "model_key": "minimaxai/minimax-m2.7"},
            messages=[{"role": "user", "content": "Return JSON."}],
        )
    )

    assert payload == {"ok": True}
    assert captured["provider"] == "nvidia_nim"
    assert captured["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "minimaxai/minimax-m2.7"


def test_nvidia_nim_rejects_non_configured_model(monkeypatch):
    import asyncio

    settings = get_settings()
    monkeypatch.setattr(settings, "nvidia_api_key", "test-key")
    monkeypatch.setattr(settings, "nvidia_nim_model_key", "minimaxai/minimax-m2.7")
    router = LLMRouter(db=None)  # type: ignore[arg-type]

    with pytest.raises(LLMRoutingError, match="minimaxai/minimax-m2.7"):
        asyncio.run(
            router._call_provider(
                {"provider_key": "nvidia_nim", "model_key": "meta/llama-3.1-8b-instruct"},
                messages=[{"role": "user", "content": "Return JSON."}],
            )
        )


def test_local_llm_provider_is_disabled_directly():
    import asyncio

    router = LLMRouter(db=None)  # type: ignore[arg-type]

    with pytest.raises(LLMRoutingError, match="Local LLM provider is disabled"):
        asyncio.run(
            router._call_provider(
                {"provider_key": "local", "model_key": "llama3.1-json"},
                messages=[{"role": "user", "content": "Return JSON."}],
            )
        )


def test_public_news_prefers_remote_nvidia_without_local_fallback(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "nvidia_nim_model_key", "minimaxai/minimax-m2.7")
    monkeypatch.setattr(settings, "llm_global_daily_hard_limit", 100)
    router = LLMRouter(db=None)  # type: ignore[arg-type]
    task = LLMTask(
        task_type="public_summary",
        input_class="PUBLIC_FACTS_ONLY",
        prompt_version="v1",
        schema_key="public_summary",
        schema={"type": "object"},
        allowed_provider_keys=frozenset({"nvidia_nim", "gemini", "groq", "cerebras"}),
        preferred_provider_keys=("nvidia_nim", "gemini", "groq", "cerebras"),
    )
    rows = [
        {"provider_key": "local", "model_key": "llama3.1-json", "privacy_class": "LOCAL_ONLY"},
        {"provider_key": "gemini", "model_key": "gemini-1.5-flash", "privacy_class": "PUBLIC_FACTS_ONLY"},
        {"provider_key": "nvidia_nim", "model_key": "minimaxai/minimax-m2.7", "privacy_class": "PUBLIC_FACTS_ONLY"},
    ]

    ordered = router._order_profiles(rows, task)

    assert ordered[0]["provider_key"] == "nvidia_nim"
    assert not router._profile_allowed(rows[0], task)


def test_external_profiles_are_ineligible_when_global_hard_limit_is_zero(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_global_daily_hard_limit", 0)
    router = LLMRouter(db=None)  # type: ignore[arg-type]
    task = LLMTask(
        task_type="public_summary",
        input_class="PUBLIC_FACTS_ONLY",
        prompt_version="v1",
        schema_key="public_summary",
        schema={"type": "object"},
    )

    assert not router._profile_allowed({"provider_key": "gemini", "privacy_class": "PUBLIC_FACTS_ONLY"}, task)
    assert not router._profile_allowed({"provider_key": "local", "privacy_class": "LOCAL_ONLY"}, task)


def test_external_llm_budget_reservation_requires_persistent_db_state(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_global_daily_hard_limit", 100)
    router = LLMRouter(db=None)  # type: ignore[arg-type]
    task = LLMTask(
        task_type="public_summary",
        input_class="PUBLIC_FACTS_ONLY",
        prompt_version="v1",
        schema_key="public_summary",
        schema={"type": "object"},
    )

    with pytest.raises(LLMRoutingError, match="persistent budget state"):
        router._reserve_external_llm_budget(
            task,
            {"provider_key": "nvidia_nim", "model_key": "minimaxai/minimax-m2.7"},
            messages=[{"role": "user", "content": "Return JSON."}],
        )
