"""Dependency Management & Build Optimization agents (FR-2.3, FR-2.4).

- Dependency update: scans package.json and pyproject.toml in a target repo
  against the npm/PyPI registries, opens a single grouped PR per ecosystem
  with the proposed bumps. Compat check is delegated to existing CI
  (Trivy + build) once the PR triggers workflows.

- Build optimization: pulls recent GitHub Actions runs + per-job timings,
  computes p50/p95 per workflow + slowest steps, asks the LLM to suggest
  caching / parallelization / step-reordering fixes, and posts the report
  as a GitHub Issue labelled `build-optimization`.

Both are intentionally lightweight (no Docker-in-Docker, no git clone) so
they can run inside the orchestrator pod.
"""

from __future__ import annotations

import base64
import json
import re
import statistics
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from shared.events import event_publisher
from shared.github_client import github_client
from shared.llm import llm_provider
from shared.state import AgentTask, TaskStatus, state_manager

logger = structlog.get_logger()


_NPM_REGISTRY = "https://registry.npmjs.org"
_PYPI = "https://pypi.org/pypi"


# ---- helpers ----

def _semver_strip(spec: str) -> str:
    return re.sub(r"^[\^~>=<!\s]+", "", (spec or "").strip()).split(",")[0].strip()


def _is_newer(latest: str, current: str) -> bool:
    def parts(v: str) -> list[int]:
        m = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", v or "0")
        if not m:
            return [0, 0, 0]
        return [int(x or 0) for x in m.groups()]
    return parts(latest) > parts(current)


async def _fetch_npm_latest(client: httpx.AsyncClient, pkg: str) -> str | None:
    try:
        r = await client.get(f"{_NPM_REGISTRY}/{pkg}", timeout=10.0)
        if r.status_code != 200:
            return None
        return r.json().get("dist-tags", {}).get("latest")
    except Exception:
        return None


async def _fetch_pypi_latest(client: httpx.AsyncClient, pkg: str) -> str | None:
    try:
        r = await client.get(f"{_PYPI}/{pkg}/json", timeout=10.0)
        if r.status_code != 200:
            return None
        return r.json().get("info", {}).get("version")
    except Exception:
        return None


# ---- Dependency Update ----

async def run_dependency_update(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Scan one repo's manifests, propose updates, open one PR per ecosystem."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    paths_npm: list[str] = context.get("npm_paths") or ["apps/dashboard/package.json"]
    paths_py: list[str] = context.get("python_paths") or ["agents/pyproject.toml"]
    max_bumps = int(context.get("max_bumps", 25))

    summary: dict[str, Any] = {"npm": [], "python": [], "prs": []}

    async with httpx.AsyncClient() as http:

        # --- npm ---
        for path in paths_npm:
            try:
                raw = await github_client.get_file_content(owner=owner, repo=repo, path=path)
                pkg = json.loads(raw)
            except Exception as e:
                logger.info("npm manifest skipped", path=path, error=str(e))
                continue

            updates: list[dict[str, str]] = []
            for section in ("dependencies", "devDependencies"):
                deps = pkg.get(section) or {}
                for name, spec in deps.items():
                    if not isinstance(spec, str) or spec.startswith(("git+", "file:", "link:", "workspace:")):
                        continue
                    current = _semver_strip(spec)
                    latest = await _fetch_npm_latest(http, name)
                    if latest and _is_newer(latest, current):
                        prefix = re.match(r"^([\^~]?)", spec).group(1) or "^"
                        new_spec = f"{prefix}{latest}"
                        deps[name] = new_spec
                        updates.append({"section": section, "name": name, "from": spec, "to": new_spec})
                        if len(updates) >= max_bumps:
                            break
                if len(updates) >= max_bumps:
                    break

            summary["npm"].append({"path": path, "updates": updates})
            if updates:
                pr = await _open_update_pr(
                    owner=owner, repo=repo,
                    ecosystem="npm", manifest_path=path,
                    updated_manifest=json.dumps(pkg, indent=2) + "\n",
                    updates=updates,
                )
                if pr:
                    summary["prs"].append(pr)

        # --- python (pyproject.toml, PEP 621 + Poetry-style) ---
        for path in paths_py:
            try:
                raw = await github_client.get_file_content(owner=owner, repo=repo, path=path)
            except Exception as e:
                logger.info("python manifest skipped", path=path, error=str(e))
                continue

            # Parse dependency lines without tomllib (avoid round-trip churn);
            # match `name = "version"` / `name>=1.2.3` style entries.
            updates_py: list[dict[str, str]] = []
            new_lines: list[str] = []
            for line in raw.splitlines():
                m = re.match(r'^(\s*)"?([A-Za-z0-9_.\-]+)"?\s*=\s*"([^"]+)"\s*,?\s*$', line)
                if m:
                    indent, name, spec = m.group(1), m.group(2), m.group(3)
                    if name.lower() in {"python"}:
                        new_lines.append(line)
                        continue
                    current = _semver_strip(spec)
                    latest = await _fetch_pypi_latest(http, name)
                    if latest and current and _is_newer(latest, current):
                        new_spec = re.sub(r"\d[\d.\w\-]*", latest, spec, count=1)
                        new_lines.append(f'{indent}"{name}" = "{new_spec}",' if line.rstrip().endswith(",") else f'{indent}"{name}" = "{new_spec}"')
                        updates_py.append({"name": name, "from": spec, "to": new_spec})
                        if len(updates_py) >= max_bumps:
                            new_lines.extend(raw.splitlines()[len(new_lines):])
                            break
                        continue
                # PEP 621 string list entries: "pkg>=1.2.3"
                m2 = re.match(r'^(\s*)"([A-Za-z0-9_.\-]+)([<>=!~]=?)([0-9][\w\.\-]*)"(\s*,?)\s*$', line)
                if m2:
                    indent, name, op, ver, tail = m2.group(1), m2.group(2), m2.group(3), m2.group(4), m2.group(5)
                    latest = await _fetch_pypi_latest(http, name)
                    if latest and _is_newer(latest, ver):
                        new_lines.append(f'{indent}"{name}{op}{latest}"{tail}')
                        updates_py.append({"name": name, "from": f"{op}{ver}", "to": f"{op}{latest}"})
                        if len(updates_py) >= max_bumps:
                            new_lines.extend(raw.splitlines()[len(new_lines):])
                            break
                        continue
                new_lines.append(line)

            summary["python"].append({"path": path, "updates": updates_py})
            if updates_py:
                pr = await _open_update_pr(
                    owner=owner, repo=repo,
                    ecosystem="python", manifest_path=path,
                    updated_manifest="\n".join(new_lines) + ("\n" if not raw.endswith("\n") else ""),
                    updates=updates_py,
                )
                if pr:
                    summary["prs"].append(pr)

    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = summary
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)
    await event_publisher.publish_task_completed(
        agent_type="code-build", task_id=task.task_id,
        task_type="dependency-update", status="completed", output=summary,
    )
    return summary


