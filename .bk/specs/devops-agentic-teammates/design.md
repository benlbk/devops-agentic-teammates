# DevOps Agentic Teammates — Design Specification

## 1. System Architecture Overview

The DevOps Agentic Teammates platform is built as a distributed multi-agent system where specialized AI agents operate across the five SDLC phases. An **Agent Orchestrator** coordinates agent activities, manages state, enforces policies, and provides a unified control plane.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Agent Control Plane                              │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────┐ ┌────────────────┐  │
│  │ Orchestrator │ │ Policy Engine│ │ Audit Log  │ │  Dashboard UI  │  │
│  └──────┬───────┘ └──────┬───────┘ └─────┬──────┘ └───────┬────────┘  │
│         │                │               │                 │           │
├─────────┴────────────────┴───────────────┴─────────────────┴───────────┤
│                         Agent Message Bus (Amazon EventBridge)          │
├────────┬──────────┬──────────┬────────────┬────────────────────────────┤
│        │          │          │            │                             │
│  ┌─────┴────┐ ┌──┴─────┐ ┌─┴──────┐ ┌──┴──────┐ ┌──────────────┐   │
│  │  Plan &   │ │ Code & │ │ Test & │ │Release &│ │  Operate &   │   │
│  │Collaborate│ │ Build  │ │ Secure │ │ Deploy  │ │   Monitor    │   │
│  │  Agent    │ │ Agent  │ │ Agent  │ │ Agent   │ │    Agent     │   │
│  └──────────┘ └────────┘ └────────┘ └─────────┘ └──────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
         │          │          │            │              │
    ┌────┴────┐ ┌──┴───┐ ┌──┴───┐   ┌───┴────┐   ┌────┴─────┐
    │ GitHub  │ │GitHub│ │GitHub│   │ ArgoCD │   │CloudWatch│
    │ Issues  │ │ Repos│ │Actions│  │  EKS   │   │  X-Ray   │
    │Projects │ │      │ │      │   │Terraform│  │          │
    └─────────┘ └──────┘ └──────┘   └────────┘   └──────────┘
```

---

## 2. Technology Stack

### 2.1 Agent Platform Infrastructure

| Component | Technology | Rationale |
|---|---|---|
| **Agent Runtime** | AWS EKS (dedicated namespace) | Co-located with application workloads; Kubernetes-native scaling |
| **Agent Framework** | Python (LangGraph / AutoGen) | Mature agent orchestration; tool-calling support; async workflows |
| **LLM Provider** | AWS Bedrock (Claude) + OpenAI fallback | Enterprise-grade; data residency; model diversity |
| **Message Bus** | Amazon EventBridge | Event-driven agent coordination; schema registry; filtering |
| **State Store** | Amazon DynamoDB | Agent workflow state; fast reads; TTL for ephemeral state |
| **Vector Store** | Amazon OpenSearch Serverless | RAG for codebase knowledge; semantic search over docs |
| **Secrets Management** | AWS Secrets Manager | Agent credentials; API keys; rotation |
| **Agent API** | AWS API Gateway + Lambda | RESTful control plane API; webhook receivers |
| **Dashboard** | Next.js (same stack as target app) | Real-time agent monitoring; DORA metrics; cost tracking |
| **Audit & Logging** | Amazon CloudWatch + S3 | Immutable audit trail; long-term retention |

### 2.2 Target Application Stack

| Component | Technology | AWS Service |
|---|---|---|
| **Frontend** | Next.js 14+ (TypeScript) | CloudFront + S3 (static) / EKS (SSR) |
| **Backend** | ASP.NET Core 8+ (C#) | AWS EKS |
| **Database** | PostgreSQL 15+ | Amazon RDS / Aurora PostgreSQL |
| **Cache** | Redis | Amazon ElastiCache |
| **Container Registry** | Docker | Amazon ECR |
| **DNS** | - | Amazon Route 53 |
| **TLS** | - | AWS Certificate Manager |
| **CDN** | - | Amazon CloudFront |

### 2.3 DevOps Toolchain

| Component | Technology |
|---|---|
| **Source Control** | GitHub Free (personal account) |
| **CI** | GitHub Actions |
| **CD** | ArgoCD + Argo Rollouts |
| **IaC** | Terraform + Terragrunt |
| **Container Orchestration** | AWS EKS (Kubernetes 1.28+) |
| **GitOps Repository** | Dedicated `*-gitops` repos |
| **Package Management** | npm (frontend), NuGet (.NET) |
| **Image Scanning** | Trivy / Amazon Inspector |
| **SAST** | GitHub CodeQL + Semgrep |
| **SCA** | Dependabot + Snyk |

---

## 3. Component Design

### 3.1 Agent Orchestrator

The Orchestrator is the central coordination service that manages agent lifecycle, routing, and policy enforcement.

**Responsibilities:**
- Receives events from GitHub webhooks, ArgoCD notifications, and CloudWatch alarms
- Routes events to the appropriate agent(s) based on event type and policy rules
- Manages agent execution context (state, permissions, budget)
- Enforces human-in-the-loop policies for sensitive operations
- Tracks agent workflow progress and handles failures

**Architecture:**
```
GitHub Webhook → API Gateway → Lambda (Event Router) → EventBridge
                                                           │
                                    ┌──────────────────────┼──────────────────┐
                                    │                      │                  │
                              Rule: PR Created       Rule: Deploy       Rule: Alert
                                    │                      │                  │
                              Code & Build Agent    Release Agent     Operate Agent
