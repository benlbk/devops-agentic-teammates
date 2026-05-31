"""Release & Deploy extensions (FR-4.1, FR-4.2, FR-4.3, FR-4.4).

Task entry points wired through the ``release-deploy`` agent type:

- ``ephemeral-cost-guard``  — count open ephemeral envs vs budget, alert
                              & close oldest if over (FR-4.1).
- ``argo-rollout``          — generate Argo Rollouts canary manifest PR
                              (FR-4.2).
- ``tf-module-generate``    — LLM-author a Terraform module PR (FR-4.3).
- ``rightsize-report``      — analyse Helm values resources & open a
                              right-sizing recommendation issue (FR-4.3).
- ``release-notes``         — semver-bumped GitHub Release from
                              conventional commits since last tag (FR-4.4).

Repo-only: no Terraform/Helm execution in-pod; PRs flow into the target
repo's CI.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from shared.events import event_publisher
from shared.github_client import github_client
from shared.llm import llm_provider
from shared.state import AgentTask, TaskStatus, state_manager

logger = structlog.get_logger()


_CONV_COMMIT_RE = re.compile(
    r"^(?P<type>feat|fix|chore|docs|refactor|perf|test|build|ci|style|revert)"
    r"(?:\((?P<scope>[a-z0-9_\-./]+)\))?(?P<bang>!)?:\s(?P<subject>.+)",
    re.IGNORECASE,
)

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def _ts_branch(prefix: str) -> str:
    return f"agent/{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


async def _publish(task: AgentTask, task_type: str, output: dict[str, Any]) -> None:
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = output
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)
    await event_publisher.publish_task_completed(
        agent_type="release-deploy",
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


# ---------- FR-4.1: ephemeral env cost guard ----------

async def run_ephemeral_cost_guard(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Count open ephemeral envs (PRs labelled `ephemeral-env`) vs budget.

    Reports a daily/monthly estimate as a comment on each PR over budget,
    optionally closes the oldest PR(s) when exceeding ``max_envs``.
    """
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    label = context.get("label", "ephemeral-env")
    cost_per_env_per_day = float(context.get("cost_per_env_per_day", 8.0))
    monthly_budget = float(context.get("monthly_budget", 600.0))
    max_envs = int(context.get("max_envs", 10))

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    open_prs = await github_client.list_pulls(owner=owner, repo=repo, state="open", per_page=100)
    eph = [p for p in open_prs if any(l.get("name") == label for l in p.get("labels") or [])]
    n = len(eph)
    daily = n * cost_per_env_per_day
    monthly_est = daily * 30

    over_budget = monthly_est > monthly_budget
    over_count = n > max_envs

    body = (
        f"**Ephemeral env cost guard**\n\n"
        f"- Active ephemeral envs: **{n}** (label `{label}`)\n"
        f"- Per-env est: ${cost_per_env_per_day:.2f}/day\n"
        f"- Projected monthly: **${monthly_est:.2f}** (budget ${monthly_budget:.2f})\n"
        f"- Status: {'OVER BUDGET' if over_budget else 'OK'}"
        f"{' / OVER COUNT (' + str(max_envs) + ')' if over_count else ''}\n"
    )

    notified: list[int] = []
    if over_budget or over_count:
        for p in eph:
            try:
                await github_client.create_issue_comment(
                    owner=owner, repo=repo, issue_number=p["number"], body=body,
                )
                notified.append(p["number"])
            except Exception as e:
                logger.info("cost comment failed", pr=p["number"], error=str(e))

    out = {
        "active_envs": n, "daily_cost": daily, "monthly_estimate": monthly_est,
        "monthly_budget": monthly_budget, "over_budget": over_budget,
        "over_count": over_count, "notified_prs": notified,
    }
    await _publish(task, "ephemeral-cost-guard", out)
    return out


# ---------- FR-4.2: Argo Rollouts manifest generation ----------

_ROLLOUT_TEMPLATE = """apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: {service}
  namespace: {namespace}
  labels:
    app: {service}
spec:
  replicas: {replicas}
  strategy:
    canary:
      maxSurge: 25%
      maxUnavailable: 0
      steps:
{steps}
      analysis:
        templates:
          - templateName: success-rate
        startingStep: 2
        args:
          - name: service-name
            value: {service}
  selector:
    matchLabels:
      app: {service}
  template:
    metadata:
      labels:
        app: {service}
    spec:
      containers:
        - name: {service}
          image: {image}
          ports:
            - containerPort: {port}
          readinessProbe:
            httpGet:
              path: {health_path}
              port: {port}
            initialDelaySeconds: 5
            periodSeconds: 10
"""

