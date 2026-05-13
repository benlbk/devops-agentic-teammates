# DevOps Agentic Teammates â€” Operations Guide

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| AWS CLI | v2 | AWS resource management |
| Terraform | â‰¥1.5 | Infrastructure provisioning |
| Terragrunt | â‰¥0.50 | DRY Terraform orchestration |
| kubectl | â‰¥1.28 | Kubernetes cluster management |
| Helm | â‰¥3.x | K8s package management |
| Docker | â‰¥24.x | Container builds |
| Poetry | â‰¥1.7 | Python dependency management |
| Node.js | â‰¥20 | Frontend/dashboard apps |
| .NET SDK | 8.0 | Backend API |
| ArgoCD CLI | â‰¥2.x | GitOps deployments |

---

## Architecture Overview

```
Developer pushes code
        â†“
GitHub Webhook â†’ API Gateway â†’ Lambda â†’ EventBridge
        â†“
EventBridge routes event to the appropriate agent:

  PR opened â†’ Code & Build Agent (reviews code)
           â†’ Test & Secure Agent (generates tests, security scan)
           â†’ Release & Deploy Agent (creates ephemeral env)

  PR merged â†’ Code & Build Agent (build images)
           â†’ Release & Deploy Agent (deploy staging â†’ canary production)

  Alert fires â†’ Operate & Monitor Agent (diagnose, remediate, postmortem)

  New feature request â†’ Plan & Collaborate Agent (parse design â†’ stories â†’ issues)
```

All agents coordinate through **EventBridge events** and track state in **DynamoDB**. The **Policy Engine** (`agents/src/shared/policy.py`) enforces governance rules (e.g., production deploys require approval, security fixes auto-approved).

---

## Project Structure

```
devops-agentic-teammates/
â”œâ”€â”€ .bk/specs/                    # Requirements, design, tasks specifications
â”œâ”€â”€ .github/workflows/            # GitHub Actions CI/CD pipelines
â”œâ”€â”€ agents/                       # Python agent platform (LangGraph + FastAPI)
â”‚   â”œâ”€â”€ src/
â”‚   â”‚   â”œâ”€â”€ agents/               # 5 specialized agents
â”‚   â”‚   â”œâ”€â”€ orchestrator/         # Central orchestrator (FastAPI)
â”‚   â”‚   â””â”€â”€ shared/               # Shared libraries (LLM, state, events, RAG, policy)
â”‚   â”œâ”€â”€ pyproject.toml
â”‚   â””â”€â”€ Dockerfile
â”œâ”€â”€ apps/
â”‚   â”œâ”€â”€ backend/                  # ASP.NET Core 8 API (PostgreSQL, EF Core)
â”‚   â”œâ”€â”€ frontend/                 # Next.js 14 application
â”‚   â””â”€â”€ dashboard/                # Agent monitoring dashboard (Next.js)
â”œâ”€â”€ gitops/
â”‚   â”œâ”€â”€ argocd/                   # ArgoCD Application & Project manifests
â”‚   â””â”€â”€ rollouts/                 # Argo Rollouts canary strategies
â”œâ”€â”€ helm/
â”‚   â”œâ”€â”€ agent-orchestrator/       # Orchestrator Helm chart
â”‚   â”œâ”€â”€ target-backend/           # Backend Helm chart
â”‚   â””â”€â”€ target-frontend/          # Frontend Helm chart
â””â”€â”€ terraform/
    â”œâ”€â”€ environments/platform/    # Terragrunt environment configs
    â”œâ”€â”€ modules/                  # 10 Terraform modules (VPC, EKS, RDS, etc.)
    â””â”€â”€ terragrunt.hcl            # Root Terragrunt config
```

---

## Phase 1: Provision AWS Infrastructure

### 1.1 Configure AWS credentials

```bash
aws configure
# or
export AWS_PROFILE=mies-eks
```

### 1.2 Deploy foundation resources

Deploy in dependency order â€” VPC first, then EKS, then supporting services:

