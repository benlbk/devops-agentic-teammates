# DevOps Agentic Teammates — Platform Usage Guide

> **How to use this platform to build and operate a modern web application**

This guide explains how each role interacts with the AI agent platform to automate the end-to-end SDLC. The platform handles: planning → coding → testing → deploying → monitoring — with AI agents as your teammates.

---

## Quick Reference — Platform URLs

| Service | URL |
|---------|-----|
| **Orchestrator API** | `https://devops.13.215.130.82.nip.io/orchestrator` |
| **Target Frontend** | `https://devops.13.215.130.82.nip.io/` |
| **Target Backend API** | `https://devops.13.215.130.82.nip.io/api` |
| **Agent Dashboard** | `https://devops.13.215.130.82.nip.io/dashboard` |
| **ArgoCD** | `https://devops.13.215.130.82.nip.io/argocd` |
| **Grafana** | `https://devops.13.215.130.82.nip.io/grafana` |
| **GitHub Repository** | `https://github.com/benlbk/devops-agentic-teammates` |

---

## Architecture — How Events Flow

```
You (Developer/PM/Ops) perform an action
        ↓
GitHub Webhook → Orchestrator → Policy Engine → Agent Dispatch
        ↓
Agent performs work (code/test/deploy/monitor)
        ↓
Results posted back (PR comments, issues, deployments, alerts)
        ↓
Dashboard shows real-time status + DORA metrics
```

---

## Role 1: Product Manager / Business Analyst

### Your Goal: Turn ideas into structured plans and tracked work items

### Workflow: Feature Planning

**Step 1 — Submit a feature request to the Plan & Collaborate Agent:**

```bash
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "plan-collaborate",
    "task_type": "feature-planning",
    "context": {
      "description": "Build a user authentication system with social login (Google, GitHub), email/password registration, and password reset flow",
      "requirements": [
        "Support Google and GitHub OAuth",
        "Email/password with email verification",
        "Password reset via email link",
        "JWT-based session management",
        "Rate limiting on auth endpoints"
      ],
      "target_stack": "Next.js frontend + .NET backend + PostgreSQL"
    }
  }'
```

**What the agent does:**
1. Parses your feature description using the LLM
2. Searches existing codebase for related code (RAG)
3. Generates user stories with acceptance criteria
4. Creates GitHub Issues with labels, dependencies, and estimates
5. Commits spec files to `.bk/specs/<feature-name>/` (requirements.md, design.md, tasks.md)

**Step 2 — Review generated artifacts:**
- Check GitHub Issues for the generated stories
- Review `.bk/specs/` for the design doc and task breakdown
- Approve or request changes via GitHub Issue comments

### Workflow: Sprint Planning

```bash
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "plan-collaborate",
    "task_type": "sprint-planning",
    "context": {
      "sprint_goal": "Complete user authentication MVP",
      "capacity_days": 10,
      "team_size": 3
    }
  }'
```

### What You Monitor:
- **Dashboard → Overview**: See planned vs. in-progress vs. completed work
- **GitHub Issues/Projects**: Track story status
- **DORA Metrics**: Deployment frequency, lead time trends

---

## Role 2: Software Developer

### Your Goal: Write code with AI assistance, automated reviews, and fast feedback

### Workflow A: AI-Assisted Code Generation

**Option 1 — Assign a GitHub Issue to trigger code generation:**

Create a GitHub Issue with a label `agent:code-build` and a structured body:

```markdown
## Feature: User Registration API

### Specification
- POST /api/auth/register endpoint
- Request body: { email, password, name }
- Validate email format, password strength (min 8 chars, 1 uppercase, 1 number)
- Hash password with bcrypt
- Store in PostgreSQL users table
- Send verification email
- Return 201 with user ID (no password in response)

### Acceptance Criteria
- [ ] Input validation with proper error messages
- [ ] Password hashed before storage
- [ ] Email uniqueness enforced
- [ ] Unit tests with >80% coverage
```

