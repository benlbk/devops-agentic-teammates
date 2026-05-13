"""Policy engine for governing agent actions."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require-approval"


class PolicyRule(BaseModel):
    """A single policy rule definition."""

    name: str
    agent: str
    action: str
    environment: str | None = None
    conditions: dict[str, Any] | None = None
    constraints: dict[str, Any] | None = None
    require_approval: bool = False
    approvers: list[str] | None = None
    enabled: bool = True


class PolicyEvaluationResult(BaseModel):
    """Result of evaluating a policy."""

    decision: PolicyDecision
    rule_name: str | None = None
    reason: str = ""
    approvers: list[str] | None = None
    constraints: dict[str, Any] | None = None


class PolicyEngine:
    """YAML-based policy engine that governs agent actions."""

    def __init__(self) -> None:
        self._rules: list[PolicyRule] = []

    def load_from_yaml(self, yaml_content: str) -> None:
        """Load policies from YAML string."""
        data = yaml.safe_load(yaml_content)
        policies = data.get("policies", [])
        self._rules = [PolicyRule(**p) for p in policies]
        logger.info("Loaded %d policy rules", len(self._rules))

    def load_from_file(self, path: str | Path) -> None:
        """Load policies from a YAML file."""
        content = Path(path).read_text()
        self.load_from_yaml(content)

    def evaluate(
        self,
        agent: str,
        action: str,
        context: dict[str, Any] | None = None,
    ) -> PolicyEvaluationResult:
        """Evaluate policies for a given agent action."""
        context = context or {}

        matching_rules = [
            rule for rule in self._rules
            if rule.enabled
            and rule.agent == agent
            and rule.action == action
        ]

        if not matching_rules:
            # Default: allow if no rules match
            return PolicyEvaluationResult(
                decision=PolicyDecision.ALLOW,
                reason="No matching policy rules; default allow",
            )

        for rule in matching_rules:
            # Check environment constraint
            if rule.environment and context.get("environment") != rule.environment:
                continue

            # Check conditions
            if rule.conditions and not self._evaluate_conditions(
                rule.conditions, context
            ):
                continue

            # Rule matches
            if rule.require_approval:
                return PolicyEvaluationResult(
                    decision=PolicyDecision.REQUIRE_APPROVAL,
                    rule_name=rule.name,
                    reason=f"Policy '{rule.name}' requires approval",
                    approvers=rule.approvers,
                    constraints=rule.constraints,
                )

            return PolicyEvaluationResult(
                decision=PolicyDecision.ALLOW,
                rule_name=rule.name,
                reason=f"Policy '{rule.name}' allows action",
                constraints=rule.constraints,
            )

        return PolicyEvaluationResult(
            decision=PolicyDecision.ALLOW,
            reason="No matching conditions; default allow",
        )

    def _evaluate_conditions(
        self, conditions: dict[str, Any], context: dict[str, Any]
    ) -> bool:
        """Evaluate condition expressions against context."""
        for key, expected in conditions.items():
            actual = context.get(key)
            if actual is None:
                return False

            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif isinstance(expected, str) and expected.startswith(("<", ">", "=")):
                op = expected[0]
                val = float(expected[1:].strip())
                if op == "<" and not (float(actual) < val):
                    return False
                elif op == ">" and not (float(actual) > val):
                    return False
            elif actual != expected:
                return False

        return True

    @property
    def rules(self) -> list[PolicyRule]:
        return self._rules.copy()


# Default policy configuration
DEFAULT_POLICIES = """
policies:
  - name: production-deploy-approval
    agent: release-deploy
    action: deploy
    environment: production
    require_approval: true
    approvers: ["platform-team", "tech-leads"]

  - name: code-review-auto
    agent: code-build
    action: approve-pr
    conditions:
      change_size: "< 50"
      test_coverage: "> 80"
      security_scan: pass
    require_approval: false

  - name: ephemeral-env-limits
    agent: release-deploy
    action: create-environment
    require_approval: false
    constraints:
      max_concurrent: 20
      max_cost_per_env: 50
      auto_destroy_hours: 48

  - name: incident-auto-remediate
    agent: operate-monitor
    action: auto-remediate
    conditions:
      severity: [low, medium]
      runbook_exists: true
    require_approval: false

  - name: incident-manual-remediate
    agent: operate-monitor
    action: auto-remediate
    conditions:
      severity: [high, critical]
    require_approval: true
    approvers: ["on-call-engineer", "platform-team"]

  - name: terraform-destroy-approval
    agent: release-deploy
    action: terraform-destroy
    require_approval: true
    approvers: ["platform-team"]

  - name: security-fix-auto
    agent: test-secure
    action: security-fix
    conditions:
      severity: [low, medium]
    require_approval: false

  - name: security-fix-critical
    agent: test-secure
    action: security-fix
    conditions:
      severity: [high, critical]
    require_approval: true
    approvers: ["security-team"]
"""

policy_engine = PolicyEngine()
policy_engine.load_from_yaml(DEFAULT_POLICIES)