```bash
# VPC (3-AZ public/private/database subnets, NAT gateways, VPC endpoints)
cd terraform/environments/platform/vpc
terragrunt apply

# EKS cluster (managed node groups, IRSA, cluster autoscaler)
cd ../eks
terragrunt apply
```

### 1.3 Deploy supporting services

Each module is deployed via its environment terragrunt config. The modules are:

| Module | Key Resources |
|--------|---------------|
| `vpc` | VPC, 3-AZ subnets, NAT Gateways, VPC endpoints (S3, DynamoDB, ECR, Secrets Manager, Bedrock) |
| `eks-cluster` | EKS 1.28, managed node groups (agent-workers: m6i.xlarge, dashboard: t3.large), IRSA |
| `rds-postgresql` | PostgreSQL 15, db.t3.medium, 20GB, credentials in Secrets Manager |
| `dynamodb` | 3 tables (agent-state, approvals, audit-log) with GSIs, TTL, PITR |
| `eventbridge` | Custom event bus, schema registry, per-agent routing rules, DLQ |
| `opensearch` | Serverless vector search collection for RAG pipeline |
| `ecr` | 9 repositories (6 agents + frontend + backend + dashboard), immutable tags |
| `cloudfront-distribution` | S3 origin (static assets) + ALB origin (SSR/API) |
| `api-gateway` | REST API, webhook endpoint, Lambda authorizer, WAF |
| `ephemeral-environment` | Per-PR K8s namespaces with resource quotas |

The root Terragrunt config (`terraform/terragrunt.hcl`) auto-manages:
- S3 backend for state (`devops-agentic-teammates-terraform-state`)
- DynamoDB lock table
- AWS provider generation with default tags

---

## Phase 2: Build & Push Container Images

### 2.1 Authenticate with ECR

```bash
aws ecr get-login-password --region ap-southeast-1 | \
  docker login --username AWS --password-stdin 448658572737.dkr.ecr.ap-southeast-1.amazonaws.com
```

### 2.2 Build and push agent images

```bash
cd agents
docker build -t agent-orchestrator .
docker tag agent-orchestrator:latest 448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/agent-orchestrator:latest
docker push 448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/agent-orchestrator:latest

# Repeat for each agent or use the CI workflow (see below)
```

### 2.3 Build and push application images

```bash
# Backend
cd apps/backend
docker build -t target-backend .
docker tag target-backend:latest 448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/target-backend:latest
docker push 448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/target-backend:latest

# Frontend
cd ../frontend
docker build -t target-frontend .
docker tag target-frontend:latest 448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/target-frontend:latest
docker push 448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/target-frontend:latest
```

### 2.4 Automated builds (CI)

The `build-push-agents.yml` workflow handles this automatically on push to `main`. It builds all 6 agent images in parallel via a matrix strategy and pushes to ECR.

---

## Phase 3: Deploy to EKS

### 3.1 Configure kubectl

```bash
aws eks update-kubeconfig --name devops-agents --region ap-southeast-1
```

### 3.2 Install ArgoCD

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Get initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

### 3.3 Install Argo Rollouts

```bash
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml
```

### 3.4 Deploy via ArgoCD (recommended)

```bash
# Create ArgoCD projects
kubectl apply -f gitops/argocd/projects.yaml

# Deploy agent orchestrator (auto-syncs from helm/agent-orchestrator)
kubectl apply -f gitops/argocd/agent-orchestrator.yaml

# Deploy target applications (auto-syncs from helm/target-frontend + helm/target-backend)
kubectl apply -f gitops/argocd/target-apps.yaml

# Deploy canary rollout strategy
kubectl apply -f gitops/rollouts/canary-backend.yaml
```

### 3.5 Deploy via Helm (alternative)

