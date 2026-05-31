# DevOps Agentic Teammates — Operations Guide

## Platform Overview

DevOps Agentic Teammates is an AI-powered software delivery platform that automates the full SDLC through specialized agents. Each agent handles a phase of delivery, triggered by webhooks or manual actions through role-based consoles.

**Live URLs:**
- Dashboard: `https://devops.13.215.130.82.nip.io/dashboard/`
- Orchestrator API: `https://devops.13.215.130.82.nip.io/orchestrator/`
- Ops Portal: `https://devops.13.215.130.82.nip.io/dashboard/portal`

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         AWS Cloud (ap-southeast-1)               │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    EKS Cluster: mies-eks                  │   │
│  │                                                           │   │
│  │  namespace: agents          namespace: dashboard           │   │
│  │  ┌─────────────────────┐   ┌────────────────────┐        │   │
│  │  │ agent-orchestrator  │   │    dashboard       │        │   │
│  │  │ (2 replicas)        │   │    (1 replica)     │        │   │
│  │  └─────────────────────┘   └────────────────────┘        │   │
│  │                                                           │   │
│  │  ┌──────────────────────────────────────────────┐        │   │
│  │  │             NGINX Ingress Controller          │        │   │
│  │  │  devops.13.215.130.82.nip.io                  │        │   │
│  │  │  /orchestrator/ → agent-orchestrator:8000     │        │   │
│  │  │  /dashboard/    → dashboard:3000              │        │   │
│  │  └──────────────────────────────────────────────┘        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌────────────────┐  ┌──────────────┐  ┌───────────────────┐   │
│  │   DynamoDB     │  │     ECR      │  │  Amazon Bedrock   │   │
│  │ agent-state    │  │ agent-orch.  │  │  Claude 3.5 Sonnet│   │
│  │ (task store)   │  │ dashboard    │  │  (LLM engine)     │   │
│  └────────────────┘  └──────────────┘  └───────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**Key Services:**
| Component | Image Tag Format | Namespace |
|-----------|-----------------|-----------|
| Agent Orchestrator | `agent-orchestrator:v{N}` | `agents` |
| Dashboard | `dashboard:portal-v{N}` | `dashboard` |

---

## Agents & Capabilities

| Agent | Type Key | Task Types | Trigger |
|-------|----------|-----------|---------|
| Plan & Collaborate | `plan-collaborate` | `feature-planning`, `sprint-planning` | Manual (PM console) |
| Code & Build | `code-build` | `code-review`, `code-generation`, `code-fix`, `merge-approval` | Webhook (PR/Issue) + Manual |
| Test & Secure | `test-secure` | `security-scan`, `generate-tests` | Webhook (PR) + Manual |
| Release & Deploy | `release-deploy` | `deploy`, `release`, `ephemeral`, `tf-review` | Manual (DevOps console) |
| Operate & Monitor | `operate-monitor` | `runbook`, `incident-response` | Alerts webhook + Manual |

---

## End-to-End Workflow

### Phase 1: Planning (Product Manager)

1. PM signs into Ops Portal → selects "Product Manager" role
2. Submits a feature planning task with description and acceptance criteria
3. **Plan & Collaborate Agent** breaks it into GitHub issues with labels:
   - `auto-codegen` — triggers automatic code generation
   - `feature` / `enhancement` — triggers feature planning

### Phase 2: Development (Automated via Webhooks)

When an issue is created with `auto-codegen` label:

```
GitHub Webhook (issue.opened + labeled)
    │
    ▼
Orchestrator receives POST /webhooks/github
    │
    ▼
Code & Build Agent (code-generation)
    │ - Reads issue spec
    │ - Generates implementation
    │ - Creates PR with "Closes #N"
    ▼
GitHub Webhook (pull_request.opened)
    │
    ├──► Code & Build Agent (code-review)    ← PARALLEL
    │    - Reviews PR diff
    │    - Posts inline comments
    │    - Recommends: APPROVE / REQUEST_CHANGES
    │
    └──► Test & Secure Agent (security-scan) ← PARALLEL
         - SAST: LLM analyzes diff for OWASP Top 10
         - Secrets: Regex detection for leaked credentials
         - SCA: Dependency vulnerability check
         - Posts report as PR comment
```

**If code review = REQUEST_CHANGES:**
```
Code & Build Agent (code-fix)
    │ - Auto-generates fixes
    │ - Pushes new commits to PR
    │ - Re-triggers review (max 2 loops)
    ▼
```