async def _open_update_pr(
    owner: str, repo: str, ecosystem: str, manifest_path: str,
    updated_manifest: str, updates: list[dict[str, str]],
) -> dict[str, Any] | None:
    branch = f"agent/deps-{ecosystem}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    try:
        await github_client.create_branch(owner=owner, repo=repo, branch=branch, from_ref="main")
    except Exception as e:
        logger.warning("create_branch failed", error=str(e), branch=branch)
        return None
    try:
        await github_client.create_or_update_file(
            owner=owner, repo=repo, path=manifest_path,
            content=updated_manifest,
            message=f"chore(deps-{ecosystem}): bump {len(updates)} packages",
            branch=branch,
        )
    except Exception as e:
        logger.warning("commit failed", error=str(e), path=manifest_path)
        return None

    body_lines = [
        f"Automated dependency update for **{ecosystem}** (`{manifest_path}`).",
        "",
        "| Package | From | To |",
        "| --- | --- | --- |",
    ]
    for u in updates:
        body_lines.append(f"| `{u['name']}` | `{u['from']}` | `{u['to']}` |")
    body_lines += [
        "",
        "CI (Trivy HIGH/CRITICAL gate + build) will validate compatibility.",
        "",
        "*Generated by DevOps Agentic Teammates — Dependency Management Agent (FR-2.3)*",
    ]
    try:
        pr = await github_client.create_pull_request(
            owner=owner, repo=repo,
            title=f"chore(deps-{ecosystem}): bump {len(updates)} packages",
            body="\n".join(body_lines),
            head=branch, base="main",
        )
        return {"number": pr.get("number"), "url": pr.get("html_url"), "ecosystem": ecosystem, "count": len(updates)}
    except Exception as e:
        logger.warning("create_pull_request failed", error=str(e))
        return None


# ---- Build Optimization ----

