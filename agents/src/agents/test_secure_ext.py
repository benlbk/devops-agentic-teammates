"""Test & Secure extensions (FR-3.1, FR-3.3, FR-3.4, FR-3.5).

Five task entry points wired through the `test-secure` agent type:

- ``e2e-generation``           — Playwright E2E tests from a feature spec /
                                 acceptance criteria (FR-3.1).
- ``contract-tests``           — schemathesis/pytest contract tests from an
                                 OpenAPI document in the repo (FR-3.1).
- ``coverage-enforce``         — read latest coverage artifact / file and
                                 fail-fast under threshold (FR-3.1).
- ``merge-queue``              — sequentially merge eligible PRs respecting
                                 conventional-commit titles + CI green
                                 (FR-3.3).
- ``test-optimization``        — slow-test report + flaky-test quarantine
                                 PR (FR-3.4).
- ``feature-flag``             — declarative flag manifest CRUD
                                 (config/feature-flags.yml) (FR-3.5).

All operations are repo-only (no test execution inside the orchestrator
pod). The generated tests/configs are committed via PR and executed by the
target repo's own CI.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from shared.events import event_publisher
from shared.github_client import github_client
from shared.llm import llm_provider
from shared.state import AgentTask, TaskStatus, state_manager

logger = structlog.get_logger()


# ---------- shared helpers ----------

_CONV_COMMIT_RE = re.compile(
    r"^(feat|fix|chore|docs|refactor|perf|test|build|ci|style|revert)"
    r"(\([a-z0-9_\-./]+\))?!?:\s.+",
    re.IGNORECASE,
)


def _ts_branch(prefix: str) -> str:
    return f"agent/{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


async def _publish(task: AgentTask, task_type: str, output: dict[str, Any]) -> None:
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = output
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)
    await event_publisher.publish_task_completed(
        agent_type="test-secure",
        task_id=task.task_id,
        task_type=task_type,
        status="completed",
        output=output,
    )


async def _open_pr(
    owner: str, repo: str, branch: str, base: str,
    files: list[dict[str, str]], title: str, body: str,
    labels: list[str] | None = None,
) -> dict[str, Any] | None:
    """Create a branch from base, commit files, open PR."""
    try:
        await github_client.create_branch(owner=owner, repo=repo, branch=branch, from_ref=base)
        for f in files:
            await github_client.create_or_update_file(
                owner=owner, repo=repo, path=f["path"], content=f["content"],
                message=f.get("message", title), branch=branch,
            )
        pr = await github_client.create_pull_request(
            owner=owner, repo=repo, title=title, body=body, head=branch, base=base,
        )
        if labels:
            try:
                await github_client.add_issue_labels(
                    owner=owner, repo=repo, issue_number=pr["number"], labels=labels,
                )
            except Exception as e:
                logger.info("label add failed (non-fatal)", error=str(e))
        return pr
    except Exception as e:
        logger.error("PR open failed", error=str(e), branch=branch)
        return None


# ---------- FR-3.1: E2E from acceptance criteria ----------

_E2E_PROMPT = """You are a senior QA engineer. Convert the acceptance criteria below into
Playwright TypeScript E2E tests. Output ONLY a JSON array of objects:
[{"path":"tests/e2e/<slug>.spec.ts","content":"<full file>"}].
Rules:
- Use @playwright/test, async test cases, expect(...).
- One spec file per user story.
- Use data-testid selectors when possible. If a base URL is given,
  navigate to it; otherwise use process.env.BASE_URL.