```

**Event Schema (EventBridge):**
```json
{
  "source": "devops-agentic-teammates",
  "detail-type": "agent.task.requested",
  "detail": {
    "agentType": "code-build",
    "taskType": "code-review",
    "context": {
      "repository": "benlbk/app-frontend",
      "prNumber": 142,
      "triggeredBy": "webhook"
    },
    "policy": {
      "requireApproval": false,
      "maxTokenBudget": 50000,
      "timeoutMinutes": 10
    }
  }
}
```

### 3.2 Policy Engine

The Policy Engine governs what agents can and cannot do autonomously.

**Policy Model:**
```yaml
# policy.yaml
policies:
  - name: production-deploy-approval
    agent: release-deploy
    action: deploy
    environment: production
    require_approval: true
    approvers: ["platform-team", "tech-leads"]

  - name: code-review-auto-approve
    agent: code-build
    action: approve-pr
    conditions:
      - change_size: < 50 lines
      - test_coverage: > 80%
      - security_scan: pass
    require_approval: false

  - name: ephemeral-env-budget
    agent: release-deploy
    action: create-environment
    constraints:
      max_concurrent: 20
      max_cost_per_env: 50  # USD/day
      auto_destroy_hours: 48

  - name: incident-auto-remediate
    agent: operate-monitor
    action: auto-remediate
    conditions:
      - severity: [low, medium]
      - runbook_exists: true
    require_approval: false
```

### 3.3 Plan & Collaborate Agent

**Service:** `agent-plan-collaborate`  
**Runtime:** EKS Pod (Python)  
**Triggers:** Manual invocation, GitHub Issue creation, Sprint planning events

**Components:**
```
┌─────────────────────────────────┐
│   Plan & Collaborate Agent      │
│                                 │
│  ┌───────────────────────────┐  │
│  │   Design Parser           │  │  ← Parses Figma/wireframes/specs
│  ├───────────────────────────┤  │
│  │   Story Generator         │  │  ← Generates user stories
│  ├───────────────────────────┤  │
│  │   Sprint Planner          │  │  ← Analyzes velocity, suggests scope
│  ├───────────────────────────┤  │
│  │   ADR Generator           │  │  ← Detects & documents arch decisions
│  ├───────────────────────────┤  │
│  │   GitHub Integration      │  │  ← Issues, Projects, Milestones
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

**Data Flow:**
1. User submits feature description or design artifact
2. Agent retrieves existing codebase context via RAG (vector store)
3. LLM generates structured plan (components, APIs, data models)
4. Agent creates GitHub Issues with labels, assignments, and dependencies
5. Spec files committed to `.bk/specs/` in the repository

### 3.4 Code & Build Agent

**Service:** `agent-code-build`  
**Runtime:** EKS Pod (Python) + GitHub Actions integration  
**Triggers:** GitHub Issue assignment, PR creation/update, Schedule (dependency updates)