```bash
helm upgrade --install orchestrator ./helm/agent-orchestrator \
  --namespace agents --create-namespace \
  --set image.repository=448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/agent-orchestrator \
  --set image.tag=latest \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=arn:aws:iam::448658572737:role/agent-orchestrator-role

helm upgrade --install frontend ./helm/target-frontend \
  --namespace target-app --create-namespace \
  --set image.repository=448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/target-frontend \
  --set image.tag=latest

helm upgrade --install backend ./helm/target-backend \
  --namespace target-app \
  --set image.repository=448658572737.dkr.ecr.ap-southeast-1.amazonaws.com/target-backend \
  --set image.tag=latest
```

---

## Phase 4: Configure GitHub Integration

### 4.1 Create a Fine-Grained Personal Access Token (PAT)

Go to **GitHub â†’ Settings â†’ Developer settings â†’ Personal access tokens â†’ Fine-grained tokens** and create a new token with these repository permissions:

| Scope | Permission |
|-------|------------|
| Contents | Read & Write |
| Pull Requests | Read & Write |
| Issues | Read & Write |
| Actions | Read |
| Checks | Read & Write |
| Metadata | Read |
| Webhooks | Read & Write |

Set **Resource owner** to your personal account (`benlbk`) and grant access to the target repositories.

### 4.2 Store secrets in AWS Secrets Manager

```bash
# Store the PAT
aws secretsmanager create-secret --name github-pat --secret-string 'ghp_your_token_here'

# Store the webhook secret separately
aws secretsmanager create-secret --name github-webhook-secret --secret-string 'your-webhook-secret'
```

### 4.3 Configure the webhook URL

In the repository **Settings â†’ Webhooks**, add a webhook with the URL:

```
https://<API_GATEWAY_URL>/webhooks/github
```

Select events: `Pushes`, `Pull requests`, `Issues`, `Workflow runs`.

The API Gateway (`terraform/modules/api-gateway/main.tf`) routes webhooks through Lambda to EventBridge, which dispatches to the appropriate agent.

### 4.4 Set GitHub Actions repository secrets

| Secret | Description |
|--------|-------------|
| `ORCHESTRATOR_URL` | Internal ALB URL of the agent orchestrator service |
| `ORCHESTRATOR_TOKEN` | API authentication token for the orchestrator |
| `AWS_DEPLOY_ROLE_ARN` | IAM role ARN for GitHub OIDC authentication |

---

## Phase 5: Run Database Migrations

```bash
# Retrieve RDS credentials from Secrets Manager
SECRET=$(aws secretsmanager get-secret-value --secret-id rds-postgresql-credentials --query SecretString --output text)
HOST=$(echo $SECRET | jq -r '.host')
USER=$(echo $SECRET | jq -r '.username')
PASS=$(echo $SECRET | jq -r '.password')

# Apply initial schema
psql "host=$HOST port=5432 dbname=targetapp user=$USER password=$PASS" \
  -f apps/backend/Migrations/001_initial_schema.sql
```

---

## Phase 6: Local Development

### Agent Platform

```bash
cd agents
poetry install
poetry run uvicorn src.orchestrator.main:app --reload --port 8000
# Orchestrator API available at http://localhost:8000
```

### Backend API

```bash
cd apps/backend
dotnet restore
dotnet run
# API available at http://localhost:5000
# Swagger UI at http://localhost:5000/swagger
```

### Frontend

```bash
cd apps/frontend
npm install
npm run dev
# App available at http://localhost:3000
```

### Dashboard

```bash
cd apps/dashboard
npm install
npm run dev
# Dashboard available at http://localhost:3001
```

### Required environment variables

Set these for local agent development (see `agents/src/shared/config.py` for full list):

| Variable | Example | Description |
|----------|---------|-------------|
| `AWS_REGION` | `ap-southeast-1` | AWS region |
| `DYNAMODB_TABLE_NAME` | `agent-state` | DynamoDB table for agent state |
| `EVENTBRIDGE_BUS_NAME` | `devops-agentic-teammates` | EventBridge custom bus |
| `LLM_PROVIDER` | `bedrock` | LLM provider (`bedrock` or `openai`) |
| `LLM_MODEL` | `anthropic.claude-sonnet-4-20250514` | LLM model identifier |
| `GITHUB_TOKEN` | `ghp_xxxx` | GitHub Personal Access Token (or use GITHUB_TOKEN_SECRET for Secrets Manager) |
| `OPENSEARCH_ENDPOINT` | `https://...aoss.ap-southeast-1.amazonaws.com` | OpenSearch Serverless endpoint |

