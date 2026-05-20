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

export interface TaskDetail {
  task_id: string;
  agent_type: string;
  task_type: string;
  status: string;
  context: Record<string, unknown>;
  input_data: Record<string, unknown>;
  output_data: Record<string, unknown>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  tokens_used: number;
}

export async function getTaskDetail(agentType: string, taskId: string): Promise<TaskDetail> {
  const { data } = await api.get<TaskDetail>(`/api/tasks/${agentType}/${taskId}`);
  return data;
}

export async function getTasksByStatus(status: string): Promise<TaskDetail[]> {
  const { data } = await api.get<TaskDetail[]>(`/api/tasks/status/${status}`);
  return Array.isArray(data) ? data : [];
}

// --- Approvals ---
export interface PendingApproval {
  task_id: string;
  agent_type: string;
  task_type: string;
  repository: string;
  pr_number: number | null;
  issue_number: number | null;
  created_at: string;
  context: Record<string, any>;
  output_data: Record<string, any> | null;
}

export async function submitApproval(params: {
  task_id: string;
  agent_type: string;
  approved: boolean;
  approver: string;
  comment?: string;
}): Promise<{ message: string }> {
  const { data } = await api.post<{ message: string }>(`/api/approvals`, params);
  return data;
}

export async function getPendingApprovals(): Promise<PendingApproval[]> {
  const { data } = await api.get<PendingApproval[]>(`/api/approvals`);
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

// --- Pipeline ---
export interface PipelineStage {
  status: string;
  task_id: string;
  created_at: string;
  completed_at: string | null;
  output: Record<string, unknown>;
}

export interface PipelineIssue {
  issue_number: number;
  title: string;
  state?: string;
  labels?: string[];
  stages: Record<string, PipelineStage>;
}

export interface PipelineStatus {
  repository: string;
  issues: PipelineIssue[];
}

export async function getPipelineStatus(owner: string, repo: string): Promise<PipelineStatus> {
  const { data } = await api.get<PipelineStatus>(`/api/pipeline/${owner}/${repo}`);
  return data;
}

// --- Performance Metrics ---
export interface AgentPerf {
  total_tasks: number;
  completed: number;
  failed: number;
  success_rate: number;
  tokens_used: number;
  avg_cycle_time_sec: number;
  p95_cycle_time_sec: number;
}

export interface TaskTypePerf {
  total: number;
  completed: number;
  failed: number;
  success_rate: number;
  tokens_used: number;
  avg_cycle_time_sec: number;
}

export interface TimelineEntry {
  task_id: string;
  agent_type: string;
  task_type: string;
  status: string;
  tokens_used: number;
  created_at: string;
  cycle_time_sec: number | null;
}

export interface PerformanceMetrics {
  period_hours: number;
  total_tasks: number;
  total_completed: number;
  total_failed: number;
  overall_success_rate: number;
  total_tokens_used: number;
  avg_cycle_time_sec: number;
  agents: Record<string, AgentPerf>;
  task_types: Record<string, TaskTypePerf>;
  timeline: TimelineEntry[];
}

export async function getPerformanceMetrics(hours: number = 168): Promise<PerformanceMetrics> {
  const { data } = await api.get<PerformanceMetrics>(`/api/metrics/performance`, { params: { hours } });
  return data;
}