**Components:**
```
┌─────────────────────────────────┐
│     Code & Build Agent          │
│                                 │
│  ┌───────────────────────────┐  │
│  │   Code Generator          │  │  ← Generates Next.js / .NET code
│  ├───────────────────────────┤  │
│  │   Code Reviewer           │  │  ← Reviews PRs, posts comments
│  ├───────────────────────────┤  │
│  │   Dependency Manager      │  │  ← Monitors & updates dependencies
│  ├───────────────────────────┤  │
│  │   Build Optimizer         │  │  ← Analyzes & optimizes CI pipelines
│  ├───────────────────────────┤  │
│  │   Codebase RAG            │  │  ← Semantic search over codebase
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

**Code Generation Workflow:**
```
Issue (spec) → Retrieve codebase context (RAG)
             → Generate code (LLM)
             → Create feature branch
             → Commit code
             → Create PR
             → Trigger Code Review Agent
             → Trigger Test Agent
```

**Code Review Workflow (GitHub Actions):**
```yaml
# .github/workflows/agent-code-review.yml
name: AI Code Review
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  ai-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Invoke Code Review Agent
        uses: ./actions/agent-code-review
        with:
          model: bedrock/claude-sonnet
          review-scope: diff
          post-comments: true
```

### 3.5 Test & Secure Agent

**Service:** `agent-test-secure`  
**Runtime:** EKS Pod (Python) + GitHub Actions integration  
**Triggers:** PR creation/update, Code generation completion, Schedule (security scans)

**Components:**
```
┌─────────────────────────────────┐
│     Test & Secure Agent         │
│                                 │
│  ┌───────────────────────────┐  │
│  │   Test Generator          │  │  ← Unit, integration, E2E tests
│  ├───────────────────────────┤  │
│  │   Security Scanner        │  │  ← SAST, SCA, container, IaC scanning
│  ├───────────────────────────┤  │
│  │   Test Optimizer          │  │  ← Impact analysis, parallelization
│  ├───────────────────────────┤  │
│  │   Feature Flag Manager    │  │  ← Feature flag lifecycle
│  ├───────────────────────────┤  │
│  │   Merge Coordinator       │  │  ← Merge queue, conflict resolution
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

**Test Generation Strategy:**

| Layer | Tool | Target | Trigger |
|---|---|---|---|
| Unit (Backend) | xUnit + Moq | .NET services, controllers | Code generation, PR |
| Unit (Frontend) | Jest + RTL | React components, hooks | Code generation, PR |
| Integration | xUnit + TestContainers | API endpoints + DB | PR merge to main |
| E2E | Playwright | User journeys | Ephemeral env ready |
| Contract | Pact | API consumer/provider | PR |
| Security | CodeQL + Semgrep | Source code | PR |
| Infrastructure | Checkov + tfsec | Terraform modules | PR (IaC changes) |

**Security Scanning Pipeline:**
```
PR Created
  → SAST (CodeQL, Semgrep)
  → SCA (Dependabot, Snyk)
  → Secret Detection (Gitleaks)
  → Container Scan (Trivy)
  → IaC Scan (Checkov)
  → Results aggregated
  → Agent generates fix PRs for auto-remediable issues
  → Security report posted to PR
```

### 3.6 Release & Deploy Agent

**Service:** `agent-release-deploy`  
**Runtime:** EKS Pod (Python)  
**Triggers:** PR merge to main, Manual release trigger, Schedule (infra optimization)

**Components:**
```
┌─────────────────────────────────┐
│    Release & Deploy Agent       │
│                                 │
│  ┌───────────────────────────┐  │
│  │   Env Provisioner         │  │  ← Ephemeral environments via Terraform
│  ├───────────────────────────┤  │
│  │   GitOps Coordinator      │  │  ← ArgoCD manifest management
│  ├───────────────────────────┤  │
│  │   Release Manager         │  │  ← Versioning, release notes
│  ├───────────────────────────┤  │
│  │   Infra Intelligence      │  │  ← Cost optimization, right-sizing
│  ├───────────────────────────┤  │
│  │   Rollback Controller     │  │  ← Health checks, auto-rollback
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

**Ephemeral Environment Architecture:**
```
PR Created
  → Terraform applies:
      ├── EKS namespace (pr-{number})
      ├── PostgreSQL (RDS snapshot clone or TestContainers)
      ├── .NET backend (Helm release)
      ├── Next.js frontend (Helm release)
      ├── Ingress (pr-{number}.dev.example.com)
      └── Seed data migration
  → URL posted to PR comment
  → E2E tests run against environment
  → Environment auto-destroyed on PR close (TTL: 48h max)