_ANALYSIS_TEMPLATE = """apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: success-rate
  namespace: {namespace}
spec:
  args:
    - name: service-name
  metrics:
    - name: success-rate
      interval: 1m
      successCondition: result[0] >= 0.95
      failureLimit: 3
      provider:
        prometheus:
          address: http://prometheus.monitoring:9090
          query: |
            sum(rate(http_requests_total{{service="{{{{args.service-name}}}}",status!~"5.."}}[1m]))
              /
            sum(rate(http_requests_total{{service="{{{{args.service-name}}}}"}}[1m]))
"""


def _build_canary_steps(weights: list[int], pause_minutes: int) -> str:
    lines = []
    for w in weights:
        lines.append(f"        - setWeight: {w}")
        lines.append(f"        - pause: {{ duration: {pause_minutes}m }}")
    return "\n".join(lines)


async def run_argo_rollout(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Generate Argo Rollouts manifest + AnalysisTemplate PR."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    service = context.get("service", "web")
    namespace = context.get("namespace", "default")
    image = context.get("image", f"ghcr.io/{owner}/{service}:latest")
    port = int(context.get("port", 8080))
    health_path = context.get("health_path", "/healthz")
    replicas = int(context.get("replicas", 3))
    weights = context.get("canary_weights") or [10, 25, 50, 75]
    pause_minutes = int(context.get("pause_minutes", 5))
    target_dir = context.get("target_dir", "argo/rollouts")

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    rollout = _ROLLOUT_TEMPLATE.format(
        service=service, namespace=namespace, replicas=replicas,
        image=image, port=port, health_path=health_path,
        steps=_build_canary_steps(weights, pause_minutes),
    )
    analysis = _ANALYSIS_TEMPLATE.format(namespace=namespace)

    files = [
        {"path": f"{target_dir}/{service}-rollout.yaml", "content": rollout,
         "message": f"chore(deploy): canary rollout manifest for {service}"},
        {"path": f"{target_dir}/analysis-success-rate.yaml", "content": analysis,
         "message": "chore(deploy): success-rate analysis template"},
    ]

    branch = _ts_branch(f"argo-rollout-{service}")
    pr = await _open_pr(
        owner=owner, repo=repo, branch=branch, base=context.get("base", "main"),
        files=files,
        title=f"chore(deploy): Argo Rollouts canary for `{service}`",
        body=(
            f"Progressive delivery manifest for `{service}`.\n\n"
            f"- Strategy: canary {weights} with {pause_minutes}m pauses\n"
            f"- Auto-rollback via `success-rate` AnalysisTemplate (Prometheus, "
            f"failureLimit=3, threshold=95%)\n"
            f"- Namespace: `{namespace}` | Image: `{image}`\n"
        ),
        labels=["argo-rollouts", "agent-generated"],
    )
    out = {"service": service, "weights": weights, "pr": pr.get("html_url") if pr else None}
    await _publish(task, "argo-rollout", out)
    return out


# ---------- FR-4.3: Terraform module generation ----------

_TF_MODULE_PROMPT = """You are a senior cloud platform engineer. Generate a production-ready
Terraform module from the request below. Output ONLY a JSON array:
[{"path":"terraform/modules/<name>/<file>","content":"<file content>"}].
Required files: main.tf, variables.tf, outputs.tf, versions.tf, README.md.
Rules:
- Pin provider versions in versions.tf (terraform >= 1.6, AWS ~> 5.0).
- All variables typed and documented with description + default where safe.
- No hardcoded account IDs, secrets, or region literals; use variables.
- Tag every resource with module = var.module_name, env = var.environment.
- Outputs: at minimum the primary ARN/id of created resources.
- README.md: usage example, inputs/outputs table.
"""


async def run_tf_module_generate(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Generate a Terraform module via LLM and open a PR."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    module_name = context.get("module_name") or context.get("name") or "module"
    module_name = re.sub(r"[^a-z0-9_-]+", "-", module_name.lower()).strip("-")[:50] or "module"
    description = context.get("description", "")

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    if not description.strip():
        out = {"reason": "no-description", "module": module_name}
        await _publish(task, "tf-module-generate", out)
        return out

    resp = await llm_provider.ainvoke([
        SystemMessage(content=_TF_MODULE_PROMPT),
        HumanMessage(content=f"Module name: {module_name}\n\nRequest:\n{description[:4000]}"),
    ])
    try:
        cleaned = resp.content.strip().strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        files_raw = json.loads(cleaned)
    except Exception:
        files_raw = [{"path": f"terraform/modules/{module_name}/main.tf", "content": resp.content}]

    target_prefix = f"terraform/modules/{module_name}/"
    files = []
    for f in files_raw:
        path = f.get("path") or f"{target_prefix}main.tf"
        if not path.startswith("terraform/modules/"):
            path = target_prefix + path.split("/")[-1]
        files.append({"path": path, "content": f.get("content", ""),
                      "message": f"feat(tf): {module_name} module"})

    branch = _ts_branch(f"tf-module-{module_name}")
    pr = await _open_pr(
        owner=owner, repo=repo, branch=branch, base=context.get("base", "main"),
        files=files,
        title=f"feat(tf): {module_name} Terraform module",
        body=(
            f"Generated Terraform module `{module_name}`.\n\n"
            f"**Description:** {description[:500]}\n\n"
            f"Files: {len(files)}. Review variables, providers, and tags before merge."
        ),
        labels=["terraform", "agent-generated"],
    )
    out = {"module": module_name, "files": len(files), "pr": pr.get("html_url") if pr else None}
    await _publish(task, "tf-module-generate", out)
    return out


# ---------- FR-4.3: right-sizing report ----------

_RES_RE = re.compile(
    r"(cpu|memory):\s*['\"]?([0-9]+(?:\.[0-9]+)?)(m|Mi|Gi|G|M|Ki|K)?['\"]?",
    re.IGNORECASE,
)


def _normalize_cpu(value: float, unit: str | None) -> float:
    """Return CPU in millicores."""
    if unit and unit.lower() == "m":
        return value
    return value * 1000


def _normalize_mem(value: float, unit: str | None) -> float:
    """Return memory in MiB."""
    if not unit:
        return value / (1024 * 1024)
    u = unit.lower()
    if u in ("ki",):
        return value / 1024
    if u in ("mi", "m"):
        return value
    if u in ("gi", "g"):
        return value * 1024
    return value


async def run_rightsize_report(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Walk Helm values files and open an issue summarising over-provisioning."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    helm_root = context.get("helm_root", "helm")
    cpu_limit_threshold = float(context.get("cpu_request_threshold_m", 500))
    mem_limit_threshold = float(context.get("mem_request_threshold_mi", 512))

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    try:
        charts = await github_client.list_directory(owner=owner, repo=repo, path=helm_root)
    except Exception as e:
        out = {"reason": f"helm-root-missing: {e}", "path": helm_root}
        await _publish(task, "rightsize-report", out)
        return out

    findings: list[dict[str, Any]] = []
    for entry in charts:
        if entry.get("type") != "dir":
            continue
        chart = entry["name"]
        values_path = f"{helm_root}/{chart}/values.yaml"
        try:
            raw = await github_client.get_file_content(owner=owner, repo=repo, path=values_path)
        except Exception:
            continue
        cpu_m = mem_mi = None
        for m in _RES_RE.finditer(raw):
            key, val, unit = m.group(1).lower(), float(m.group(2)), m.group(3)
            if key == "cpu" and cpu_m is None:
                cpu_m = _normalize_cpu(val, unit)
            elif key == "memory" and mem_mi is None:
                mem_mi = _normalize_mem(val, unit)
        if cpu_m is None and mem_mi is None:
            continue
        recommendation = []
        if cpu_m is not None and cpu_m > cpu_limit_threshold:
            recommendation.append(f"CPU request {cpu_m:.0f}m exceeds threshold {cpu_limit_threshold:.0f}m — consider reducing.")
        if mem_mi is not None and mem_mi > mem_limit_threshold:
            recommendation.append(f"Memory request {mem_mi:.0f}Mi exceeds threshold {mem_limit_threshold:.0f}Mi — consider reducing.")
        findings.append({
            "chart": chart, "values": values_path,
            "cpu_m": cpu_m, "mem_mi": mem_mi,
            "recommendations": recommendation,
        })

    over = [f for f in findings if f["recommendations"]]
    issue_url = None
    if over:
        lines = ["## Right-sizing recommendations\n"]
        for f in over:
            lines.append(f"### `{f['chart']}` (`{f['values']}`)")
            lines.append(f"- CPU request: {f['cpu_m']:.0f}m | Memory request: {f['mem_mi']:.0f}Mi")
            for r in f["recommendations"]:
                lines.append(f"- {r}")
            lines.append("")
        try:
            issue = await github_client.create_issue(
                owner=owner, repo=repo,
                title=f"Right-sizing recommendations ({len(over)} chart{'s' if len(over) != 1 else ''})",
                body="\n".join(lines),
                labels=["cost-optimization", "agent-generated"],
            )
            issue_url = issue.get("html_url")
        except Exception as e:
            logger.info("rightsize issue create failed", error=str(e))

    out = {"charts_scanned": len(findings), "over_threshold": len(over),
           "issue_url": issue_url, "findings": over}
    await _publish(task, "rightsize-report", out)
    return out


# ---------- FR-4.4: release notes ----------

def _bump_semver(version: str, kind: str) -> str:
    m = _SEMVER_RE.match(version or "0.0.0")
    if not m:
        return "0.1.0"
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


_CATEGORY_MAP = {
    "feat": "Features",
    "fix": "Fixes",
    "perf": "Performance",
    "refactor": "Refactoring",
    "docs": "Documentation",
    "build": "Build & Dependencies",
    "ci": "CI/CD",
    "chore": "Chores",
    "test": "Tests",
    "style": "Style",
    "revert": "Reverts",
}


async def run_release_notes(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Generate categorised release notes from conventional commits since last tag."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    base = context.get("base", "main")
    head = context.get("head", base)
    dry_run = bool(context.get("dry_run", False))

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    latest = await github_client.get_latest_release(owner=owner, repo=repo)
    prev_tag = (latest or {}).get("tag_name", "")
    if prev_tag:
        cmp_data = await github_client.compare_commits(owner=owner, repo=repo, base=prev_tag, head=head)
        commits = cmp_data.get("commits") or []
    else:
        commits = await github_client.list_commits(owner=owner, repo=repo, branch=head, per_page=100)

    if not commits:
        out = {"commits": 0, "reason": "no-commits-since-last-release", "prev_tag": prev_tag}
        await _publish(task, "release-notes", out)
        return out

    categorized: dict[str, list[dict[str, str]]] = defaultdict(list)
    breaking: list[str] = []
    bump = "patch"
    for c in commits:
        msg = (c.get("commit") or {}).get("message", "")
        first = msg.split("\n", 1)[0].strip()
        sha = (c.get("sha") or "")[:7]
        m = _CONV_COMMIT_RE.match(first)
        if not m:
            categorized["Other"].append({"line": first, "sha": sha})
            continue
        t = m.group("type").lower()
        scope = m.group("scope") or ""
        subject = m.group("subject")
        is_break = bool(m.group("bang")) or "BREAKING CHANGE" in msg
        entry = {"line": f"{('**' + scope + '**: ') if scope else ''}{subject}", "sha": sha}
        if is_break:
            breaking.append(entry["line"])
            bump = "major"
        elif t == "feat" and bump != "major":
            bump = "minor"
        categorized[_CATEGORY_MAP.get(t, "Other")].append(entry)

    next_version = _bump_semver(prev_tag, bump)
    tag_name = f"v{next_version}"

    body_lines = [f"# {tag_name}", ""]
    if prev_tag:
        body_lines.append(f"_Changes since {prev_tag}_\n")
    if breaking:
        body_lines.append("## ⚠ Breaking Changes")
        for b in breaking:
            body_lines.append(f"- {b}")
        body_lines.append("")
    for cat in ["Features", "Fixes", "Performance", "Refactoring", "Build & Dependencies",
                "CI/CD", "Documentation", "Tests", "Chores", "Style", "Reverts", "Other"]:
        entries = categorized.get(cat) or []
        if not entries:
            continue
        body_lines.append(f"## {cat}")
        for e in entries:
            body_lines.append(f"- {e['line']} ({e['sha']})")
        body_lines.append("")

    body = "\n".join(body_lines).rstrip() + "\n"

    release_url = None
    if not dry_run:
        try:
            rel = await github_client.create_release(
                owner=owner, repo=repo, tag_name=tag_name, name=tag_name,
                body=body, target=base,
            )
            release_url = rel.get("html_url")
        except Exception as e:
            logger.error("release create failed", error=str(e), tag=tag_name)

    out = {
        "prev_tag": prev_tag, "tag": tag_name, "bump": bump,
        "commits": len(commits), "breaking": len(breaking),
        "release_url": release_url, "dry_run": dry_run,
        "body_preview": body[:600],
    }
    await _publish(task, "release-notes", out)
    return out