The **Code & Build Agent** will:
1. Read the spec and existing codebase context
2. Generate implementation code (`.NET controller, service, repository`)
3. Create a feature branch (`feature/user-registration-api`)
4. Commit the code and open a PR
5. The PR automatically triggers Code Review + Test agents

**Option 2 — Direct task submission:**

```bash
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "code-build",
    "task_type": "code-generation",
    "context": {
      "repository": "benlbk/devops-agentic-teammates",
      "specification": "Create a Next.js page at /auth/login with email/password form, Google OAuth button, and GitHub OAuth button. Use Tailwind CSS for styling.",
      "target_path": "apps/frontend/src/app/auth/login/page.tsx"
    }
  }'
```

### Workflow B: Open a PR → Automatic AI Code Review

Simply open a PR on the repository. The platform automatically:

1. **Code Review Agent** analyzes your changes for:
   - Bugs and logic errors
   - Security vulnerabilities
   - Performance issues
   - Code style and best practices
   - Missing error handling

2. **Test & Secure Agent** runs:
   - Security scanning (Trivy, Checkov, Gitleaks)
   - Generates suggested test cases
   - Dependency vulnerability check

3. Results posted as **PR comments** with inline annotations

### Workflow C: Dependency Management

```bash
# Check for outdated/vulnerable dependencies
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/dependencies/check \
  -H "Content-Type: application/json" \
  -d '{
    "repository": "benlbk/devops-agentic-teammates",
    "package_manager": "npm",
    "path": "apps/frontend/package.json"
  }'
```

### Your Daily Developer Loop:

```
1. Pick an Issue from the backlog (or let the agent generate code from a spec)
2. Create a feature branch → write code → push
3. Open a PR → AI review happens automatically (comments in ~2 min)
4. Address review feedback → push again → re-review
5. Merge PR → auto-deploy to staging (canary)
6. Monitor canary metrics in Dashboard/Grafana
7. Full promotion happens automatically if metrics pass
```

### What You Monitor:
- **PR Comments**: AI review feedback, test results, security findings
- **GitHub Actions**: CI build status
- **ArgoCD**: Deployment sync status after merge
- **Grafana**: Application metrics post-deploy

---

## Role 3: QA / Security Engineer

### Your Goal: Ensure code quality, test coverage, and security compliance

### Workflow A: Trigger Security Scan

```bash
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "test-secure",
    "task_type": "security-scan",
    "context": {
      "repository": "benlbk/devops-agentic-teammates",
      "scan_types": ["sast", "sca", "container", "iac", "secrets"],
      "branch": "main"
    }
  }'
```

**What runs:**
| Scan Type | Tool | What It Finds |
|-----------|------|---------------|
| SAST | Semgrep / CodeQL | Code vulnerabilities, injection flaws |
| SCA | Trivy | Vulnerable dependencies (CVEs) |
| Container | Trivy | Base image vulnerabilities |
| IaC | Checkov | Terraform/K8s misconfigurations |
| Secrets | Gitleaks | Leaked credentials, API keys |

### Workflow B: Generate Tests

```bash
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "test-secure",
    "task_type": "test-generation",
    "context": {
      "repository": "benlbk/devops-agentic-teammates",
      "target_files": ["apps/backend/Controllers/AuthController.cs"],
      "test_types": ["unit", "integration"],
      "framework": "xUnit"
    }
  }'
```

The agent generates:
- Unit tests with mocked dependencies
- Integration tests with test database
- Edge cases and error scenarios
- PR with the test code for your review

### Workflow C: Container/IaC Scanning (CI)

The `.github/workflows/container-iac-scan.yml` workflow runs automatically on every push:
- **Trivy** scans Docker images for HIGH/CRITICAL CVEs
- **Checkov** scans Terraform and Kubernetes manifests

### What You Monitor:
- **GitHub Actions** → Security scan workflow results
- **PR Comments** → Vulnerability findings with severity
- **Dashboard → Security** → Aggregate vulnerability trends
- **Container scan results** → Image CVEs before deployment

---

## Role 4: DevOps / Platform Engineer

