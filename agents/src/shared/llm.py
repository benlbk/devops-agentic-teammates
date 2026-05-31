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

# Per-task token accumulator (asyncio-task-scoped). Holds a mutable [int] so increments
# inside the same context propagate without resetting the ContextVar each time.
_task_tokens: ContextVar[list[int] | None] = ContextVar("task_tokens", default=None)


def start_task_token_tracking() -> None:
    """Begin per-task token accounting for the current asyncio context."""
    _task_tokens.set([0])


def get_task_tokens() -> int:
    """Return tokens consumed since start_task_token_tracking() in this context."""
    v = _task_tokens.get()
    return v[0] if v else 0


class TokenBudgetExceeded(Exception):
    """Raised when the token budget is exhausted."""


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
        if self._tokens_used + estimated_tokens > settings.llm_token_budget:
            raise TokenBudgetExceeded(
                f"Token budget exceeded: {self._tokens_used}/{settings.llm_token_budget}"
            )

    def _track_usage(self, response: Any) -> None:
        usage = getattr(response, "usage_metadata", None)
        if usage and isinstance(usage, dict):
            delta = usage.get("total_tokens", 0)
            self._tokens_used += delta
            v = _task_tokens.get()
            if v is not None:
                v[0] += delta

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

        try:
            response = await self.primary.ainvoke(messages, **kwargs)
            self._track_usage(response)
            return response
        except Exception as e:
            logger.warning("Primary LLM (Bedrock) failed: %s, trying fallback", e)
            if self.fallback is None:
                raise

            response = await self.fallback.ainvoke(messages, **kwargs)
            self._track_usage(response)
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

        try:
            response = self.primary.invoke(messages, **kwargs)
            self._track_usage(response)
            return response
        except Exception as e:
            logger.warning("Primary LLM (Bedrock) failed: %s, trying fallback", e)
            if self.fallback is None:
                raise

            response = self.fallback.invoke(messages, **kwargs)
            self._track_usage(response)
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