**If code review = APPROVE:**
```
Creates merge-approval task (status: AWAITING_APPROVAL)
    │
    ▼
Appears on Approvals page for Tech Lead
```

### Phase 3: Quality Gate (QA / Security)

- **Automatic**: Security scan runs on every PR (webhook-triggered)
- **Manual**: QA can run additional scans from the QA Console with specific PR numbers
- Scan report posted as PR comment + stored in task output

### Phase 4: Approval (Tech Lead)

1. Tech Lead visits **Approvals** page
2. Reviews: code review summary + security findings + PR link
3. **Approve** → Orchestrator performs squash merge → PR closed → issue closed → branch deleted
4. **Reject** → Task marked rejected, developer notified

### Phase 5: Deployment (DevOps Engineer)

1. DevOps Engineer submits deploy task from console
2. **Release & Deploy Agent** handles:
   - Container build + push to ECR
   - Kubernetes deployment to EKS
   - Production deploys require additional approval gate

### Phase 6: Operations (SRE)

1. Monitoring alerts fire → `POST /webhooks/alerts` → auto-creates incident tasks
2. SRE can execute runbooks from the SRE Console
3. **Operate & Monitor Agent** diagnoses and remediates

---

## API Reference

### Core Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/info` | Service info |
| POST | `/api/tasks` | Create a new task |
| GET | `/api/tasks/{agent_type}/{task_id}` | Get task details |
| GET | `/api/tasks/status/{status}` | List tasks by status |
| GET | `/api/tasks/repo/{owner}/{repo}` | List tasks for a repo |

### Webhook Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/webhooks/github` | GitHub webhook receiver |
| POST | `/webhooks/alerts` | Alert webhook receiver |
| GET | `/webhooks/github/info` | Webhook configuration info |

### Approvals

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/approvals` | List pending approvals |
| POST | `/api/approvals` | Approve or reject (body: `{task_id, decision, comment}`) |

### Metrics & Monitoring

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/metrics/dora` | DORA metrics with performance levels |
| GET | `/api/metrics/agents` | Agent activity (24h) |
| GET | `/api/metrics/events` | Recent events timeline |
| GET | `/api/metrics/performance` | Agent & task type performance |
| GET | `/api/pipeline/{owner}/{repo}` | Pipeline status per issue |

### Operations

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/dependencies/check` | Dependency vulnerability check |
| POST | `/api/runbooks/execute` | Execute a runbook |
| GET | `/api/runbooks` | List available runbooks |
| POST | `/api/merge` | Merge a PR |

---

## Deployment Procedures

### Prerequisites

```powershell
$env:AWS_PROFILE = "mies-eks"  # Required for every terminal session
```

### Deploy Orchestrator

```powershell
# 1. Build
cd agents
docker build -t 448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/agent-orchestrator:v{N} .

# 2. Authenticate & Push
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin 448658572737.dkr.ecr.ap-southeast-1.amazonaws.com
docker push 448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/agent-orchestrator:v{N}

# 3. Deploy
kubectl set image deployment/orchestrator-agent-orchestrator agent-orchestrator=448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/agent-orchestrator:v{N} -n agents
kubectl rollout status deployment/orchestrator-agent-orchestrator -n agents --timeout=90s
```

### Deploy Dashboard

```powershell
# 1. Build
cd apps/dashboard
docker build -t 448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/dashboard:portal-v{N} .

# 2. Push
docker push 448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/dashboard:portal-v{N}