### Your Goal: Manage infrastructure, deployments, and platform reliability

### Workflow A: Deploy a New Feature (GitOps)

After a PR is merged to `main`:

1. **GitHub Actions** builds the Docker image and pushes to ECR
2. **Release & Deploy Agent** updates the Helm chart `values.yaml` with the new image tag
3. **ArgoCD** detects the change and syncs to EKS
4. **Argo Rollouts** performs canary deployment:
   - 10% traffic → wait 2 min → check metrics
   - 30% traffic → wait 3 min → check metrics
   - 60% traffic → wait 5 min → check metrics
   - 100% traffic → deployment complete

**Manual promotion (if needed):**
```bash
kubectl argo rollouts promote target-backend-canary -n target-app
```

**Manual rollback:**
```bash
kubectl argo rollouts abort target-backend-canary -n target-app
kubectl argo rollouts undo target-backend-canary -n target-app
```

### Workflow B: Infrastructure Changes

```bash
# Modify Terraform modules, then:
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "release-deploy",
    "task_type": "terraform-plan-review",
    "context": {
      "repository": "benlbk/devops-agentic-teammates",
      "module": "terraform/modules/rds-postgresql",
      "change_description": "Increase RDS instance size from db.t3.medium to db.t3.large"
    }
  }'
```

The agent will:
- Run `terraform plan`
- Analyze the changes for risk
- Post a summary with cost impact
- Request approval if production-affecting

### Workflow C: Create Ephemeral Environment

For every PR, an ephemeral environment can be created:

```bash
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "release-deploy",
    "task_type": "ephemeral-environment",
    "context": {
      "pr_number": 15,
      "repository": "benlbk/devops-agentic-teammates",
      "services": ["frontend", "backend"],
      "ttl_hours": 24
    }
  }'
```

This creates a `pr-15` namespace in EKS with the PR's code deployed.

### Workflow D: Check Deployment Status

```bash
# ArgoCD status
argocd app list
argocd app get target-backend

# Argo Rollouts status
kubectl argo rollouts status target-backend-canary -n target-app

# Pod health
kubectl get pods -n target-app
kubectl get pods -n agents
```

### What You Monitor:
- **ArgoCD UI** → Sync status, health, resource tree
- **Grafana** → Cluster metrics, pod resources, node utilization
- **Argo Rollouts** → Canary progress, metrics gates
- **Terraform** → State drift detection

---

## Role 5: Site Reliability Engineer (SRE) / Operations

### Your Goal: Keep the platform running, respond to incidents, optimize performance

### Workflow A: Automated Incident Response

When Prometheus/Grafana fires an alert, it hits the orchestrator alert webhook:

```bash
# Alert webhook (usually fired by Alertmanager, but you can test manually):
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/webhooks/alertmanager \
  -H "Content-Type: application/json" \
  -d '{
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "HighPodRestartCount",
        "namespace": "target-app",
        "pod": "target-backend-7d4f5b6c8-x9z2k"
      },
      "annotations": {
        "summary": "Pod has restarted 5 times in 10 minutes",
        "severity": "warning"
      }
    }]
  }'
```

The **Operate & Monitor Agent** will:
1. Diagnose the issue (check logs, events, resource usage)
2. Match against runbooks
3. Execute auto-remediation if policy allows (low/medium severity + runbook exists)
4. Post incident summary and RCA

### Workflow B: Execute Runbooks Manually

```bash
# List available runbooks
curl -k https://devops.13.215.130.82.nip.io/orchestrator/api/runbooks

# Execute a specific runbook
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/runbooks/execute \
  -H "Content-Type: application/json" \
  -d '{
    "runbook": "pod_restart",
    "parameters": {
      "namespace": "target-app",
      "pod_name": "target-backend-7d4f5b6c8-x9z2k"
    }
  }'
```

**Available Runbooks:**

