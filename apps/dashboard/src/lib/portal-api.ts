import axios from "axios";

const api = axios.create({
  baseURL: "/orchestrator",
  timeout: 30000,
});

// --- Task submission ---
export interface TaskRequest {
  agent_type: string;
  task_type: string;
  context: Record<string, unknown>;
}

export interface TaskResponse {
  task_id: string;
  status: string;
  message?: string;
}

export async function submitTask(task: TaskRequest): Promise<TaskResponse> {
  const { data } = await api.post<TaskResponse>("/api/tasks", task);
  return data;
}

export async function getTask(taskId: string): Promise<TaskResponse> {
  const { data } = await api.get<TaskResponse>(`/api/tasks/${taskId}`);
  return data;
}

// --- Approvals ---
export interface ApprovalRequest {
  task_id: string;
  decision: "approved" | "rejected";
  approver: string;
  comment: string;
}

export interface Approval {
  task_id: string;
  status: string;
  approver?: string;
  created_at: string;
}

export async function submitApproval(approval: ApprovalRequest): Promise<{ status: string }> {
  const { data } = await api.post("/api/approvals", approval);
  return data;
}

export async function getPendingApprovals(): Promise<Approval[]> {
  const { data } = await api.get<Approval[]>("/api/approvals", { params: { status: "pending" } });
  return Array.isArray(data) ? data : [];
}

// --- Runbooks ---
export interface Runbook {
  name: string;
  description: string;
  parameters: string[];
}

export interface RunbookExecRequest {
  runbook: string;
  parameters: Record<string, string>;
}

export async function listRunbooks(): Promise<Runbook[]> {
  const { data } = await api.get<Runbook[]>("/api/runbooks");
  return Array.isArray(data) ? data : [];
}

export async function executeRunbook(req: RunbookExecRequest): Promise<{ status: string; output?: string }> {
  const { data } = await api.post("/api/runbooks/execute", req);
  return data;
}

// --- Dependencies ---
export interface DependencyCheckRequest {
  repository: string;
  package_manager: string;
  path: string;
}

export async function checkDependencies(req: DependencyCheckRequest): Promise<{ status: string; findings?: unknown[] }> {
  const { data } = await api.post("/api/dependencies/check", req);
  return data;
}

// --- Merge ---
export interface MergeRequest {
  repository: string;
  pr_number: number;
}

export async function requestMerge(req: MergeRequest): Promise<{ status: string; message?: string }> {
  const { data } = await api.post("/api/merge", req);
  return data;
}

// --- Metrics ---
export async function getDORAMetrics() {
  const { data } = await api.get("/api/metrics/dora");
  return data;
}

export async function getAgentMetrics() {
  const { data } = await api.get("/api/metrics/agents");
  return data;
}

// --- Health ---
export async function getHealthStatus() {
  const { data } = await api.get("/health");
  return data;
}

export async function getServiceInfo() {
  const { data } = await api.get("/info");
  return data;
}