```

**GitOps Deployment Flow:**
```
Main branch merge
  → GitHub Actions builds & pushes images to ECR
  → Agent updates image tags in gitops repo:
      gitops-repo/
      ├── environments/
      │   ├── dev/
      │   │   ├── frontend/values.yaml    ← image tag updated
      │   │   └── backend/values.yaml     ← image tag updated
      │   ├── staging/
      │   └── production/
      └── base/
  → ArgoCD detects change
  → ArgoCD syncs to cluster
  → Argo Rollouts manages progressive delivery:
      dev → staging (auto) → production (manual approval)
```

**Progressive Delivery Strategy:**
```yaml
# Argo Rollout - Canary Strategy
apiVersion: argoproj.io/v1alpha1
kind: Rollout
spec:
  strategy:
    canary:
      steps:
        - setWeight: 10
        - pause: { duration: 5m }
        - analysis:
            templates:
              - templateName: success-rate
              - templateName: latency-p99
        - setWeight: 30
        - pause: { duration: 10m }
        - analysis:
            templates:
              - templateName: success-rate
        - setWeight: 60
        - pause: { duration: 10m }
        - setWeight: 100
      rollbackWindow:
        revisions: 2
```

### 3.7 Operate & Monitor Agent

**Service:** `agent-operate-monitor`  
**Runtime:** EKS Pod (Python) — always running  
**Triggers:** CloudWatch Alarms, EventBridge scheduled rules, Manual escalation

**Components:**
```
┌─────────────────────────────────┐
│    Operate & Monitor Agent      │
│                                 │
│  ┌───────────────────────────┐  │
│  │   Incident Responder      │  │  ← Alert triage, RCA, remediation
│  ├───────────────────────────┤  │
│  │   Performance Optimizer   │  │  ← Latency, throughput tuning
│  ├───────────────────────────┤  │
│  │   Self-Healer             │  │  ← Auto-scaling, restarts, failover
│  ├───────────────────────────┤  │
│  │   Cost Analyzer           │  │  ← Resource utilization, recommendations
│  ├───────────────────────────┤  │
│  │   Runbook Executor        │  │  ← Automated operational procedures
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

**Incident Response Flow:**
```
CloudWatch Alarm fires
  → EventBridge routes to Operate Agent
  → Agent correlates with:
      ├── Recent deployments (ArgoCD)
      ├── Recent code changes (GitHub)
      ├── Historical incidents (DynamoDB)
      └── Current metrics (CloudWatch/X-Ray)
  → Agent determines severity and action:
      ├── Auto-remediate (restart pod, scale up, rollback)
      ├── Create incident ticket with RCA
      └── Escalate to on-call (PagerDuty/Opsgenie)
  → Post-incident: Agent generates postmortem draft
```

---

## 4. Data Architecture

### 4.1 Data Flow Diagram

```
┌──────────┐     ┌──────────┐     ┌───────────┐     ┌──────────┐
│  GitHub   │────▶│  Agent   │────▶│ DynamoDB  │     │ OpenSearch│
│Enterprise │     │Orchestrat│     │(State/Audit│    │(Vector   │
│(Source of │◀────│   or     │     │  Store)   │     │  Store)  │
│  Truth)   │     └────┬─────┘     └───────────┘     └────┬─────┘
└──────────┘          │                                    │
                      │         ┌───────────┐              │
                      ├────────▶│  Bedrock  │◀─────────────┘
                      │         │  (LLM)    │  (RAG context)
                      │         └───────────┘
                      │
                ┌─────┴──────┐
                │ EventBridge│
                │  (Events)  │
                └─────┬──────┘
                      │
         ┌────────────┼────────────┐
         │            │            │
    ┌────┴───┐  ┌────┴───┐  ┌────┴───┐
    │ArgoCD  │  │CloudWatch│ │  AWS   │
    │        │  │ X-Ray   │  │ Cost   │
    │        │  │         │  │Explorer│
    └────────┘  └─────────┘  └────────┘
```

### 4.2 Agent State Schema (DynamoDB)