| Runbook | Purpose | Parameters |
|---------|---------|------------|
| `pod_restart` | Restart a failing pod | `namespace`, `pod_name` |
| `scale_up` | Scale deployment replicas | `namespace`, `deployment`, `replicas` |
| `rollback` | Rollback to previous version | `namespace`, `deployment` |
| `cache_clear` | Clear application cache | `namespace`, `service` |
| `hpa_adjust` | Adjust HPA thresholds | `namespace`, `hpa_name`, `min`, `max` |
| `dns_check` | Diagnose DNS resolution | `namespace`, `hostname` |

### Workflow C: Performance Optimization

```bash
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "operate-monitor",
    "task_type": "performance-analysis",
    "context": {
      "service": "target-backend",
      "namespace": "target-app",
      "symptoms": "P95 latency increased from 200ms to 800ms in the last hour",
      "metrics_window": "1h"
    }
  }'
```

### Workflow D: Cost Analysis

```bash
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "operate-monitor",
    "task_type": "cost-analysis",
    "context": {
      "scope": "all",
      "period": "last-30-days"
    }
  }'
```

### What You Monitor:
- **Grafana Dashboards**:
  - Cluster Overview (node CPU/memory, pod count)
  - Application Metrics (request rate, latency, errors)
  - Agent Activity (task count, duration, success rate)
  - DORA Metrics (deployment frequency, lead time, MTTR)
- **Prometheus Alerts** → Fires to Alertmanager → Orchestrator webhook
- **Dashboard → Costs** → Monthly spend and forecast

---

## Role 6: Tech Lead / Architect

### Your Goal: Enforce standards, review architecture, track engineering health

### Workflow A: Architecture Decision Records (ADRs)

```bash
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "agent_type": "plan-collaborate",
    "task_type": "adr-generation",
    "context": {
      "decision": "Migrate from REST to GraphQL for the frontend BFF layer",
      "drivers": [
        "Frontend needs to fetch data from 5+ microservices per page",
        "Over-fetching causing performance issues",
        "N+1 API calls on list pages"
      ],
      "options_considered": ["GraphQL", "BFF pattern with REST aggregation", "tRPC"],
      "repository": "benlbk/devops-agentic-teammates"
    }
  }'
```

### Workflow B: Approval Management

Production deployments and high-risk changes require approval:

```bash
# List pending approvals
curl -k https://devops.13.215.130.82.nip.io/orchestrator/api/approvals?status=pending

# Approve a task
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/approvals \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task-uuid-here",
    "decision": "approved",
    "approver": "tech-lead",
    "comment": "Reviewed the terraform plan, changes look safe"
  }'

# Reject a task
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/approvals \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task-uuid-here",
    "decision": "rejected",
    "approver": "tech-lead",
    "comment": "Missing rollback plan for database migration"
  }'
```

### Workflow C: DORA Metrics Review

```bash
# Get DORA metrics
curl -k https://devops.13.215.130.82.nip.io/orchestrator/api/metrics/dora
```

Returns:
- **Deployment Frequency** — How often you deploy to production
- **Lead Time for Changes** — Time from commit to production
- **Change Failure Rate** — % of deployments causing incidents
- **Mean Time to Recovery** — How fast you recover from failures

### Workflow D: Policy Configuration

The policy engine (`agents/src/shared/policy.py`) enforces rules:

```yaml
# Key policies in effect:
- Production deploys → REQUIRE_APPROVAL
- Security vulnerabilities (HIGH/CRITICAL) → BLOCK deployment
- Auto-remediation (low severity + runbook exists) → ALLOW
- Code review (small PRs, passing tests) → AUTO_APPROVE
- Ephemeral environments → ALLOW (max 20 concurrent, 48h TTL)
```

### What You Monitor:
- **DORA Metrics** → Team delivery performance
- **Approval Queue** → Pending decisions
- **Agent Activity** → Token usage, success rates
- **Security Dashboard** → Vulnerability trends

---

## Complete End-to-End Example: Building a New Feature

Here's how the entire platform works together when building a "User Profile Page":