---

## CI/CD Pipelines

### GitHub Actions Workflows

| Workflow | File | Trigger | Purpose |
|----------|------|---------|---------|
| Build & Push Agents | `.github/workflows/build-push-agents.yml` | Push to `main` (agents/**) or manual | Docker build + ECR push for all 6 agents |
| Agent Code Review | `.github/workflows/agent-code-review.yml` | PR opened/updated on `apps/**` or `agents/**` | Triggers AI code review via orchestrator |
| Agent Security Scan | `.github/workflows/agent-security-scan.yml` | PR or push to `main`/`develop` | Gitleaks + Trivy + Checkov + agent analysis |
| Backend CI | `.github/workflows/backend-ci.yml` | PR/push on `apps/backend/**` | dotnet restore â†’ build â†’ test â†’ Docker push |
| Frontend CI | `.github/workflows/frontend-ci.yml` | PR/push on `apps/frontend/**` | npm ci â†’ lint â†’ test â†’ Docker push |

### Deployment flow

1. **Code push** â†’ GitHub Actions builds and pushes images to ECR
2. **Image tag update** â†’ Release & Deploy agent updates `values.yaml` in the Helm chart
3. **ArgoCD sync** â†’ ArgoCD detects the change and deploys to EKS
4. **Canary rollout** â†’ Argo Rollouts promotes traffic gradually (10% â†’ 30% â†’ 60% â†’ 100%)
5. **Analysis** â†’ CloudWatch success-rate metric must be â‰¥95% to proceed; auto-rollback on failure

---

## Agent Services

### Agent Descriptions

| Agent | Module | Capabilities |
|-------|--------|-------------|
| **Plan & Collaborate** | `agents/src/agents/plan_collaborate.py` | Design parsing, user story generation, sprint planning, ADR generation, GitHub Issues creation |
| **Code & Build** | `agents/src/agents/code_build.py` | AI code review (bugs/security/performance/style), code generation (Next.js + .NET), branch & PR management |
| **Test & Secure** | `agents/src/agents/test_secure.py` | Test generation (xUnit, Jest, Playwright), security scanning (SAST/SCA/container/IaC/secrets) |
| **Release & Deploy** | `agents/src/agents/release_deploy.py` | Release management, ArgoCD GitOps deploys, canary rollouts, ephemeral environments, Terraform plan review |
| **Operate & Monitor** | `agents/src/agents/operate_monitor.py` | Incident response, automated remediation, cost analysis, performance optimization, postmortem generation |
| **Orchestrator** | `agents/src/orchestrator/main.py` | Central control plane (FastAPI), task routing, policy evaluation, DORA metrics, approval management |

### Shared Libraries

| Module | Purpose |
|--------|---------|
| `agents/src/shared/config.py` | Pydantic Settings with all environment variables |
| `agents/src/shared/llm.py` | LLM provider (Bedrock primary + OpenAI fallback), token budgets, retries |
| `agents/src/shared/state.py` | DynamoDB state management, AgentTask model, audit logging |
| `agents/src/shared/github_client.py` | GitHub PAT auth, file/branch/PR/issue CRUD |
| `agents/src/shared/events.py` | EventBridge publisher for inter-agent communication |
| `agents/src/shared/rag.py` | OpenSearch vector search, code chunking, Titan embeddings |
| `agents/src/shared/policy.py` | YAML-based policy engine (ALLOW/DENY/REQUIRE_APPROVAL) |

### Orchestrator API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/info` | Service info |
| POST | `/api/tasks` | Create a new agent task |
| GET | `/api/tasks` | List tasks (with filters) |
| GET | `/api/tasks/{id}` | Get task details |
| POST | `/api/approvals` | Submit approval decisions |
| POST | `/webhooks/github` | GitHub webhook receiver |
| GET | `/api/metrics/dora` | DORA metrics endpoint |

---

## Monitoring & Observability

### Dashboard

The agent monitoring dashboard (`apps/dashboard`) provides:

| Page | Description |
|------|-------------|
| **Overview** | DORA metrics summary, agent status, recent events |
| **DORA Metrics** | Deployment frequency, lead time, change failure rate, MTTR charts |
| **Agent Activity** | Per-agent task counts, success rates, durations, token usage |
| **Environments** | Production/staging/dev status, ephemeral environment list |
| **Security** | Vulnerability counts by severity, scan history by tool |
| **Costs** | Monthly spend, forecast, savings recommendations, service breakdown |
| **Settings** | Agent config, GitHub integration status, notification channels, policy rules |

### Health Checks

Every service exposes a `/health` endpoint:
- Agent orchestrator: `http://<orchestrator>:8000/health`
- Backend API: `http://<backend>:5000/health`
- Frontend: `http://<frontend>:3000/`

### Prometheus Metrics

Pod annotations enable Prometheus scraping:
```yaml
prometheus.io/scrape: "true"
prometheus.io/port: "8000"
prometheus.io/path: /metrics
```

### ArgoCD

Monitor deployment sync status at:
```
https://argocd.<your-domain>
```

### Argo Rollouts

Canary deployments are monitored via:
- CloudWatch success-rate metrics (must be â‰¥95% to promote)
- Automatic rollback on failure (success-rate < 90%)
- Steps: 10% â†’ 30% â†’ 60% â†’ 100% with 2â€“5 minute pauses

---

## Kubernetes Resources

### Namespaces

| Namespace | Contents |
|-----------|----------|
| `argocd` | ArgoCD server and controllers |
| `argo-rollouts` | Argo Rollouts controller |
| `agents` | Agent orchestrator and agent pods |
| `target-app` | Target frontend and backend pods |
| `pr-*` | Ephemeral environments (per PR) |

### Resource Allocation

| Service | CPU Request | CPU Limit | Memory Request | Memory Limit | Replicas |
|---------|-------------|-----------|----------------|--------------|----------|
| Orchestrator | 500m | 1 | 512Mi | 1Gi | 2â€“6 (HPA) |
| Target Frontend | 200m | 500m | 256Mi | 512Mi | 2â€“10 (HPA) |
| Target Backend | 250m | 1 | 256Mi | 512Mi | 2â€“10 (HPA) |

### Autoscaling

- HPA targets: 70% CPU utilization (all services), 80% memory (orchestrator)
- Pod Disruption Budget: `minAvailable: 1` for orchestrator
- Cluster Autoscaler managed via IRSA role on EKS

---

## Troubleshooting

### Check agent orchestrator logs

```bash
kubectl logs -n agents -l app.kubernetes.io/name=agent-orchestrator -f
```

### Check ArgoCD sync status

```bash
argocd app list
argocd app get agent-orchestrator
argocd app get target-frontend
argocd app get target-backend
```

### Check Argo Rollout status

```bash
kubectl argo rollouts status target-backend-canary -n target-app
kubectl argo rollouts get rollout target-backend-canary -n target-app
```

### Verify EventBridge event delivery

```bash
aws events describe-event-bus --name devops-agentic-teammates
aws sqs get-queue-attributes --queue-url <DLQ_URL> --attribute-names ApproximateNumberOfMessages
```

### Check DynamoDB agent state

```bash
aws dynamodb scan --table-name agent-state --max-items 10
aws dynamodb query --table-name agent-state \
  --index-name GSI2-Status \
  --key-condition-expression "task_status = :s" \
  --expression-attribute-values '{":s": {"S": "IN_PROGRESS"}}'
```

### RDS connectivity test

```bash
kubectl run pg-test --rm -it --image=postgres:15-alpine -- \
  psql "host=<RDS_ENDPOINT> port=5432 dbname=targetapp user=dbadmin password=<password>"
```
