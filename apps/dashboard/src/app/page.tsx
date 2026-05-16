"use client";

import { useEffect, useState } from "react";
import { fetchDORAMetrics, fetchAgentMetrics, fetchRecentEvents, type DORAMetrics, type AgentMetrics, type AgentEvent } from "@/lib/api";

const AGENT_LABELS: Record<string, string> = {
  "plan-collaborate": "Plan & Collaborate",
  "code-build": "Code & Build",
  "test-secure": "Test & Secure",
  "release-deploy": "Release & Deploy",
  "operate-monitor": "Operate & Monitor",
};

export default function DashboardHome() {
  const [dora, setDora] = useState<DORAMetrics | null>(null);
  const [agents, setAgents] = useState<AgentMetrics | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);

  useEffect(() => {
    const load = async () => {
      try {
        const [d, a, e] = await Promise.all([
          fetchDORAMetrics(),
          fetchAgentMetrics(),
          fetchRecentEvents(),
        ]);
        setDora(d);
        setAgents(a);
        setEvents(e);
      } catch {
        // Fallback: keep null state, show placeholder
      }
    };
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold tracking-tight">Overview</h2>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Deployment Frequency"
          value={dora ? `${dora.deployment_frequency.value}/day` : "—"}
          trend=""
        />
        <MetricCard
          title="Lead Time"
          value={dora ? `${dora.lead_time_for_changes.value}h` : "—"}
          trend=""
        />
        <MetricCard
          title="Change Failure Rate"
          value={dora ? `${dora.change_failure_rate.value}%` : "—"}
          trend=""
        />
        <MetricCard
          title="MTTR"
          value={dora ? `${dora.mean_time_to_recovery.value}min` : "—"}
          trend=""
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border bg-white p-6">
          <h3 className="text-lg font-semibold mb-4">Agent Activity (24h)</h3>
          <div className="space-y-3">
            {agents ? (
              Object.entries(agents.agents).map(([key, data]) => (
                <AgentRow
                  key={key}
                  name={AGENT_LABELS[key] || key}
                  tasks={data.total}
                  status={data.in_progress > 0 ? "active" : "idle"}
                />
              ))
            ) : (
              Object.values(AGENT_LABELS).map((name) => (
                <AgentRow key={name} name={name} tasks={0} status="idle" />
              ))
            )}
          </div>
          {agents && (
            <p className="mt-3 text-xs text-gray-400">
              Total: {agents.total_tasks_24h} tasks in last 24h
            </p>
          )}
        </div>
        <div className="rounded-lg border bg-white p-6">
          <h3 className="text-lg font-semibold mb-4">Recent Events</h3>
          <div className="space-y-2 text-sm">
            {events.length > 0 ? (
              events.slice(0, 8).map((e, i) => (
                <EventRow
                  key={i}
                  time={e.timestamp ? formatRelativeTime(e.timestamp) : ""}
                  message={`[${AGENT_LABELS[e.agent] || e.agent}] ${e.task_type} — ${e.status}`}
                />
              ))
            ) : (
              <p className="text-gray-400">No recent events</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function MetricCard({ title, value, trend }: { title: string; value: string; trend: string }) {
  const isPositive = trend.startsWith("-");
  return (
    <div className="rounded-lg border bg-white p-4">
      <p className="text-sm text-gray-500">{title}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
      <p className={`text-xs mt-1 ${isPositive ? "text-green-600" : "text-red-600"}`}>{trend}</p>
    </div>
  );
}

function AgentRow({ name, tasks, status }: { name: string; tasks: number; status: string }) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${status === "active" ? "bg-green-500" : "bg-gray-300"}`} />
        <span className="text-sm font-medium">{name}</span>
      </div>
      <span className="text-sm text-gray-500">{tasks} tasks</span>
    </div>
  );
}

function EventRow({ time, message }: { time: string; message: string }) {
  return (
    <div className="flex gap-3 py-1">
      <span className="text-gray-400 whitespace-nowrap">{time}</span>
      <span>{message}</span>
    </div>
  );
}