# 3. Deploy
kubectl set image deployment/dashboard dashboard=448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/dashboard:portal-v{N} -n dashboard
kubectl rollout status deployment/dashboard -n dashboard --timeout=90s
```

### Rollback

```powershell
# Rollback to previous version
kubectl rollout undo deployment/orchestrator-agent-orchestrator -n agents
kubectl rollout undo deployment/dashboard -n dashboard
```

> **Note**: ECR tag immutability is ENABLED. Each deployment must use a new tag version.

---

## Monitoring & Troubleshooting

### Check Pod Status

```powershell
kubectl get pods -n agents
kubectl get pods -n dashboard
```

### View Logs

```powershell
kubectl logs -n agents deploy/orchestrator-agent-orchestrator --tail=100 -f
kubectl logs -n dashboard deploy/dashboard --tail=100 -f
```

### Test API from Inside Cluster

```powershell
kubectl exec -n agents deploy/orchestrator-agent-orchestrator -- python -c "
import httpx; r = httpx.get('http://localhost:8000/health'); print(r.text)
"
```

### DORA Metrics Interpretation

| Metric | Elite | High | Medium | Low |
|--------|-------|------|--------|-----|
| Deployment Frequency | Multiple/day | Weekly | Monthly | <Monthly |
| Lead Time for Changes | <1 hour | <1 day | <1 week | >1 week |
| Change Failure Rate | ≤5% | ≤10% | ≤15% | >15% |
| Mean Time to Recovery | <1 hour | <1 day | <1 week | >1 week |

---

## Security Scanning Details

### Scan Engines

| Engine | Method | What It Detects |
|--------|--------|-----------------|
| SAST (LLM-based) | Sends PR diff to Claude for analysis | SQL injection, XSS, command injection, auth flaws, crypto weaknesses, path traversal, race conditions |
| Secret Scanner | Regex patterns against diff | API keys, AWS credentials, GitHub PATs, private keys, passwords |
| SCA (LLM-based) | Analyzes changed dependency files | Unpinned deps, known vulnerable patterns, deprecated packages |

### Scan Triggers

1. **Automatic**: Every PR opened/updated (webhook) → runs in parallel with code review
2. **Manual**: QA Console → specify repository + PR number → click "Run Security Scan"

### Where Reports Appear

- **GitHub PR**: Comment with formatted report (executive summary + remediation steps)
- **Task Monitor**: Raw output with `severity_summary`, `scan_results`, `security_report`
- **Approvals page**: Security context available when reviewing merge requests

---

## Webhook Configuration

### GitHub Webhook Setup

- **URL**: `https://devops.13.215.130.82.nip.io/orchestrator/webhooks/github`
- **Content type**: `application/json`
- **Events**: `pull_request`, `issues`, `push`
- **Idempotency**: Duplicate tasks are prevented using `{repo}/pr-review/{pr}/{sha}` keys

### Smart Routing Rules

| Event | Condition | Action |
|-------|-----------|--------|
| `pull_request.opened/synchronize` | Not draft, not bot | Auto code-review + security scan |
| `issues.opened` | Has `codegen`/`auto-codegen`/`auto-implement` label | Auto code-generation |
| `issues.opened` | Has `feature`/`enhancement`/`agent-generated` label | Feature planning |
| `push` | Any | RAG indexing of changed files |

---

## Role-Based Access

| Role | Console Path | Key Capabilities |
|------|-------------|------------------|
| Product Manager | `/dashboard/portal/pm` | Feature planning, sprint planning, story generation |
| Developer | `/dashboard/portal/dev` | Code generation, dependency checks, PR merge, code review status |
| QA / Security | `/dashboard/portal/qa` | Security scans (with PR#), test generation |
| DevOps Engineer | `/dashboard/portal/devops` | Deployments, infrastructure, ephemeral environments |
| SRE / Operations | `/dashboard/portal/sre` | Runbooks, incident response, performance optimization |
| Tech Lead | `/dashboard/portal/techlead` | Approvals, DORA metrics, architecture decisions |

---

## Infrastructure Details

| Resource | Details |
|----------|---------|
| AWS Account | 448658572737 |
| Region | ap-southeast-1 (Singapore) |
| EKS Cluster | mies-eks |
| ECR Repositories | `agent-orchestrator`, `dashboard` |
| DynamoDB Table | `agent-state` (PK: `AGENT#{type}`, SK: `TASK#{created_at}#{task_id}`) |
| LLM | Amazon Bedrock — `apac.anthropic.claude-3-5-sonnet-20241022-v2:0` |
| Ingress | NGINX Ingress with self-signed TLS on nip.io |
| GitHub Integration | PAT-based auth + webhook on `benlbk/online-shopping-app` |

---

## Task Lifecycle

```
PENDING → IN_PROGRESS → COMPLETED
                     └→ FAILED
                     └→ AWAITING_APPROVAL → COMPLETED (approved)
                                          → REJECTED
```

All tasks are stored in DynamoDB with:
- `task_id` (UUID)
- `agent_type`, `task_type`
- `status`, `context`, `input_data`, `output_data`
- `created_at`, `started_at`, `completed_at`
- `tokens_used` (LLM token consumption)
- `idempotency_key` (prevents duplicate processing)
