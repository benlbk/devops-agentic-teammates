"""Shared configuration module for all agents."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # General
    project_name: str = "devops-agentic-teammates"
    environment: str = "dev"
    log_level: str = "INFO"

    # AWS
    aws_region: str = "ap-southeast-1"
    aws_account_id: str = ""

    # DynamoDB
    dynamodb_state_table: str = ""
    dynamodb_approvals_table: str = ""
    dynamodb_audit_table: str = ""

    # EventBridge
    event_bus_name: str = ""

    # OpenSearch
    opensearch_endpoint: str = ""
    opensearch_index: str = "codebase-knowledge"

    # LLM
    bedrock_model_id: str = "anthropic.claude-sonnet-4-20250514"
    bedrock_region: str = "ap-southeast-1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.1
    llm_token_budget: int = 100000

    # GitHub (personal free account — fine-grained PAT)
    github_token: str = ""
    github_token_secret: str = ""
    github_webhook_secret: str = ""

    # ArgoCD
    argocd_server: str = ""
    argocd_auth_token_secret: str = ""

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    model_config = {"env_prefix": "AGENT_"}


settings = Settings()