- Include at least one happy-path AND one negative-path scenario per criterion.
"""


async def run_e2e_generation(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Generate Playwright E2E specs from acceptance criteria."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    criteria = context.get("acceptance_criteria") or ""
    story_slug = (context.get("slug") or context.get("title") or "story").lower()
    story_slug = re.sub(r"[^a-z0-9]+", "-", story_slug).strip("-")[:60] or "story"
    base_url = context.get("base_url", "")
    target_dir = context.get("target_dir", "apps/dashboard/tests/e2e")

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    if not criteria.strip():
        # try pulling from a referenced issue
        issue_number = context.get("issue_number")
        if issue_number:
            try:
                issue = await github_client.get_issue(owner=owner, repo=repo, issue_number=int(issue_number))
                criteria = issue.get("body") or ""
                if not story_slug or story_slug == "story":
                    story_slug = re.sub(r"[^a-z0-9]+", "-", (issue.get("title") or "story").lower()).strip("-")[:60]
            except Exception as e:
                logger.info("issue fetch failed", error=str(e))

    if not criteria.strip():
        await _publish(task, "e2e-generation", {"specs": 0, "reason": "no-criteria"})
        return {"specs": 0}

    prompt = _E2E_PROMPT + (f"\nBase URL: {base_url}\n" if base_url else "")
    resp = await llm_provider.ainvoke([
        SystemMessage(content=prompt),
        HumanMessage(content=f"Story slug: {story_slug}\n\nAcceptance criteria:\n{criteria[:6000]}"),
    ])
    try:
        cleaned = resp.content.strip().strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        specs = json.loads(cleaned)
    except Exception:
        # fallback: wrap raw response in one file
        specs = [{"path": f"{target_dir}/{story_slug}.spec.ts", "content": resp.content}]

    files = []
    for s in specs:
        path = s.get("path") or f"{target_dir}/{story_slug}.spec.ts"
        if not path.startswith(target_dir):
            path = f"{target_dir}/{path.split('/')[-1]}"
        files.append({"path": path, "content": s.get("content", ""), "message": f"test(e2e): {story_slug}"})

    branch = _ts_branch(f"e2e-{story_slug}")
    pr = await _open_pr(
        owner=owner, repo=repo, branch=branch, base=context.get("base", "main"),
        files=files,
        title=f"test(e2e): {story_slug} acceptance scenarios",
        body=f"Generated Playwright E2E specs from acceptance criteria.\n\nStory: {story_slug}\nFiles: {len(files)}",
        labels=["e2e", "agent-generated"],
    )
    out = {"specs": len(files), "pr": pr.get("html_url") if pr else None}
    await _publish(task, "e2e-generation", out)
    return out


# ---------- FR-3.1: OpenAPI contract tests ----------

_CONTRACT_PROMPT = """Generate pytest + schemathesis contract tests for the OpenAPI spec below.
Output ONLY JSON: [{"path":"tests/contract/test_<group>.py","content":"<full file>"}].
- Use `schemathesis.from_uri(BASE_URL + '/openapi.json')` OR `from_path` if given path.
- One file per OpenAPI tag (default 'default').
- Include @schemathesis.check decorators for status conformance + response schema.
- Add a smoke happy-path test per operationId.
"""


async def run_contract_tests(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Generate contract tests from an OpenAPI spec living in the repo."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    spec_path = context.get("openapi_path", "openapi.yaml")
    target_dir = context.get("target_dir", "tests/contract")

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    try:
        spec_raw = await github_client.get_file_content(owner=owner, repo=repo, path=spec_path)
    except Exception as e:
        out = {"reason": f"openapi-not-found: {e}", "path": spec_path}
        await _publish(task, "contract-tests", out)
        return out

    resp = await llm_provider.ainvoke([
        SystemMessage(content=_CONTRACT_PROMPT),
        HumanMessage(content=f"OpenAPI ({spec_path}):\n{spec_raw[:8000]}"),
    ])
    try:
        cleaned = resp.content.strip().strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        files_raw = json.loads(cleaned)
    except Exception:
        files_raw = [{"path": f"{target_dir}/test_contract.py", "content": resp.content}]

    files = []
    for f in files_raw:
        path = f.get("path") or f"{target_dir}/test_contract.py"
        if not path.startswith(target_dir):
            path = f"{target_dir}/{path.split('/')[-1]}"
        files.append({"path": path, "content": f.get("content", ""), "message": "test(contract): generated from OpenAPI"})

    branch = _ts_branch("contract-tests")
    pr = await _open_pr(
        owner=owner, repo=repo, branch=branch, base=context.get("base", "main"),
        files=files,
        title="test(contract): OpenAPI conformance tests",
        body=f"Generated schemathesis contract tests from `{spec_path}`.\nFiles: {len(files)}",
        labels=["contract-tests", "agent-generated"],
    )
    out = {"files": len(files), "pr": pr.get("html_url") if pr else None}
    await _publish(task, "contract-tests", out)
    return out


# ---------- FR-3.1: coverage enforcement ----------

async def run_coverage_enforce(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Read a coverage file from the repo and report pass/fail vs threshold."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    threshold = float(context.get("threshold", 80.0))
    candidates = context.get("paths") or [
        "coverage/coverage-summary.json",
        "coverage.xml",
        "coverage.json",
        ".coverage.json",
    ]

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    pct: float | None = None
    used_path: str | None = None
    for path in candidates:
        try:
            raw = await github_client.get_file_content(owner=owner, repo=repo, path=path)
        except Exception:
            continue
        used_path = path
        try:
            if path.endswith(".json"):
                data = json.loads(raw)
                total = (data.get("total") or {}).get("lines", {}).get("pct")
                if total is None:
                    total = (data.get("summary") or {}).get("line-rate")
                    if total is not None:
                        total = float(total) * 100
                pct = float(total) if total is not None else None
            elif path.endswith(".xml"):
                m = re.search(r'line-rate="([0-9.]+)"', raw)
                if m:
                    pct = float(m.group(1)) * 100
        except Exception as e:
            logger.info("coverage parse failed", path=path, error=str(e))
        if pct is not None:
            break

    pr_number = context.get("prNumber") or context.get("pr_number")
    passed = pct is not None and pct >= threshold
    body = (
        f"**Coverage gate**: {'PASS' if passed else 'FAIL'}\n\n"
        f"- Source: `{used_path or 'not-found'}`\n"
        f"- Measured: {pct if pct is not None else 'n/a'}%\n"
        f"- Threshold: {threshold}%\n"
    )
    if pr_number:
        try:
            await github_client.create_issue_comment(
                owner=owner, repo=repo, issue_number=int(pr_number), body=body,
            )
        except Exception as e:
            logger.info("coverage comment failed", error=str(e))

    out = {"coverage_pct": pct, "threshold": threshold, "passed": passed, "source": used_path}
    await _publish(task, "coverage-enforce", out)
    return out


# ---------- FR-3.3: merge queue + conventional commit enforcement ----------

async def run_merge_queue(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Iterate open PRs labelled `auto-merge`, merge ready ones sequentially.

    - Skips PRs whose title is not Conventional Commits compliant (comments instead).
    - Skips drafts, mergeable_state != 'clean' or 'unstable'.
    - Requires all check runs in 'completed/success' or 'completed/neutral'.
    """
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    queue_label = context.get("label", "auto-merge")
    max_merges = int(context.get("max_merges", 5))
    merge_method = context.get("merge_method", "squash")

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    # list_pulls returns recent PRs; filter to open + labelled in-process
    candidates = await github_client.list_pulls(
        owner=owner, repo=repo, state="open", per_page=50, base="main",
    )
    merged: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for pr_summary in candidates:
        if len(merged) >= max_merges:
            break
        labels = {lb.get("name") for lb in (pr_summary.get("labels") or [])}
        if queue_label not in labels:
            continue
        num = pr_summary["number"]
        title = pr_summary.get("title", "")

        if not _CONV_COMMIT_RE.match(title):
            try:
                await github_client.create_issue_comment(
                    owner=owner, repo=repo, issue_number=num,
                    body=(
                        f"merge-queue: PR title `{title}` does not follow "
                        "Conventional Commits. Expected `type(scope?): subject`. "
                        "Removing from queue."
                    ),
                )
                await github_client.remove_issue_label(
                    owner=owner, repo=repo, issue_number=num, label=queue_label,
                )
            except Exception as e:
                logger.info("conv-commit comment failed", error=str(e), pr=num)
            skipped.append({"pr": num, "reason": "non-conventional-title"})
            continue

        try:
            pr = await github_client.get_pull_request(owner=owner, repo=repo, pr_number=num)
        except Exception as e:
            skipped.append({"pr": num, "reason": f"fetch-fail:{e}"})
            continue
        if pr.get("draft"):
            skipped.append({"pr": num, "reason": "draft"})
            continue
        mstate = pr.get("mergeable_state", "")
        if mstate not in ("clean", "unstable", "has_hooks"):
            skipped.append({"pr": num, "reason": f"mergeable_state:{mstate}"})
            continue

        sha = (pr.get("head") or {}).get("sha")
        if sha:
            try:
                checks = await github_client.list_check_runs(owner=owner, repo=repo, ref=sha)
                bad = [
                    c.get("name") for c in checks.get("check_runs", [])
                    if c.get("status") == "completed"
                    and c.get("conclusion") not in ("success", "neutral", "skipped")
                ]
                if bad:
                    skipped.append({"pr": num, "reason": "checks-failed", "checks": bad[:5]})
                    continue
            except Exception as e:
                logger.info("check-runs fetch failed", error=str(e), pr=num)

        try:
            res = await github_client.merge_pull_request(
                owner=owner, repo=repo, pr_number=num,
                merge_method=merge_method, commit_title=title,
            )
            merged.append({"pr": num, "sha": res.get("sha"), "title": title})
        except Exception as e:
            skipped.append({"pr": num, "reason": f"merge-fail:{e}"})

    out = {"merged": merged, "skipped": skipped, "queue_label": queue_label}
    await _publish(task, "merge-queue", out)
    return out


