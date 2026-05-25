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
