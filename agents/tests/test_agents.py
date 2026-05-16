"""Tests for agent graph compilation and structure."""

import pytest


def test_code_review_agent_compiles():
    from agents.code_build import code_review_agent
    assert code_review_agent is not None
    # Verify it's a compiled graph
    assert hasattr(code_review_agent, "invoke")


def test_code_gen_agent_compiles():
    from agents.code_build import code_gen_agent
    assert code_gen_agent is not None
    assert hasattr(code_gen_agent, "invoke")


def test_test_gen_agent_compiles():
    from agents.test_secure import test_gen_agent
    assert test_gen_agent is not None
    assert hasattr(test_gen_agent, "invoke")


def test_security_scan_agent_compiles():
    from agents.test_secure import security_scan_agent
    assert security_scan_agent is not None
    assert hasattr(security_scan_agent, "invoke")


def test_release_agent_compiles():
    from agents.release_deploy import release_agent
    assert release_agent is not None
    assert hasattr(release_agent, "invoke")


def test_deploy_agent_compiles():
    from agents.release_deploy import deploy_agent
    assert deploy_agent is not None
    assert hasattr(deploy_agent, "invoke")


def test_ephemeral_env_agent_compiles():
    from agents.release_deploy import ephemeral_env_agent
    assert ephemeral_env_agent is not None
    assert hasattr(ephemeral_env_agent, "invoke")


def test_tf_review_agent_compiles():
    from agents.release_deploy import tf_review_agent
    assert tf_review_agent is not None
    assert hasattr(tf_review_agent, "invoke")


def test_plan_agent_compiles():
    from agents.plan_collaborate import plan_agent
    assert plan_agent is not None
    assert hasattr(plan_agent, "invoke")


def test_incident_agent_compiles():
    from agents.operate_monitor import incident_agent
    assert incident_agent is not None
    assert hasattr(incident_agent, "invoke")


def test_cost_analysis_agent_compiles():
    from agents.operate_monitor import cost_analysis_agent
    assert cost_analysis_agent is not None
    assert hasattr(cost_analysis_agent, "invoke")