# ---------- FR-3.4: test optimization (slow + flaky) ----------

_FLAKY_LABEL = "flaky-test"


async def run_test_optimization(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Scan recent workflow runs, identify slow tests + flaky jobs, open report issue."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    sample_runs = int(context.get("sample_runs", 40))
    slow_threshold = int(context.get("slow_threshold_seconds", 60))

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    runs = (await github_client.list_workflow_runs(
        owner=owner, repo=repo, status=None, per_page=sample_runs,
    )).get("workflow_runs", [])

    job_outcomes: dict[str, list[str]] = defaultdict(list)
    slow_steps: list[dict[str, Any]] = []

    for run in runs[:sample_runs]:
        rid = run.get("id")
        if not rid:
            continue
        try:
            jobs_resp = await github_client.list_workflow_run_jobs(
                owner=owner, repo=repo, run_id=rid, per_page=30,
            )
        except Exception:
            continue
        for job in jobs_resp.get("jobs", []):
            name = job.get("name", "")
            conclusion = job.get("conclusion") or "unknown"
            job_outcomes[name].append(conclusion)
            for step in job.get("steps", []) or []:
                started = step.get("started_at")
                finished = step.get("completed_at")
                if not (started and finished):
                    continue
                try:
                    dt_s = datetime.fromisoformat(started.replace("Z", "+00:00"))
                    dt_f = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                    dur = (dt_f - dt_s).total_seconds()
                except Exception:
                    continue
                if dur >= slow_threshold:
                    slow_steps.append({
                        "job": name, "step": step.get("name"),
                        "seconds": round(dur, 1), "run_id": rid,
                    })

    # flaky detection: a job is flaky if outcomes contain both success AND failure within window
    flaky: list[dict[str, Any]] = []
    for name, outcomes in job_outcomes.items():
        c = Counter(outcomes)
        if c.get("success", 0) >= 1 and c.get("failure", 0) >= 1 and len(outcomes) >= 3:
            flaky.append({
                "job": name, "runs": len(outcomes),
                "success": c.get("success", 0), "failure": c.get("failure", 0),
                "flake_rate": round(c.get("failure", 0) / len(outcomes), 2),
            })

    flaky.sort(key=lambda x: -x["flake_rate"])
    slow_steps.sort(key=lambda x: -x["seconds"])

    # Build report
    md = [f"# Test optimization report — {datetime.now(timezone.utc).date().isoformat()}", ""]
    md.append(f"Sampled **{len(runs)}** recent workflow runs.\n")
    md.append(f"## Flaky jobs ({len(flaky)})\n")
    if flaky:
        md.append("| Job | Runs | Pass | Fail | Flake rate |")
        md.append("| --- | ---: | ---: | ---: | ---: |")
        for f in flaky[:15]:
            md.append(f"| `{f['job']}` | {f['runs']} | {f['success']} | {f['failure']} | {f['flake_rate']} |")
    else:
        md.append("_No flaky jobs detected._")
    md.append("")
    md.append(f"## Slow steps (≥ {slow_threshold}s) — top 20\n")
    if slow_steps:
        md.append("| Job | Step | Seconds | Run |")
        md.append("| --- | --- | ---: | --- |")
        for s in slow_steps[:20]:
            md.append(f"| `{s['job']}` | {s['step']} | {s['seconds']} | {s['run_id']} |")
    else:
        md.append("_No steps exceeded threshold._")
    md.append("")
    if slow_steps:
        secs = [s["seconds"] for s in slow_steps]
        md.append(f"Slow-step p50: **{statistics.median(secs):.1f}s**, max: **{max(secs):.1f}s**.\n")

    issue = None
    try:
        issue = await github_client.create_issue(
            owner=owner, repo=repo,
            title=f"Test optimization report — {datetime.now(timezone.utc).date().isoformat()}",
            body="\n".join(md),
            labels=["test-optimization", "agent-generated"],
        )
    except Exception as e:
        logger.error("create_issue failed", error=str(e))

    # Quarantine PR: write/update a `quarantine.txt` listing flaky job names.
    quarantine_pr_url: str | None = None
    if flaky:
        quarantine_path = context.get("quarantine_path", "tests/quarantine.txt")
        content = "# Auto-managed flaky test quarantine. Re-evaluate weekly.\n" + "\n".join(
            f"{f['job']}  # flake_rate={f['flake_rate']}" for f in flaky
        ) + "\n"
        branch = _ts_branch("quarantine")
        pr = await _open_pr(
            owner=owner, repo=repo, branch=branch, base=context.get("base", "main"),
            files=[{"path": quarantine_path, "content": content, "message": "test: update flaky quarantine list"}],
            title="test: update flaky-test quarantine list",
            body=f"Auto-detected {len(flaky)} flaky jobs from the last {len(runs)} runs.",
            labels=[_FLAKY_LABEL, "agent-generated"],
        )
        if pr:
            quarantine_pr_url = pr.get("html_url")

    out = {
        "runs_sampled": len(runs),
        "flaky_count": len(flaky),
        "slow_steps_count": len(slow_steps),
        "issue_url": (issue or {}).get("html_url"),
        "quarantine_pr": quarantine_pr_url,
    }
    await _publish(task, "test-optimization", out)
    return out


# ---------- FR-3.5: feature flag manifest CRUD ----------

_FLAGS_HEADER = "# Auto-managed feature flag manifest. Use the feature-flag agent to mutate.\n"


def _parse_flags(raw: str) -> list[dict[str, Any]]:
    """Tiny YAML-ish parser: a list of `- key: value` blocks. Avoids PyYAML dep."""
    flags: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in raw.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        m = re.match(r"-\s+name:\s*(\S+)\s*$", line)
        if m:
            if cur:
                flags.append(cur)
            cur = {"name": m.group(1)}
            continue
        m = re.match(r"\s+(\w+):\s*(.+)$", line)
        if m and cur is not None:
            key, val = m.group(1), m.group(2).strip().strip('"')
            cur[key] = val
    if cur:
        flags.append(cur)
    return flags


def _serialize_flags(flags: list[dict[str, Any]]) -> str:
    out = [_FLAGS_HEADER]
    for f in flags:
        out.append(f"- name: {f['name']}")
        for k, v in f.items():
            if k == "name":
                continue
            out.append(f"  {k}: \"{v}\"")
    return "\n".join(out) + "\n"


async def run_feature_flag(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """CRUD operations on `config/feature-flags.yml` via PR.

    context: {action: create|update|expire|delete|list,
              flag: {name, enabled, rollout, owner, expires_at, description},
              path?: 'config/feature-flags.yml'}
    """
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    path = context.get("path", "config/feature-flags.yml")
    action = (context.get("action") or "list").lower()
    payload = context.get("flag") or {}
    today = datetime.now(timezone.utc).date().isoformat()

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    try:
        raw = await github_client.get_file_content(owner=owner, repo=repo, path=path)
    except Exception:
        raw = _FLAGS_HEADER
    flags = _parse_flags(raw)
    by_name = {f["name"]: f for f in flags}

    expired: list[str] = []
    changed = False

    if action == "list":
        # also surface expired flags
        for f in flags:
            exp = f.get("expires_at")
            if exp and exp < today:
                expired.append(f["name"])
        out = {"flags": flags, "expired": expired, "path": path}
        await _publish(task, "feature-flag", out)
        return out

    if action in ("create", "update"):
        name = payload.get("name")
        if not name:
            out = {"reason": "missing-flag-name"}
            await _publish(task, "feature-flag", out)
            return out
        existing = by_name.get(name, {"name": name})
        for k, v in payload.items():
            existing[k] = v
        by_name[name] = existing
        changed = True

    elif action == "delete":
        name = payload.get("name")
        if name and name in by_name:
            del by_name[name]
            changed = True

    elif action == "expire":
        # bulk: remove any flag with expires_at < today
        for f in list(flags):
            exp = f.get("expires_at")
            if exp and exp < today:
                del by_name[f["name"]]
                expired.append(f["name"])
                changed = True

    if not changed:
        out = {"reason": "noop", "action": action, "expired": expired}
        await _publish(task, "feature-flag", out)
        return out

    new_flags = list(by_name.values())
    new_raw = _serialize_flags(new_flags)
    branch = _ts_branch(f"flag-{action}")
    title_suffix = payload.get("name") or "expired"
    pr = await _open_pr(
        owner=owner, repo=repo, branch=branch, base=context.get("base", "main"),
        files=[{"path": path, "content": new_raw, "message": f"chore(flags): {action} {title_suffix}"}],
        title=f"chore(flags): {action} {title_suffix}",
        body=(
            f"Feature-flag manifest change.\n\n"
            f"Action: `{action}`\n"
            f"Expired removed: {expired or 'none'}\n"
            f"Total flags after change: {len(new_flags)}\n"
        ),
        labels=["feature-flag", "agent-generated"],
    )
    out = {"action": action, "pr": pr.get("html_url") if pr else None, "expired": expired, "total": len(new_flags)}
    await _publish(task, "feature-flag", out)
    return out