```json
{
  "PK": "AGENT#code-build",
  "SK": "TASK#2026-05-13T10:30:00Z#abc123",
  "agentType": "code-build",
  "taskType": "code-review",
  "status": "completed",
  "context": {
    "repository": "benlbk/app-frontend",
    "prNumber": 142,
    "branch": "feature/user-profile"
  },
  "input": {
    "diffSize": 87,
    "filesChanged": ["src/components/Profile.tsx", "src/api/user.ts"]
  },
  "output": {
    "reviewComments": 3,
    "recommendation": "approve",
    "tokensUsed": 12450
  },
  "timestamps": {
    "created": "2026-05-13T10:30:00Z",
    "started": "2026-05-13T10:30:02Z",
    "completed": "2026-05-13T10:30:45Z"
  },
  "TTL": 1721900000
}
```

### 4.3 Vector Store Schema (OpenSearch)

```json
{
  "index": "codebase-knowledge",
  "document": {
    "id": "benlbk/app-frontend/src/components/Profile.tsx",
    "repository": "benlbk/app-frontend",
    "filePath": "src/components/Profile.tsx",
    "language": "typescript",
    "content_chunk": "export function ProfileCard({ user }: ProfileCardProps) ...",
    "embedding": [0.0123, -0.0456, ...],
    "metadata": {
      "lastModified": "2026-05-10T14:20:00Z",
      "authors": ["dev1", "dev2"],
      "dependencies": ["@/api/user", "@/components/Avatar"]
    }
  }
}
```

---

## 5. Infrastructure Architecture (AWS)

### 5.1 AWS Account Structure

```
Organization Root
├── Management Account
├── Platform Account (Agent Infrastructure)
│   ├── EKS Cluster (agents)
│   ├── DynamoDB (agent state)
│   ├── OpenSearch (vector store)
│   ├── EventBridge (event bus)
│   └── API Gateway (control plane)
├── Development Account
│   ├── EKS Cluster (dev workloads + ephemeral envs)
│   ├── RDS PostgreSQL (dev)
│   └── CloudFront (dev)
├── Staging Account
│   ├── EKS Cluster (staging workloads)
│   ├── RDS PostgreSQL (staging)
│   └── CloudFront (staging)
└── Production Account
    ├── EKS Cluster (production workloads)
    ├── RDS PostgreSQL (production)
    ├── CloudFront (production)
    ├── ElastiCache Redis
    └── CloudWatch + X-Ray
```

### 5.2 EKS Cluster Design

```yaml
# Agent EKS Cluster
cluster:
  name: devops-agents
  version: "1.28"
  nodeGroups:
    - name: agent-workers
      instanceTypes: [m6i.xlarge, m6i.2xlarge]
      minSize: 2
      maxSize: 10
      labels:
        workload-type: agent
    - name: dashboard
      instanceTypes: [t3.large]
      minSize: 1
      maxSize: 3
      labels:
        workload-type: dashboard

# Application EKS Cluster (per environment)
cluster:
  name: app-{environment}
  version: "1.28"
  nodeGroups:
    - name: frontend
      instanceTypes: [t3.large]
      minSize: 2
      maxSize: 8
    - name: backend
      instanceTypes: [m6i.large, m6i.xlarge]
      minSize: 2
      maxSize: 12
```

### 5.3 Networking

```
VPC (10.0.0.0/16)
├── Public Subnets (10.0.0.0/20, 10.0.16.0/20, 10.0.32.0/20)
│   ├── ALB (Application Load Balancer)
│   ├── NAT Gateways
│   └── CloudFront Origin
├── Private Subnets (10.0.48.0/20, 10.0.64.0/20, 10.0.80.0/20)
│   ├── EKS Worker Nodes
│   ├── Agent Pods
│   └── Application Pods
└── Database Subnets (10.0.96.0/20, 10.0.112.0/20, 10.0.128.0/20)
    ├── RDS PostgreSQL
    └── ElastiCache Redis
```

---

## 6. Security Architecture

### 6.1 IAM & Access Control

