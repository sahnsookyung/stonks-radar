import pytest

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
