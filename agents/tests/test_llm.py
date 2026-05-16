"""Tests for the LLM Provider."""

import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage


@pytest.fixture
def llm_provider():
    with patch("shared.llm.ChatBedrockConverse") as mock_bedrock, \
         patch("shared.llm.ChatOpenAI") as mock_openai:
        mock_bedrock.return_value = MagicMock()
        mock_openai.return_value = MagicMock()
        from shared.llm import LLMProvider
        provider = LLMProvider()
        yield provider


def test_invoke_uses_primary(llm_provider):
    llm_provider.primary.invoke.return_value = AIMessage(content="hello")
    result = llm_provider.invoke([HumanMessage(content="test")])
    assert result.content == "hello"
    llm_provider.primary.invoke.assert_called_once()


def test_invoke_fallback_on_primary_failure(llm_provider):
    llm_provider.primary.invoke.side_effect = Exception("Bedrock error")
    llm_provider.fallback = MagicMock()
    llm_provider.fallback.invoke.return_value = AIMessage(content="fallback-response")
    result = llm_provider.invoke([HumanMessage(content="test")])
    assert result.content == "fallback-response"


@pytest.mark.asyncio
async def test_ainvoke_uses_primary(llm_provider):
    from unittest.mock import AsyncMock
    llm_provider.primary.ainvoke = AsyncMock(return_value=AIMessage(content="async-hello"))
    result = await llm_provider.ainvoke([HumanMessage(content="test")])
    assert result.content == "async-hello"


def test_budget_tracking(llm_provider):
    response = MagicMock()
    response.usage_metadata = {"total_tokens": 100}
    llm_provider.primary.invoke.return_value = response
    llm_provider.invoke([HumanMessage(content="test")])
    assert llm_provider.tokens_used == 100


def test_reset_budget(llm_provider):
    llm_provider._tokens_used = 5000
    llm_provider.reset_budget()
    assert llm_provider.tokens_used == 0
