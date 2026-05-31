"""LLM abstraction layer supporting AWS Bedrock and OpenAI with fallback."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from tenacity import retry, stop_after_attempt, wait_exponential

from shared.config import settings

logger = logging.getLogger(__name__)

# Per-task token accumulator (asyncio-task-scoped). Stores a mutable dict so increments
# inside the same context propagate. Shape: {"_total": int, "by_model": {model_id: int}}.
_task_tokens: ContextVar[dict | None] = ContextVar("task_tokens", default=None)


def start_task_token_tracking() -> None:
    """Begin per-task token accounting for the current asyncio context."""
    _task_tokens.set({"_total": 0, "by_model": {}})


def get_task_tokens() -> int:
    """Return total tokens consumed since start_task_token_tracking() in this context."""
    v = _task_tokens.get()
    return v["_total"] if v else 0


def get_task_tokens_by_model() -> dict[str, int]:
    """Return per-model token usage for the current task context."""
    v = _task_tokens.get()
    return dict(v["by_model"]) if v else {}


class TokenBudgetExceeded(Exception):
    """Raised when the token budget is exhausted."""


def _sanitize_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """NFR-2: strip secrets + PII from prompts before they leave the process.

    Lazy-imports compliance to avoid pulling boto3 at module import time.
    Best-effort: failures fall back to the original messages (logged).
    """
    try:
        from shared.compliance import redact
    except Exception:
        return messages
    out: list[BaseMessage] = []
    for m in messages:
        content = getattr(m, "content", None)
        if isinstance(content, str) and content:
            r = redact(content)
            if r.findings:
                try:
                    m = m.model_copy(update={"content": r.redacted})  # type: ignore[attr-defined]
                except Exception:
                    m.content = r.redacted  # type: ignore[assignment]
                logger.warning(
                    "llm prompt redacted: %d finding(s), class=%s",
                    len(r.findings), r.highest_class.value,
                )
        out.append(m)
    return out


class LLMProvider:
    """Provider-agnostic LLM client with model routing, token budgets, and fallback."""

    def __init__(self) -> None:
        self._tokens_used: int = 0
        self._primary: BaseChatModel | None = None
        self._fallback: BaseChatModel | None = None

    @property
    def primary(self) -> BaseChatModel:
        if self._primary is None:
            from langchain_aws import ChatBedrock

            self._primary = ChatBedrock(
                model_id=settings.bedrock_model_id,
                region_name=settings.bedrock_region,
                model_kwargs={
                    "max_tokens": settings.llm_max_tokens,
                    "temperature": settings.llm_temperature,
                },
            )
        return self._primary

    @property
    def fallback(self) -> BaseChatModel | None:
        if self._fallback is None and settings.openai_api_key:
            from langchain_openai import ChatOpenAI

            self._fallback = ChatOpenAI(
                model=settings.openai_model,
                api_key=settings.openai_api_key,
                max_tokens=settings.llm_max_tokens,
                temperature=settings.llm_temperature,
            )
        return self._fallback

    def _check_budget(self, estimated_tokens: int = 1000) -> None:
        # Per-task cap: prevents one runaway task from burning the whole process budget.
        # Default to 1/4 of process budget; configurable via settings.llm_task_token_budget if set.
        per_task_cap = getattr(settings, "llm_task_token_budget", 0) or max(
            10_000, settings.llm_token_budget // 4
        )
        task_used = get_task_tokens()
        if task_used + estimated_tokens > per_task_cap:
            raise TokenBudgetExceeded(
                f"Per-task token budget exceeded: {task_used}/{per_task_cap}"
            )
        if self._tokens_used + estimated_tokens > settings.llm_token_budget:
            raise TokenBudgetExceeded(
                f"Process token budget exceeded: {self._tokens_used}/{settings.llm_token_budget}"
            )

    @staticmethod
    def _model_id_of(response: Any, fallback: str) -> str:
        meta = getattr(response, "response_metadata", None) or {}
        return (
            meta.get("model_id")
            or meta.get("model_name")
            or meta.get("model")
            or fallback
        )

    def _track_usage(self, response: Any, model_id: str = "unknown") -> None:
        usage = getattr(response, "usage_metadata", None)
        if usage and isinstance(usage, dict):
            delta = usage.get("total_tokens", 0)
            self._tokens_used += delta
            v = _task_tokens.get()
            if v is not None:
                v["_total"] += delta
                mid = self._model_id_of(response, model_id)
                v["by_model"][mid] = v["by_model"].get(mid, 0) + delta

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def ainvoke(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> BaseMessage:
        """Invoke LLM with automatic fallback on failure."""
        self._check_budget()
        messages = _sanitize_messages(messages)

        try:
            response = await self.primary.ainvoke(messages, **kwargs)
            self._track_usage(response, model_id=settings.bedrock_model_id)
            return response
        except Exception as e:
            logger.warning("Primary LLM (Bedrock) failed: %s, trying fallback", e)
            if self.fallback is None:
                raise

            response = await self.fallback.ainvoke(messages, **kwargs)
            self._track_usage(response, model_id=settings.openai_model)
            return response

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def invoke(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> BaseMessage:
        """Synchronous invoke with automatic fallback."""
        self._check_budget()
        messages = _sanitize_messages(messages)

        try:
            response = self.primary.invoke(messages, **kwargs)
            self._track_usage(response, model_id=settings.bedrock_model_id)
            return response
        except Exception as e:
            logger.warning("Primary LLM (Bedrock) failed: %s, trying fallback", e)
            if self.fallback is None:
                raise

            response = self.fallback.invoke(messages, **kwargs)
            self._track_usage(response, model_id=settings.openai_model)
            return response

    def get_model_with_tools(self, tools: list[Any]) -> BaseChatModel:
        """Return the primary model bound with tools, with fallback."""
        try:
            return self.primary.bind_tools(tools)
        except Exception:
            if self.fallback:
                return self.fallback.bind_tools(tools)
            raise

    @property
    def tokens_used(self) -> int:
        return self._tokens_used

    @property
    def tokens_remaining(self) -> int:
        return max(0, settings.llm_token_budget - self._tokens_used)

    def reset_budget(self) -> None:
        self._tokens_used = 0


# Singleton instance
llm_provider = LLMProvider()