### Step 1: PM Creates Feature Request
```bash
curl -k -X POST .../api/tasks -d '{
  "agent_type": "plan-collaborate",
  "task_type": "feature-planning",
  "context": { "description": "User profile page showing avatar, name, email, and activity history" }
}'
```
→ Agent creates 4 GitHub Issues + spec files

### Step 2: Developer Picks Up Issue & Pushes Code
```bash
git checkout -b feature/user-profile
# Write code...
git push origin feature/user-profile
# Open PR on GitHub
```
→ Code Review Agent posts inline feedback  
→ Test Agent generates test suggestions  
→ Security Agent scans for vulnerabilities

### Step 3: Developer Addresses Feedback & Merges
```bash
# Fix review comments, push, then merge PR
```
→ GitHub Actions builds Docker image → pushes to ECR  
→ Release Agent updates Helm values.yaml  
→ ArgoCD syncs to EKS  
→ Argo Rollouts does canary (10% → 30% → 60% → 100%)

### Step 4: Operations Monitors
→ Grafana shows request metrics for the new endpoint  
→ If errors spike: Alertmanager → Operate Agent → auto-rollback  
→ If healthy: full promotion completes automatically

### Step 5: Review
→ Tech Lead checks DORA metrics (was lead time good?)  
→ Dashboard shows the full lifecycle of the feature  
→ Postmortem generated automatically if rollback occurred

---

## Useful Commands Cheat Sheet

### Platform Health
```bash
# Check all pods
kubectl get pods -A | grep -v kube-system

# Check orchestrator health
curl -k https://devops.13.215.130.82.nip.io/orchestrator/health

# Check orchestrator info
curl -k https://devops.13.215.130.82.nip.io/orchestrator/info
```

### Task Management
```bash
# Create a task
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/tasks \
  -H "Content-Type: application/json" -d '{"agent_type": "...", "task_type": "...", "context": {...}}'

# Get task status
curl -k https://devops.13.215.130.82.nip.io/orchestrator/api/tasks/{task_id}
```

### Merge Coordination
```bash
# Request PR merge with checks
curl -k -X POST https://devops.13.215.130.82.nip.io/orchestrator/api/merge \
  -H "Content-Type: application/json" \
  -d '{"repository": "benlbk/devops-agentic-teammates", "pr_number": 42}'
```

### Monitoring
```bash
# DORA metrics
curl -k https://devops.13.215.130.82.nip.io/orchestrator/api/metrics/dora

# Agent metrics
curl -k https://devops.13.215.130.82.nip.io/orchestrator/api/metrics/agents

# Event bus metrics
curl -k https://devops.13.215.130.82.nip.io/orchestrator/api/metrics/events
```

---

## Policy & Governance Summary

| Action | Policy | Behavior |
|--------|--------|----------|
| Deploy to production | REQUIRE_APPROVAL | Blocks until Tech Lead approves |
| Deploy to staging | ALLOW | Auto-deploys on merge to main |
| Auto-remediate (low/medium) | ALLOW | Agent fixes if runbook exists |
| Auto-remediate (high/critical) | REQUIRE_APPROVAL | Must be approved first |
| Create ephemeral env | ALLOW | Max 20 concurrent, 48h auto-destroy |
| Code review (small PR) | AUTO_APPROVE | If <50 lines, tests pass, no vulns |
| Security fix | AUTO_APPROVE | Critical CVE patches auto-merged |

---

## Getting Started Checklist

- [ ] Access the Dashboard: `https://devops.13.215.130.82.nip.io/dashboard`
- [ ] Verify Orchestrator health: `curl -k https://devops.13.215.130.82.nip.io/orchestrator/health`
- [ ] Clone the repo: `git clone https://github.com/benlbk/devops-agentic-teammates.git`
- [ ] Create your first feature request via the Plan & Collaborate agent
- [ ] Open a PR and watch the Code Review + Test agents respond
- [ ] Monitor deployment in ArgoCD: `https://devops.13.215.130.82.nip.io/argocd`
- [ ] Check DORA metrics after your first deployment
- [ ] Set up Grafana alerts for your application endpoints
