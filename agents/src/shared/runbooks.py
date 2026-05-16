"""Automated runbook scripts for incident remediation.

These runbooks are executed by the Operate & Monitor agent during
incident response. Each runbook is a Python async function that
takes incident context and returns a result.
"""

from __future__ import annotations

import asyncio
import subprocess
import structlog
from typing import Any

logger = structlog.get_logger()


async def runbook_pod_restart(context: dict[str, Any]) -> dict[str, Any]:
    """Restart pods in a deployment when they are crash-looping or unresponsive."""
    namespace = context.get("namespace", "target-app")
    deployment = context.get("deployment", "")
    
    if not deployment:
        return {"success": False, "error": "No deployment specified"}

    cmd = [
        "kubectl", "rollout", "restart",
        f"deployment/{deployment}",
        "-n", namespace,
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    
    if result.returncode == 0:
        logger.info("Pod restart successful", deployment=deployment, namespace=namespace)
        return {
            "success": True,
            "action": "pod_restart",
            "deployment": deployment,
            "namespace": namespace,
            "output": result.stdout.strip(),
        }
    else:
        logger.error("Pod restart failed", error=result.stderr)
        return {"success": False, "error": result.stderr.strip()}


async def runbook_scale_up(context: dict[str, Any]) -> dict[str, Any]:
    """Scale up a deployment to handle increased load."""
    namespace = context.get("namespace", "target-app")
    deployment = context.get("deployment", "")
    target_replicas = context.get("target_replicas", 5)
    max_replicas = context.get("max_replicas", 10)

    # Safety guard
    if target_replicas > max_replicas:
        target_replicas = max_replicas

    if not deployment:
        return {"success": False, "error": "No deployment specified"}

    cmd = [
        "kubectl", "scale",
        f"deployment/{deployment}",
        f"--replicas={target_replicas}",
        "-n", namespace,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode == 0:
        logger.info("Scale up successful", deployment=deployment, replicas=target_replicas)
        return {
            "success": True,
            "action": "scale_up",
            "deployment": deployment,
            "replicas": target_replicas,
            "output": result.stdout.strip(),
        }
    else:
        return {"success": False, "error": result.stderr.strip()}


async def runbook_rollback(context: dict[str, Any]) -> dict[str, Any]:
    """Rollback a deployment to the previous revision."""
    namespace = context.get("namespace", "target-app")
    deployment = context.get("deployment", "")
    
    if not deployment:
        return {"success": False, "error": "No deployment specified"}

    # Check if it's an Argo Rollout
    rollout_name = context.get("rollout_name")
    if rollout_name:
        cmd = [
            "kubectl", "argo", "rollouts", "abort",
            rollout_name, "-n", namespace,
        ]
    else:
        cmd = [
            "kubectl", "rollout", "undo",
            f"deployment/{deployment}",
            "-n", namespace,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode == 0:
        logger.info("Rollback successful", deployment=deployment)
        return {
            "success": True,
            "action": "rollback",
            "deployment": deployment,
            "namespace": namespace,
            "output": result.stdout.strip(),
        }
    else:
        return {"success": False, "error": result.stderr.strip()}


async def runbook_cache_clear(context: dict[str, Any]) -> dict[str, Any]:
    """Clear application caches by restarting cache pods or executing cache flush."""
    namespace = context.get("namespace", "target-app")
    cache_type = context.get("cache_type", "redis")

    if cache_type == "redis":
        # Execute FLUSHDB on Redis
        cmd = [
            "kubectl", "exec", "-n", namespace,
            "deploy/redis", "--",
            "redis-cli", "FLUSHDB",
        ]
    else:
        # Restart the application to clear in-memory caches
        deployment = context.get("deployment", "")
        cmd = [
            "kubectl", "rollout", "restart",
            f"deployment/{deployment}",
            "-n", namespace,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode == 0:
        return {
            "success": True,
            "action": "cache_clear",
            "cache_type": cache_type,
            "output": result.stdout.strip(),
        }
    else:
        return {"success": False, "error": result.stderr.strip()}


async def runbook_hpa_adjust(context: dict[str, Any]) -> dict[str, Any]:
    """Adjust HPA min/max replicas for a deployment."""
    namespace = context.get("namespace", "target-app")
    deployment = context.get("deployment", "")
    min_replicas = context.get("min_replicas", 3)
    max_replicas = context.get("max_replicas", 10)

    if not deployment:
        return {"success": False, "error": "No deployment specified"}

    # Patch the HPA
    patch = f'{{"spec":{{"minReplicas":{min_replicas},"maxReplicas":{max_replicas}}}}}'
    cmd = [
        "kubectl", "patch", "hpa", deployment,
        "-n", namespace,
        "--type=merge",
        f"-p={patch}",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode == 0:
        return {
            "success": True,
            "action": "hpa_adjust",
            "deployment": deployment,
            "min_replicas": min_replicas,
            "max_replicas": max_replicas,
        }
    else:
        return {"success": False, "error": result.stderr.strip()}


async def runbook_dns_check(context: dict[str, Any]) -> dict[str, Any]:
    """Verify DNS resolution and endpoint connectivity."""
    endpoint = context.get("endpoint", "")
    
    if not endpoint:
        return {"success": False, "error": "No endpoint specified"}

    # Check from within cluster
    cmd = [
        "kubectl", "run", "dns-check", "--rm", "-i", "--restart=Never",
        "--image=busybox", "--",
        "nslookup", endpoint,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    return {
        "success": result.returncode == 0,
        "action": "dns_check",
        "endpoint": endpoint,
        "output": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
    }


# Registry of available runbooks
RUNBOOK_REGISTRY: dict[str, Any] = {
    "pod_restart": runbook_pod_restart,
    "scale_up": runbook_scale_up,
    "rollback": runbook_rollback,
    "cache_clear": runbook_cache_clear,
    "hpa_adjust": runbook_hpa_adjust,
    "dns_check": runbook_dns_check,
}


async def execute_runbook(runbook_name: str, context: dict[str, Any]) -> dict[str, Any]:
    """Execute a runbook by name with the given context."""
    if runbook_name not in RUNBOOK_REGISTRY:
        return {
            "success": False,
            "error": f"Unknown runbook: {runbook_name}",
            "available": list(RUNBOOK_REGISTRY.keys()),
        }

    logger.info("Executing runbook", runbook=runbook_name, context=context)
    try:
        result = await RUNBOOK_REGISTRY[runbook_name](context)
        logger.info("Runbook completed", runbook=runbook_name, success=result.get("success"))
        return result
    except Exception as e:
        logger.error("Runbook execution failed", runbook=runbook_name, error=str(e))
        return {"success": False, "error": str(e)}
