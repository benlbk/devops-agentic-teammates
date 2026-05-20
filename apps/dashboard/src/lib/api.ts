import axios from "axios";

const api = axios.create({
  baseURL: "/orchestrator",
  timeout: 10000,
});

export interface DORAMetricItem {
  value: number;
  unit: string;
  level?: "elite" | "high" | "medium" | "low";
  total_7d?: number;
  sample_size?: number;
  failed?: number;
  total?: number;
}

export interface DORAMetrics {
  deployment_frequency: DORAMetricItem;
  lead_time_for_changes: DORAMetricItem;
  change_failure_rate: DORAMetricItem;
  mean_time_to_recovery: DORAMetricItem;
}

export interface AgentMetrics {
  agents: Record<string, { total: number; completed: number; failed: number; in_progress: number }>;
  total_tasks_24h: number;
}

export interface AgentEvent {
  agent: string;
  task_type: string;
  status: string;
  timestamp: string;
  output: Record<string, unknown>;
}

export interface TaskInfo {
  task_id: string;
  agent_type: string;
  task_type: string;
  status: string;
  context: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
  tokens_used: number;
}

export async function fetchDORAMetrics(): Promise<DORAMetrics> {
  const { data } = await api.get<DORAMetrics>("/api/metrics/dora");
  return data;
}

export async function fetchAgentMetrics(): Promise<AgentMetrics> {
  const { data } = await api.get<AgentMetrics>("/api/metrics/agents");
  return data;
}

export async function fetchRecentEvents(): Promise<AgentEvent[]> {
  const { data } = await api.get<AgentEvent[]>("/api/metrics/events");
  return data;
}

export async function fetchTasksByStatus(status: string): Promise<TaskInfo[]> {
  const { data } = await api.get<TaskInfo[]>(`/api/tasks/status/${status}`);
  return data;
}

export async function fetchHealth(): Promise<{ status: string }> {
  const { data } = await api.get<{ status: string }>("/health");
  return data;
}

export default api;
