"""Operate & Monitor extensions (FR-5.1, FR-5.2, FR-5.3, FR-5.4).

Task entry points routed through the ``operate-monitor`` agent type:

- ``incident-correlate`` — correlate an alert with recent deploys/PRs and
                           open an incident issue with the most likely
                           change candidates (FR-5.1).
- ``runbook-execute``    — match an alert pattern to a runbook from the
                           target repo's ``runbooks/`` dir and post the
                           steps as an issue comment (FR-5.1).
- ``slo-report``         — compute P50/P95/P99 + error-rate vs SLO and
                           recommend caching/perf actions in an issue
                           (FR-5.2).
- ``hpa-pdb-tune``       — propose HPA + PodDisruptionBudget manifests
                           for Helm charts that lack them (FR-5.3).
- ``dora-snapshot``      — compute DORA-4 metrics from GitHub history
                           and commit a markdown snapshot to
                           ``docs/dora/YYYY-MM-DD.md`` (FR-5.4).

Repo-only — no production cluster mutations from this pod.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from shared.events import event_publisher
from shared.github_client import github_client
from shared.llm import llm_provider
from shared.state import AgentTask, TaskStatus, state_manager

logger = structlog.get_logger()


def _ts_branch(prefix: str) -> str:
    return f"agent/{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


async def _publish(task: AgentTask, task_type: str, output: dict[str, Any]) -> None:
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc).isoformat()
    task.output_data = output
    task.tokens_used = llm_provider.tokens_used
    await state_manager.update_task(task)
    await event_publisher.publish_task_completed(
        agent_type="operate-monitor",
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


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


# ---------- FR-5.1: incident correlation ----------

async def run_incident_correlate(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Correlate an alert with recent merged PRs / commits and open an issue."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    alert = context.get("alert") or context.get("alertData") or {}
    lookback_minutes = int(context.get("lookback_minutes", 120))

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    alert_name = alert.get("name") or alert.get("alertname") or "unknown"
    severity = alert.get("severity", "warning")
    service = alert.get("service") or alert.get("labels", {}).get("service", "")
    summary = alert.get("summary") or alert.get("annotations", {}).get("summary", "")
    fired_at_raw = alert.get("startsAt") or alert.get("fired_at") or ""
    fired_at = _parse_iso(fired_at_raw) or datetime.now(timezone.utc)
    cutoff = fired_at - timedelta(minutes=lookback_minutes)

    # Pull recent merged PRs + commits since cutoff
    candidates: list[dict[str, Any]] = []
    try:
        prs = await github_client.list_pulls(owner=owner, repo=repo, state="closed", per_page=50)
    except Exception as e:
        logger.info("list_pulls failed", error=str(e))
        prs = []
    for p in prs:
        merged = _parse_iso(p.get("merged_at"))
        if not merged or merged < cutoff:
            continue
        score = 1
        title = (p.get("title") or "").lower()
        if service and service.lower() in title:
            score += 3
        labels = [l.get("name", "").lower() for l in (p.get("labels") or [])]
        if any(k in labels for k in ("deploy", "release", "infra")):
            score += 2
        candidates.append({
            "kind": "pr", "number": p.get("number"),
            "title": p.get("title"), "merged_at": p.get("merged_at"),
            "url": p.get("html_url"), "user": (p.get("user") or {}).get("login"),
            "score": score,
        })

    try:
        commits = await github_client.list_commits(owner=owner, repo=repo, branch="main", per_page=30)
    except Exception:
        commits = []
    for c in commits:
        author_date = _parse_iso(((c.get("commit") or {}).get("author") or {}).get("date"))
        if not author_date or author_date < cutoff:
            continue
        msg = ((c.get("commit") or {}).get("message") or "").split("\n", 1)[0]
        score = 1
        if service and service.lower() in msg.lower():
            score += 2
        candidates.append({
            "kind": "commit", "sha": (c.get("sha") or "")[:7],
            "title": msg, "merged_at": ((c.get("commit") or {}).get("author") or {}).get("date"),
            "url": c.get("html_url"), "user": ((c.get("author") or {}) or {}).get("login"),
            "score": score,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    top = candidates[:10]

    body_lines = [
        f"## Alert: `{alert_name}` ({severity})",
        "",
        f"- Service: `{service or 'n/a'}`",
        f"- Fired at: {fired_at_raw or 'n/a'}",
        f"- Lookback: {lookback_minutes} min",
        f"- Summary: {summary or '(none)'}",
        "",
        "## Likely change candidates",
        "",
    ]
    if not top:
        body_lines.append("_No PR/commit activity within the lookback window._")
    for c in top:
        if c["kind"] == "pr":
            body_lines.append(
                f"- **PR #{c['number']}** ({c['score']}★) — [{c['title']}]({c['url']}) "
                f"by @{c.get('user') or 'unknown'} at {c['merged_at']}"
            )
        else:
            body_lines.append(
                f"- **Commit `{c['sha']}`** ({c['score']}★) — {c['title']} "
                f"by @{c.get('user') or 'unknown'} at {c['merged_at']}"
            )
    body_lines.append("")
    body_lines.append("## Suggested next steps")
    body_lines.append("- Review the top-ranked PR/commit for behavior change")
    body_lines.append("- Roll back if a clear correlation is found (deploy < 30m before alert)")
    body_lines.append("- If unclear, escalate to on-call")

    issue_url = None
    issue_number = None
    try:
        labels = ["incident", "agent-generated"]
        if severity in ("critical", "high"):
            labels.append("severity-high")
        issue = await github_client.create_issue(
            owner=owner, repo=repo,
            title=f"[INCIDENT] {alert_name} on {service or 'unknown service'}",
            body="\n".join(body_lines),
            labels=labels,
        )
        issue_url = issue.get("html_url")
        issue_number = issue.get("number")
    except Exception as e:
        logger.error("incident issue failed", error=str(e))

    out = {
        "alert": alert_name, "severity": severity, "service": service,
        "candidates_found": len(candidates), "top_candidates": top,
        "issue_url": issue_url, "issue_number": issue_number,
    }
    await _publish(task, "incident-correlate", out)
    return out


# ---------- FR-5.1: runbook execution ----------

async def run_runbook_execute(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Match alert name to a runbook file and post steps to the incident issue."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    alert_name = context.get("alert_name") or context.get("alertname") or ""
    issue_number = context.get("issue_number") or context.get("issueNumber")
    runbook_dir = context.get("runbook_dir", "runbooks")

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    if not alert_name:
        out = {"reason": "no-alert-name"}
        await _publish(task, "runbook-execute", out)
        return out

    try:
        entries = await github_client.list_directory(owner=owner, repo=repo, path=runbook_dir)
    except Exception as e:
        out = {"reason": f"runbook-dir-missing: {e}", "dir": runbook_dir}
        await _publish(task, "runbook-execute", out)
        return out

    norm = re.sub(r"[^a-z0-9]+", "", alert_name.lower())
    matched = None
    for e in entries:
        if e.get("type") != "file":
            continue
        name_norm = re.sub(r"[^a-z0-9]+", "", e["name"].lower())
        if norm in name_norm or name_norm.replace("md", "") in norm:
            matched = e
            break

    runbook_content = None
    if matched:
        try:
            runbook_content = await github_client.get_file_content(
                owner=owner, repo=repo, path=f"{runbook_dir}/{matched['name']}",
            )
        except Exception as e:
            logger.info("runbook fetch failed", error=str(e))

    if not runbook_content:
        out = {"reason": "no-matching-runbook", "alert": alert_name,
               "candidates": [e["name"] for e in entries if e.get("type") == "file"]}
        await _publish(task, "runbook-execute", out)
        return out

    comment_url = None
    if issue_number:
        comment_body = (
            f"## Runbook: `{matched['name']}`\n\n"
            f"Auto-matched to alert `{alert_name}`.\n\n---\n\n{runbook_content[:5000]}"
        )
        try:
            c = await github_client.create_issue_comment(
                owner=owner, repo=repo, issue_number=int(issue_number), body=comment_body,
            )
            comment_url = c.get("html_url")
        except Exception as e:
            logger.info("runbook comment failed", error=str(e))

    out = {
        "alert": alert_name, "runbook": matched["name"],
        "issue_number": issue_number, "comment_url": comment_url,
    }
    await _publish(task, "runbook-execute", out)
    return out


# ---------- FR-5.2: SLO report ----------

def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


async def run_slo_report(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Compute P50/P95/P99 + error-rate vs SLO and create an issue with recs."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    service = context.get("service", "web")
    latencies_ms = [float(x) for x in (context.get("latencies_ms") or [])]
    error_rate = float(context.get("error_rate", 0.0))
    throughput_rps = float(context.get("throughput_rps", 0.0))
    slo_p99_ms = float(context.get("slo_p99_ms", 500.0))
    slo_error_rate = float(context.get("slo_error_rate", 0.01))

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    p50 = _percentile(latencies_ms, 0.50)
    p95 = _percentile(latencies_ms, 0.95)
    p99 = _percentile(latencies_ms, 0.99)
    avg = statistics.mean(latencies_ms) if latencies_ms else 0.0

    latency_breach = p99 > slo_p99_ms
    error_breach = error_rate > slo_error_rate

    recs: list[str] = []
    if latency_breach:
        recs.append(f"P99 {p99:.0f}ms exceeds SLO {slo_p99_ms:.0f}ms — enable CloudFront edge caching for static & GET-cacheable paths")
        recs.append("Consider Redis read-through for hot data; pre-warm caches on deploy")
        recs.append("Capture pg_stat_statements; create indices on top slow queries")
    if error_breach:
        recs.append(f"Error rate {error_rate*100:.2f}% exceeds SLO {slo_error_rate*100:.2f}% — add circuit breaker + exponential backoff on downstream calls")
    if not recs:
        recs.append("Within SLOs — no action required.")

    body = "\n".join([
        f"## SLO report: `{service}`",
        "",
        f"- Samples: {len(latencies_ms)} latency observations",
        f"- Throughput: {throughput_rps:.1f} rps",
        "",
        "### Latency (ms)",
        f"- Mean: {avg:.1f}",
        f"- P50: {p50:.1f}",
        f"- P95: {p95:.1f}",
        f"- **P99: {p99:.1f}** (SLO: {slo_p99_ms:.0f}) — {'BREACH' if latency_breach else 'OK'}",
        "",
        "### Errors",
        f"- **Error rate: {error_rate*100:.3f}%** (SLO: {slo_error_rate*100:.3f}%) — {'BREACH' if error_breach else 'OK'}",
        "",
        "### Recommendations",
        *[f"- {r}" for r in recs],
    ])

    issue_url = None
    if latency_breach or error_breach:
        try:
            labels = ["slo-breach", "performance", "agent-generated"]
            issue = await github_client.create_issue(
                owner=owner, repo=repo,
                title=f"SLO breach: {service} (P99={p99:.0f}ms, err={error_rate*100:.2f}%)",
                body=body,
                labels=labels,
            )
            issue_url = issue.get("html_url")
        except Exception as e:
            logger.info("SLO issue failed", error=str(e))

    out = {
        "service": service, "p50": p50, "p95": p95, "p99": p99,
        "error_rate": error_rate, "latency_breach": latency_breach,
        "error_breach": error_breach, "recommendations": recs,
        "issue_url": issue_url,
    }
    await _publish(task, "slo-report", out)
    return out


# ---------- FR-5.3: HPA + PDB tuning ----------

_HPA_TEMPLATE = """apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {service}
  namespace: {namespace}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {service}
  minReplicas: {min_replicas}
  maxReplicas: {max_replicas}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {cpu_target}
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: {mem_target}
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 30
"""

_PDB_TEMPLATE = """apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {service}
  namespace: {namespace}