async def run_build_optimization(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Analyze GHA run history; post an Issue with caching/parallelization suggestions."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    sample_runs = int(context.get("sample_runs", 30))
    sample_jobs = int(context.get("sample_jobs", 5))

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    workflows = (await github_client.list_workflows(owner=owner, repo=repo)).get("workflows", [])
    per_wf_stats: list[dict[str, Any]] = []
    slow_steps: list[dict[str, Any]] = []

    for wf in workflows:
        wf_id = wf["id"]
        wf_name = wf.get("name") or wf.get("path", str(wf_id))
        runs = (await github_client.list_workflow_runs(
            owner=owner, repo=repo, workflow_id=wf_id, per_page=sample_runs,
        )).get("workflow_runs", [])

        durations: list[float] = []
        success = 0
        failed = 0
        for r in runs:
            if not r.get("run_started_at") or not r.get("updated_at"):
                continue
            try:
                start = datetime.fromisoformat(r["run_started_at"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(r["updated_at"].replace("Z", "+00:00"))
                durations.append((end - start).total_seconds())
            except ValueError:
                continue
            if r.get("conclusion") == "success":
                success += 1
            elif r.get("conclusion") == "failure":
                failed += 1
        if not durations:
            continue

        per_wf_stats.append({
            "workflow": wf_name,
            "runs_sampled": len(durations),
            "p50_s": round(statistics.median(durations), 1),
            "p95_s": round(statistics.quantiles(durations, n=20)[18], 1) if len(durations) >= 5 else round(max(durations), 1),
            "max_s": round(max(durations), 1),
            "success": success,
            "failed": failed,
        })

        # Pull jobs from the slowest recent successful run for step timing
        sorted_runs = sorted(
            [r for r in runs if r.get("conclusion") == "success"],
            key=lambda r: r.get("updated_at", ""),
            reverse=True,
        )[:sample_jobs]
        for r in sorted_runs:
            jobs = (await github_client.list_workflow_run_jobs(
                owner=owner, repo=repo, run_id=r["id"],
            )).get("jobs", [])
            for job in jobs:
                for step in job.get("steps", []):
                    if not (step.get("started_at") and step.get("completed_at")):
                        continue
                    try:
                        s = datetime.fromisoformat(step["started_at"].replace("Z", "+00:00"))
                        e = datetime.fromisoformat(step["completed_at"].replace("Z", "+00:00"))
                        dur = (e - s).total_seconds()
                    except ValueError:
                        continue
                    if dur >= 30:  # only consider steps >=30s
                        slow_steps.append({
                            "workflow": wf_name,
                            "job": job.get("name"),
                            "step": step.get("name"),
                            "seconds": round(dur, 1),
                        })

    slow_steps.sort(key=lambda s: s["seconds"], reverse=True)
    top_slow = slow_steps[:20]

    # Ask LLM for concrete actions
    suggestions = ""
    if per_wf_stats or top_slow:
        messages = [
            SystemMessage(content=(
                "You are a CI performance expert. Given GitHub Actions workflow "
                "duration stats and the slowest individual steps, recommend 3-7 "
                "concrete actions to cut build time. Focus on: caching (actions/cache, "
                "buildx layer cache, language-specific caches), parallelization "
                "(matrix, concurrent jobs), step reordering, removing redundant work. "
                "For each recommendation include: title, target workflow, expected "
                "saving (rough %), and the exact YAML snippet to add/change. "
                "Return Markdown."
            )),
            HumanMessage(content=(
                f"Workflow stats (seconds):\n{json.dumps(per_wf_stats, indent=2)}\n\n"
                f"Top slow steps:\n{json.dumps(top_slow, indent=2)}"
            )),
        ]
        try:
            resp = await llm_provider.ainvoke(messages)
            suggestions = resp.content if hasattr(resp, "content") else str(resp)
        except Exception as e:
            logger.warning("LLM call failed for build-opt", error=str(e))
            suggestions = "_LLM unavailable — raw stats only._"
    else:
        suggestions = "_No workflow run data available._"

    # Build report
    report_lines = [
        f"# CI Build Optimization Report — {repository}",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat()}_",
        "",
        "## Workflow duration stats",
        "",
        "| Workflow | Runs | p50 | p95 | max | success | failed |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in per_wf_stats:
        report_lines.append(
            f"| {s['workflow']} | {s['runs_sampled']} | {s['p50_s']}s | {s['p95_s']}s | {s['max_s']}s | {s['success']} | {s['failed']} |"
        )
    report_lines += ["", "## Slowest steps (top 20, ≥30s)", "", "| Workflow | Job | Step | Seconds |", "| --- | --- | --- | --- |"]
    for s in top_slow:
        report_lines.append(f"| {s['workflow']} | {s['job']} | {s['step']} | {s['seconds']} |")
    report_lines += ["", "## Recommendations", "", suggestions, "",
                     "---", "*Generated by DevOps Agentic Teammates — Build Optimization Agent (FR-2.4)*"]

    report = "\n".join(report_lines)

    issue_url = None
    try:
        issue = await github_client.create_issue(
            owner=owner, repo=repo,
            title=f"CI build optimization report — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            body=report,
            labels=["build-optimization", "agent-generated"],
        )
        issue_url = issue.get("html_url")
    except Exception as e:
        logger.warning("create_issue failed for build-opt", error=str(e))

    output = {
        "workflows_analyzed": len(per_wf_stats),
        "slow_steps_found": len(top_slow),
        "issue_url": issue_url,
        "stats": per_wf_stats,
    }
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = output
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)
    await event_publisher.publish_task_completed(
        agent_type="code-build", task_id=task.task_id,
        task_type="build-optimization", status="completed", output=output,
    )
    return output
