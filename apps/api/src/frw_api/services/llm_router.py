from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from jsonschema import Draft202012Validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.core.settings import get_settings
from frw_api.services.provider_budget import provider_is_available, record_usage

InputClass = Literal[
    "PUBLIC_FACTS_ONLY",
    "PUBLIC_SOURCE_TEXT",
    "PRIVATE_RESEARCH",
    "RESTRICTED_SOURCE",
    "SECRETS",
]

PUBLIC_FREE_ONLY = {"PUBLIC_FACTS_ONLY"}


class LLMRoutingError(ValueError):
    pass


@dataclass(frozen=True)
class LLMTask:
    task_type: str
    input_class: InputClass
    prompt_version: str
    schema_key: str
    schema: dict[str, Any]
    locale: str | None = None
    glossary_hash: str | None = None


def input_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class LLMRouter:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    async def run_json(self, task: LLMTask, *, messages: list[dict[str, str]]) -> dict[str, Any]:
        if task.input_class == "SECRETS":
            raise LLMRoutingError("SECRETS are never routed to LLM providers")
        profile = self._select_profile(task)
        cache_key = self._cache_key(task, profile["id"], messages)
        cached = self._get_cache(cache_key)
        if cached is not None:
            self._log_invocation(task, profile, messages, cached, "succeeded", cache_hit=True, count_usage=False)
            return cached
        try:
            output = await self._call_provider(profile, messages)
        except Exception as exc:
            self._log_invocation(task, profile, messages, None, "provider_failed", cache_hit=False)
            raise LLMRoutingError(f"Provider failed and task requires manual review: {exc}") from exc
        try:
            self._validate(task.schema, output)
            self._assert_grounded_public_facts(task, output)
        except LLMRoutingError as first_error:
            self._log_invocation(task, profile, messages, output, "schema_failed", cache_hit=False)
            try:
                repaired = await self._call_provider(
                    profile,
                    [
                        *messages,
                        {
                            "role": "system",
                            "content": (
                                "Repair the previous answer into valid grounded JSON only. "
                                "Do not add facts. If grounding is impossible, return a JSON object "
                                "with status='manual_review_required'."
                            ),
                        },
                    ],
                )
                self._validate(task.schema, repaired)
                self._assert_grounded_public_facts(task, repaired)
            except Exception as repair_error:
                self._log_invocation(task, profile, messages, None, "rejected", cache_hit=False)
                raise LLMRoutingError(
                    f"LLM output rejected after repair attempt; manual review required: {first_error}"
                ) from repair_error
            output = repaired
        self._write_cache(cache_key, task, profile["id"], messages, output)
        self._log_invocation(task, profile, messages, output, "succeeded", cache_hit=False)
        return output

    def _select_profile(self, task: LLMTask) -> dict[str, Any]:
        rows = (
            self.db.execute(
                text(
                    """
                    select p.*
                    from llm_model_profile p
                    join provider_budget b on b.provider_key = p.provider_key
                    where p.enabled = true
                    order by
                      case when p.provider_key = 'local' then 0 else 1 end,
                      coalesce((p.quality_scores ->> :task_type)::numeric, 0) desc,
                      coalesce(p.latency_score, 999) asc
                    """
                ),
                {"task_type": task.task_type},
            )
            .mappings()
            .all()
        )
        for row in rows:
            if self._profile_allowed(row, task) and provider_is_available(self.db, row["provider_key"]):
                return dict(row)
        raise LLMRoutingError("No eligible LLM provider is available for task/data class")

    def _profile_allowed(self, profile: dict[str, Any], task: LLMTask) -> bool:
        provider_key = profile["provider_key"]
        if task.input_class == "PRIVATE_RESEARCH":
            return provider_key == "local" or profile["privacy_class"] in ("PRIVATE_ALLOWED", "LOCAL_ONLY")
        if task.input_class == "RESTRICTED_SOURCE":
            return profile["privacy_class"] in ("PRIVATE_ALLOWED", "LOCAL_ONLY", "EXTRACT_ONLY")
        if provider_key != "local" and profile["privacy_class"] == "PUBLIC_FACTS_ONLY":
            return task.input_class in PUBLIC_FREE_ONLY
        return True

    async def _call_provider(self, profile: dict[str, Any], messages: list[dict[str, str]]) -> dict[str, Any]:
        provider = profile["provider_key"]
        model = profile["model_key"]
        if provider == "local":
            return await self._call_openai_compatible(
                self.settings.local_llm_base_url or "http://localhost:11434",
                None,
                model,
                messages,
            )
        keys = {
            "openrouter": self.settings.openrouter_api_key,
            "groq": self.settings.groq_api_key,
            "mistral": self.settings.mistral_api_key,
            "cerebras": self.settings.cerebras_api_key,
        }
        if provider in keys:
            api_key = keys[provider]
            if not api_key:
                raise LLMRoutingError(f"{provider} credential is not configured")
            base_urls = {
                "openrouter": "https://openrouter.ai/api/v1",
                "groq": "https://api.groq.com/openai/v1",
                "mistral": "https://api.mistral.ai/v1",
                "cerebras": "https://api.cerebras.ai/v1",
            }
            return await self._call_openai_compatible(base_urls[provider], api_key, model, messages)
        if provider == "gemini":
            if not self.settings.gemini_api_key:
                raise LLMRoutingError("Gemini credential is not configured")
            return await self._call_gemini(model, messages)
        raise LLMRoutingError(f"Unsupported LLM provider: {provider}")

    async def _call_openai_compatible(
        self, base_url: str, api_key: str | None, model: str, messages: list[dict[str, str]]
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                },
            )
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)

    async def _call_gemini(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        prompt = "\n\n".join(f"{message['role']}: {message['content']}" for message in messages)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={self.settings.gemini_api_key}"
        )
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
                },
            )
            response.raise_for_status()
            data = response.json()
        text_payload = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text_payload)

    def _validate(self, schema: dict[str, Any], output: dict[str, Any]) -> None:
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(output), key=lambda err: err.path)
        if errors:
            raise LLMRoutingError(f"LLM output schema failed: {errors[0].message}")

    def _assert_grounded_public_facts(self, task: LLMTask, output: dict[str, Any]) -> None:
        cited = output.get("cited_fact_ids") or output.get("fact_ids")
        if task.task_type != "public_summary" and cited is None:
            return
        if not isinstance(cited, list) or not cited:
            raise LLMRoutingError("Public summary requires cited public fact IDs")
        count = self.db.execute(
            text(
                """
                select count(*)
                from source_fact
                where id::text = any(cast(:ids as text[]))
                  and public_allowed = true
                  and review_status in ('approved','editor_approved','owner_approved')
                """
            ),
            {"ids": cited},
        ).scalar_one()
        if int(count or 0) != len(set(cited)):
            raise LLMRoutingError("Public summary cited facts must exist and be public allowed")

    def _cache_key(self, task: LLMTask, model_profile_id: str, messages: list[dict[str, str]]) -> str:
        return input_hash(
            {
                "task_type": task.task_type,
                "prompt_version": task.prompt_version,
                "model_profile_id": model_profile_id,
                "input_object_hash": input_hash(messages),
                "locale": task.locale,
                "glossary_hash": task.glossary_hash,
            }
        )

    def _get_cache(self, cache_key: str) -> dict[str, Any] | None:
        row = self.db.execute(
            text("select output_json from llm_cache where cache_key = :cache_key"),
            {"cache_key": cache_key},
        ).scalar_one_or_none()
        return row

    def _write_cache(
        self,
        cache_key: str,
        task: LLMTask,
        model_profile_id: str,
        messages: list[dict[str, str]],
        output: dict[str, Any],
    ) -> None:
        self.db.execute(
            text(
                """
                insert into llm_cache(
                  cache_key, task_type, prompt_version, model_profile_id, input_object_hash,
                  locale, glossary_hash, output_json, output_hash
                )
                values (
                  :cache_key, :task_type, :prompt_version, :model_profile_id, :input_object_hash,
                  :locale, :glossary_hash, cast(:output_json as jsonb), :output_hash
                )
                on conflict (cache_key) do nothing
                """
            ),
            {
                "cache_key": cache_key,
                "task_type": task.task_type,
                "prompt_version": task.prompt_version,
                "model_profile_id": model_profile_id,
                "input_object_hash": input_hash(messages),
                "locale": task.locale,
                "glossary_hash": task.glossary_hash,
                "output_json": json.dumps(output),
                "output_hash": input_hash(output),
            },
        )

    def _log_invocation(
        self,
        task: LLMTask,
        profile: dict[str, Any],
        messages: list[dict[str, str]],
        output: dict[str, Any] | None,
        status: str,
        cache_hit: bool,
        count_usage: bool = True,
    ) -> None:
        self.db.execute(
            text(
                """
                insert into llm_invocation(
                  task_type, model_profile_id, provider_key, input_class, input_hash,
                  output_hash, prompt_version, schema_key, status, cache_hit
                )
                values (
                  :task_type, :model_profile_id, :provider_key, :input_class, :input_hash,
                  :output_hash, :prompt_version, :schema_key, :status, :cache_hit
                )
                """
            ),
            {
                "task_type": task.task_type,
                "model_profile_id": profile["id"],
                "provider_key": profile["provider_key"],
                "input_class": task.input_class,
                "input_hash": input_hash(messages),
                "output_hash": input_hash(output) if output is not None else None,
                "prompt_version": task.prompt_version,
                "schema_key": task.schema_key,
                "status": status,
                "cache_hit": cache_hit,
            },
        )
        if count_usage:
            record_usage(self.db, provider_key=profile["provider_key"], unit="invocation", quantity=1)