spec:
  minAvailable: {min_available}
  selector:
    matchLabels:
      app: {service}
"""


async def run_hpa_pdb_tune(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Propose HPA + PDB manifests for charts that don't have them."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    helm_root = context.get("helm_root", "helm")
    namespace = context.get("namespace", "default")
    min_replicas = int(context.get("min_replicas", 2))
    max_replicas = int(context.get("max_replicas", 10))
    cpu_target = int(context.get("cpu_target", 70))
    mem_target = int(context.get("mem_target", 80))
    min_available = context.get("min_available", "50%")

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    try:
        charts = await github_client.list_directory(owner=owner, repo=repo, path=helm_root)
    except Exception as e:
        out = {"reason": f"helm-root-missing: {e}", "path": helm_root}
        await _publish(task, "hpa-pdb-tune", out)
        return out

    proposals = []
    files: list[dict[str, str]] = []
    for entry in charts:
        if entry.get("type") != "dir":
            continue
        chart = entry["name"]
        templates_dir = f"{helm_root}/{chart}/templates"
        try:
            tmpl = await github_client.list_directory(owner=owner, repo=repo, path=templates_dir)
        except Exception:
            continue
        existing = {t["name"].lower() for t in tmpl if t.get("type") == "file"}
        needs_hpa = not any("hpa" in n or "autoscal" in n for n in existing)
        needs_pdb = not any("pdb" in n or "disruption" in n for n in existing)
        if not needs_hpa and not needs_pdb:
            continue
        added = []
        if needs_hpa:
            files.append({
                "path": f"{templates_dir}/hpa.yaml",
                "content": _HPA_TEMPLATE.format(
                    service=chart, namespace=namespace,
                    min_replicas=min_replicas, max_replicas=max_replicas,
                    cpu_target=cpu_target, mem_target=mem_target,
                ),
                "message": f"feat(helm/{chart}): add HPA",
            })
            added.append("hpa.yaml")
        if needs_pdb:
            files.append({
                "path": f"{templates_dir}/pdb.yaml",
                "content": _PDB_TEMPLATE.format(
                    service=chart, namespace=namespace, min_available=min_available,
                ),
                "message": f"feat(helm/{chart}): add PodDisruptionBudget",
            })
            added.append("pdb.yaml")
        proposals.append({"chart": chart, "added": added})

    pr_url = None
    if files:
        branch = _ts_branch("hpa-pdb-tune")
        pr = await _open_pr(
            owner=owner, repo=repo, branch=branch, base=context.get("base", "main"),
            files=files,
            title=f"feat(helm): add HPA + PDB for {len(proposals)} chart{'s' if len(proposals) != 1 else ''}",
            body=(
                "Adds Horizontal Pod Autoscalers and Pod Disruption Budgets where missing.\n\n"
                + "\n".join(f"- `{p['chart']}`: {', '.join(p['added'])}" for p in proposals)
                + f"\n\nDefaults: min={min_replicas}, max={max_replicas}, CPU target={cpu_target}%, "
                  f"memory target={mem_target}%, minAvailable={min_available}"
            ),
            labels=["reliability", "agent-generated"],
        )
        pr_url = pr.get("html_url") if pr else None

    out = {"charts_scanned": len(charts), "proposals": proposals,
           "files_added": len(files), "pr": pr_url}
    await _publish(task, "hpa-pdb-tune", out)
    return out


# ---------- FR-5.4: DORA snapshot ----------

async def run_dora_snapshot(task: AgentTask, context: dict[str, Any]) -> dict[str, Any]:
    """Compute DORA-4 metrics from GitHub history and commit a snapshot."""
    repository = context.get("repository") or "benlbk/devops-agentic-teammates"
    owner, repo = repository.split("/", 1)
    window_days = int(context.get("window_days", 30))
    target_dir = context.get("target_dir", "docs/dora")

    task.status = TaskStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc).isoformat()
    await state_manager.update_task(task)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    # Deployment Frequency: count of GitHub Releases in window
    try:
        rel_headers = await github_client._auth_headers()
        rel_resp = await github_client._http.get(
            f"/repos/{owner}/{repo}/releases", headers=rel_headers,
            params={"per_page": 100},
        )
        rel_resp.raise_for_status()
        releases = rel_resp.json()
    except Exception:
        releases = []
    releases_in_window = [
        r for r in releases
        if (_parse_iso(r.get("published_at")) or now) >= cutoff
    ]
    deploy_freq_per_week = (len(releases_in_window) / max(window_days, 1)) * 7

    # Lead time for changes: median PR merge -> first release after merge
    try:
        prs = await github_client.list_pulls(owner=owner, repo=repo, state="closed", per_page=100)
    except Exception:
        prs = []
    merged_prs = [
        p for p in prs
        if p.get("merged_at") and (_parse_iso(p["merged_at"]) or now) >= cutoff
    ]
    release_times = sorted(
        [t for t in (_parse_iso(r.get("published_at")) for r in releases) if t]
    )
    lead_hours: list[float] = []
    for p in merged_prs:
        mt = _parse_iso(p["merged_at"])
        if not mt:
            continue
        rel_after = next((r for r in release_times if r >= mt), None)
        if rel_after:
            lead_hours.append((rel_after - mt).total_seconds() / 3600.0)
    median_lead_hours = statistics.median(lead_hours) if lead_hours else 0.0

    # MTTR: median resolution time of issues labelled "incident"
    try:
        inc_headers = await github_client._auth_headers()
        inc_resp = await github_client._http.get(
            f"/repos/{owner}/{repo}/issues", headers=inc_headers,
            params={"labels": "incident", "state": "closed", "per_page": 100,
                    "since": cutoff.isoformat()},
        )
        inc_resp.raise_for_status()
        incidents = [i for i in inc_resp.json() if not i.get("pull_request")]
    except Exception:
        incidents = []
    mttr_hours: list[float] = []
    for i in incidents:
        c = _parse_iso(i.get("created_at"))
        cl = _parse_iso(i.get("closed_at"))
        if c and cl:
            mttr_hours.append((cl - c).total_seconds() / 3600.0)
    median_mttr_hours = statistics.median(mttr_hours) if mttr_hours else 0.0

    # Change failure rate: deploys followed by rollback/incident label within 24h
    deploy_failures = 0
    for r in releases_in_window:
        rt = _parse_iso(r.get("published_at"))
        if not rt:
            continue
        for i in incidents:
            ic = _parse_iso(i.get("created_at"))
            if ic and rt <= ic <= rt + timedelta(hours=24):
                deploy_failures += 1
                break
    change_fail_rate = (deploy_failures / len(releases_in_window)) if releases_in_window else 0.0

    today = now.strftime("%Y-%m-%d")
    path = f"{target_dir}/{today}.md"
    md = "\n".join([
        f"# DORA snapshot — {today}",
        "",
        f"Window: last {window_days} days ({cutoff.date()} → {now.date()})",
        f"Repository: `{repository}`",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Deployment Frequency | **{deploy_freq_per_week:.2f}** deploys/week ({len(releases_in_window)} in window) |",
        f"| Lead Time for Changes | **{median_lead_hours:.1f} h** (median, {len(lead_hours)} merged PRs) |",
        f"| Mean Time to Restore | **{median_mttr_hours:.1f} h** (median, {len(mttr_hours)} incidents) |",
        f"| Change Failure Rate | **{change_fail_rate*100:.1f}%** ({deploy_failures}/{len(releases_in_window) or '0'}) |",
        "",
        "Generated by operate-monitor agent.",
        "",
    ])

    branch = _ts_branch("dora-snapshot")
    pr = await _open_pr(
        owner=owner, repo=repo, branch=branch, base=context.get("base", "main"),
        files=[{"path": path, "content": md, "message": f"docs(dora): snapshot {today}"}],
        title=f"docs(dora): snapshot {today}",
        body="Auto-generated DORA-4 snapshot for the engineering dashboard.",
        labels=["dora", "observability", "agent-generated"],
    )

    out = {
        "window_days": window_days,
        "deploy_frequency_per_week": deploy_freq_per_week,
        "lead_time_hours_median": median_lead_hours,
        "mttr_hours_median": median_mttr_hours,
        "change_failure_rate": change_fail_rate,
        "releases_in_window": len(releases_in_window),
        "incidents_in_window": len(incidents),
        "pr": pr.get("html_url") if pr else None,
        "snapshot_path": path,
    }
    await _publish(task, "dora-snapshot", out)
    return out
