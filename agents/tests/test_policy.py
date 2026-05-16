"""Tests for the Policy Engine."""

import pytest
from shared.policy import PolicyEngine, PolicyDecision


@pytest.fixture
def policy_engine():
    engine = PolicyEngine()
    engine.load_from_yaml("""
policies:
  - name: code-review-allow
    agent: code-build
    action: pull_request.opened
    enabled: true

  - name: deploy-staging-allow
    agent: release-deploy
    action: deploy
    environment: staging
    enabled: true

  - name: deploy-production-approval
    agent: release-deploy
    action: deploy
    environment: production
    require_approval: true
    approvers: ["lead-dev", "sre-team"]
    constraints:
      strategy: canary

  - name: deploy-deny-disabled
    agent: release-deploy
    action: deploy
    environment: testing
    enabled: false

  - name: incident-critical-approval
    agent: operate-monitor
    action: incident-response
    environment: production
    conditions:
      severity: SEV1
    require_approval: true
    approvers: ["sre-team"]
""")
    return engine


def test_allow_when_rule_matches(policy_engine: PolicyEngine):
    result = policy_engine.evaluate(
        agent="code-build",
        action="pull_request.opened",
        context={"repository": "org/repo"},
    )
    assert result.decision == PolicyDecision.ALLOW


def test_allow_when_no_rules_match(policy_engine: PolicyEngine):
    result = policy_engine.evaluate(
        agent="unknown-agent",
        action="unknown-action",
    )
    assert result.decision == PolicyDecision.ALLOW
    assert "No matching" in result.reason


def test_require_approval_for_production_deploy(policy_engine: PolicyEngine):
    result = policy_engine.evaluate(
        agent="release-deploy",
        action="deploy",
        context={"environment": "production"},
    )
    assert result.decision == PolicyDecision.REQUIRE_APPROVAL
    assert "lead-dev" in result.approvers
    assert result.constraints == {"strategy": "canary"}


def test_allow_staging_deploy(policy_engine: PolicyEngine):
    result = policy_engine.evaluate(
        agent="release-deploy",
        action="deploy",
        context={"environment": "staging"},
    )
    assert result.decision == PolicyDecision.ALLOW