```
Agent IAM Roles (IRSA - IAM Roles for Service Accounts):

agent-plan-collaborate:
  - github:read (repos, issues, projects)
  - github:write (issues, comments)
  - bedrock:InvokeModel
  - dynamodb:PutItem, GetItem, Query
  - opensearch:ESHttpGet, ESHttpPost

agent-code-build:
  - github:read (repos, PRs, actions)
  - github:write (branches, commits, PRs, comments)
  - bedrock:InvokeModel
  - ecr:GetAuthorizationToken, PutImage
  - dynamodb:PutItem, GetItem, Query

agent-test-secure:
  - github:read (repos, PRs)
  - github:write (PR comments, checks)
  - bedrock:InvokeModel
  - dynamodb:PutItem, GetItem, Query

agent-release-deploy:
  - github:write (gitops repo)
  - eks:DescribeCluster
  - terraform:* (scoped to dev/staging)
  - rds:CreateDBSnapshot, RestoreDBInstanceFromSnapshot
  - ec2:* (scoped to ephemeral resources)
  - cloudfront:CreateInvalidation

agent-operate-monitor:
  - cloudwatch:GetMetricData, DescribeAlarms
  - xray:GetTraceSummaries, BatchGetTraces
  - eks:DescribeCluster, ListPods
  - logs:GetLogEvents, FilterLogEvents
  - autoscaling:UpdateAutoScalingGroup
```

### 6.2 Secret Management

```
AWS Secrets Manager:
├── /devops-agents/github-app-private-key
├── /devops-agents/github-app-id
├── /devops-agents/bedrock-api-config
├── /devops-agents/openai-api-key (fallback)
├── /devops-agents/argocd-auth-token
├── /devops-agents/pagerduty-api-key
└── /devops-agents/slack-webhook-url
```

### 6.3 Network Security

- All agent-to-AWS communication via VPC endpoints (no public internet)
- GitHub webhooks received via API Gateway with webhook secret validation
- Agent-to-LLM communication via AWS PrivateLink (Bedrock)
- Network policies enforce pod-to-pod isolation in EKS
- WAF on API Gateway for control plane protection

---

## 7. Integration Architecture

### 7.1 GitHub Integration

**GitHub Personal Access Token (Fine-Grained PAT) Configuration:**
```yaml
github_pat:
  owner: benlbk
  token_permissions:
    contents: write          # Read/write repo contents
    pull_requests: write     # Create/review PRs
    issues: write            # Create/manage issues
    checks: write            # Create check runs
    actions: read            # Read workflow runs
    metadata: read           # Read repo metadata
    webhooks: write          # Manage webhooks
  webhook_events:
    - pull_request
    - push
    - issues
    - issue_comment
    - check_run
    - workflow_run
    - release
```

### 7.2 GitHub Actions Integration

Agents integrate with GitHub Actions via:
1. **Custom Actions** — Reusable actions in `.github/actions/` for agent invocations
2. **Webhook Triggers** — Agents receive PR/push events and act autonomously
3. **Workflow Dispatch** — Agents trigger workflows programmatically via API

**Example Workflow Integration:**
```yaml
# .github/workflows/ci.yml
name: CI Pipeline
on:
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      # Frontend
      - name: Build Next.js
        run: cd frontend && npm ci && npm run build
      
      # Backend
      - name: Build .NET
        run: cd backend && dotnet restore && dotnet build

  agent-code-review:
    needs: build
    uses: ./.github/workflows/agent-code-review.yml

  agent-test-generation:
    needs: build
    uses: ./.github/workflows/agent-test-gen.yml

  agent-security-scan:
    needs: build
    uses: ./.github/workflows/agent-security.yml

  quality-gate:
    needs: [agent-code-review, agent-test-generation, agent-security-scan]
    runs-on: ubuntu-latest
    steps:
      - name: Evaluate Quality Gate
        uses: ./.github/actions/quality-gate
```

### 7.3 ArgoCD Integration

```yaml
# ArgoCD ApplicationSet for multi-environment deployment
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: web-app
spec:
  generators:
    - list:
        elements:
          - environment: dev
            cluster: app-dev
            autoSync: true
          - environment: staging
            cluster: app-staging
            autoSync: true
          - environment: production
            cluster: app-prod
            autoSync: false  # Manual approval required
  template:
    metadata:
      name: "web-app-{{environment}}"
    spec:
      project: default
      source:
        repoURL: https://github.com/benlbk/web-app-gitops
        path: "environments/{{environment}}"
        targetRevision: main
      destination:
        server: "{{cluster}}"
        namespace: "web-app"
```

### 7.4 Terraform Integration

```
terraform/
├── modules/
│   ├── eks-cluster/
│   ├── rds-postgresql/
│   ├── cloudfront-distribution/
│   ├── vpc-networking/
│   ├── agent-infrastructure/
│   └── ephemeral-environment/
├── environments/
│   ├── platform/        # Agent infrastructure
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   └── terraform.tfvars
│   ├── dev/
│   ├── staging/
│   └── production/
└── terragrunt.hcl       # DRY configuration
```

---

## 8. Agent Communication Protocol

### 8.1 Inter-Agent Messaging

Agents communicate via EventBridge with structured events:

```json
{
  "source": "agent.code-build",
  "detail-type": "agent.task.completed",
  "detail": {
    "taskId": "task-abc123",
    "agentType": "code-build",
    "taskType": "code-generation",
    "status": "completed",
    "output": {
      "branch": "feature/user-profile",
      "prNumber": 142,
      "filesGenerated": 5
    },
    "nextActions": [
      {
        "agent": "test-secure",
        "taskType": "generate-tests",
        "context": { "prNumber": 142 }
      }
    ]
  }
}
```

### 8.2 Human-in-the-Loop Protocol

For actions requiring human approval:

```
Agent determines action requires approval (per policy)
  → Agent posts approval request to GitHub PR / Slack
  → Agent creates DynamoDB record with status: "awaiting-approval"
  → Human approves/rejects via GitHub comment or Slack action
  → Webhook fires → EventBridge → Agent resumes or aborts
  → Timeout (configurable): auto-escalate or auto-abort
```

---

## 9. Dashboard & Observability

### 9.1 Dashboard Architecture

```
Next.js Dashboard App
├── Pages
│   ├── /dashboard          # Overview: DORA metrics, agent status
│   ├── /agents             # Agent activity feed, logs
│   ├── /pipelines          # CI/CD pipeline status
│   ├── /environments       # Ephemeral env management
│   ├── /security           # Vulnerability dashboard
│   ├── /costs              # Cost tracking & optimization
│   └── /settings           # Agent policies, configuration
├── Data Sources
│   ├── API Gateway → DynamoDB (agent state)
│   ├── GitHub API (repo/PR metrics)
│   ├── ArgoCD API (deployment status)
│   ├── CloudWatch API (metrics/logs)
│   └── AWS Cost Explorer API (cost data)
└── Real-time Updates
    └── WebSocket via API Gateway
```

### 9.2 DORA Metrics Collection

```
Deployment Frequency:
  Source: ArgoCD sync events + GitHub Releases
  Calculation: Count of production deployments per day/week

Lead Time for Changes:
  Source: GitHub (first commit timestamp) → ArgoCD (production sync timestamp)
  Calculation: Time delta between first commit and production deploy

Change Failure Rate:
  Source: ArgoCD rollback events / total deployments
  Calculation: Percentage of deployments causing rollbacks or incidents

Mean Time to Recovery:
  Source: CloudWatch alarm start → alarm resolved
  Calculation: Average time from incident detection to resolution
```

---

## 10. Architectural Decision Records

### ADR-001: Agent Framework Selection
- **Context:** Need a framework for building LLM-powered agents with tool-calling
- **Decision:** LangGraph (Python) for agent orchestration
- **Rationale:** Supports stateful workflows, tool calling, human-in-the-loop, and graph-based agent topologies
- **Consequences:** Python runtime required for all agents; team needs Python expertise

### ADR-002: Event-Driven Architecture
- **Context:** Agents need to communicate and coordinate across SDLC phases
- **Decision:** Amazon EventBridge as the central event bus
- **Rationale:** Native AWS integration, schema registry, event filtering, replay capability
- **Consequences:** Eventual consistency between agents; need idempotent handlers

### ADR-003: GitOps for Deployment
- **Context:** Need reliable, auditable deployment process
- **Decision:** ArgoCD with Argo Rollouts for progressive delivery
- **Rationale:** Git as single source of truth; declarative; supports canary/blue-green
- **Consequences:** Requires separate gitops repository; agents must update manifests, not deploy directly

### ADR-004: RAG for Codebase Understanding
- **Context:** Agents need context about existing codebase to generate quality code
- **Decision:** OpenSearch Serverless with codebase embeddings
- **Rationale:** Serverless scaling, vector search support, existing AWS ecosystem
- **Consequences:** Need to maintain embedding pipeline; re-index on code changes

### ADR-005: Separate Agent and Application Clusters
- **Context:** Should agents run on the same EKS cluster as applications?
- **Decision:** Dedicated EKS cluster for agent infrastructure
- **Rationale:** Blast radius isolation; independent scaling; different security posture
- **Consequences:** Additional infrastructure cost; cross-cluster networking complexity
